"""AKShare fundamental data adapter for A-share stocks (SH / SZ).

Provides balance sheet, income statement, cash flow and fundamentals
summary for Chinese A-share equities using the AKShare library.

Ticker formats accepted (case-insensitive):
  - 601298.SH  →  Sina prefix: sh601298  |  THS code: 601298
  - 000792.SZ  →  Sina prefix: sz000792  |  THS code: 000792

All functions match the interface expected by interface.py:
  get_fundamentals(ticker, curr_date=None) -> str
  get_balance_sheet(ticker, freq="quarterly", curr_date=None) -> str
  get_cashflow(ticker, freq="quarterly", curr_date=None) -> str
  get_income_statement(ticker, freq="quarterly", curr_date=None) -> str
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import pandas as pd

logger = logging.getLogger(__name__)


# ── Ticker helpers ────────────────────────────────────────────────────────────

def _to_sina_prefix(ticker: str) -> str:
    """Convert 601298.SH → sh601298 / 000792.SZ → sz000792."""
    t = ticker.upper().strip()
    if "." in t:
        code, exch = t.rsplit(".", 1)
        if exch in ("SH", "SS"):
            return "sh" + code
        if exch == "SZ":
            return "sz" + code
    # Fallback: guess by code prefix
    if t.startswith("6"):
        return "sh" + t
    return "sz" + t


def _to_ths_code(ticker: str) -> str:
    """Convert 601298.SH → 601298 (6-digit code)."""
    t = ticker.upper().strip()
    if "." in t:
        return t.split(".")[0]
    return t


def _is_a_share(ticker: str) -> bool:
    """Return True if ticker looks like an A-share (SH / SZ / SS suffix or 6-digit code)."""
    t = ticker.upper().strip()
    if "." in t:
        exch = t.rsplit(".", 1)[1]
        return exch in ("SH", "SS", "SZ")
    return t.isdigit() and len(t) == 6


def _filter_by_date(df: pd.DataFrame, date_col: str, curr_date: str | None) -> pd.DataFrame:
    """Drop rows whose report date is strictly after curr_date (look-ahead prevention)."""
    if not curr_date or df.empty:
        return df
    try:
        cutoff = pd.to_datetime(str(curr_date).replace("-", ""), format="%Y%m%d")
        col_parsed = pd.to_datetime(df[date_col].astype(str), format="%Y%m%d", errors="coerce")
        return df[col_parsed <= cutoff].copy()
    except Exception:
        return df


# ── Public API ────────────────────────────────────────────────────────────────

def get_fundamentals(
    ticker: Annotated[str, "A-share ticker, e.g. 601298.SH"],
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Return a formatted fundamentals summary using AKShare / THS financial abstract."""
    try:
        import akshare as ak
    except ImportError:
        return "Error: akshare is not installed. Run: pip install akshare"

    if not _is_a_share(ticker):
        return f"akshare_fundamentals: {ticker} does not appear to be an A-share ticker"

    code = _to_ths_code(ticker)
    sina_id = _to_sina_prefix(ticker)

    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if curr_date:
            # THS uses YYYY-MM-DD in 报告期 column
            cutoff = pd.to_datetime(curr_date)
            df["_dt"] = pd.to_datetime(df["报告期"], errors="coerce")
            df = df[df["_dt"] <= cutoff].drop(columns=["_dt"])

        if df.empty:
            return f"No fundamentals data found for {ticker} (AKShare)"

        # THS data is ordered oldest-first; take the most recent row
        latest = df.iloc[-1]
        lines = [
            f"# AKShare Fundamentals for {ticker.upper()}",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Source: 同花顺 (THS) financial abstract",
            "",
        ]
        for col in df.columns:
            val = latest[col]
            if pd.notna(val) and str(val).strip() not in ("", "False", "NaN"):
                lines.append(f"{col}: {val}")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("AKShare get_fundamentals(%s) failed: %s", ticker, e)
        return f"Error retrieving AKShare fundamentals for {ticker}: {e}"


def get_balance_sheet(
    ticker: Annotated[str, "A-share ticker, e.g. 601298.SH"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Return balance sheet data from Sina Finance via AKShare."""
    return _get_sina_report(ticker, "资产负债表", freq, curr_date)


def get_cashflow(
    ticker: Annotated[str, "A-share ticker, e.g. 601298.SH"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Return cash flow statement from Sina Finance via AKShare."""
    return _get_sina_report(ticker, "现金流量表", freq, curr_date)


def get_income_statement(
    ticker: Annotated[str, "A-share ticker, e.g. 601298.SH"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date YYYY-MM-DD"] = None,
) -> str:
    """Return income statement from Sina Finance via AKShare."""
    return _get_sina_report(ticker, "利润表", freq, curr_date)


# ── Internal ──────────────────────────────────────────────────────────────────

def _get_sina_report(
    ticker: str,
    report_type: str,   # '资产负债表' | '利润表' | '现金流量表'
    freq: str,
    curr_date: str | None,
) -> str:
    """Fetch one of the three Sina financial reports, optionally filtered to curr_date."""
    try:
        import akshare as ak
    except ImportError:
        return "Error: akshare is not installed. Run: pip install akshare"

    if not _is_a_share(ticker):
        return f"akshare_fundamentals: {ticker} does not appear to be an A-share ticker"

    sina_id = _to_sina_prefix(ticker)
    report_label = {"资产负债表": "Balance Sheet", "利润表": "Income Statement", "现金流量表": "Cash Flow"}.get(report_type, report_type)

    try:
        df = ak.stock_financial_report_sina(stock=sina_id, symbol=report_type)

        if df is None or df.empty:
            return f"No {report_label} data found for {ticker} (AKShare)"

        # Filter by look-ahead bias
        df = _filter_by_date(df, "报告日", curr_date)

        if df.empty:
            return f"No {report_label} data before {curr_date} for {ticker} (AKShare)"

        # For annual freq, keep only year-end rows (报告日 ends with '1231')
        if freq.lower() == "annual":
            df = df[df["报告日"].astype(str).str.endswith("1231")]
            if df.empty:
                return f"No annual {report_label} data found for {ticker} (AKShare)"

        # Keep most recent N periods
        n_periods = 4 if freq.lower() == "quarterly" else 3
        df = df.head(n_periods)

        csv_string = df.to_csv(index=False)
        header = (
            f"# {report_label} ({report_type}) for {ticker.upper()} ({freq})\n"
            f"# Source: AKShare / Sina Finance\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        return header + csv_string

    except Exception as e:
        logger.warning("AKShare %s(%s) failed: %s", report_type, ticker, e)
        return f"Error retrieving AKShare {report_label} for {ticker}: {e}"
