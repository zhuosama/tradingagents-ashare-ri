import time
import logging

import pandas as pd
import requests
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from stockstats import wrap
from typing import Annotated
import os
from .config import get_config

logger = logging.getLogger(__name__)

# ── Timeout / retry settings ─────────────────────────────────────────────────
_YF_TIMEOUT = int(os.getenv("YF_API_TIMEOUT", "60"))   # seconds per download call


def normalize_ticker_yf(ticker: str) -> str:
    """Normalize A-share ticker suffixes for yfinance.

    yfinance uses .SS for Shanghai (not .SH) and .SZ for Shenzhen (already correct).
    """
    t = ticker.upper()
    if t.endswith(".SH"):
        return t[:-3] + ".SS"
    return t


def _yf_is_retryable(exc: Exception) -> bool:
    """Return True for transient yfinance / network errors worth retrying."""
    if isinstance(exc, YFRateLimitError):
        return True
    if isinstance(exc, (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError)):
        return True
    err = str(exc).lower()
    return any(kw in err for kw in ("timeout", "connection", "429", "502", "503", "504"))


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits and
    transient network errors (Timeout, ConnectionError, 5xx).

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic for rate limits
    *and* common connection failures.  Hard errors (ValueError, KeyError,
    authentication) propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as exc:
            if _yf_is_retryable(exc) and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Yahoo Finance transient error, retrying in %.0fs "
                    "(attempt %d/%d): %s",
                    delay, attempt + 1, max_retries, exc,
                )
                time.sleep(delay)
            else:
                raise


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 15 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    # Cache uses a fixed window (15y to today) so one file per symbol
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip")
    else:
        yf_symbol = normalize_ticker_yf(symbol)
        data = yf_retry(lambda: yf.download(
            yf_symbol,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
            timeout=_YF_TIMEOUT,
        ))
        data = data.reset_index()
        data.to_csv(data_file, index=False)

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """Drop financial statement columns (fiscal period timestamps) after curr_date.

    yfinance financial statements use fiscal period end dates as columns.
    Columns after curr_date represent future data and are removed to
    prevent look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
