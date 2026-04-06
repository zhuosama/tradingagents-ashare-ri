"""
adapters/yfinance_adapter.py — yfinance 数据适配器
====================================================
支持的市场类型：
  US_STOCK  : 美股（AAPL、MSFT 等）
  EU_STOCK  : 欧股（SAP.DE、SHEL.L 等）
  HK_STOCK  : 港股备用（00700.HK）
  CN_ETF    : A 股 ETF 备用（510300.SS）
  CN_STOCK  : A 股个股备用（600519.SS）
  CN_INDEX  : A 股指数备用（000001.SS）

Ticker 约定：
  - 所有 A 股上交所代码使用 .SS（yfinance 格式），由 ResolvedTicker.yf_symbol 提供
  - 港股使用 .HK，深交所使用 .SZ（yfinance 原生支持）

重试策略：
  最多 3 次，指数退避，仅对可重试错误（Timeout / RateLimit / 5xx）重试
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Optional

import pandas as pd
import requests
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from ..core.base_adapter import BaseDataAdapter
from ..core.exceptions import DataValidationError
from ..core.models import FundamentalReport, OHLCVBar, ResolvedTicker

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0   # 秒，指数退避


def _is_retryable(exc: Exception) -> bool:
    """判断异常是否值得重试（网络瞬时抖动）。"""
    if isinstance(exc, YFRateLimitError):
        return True
    if isinstance(exc, (requests.exceptions.Timeout,
                        requests.exceptions.ConnectionError)):
        return True
    msg = str(exc).lower()
    return any(kw in msg for kw in ("timeout", "connection", "429", "502", "503", "504"))


def _with_retry(fn, *args, **kwargs):
    """简单指数退避重试，仅对可重试异常生效。"""
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if not _is_retryable(e) or attempt == _MAX_RETRIES - 1:
                raise
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("yfinance 重试 %d/%d (%.1fs): %s", attempt + 1, _MAX_RETRIES, delay, e)
            time.sleep(delay)
    raise last_exc  # 不可达，但让类型检查器满意


def _df_to_bars(df: pd.DataFrame, symbol: str) -> list[OHLCVBar]:
    """
    将 yfinance 返回的 OHLCV DataFrame 转换为 list[OHLCVBar]。
    yfinance 列名：Open / High / Low / Close / Volume（首字母大写）
    """
    bars: list[OHLCVBar] = []
    for idx, row in df.iterrows():
        try:
            bars.append(OHLCVBar(
                symbol=symbol,
                trade_date=idx.date() if hasattr(idx, "date") else pd.to_datetime(idx).date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
                # yfinance 无成交额 / 换手率 / 振幅
            ))
        except Exception as e:
            logger.warning("yfinance 跳过行 %s: %s", idx, e)

    return bars


class YFinanceAdapter(BaseDataAdapter):
    """
    yfinance 数据适配器。
    Primary 数据源：US_STOCK / EU_STOCK
    Fallback 数据源：HK_STOCK / CN_ETF / CN_STOCK / CN_INDEX
    """

    SUPPORTED_MARKETS = frozenset({
        "US_STOCK", "EU_STOCK",
        "HK_STOCK",
        "CN_ETF", "CN_STOCK", "CN_INDEX",
    })

    def __init__(self, cache, proxy=None) -> None:
        super().__init__(cache=cache, proxy=proxy, source_name="yfinance")

    # ── OHLCV ────────────────────────────────────────────────────────────────

    def _fetch_ohlcv(
        self,
        resolved: ResolvedTicker,
        start: date,
        end: date,
    ) -> list[OHLCVBar]:
        """
        使用 resolved.yf_symbol 进行请求（含 .SS 转换等）。
        """
        ticker_obj = yf.Ticker(resolved.yf_symbol)
        df = _with_retry(
            ticker_obj.history,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,      # 自动复权（等效 hfq）
            timeout=60,
        )

        if df is None or df.empty:
            raise DataValidationError(
                source=self._source,
                symbol=resolved.symbol,
                field="bars",
                detail=f"yfinance 返回空 DataFrame (ticker={resolved.yf_symbol})",
            )

        return _df_to_bars(df, resolved.symbol)

    # ── 基本面 ───────────────────────────────────────────────────────────────

    def _fetch_fundamental(self, resolved: ResolvedTicker) -> FundamentalReport:
        """
        从 yfinance Ticker.info 提取估值字段。
        info 字典字段因股票/版本不同而差异极大，全部用 .get() 防护。
        """
        today = date.today()
        ticker_obj = yf.Ticker(resolved.yf_symbol)

        try:
            info = _with_retry(lambda: ticker_obj.info)
        except Exception as e:
            logger.warning("yfinance info 获取失败 %s: %s", resolved.symbol, e)
            return FundamentalReport(symbol=resolved.symbol, report_date=today)

        def _safe_float(key: str) -> Optional[float]:
            val = info.get(key)
            try:
                return float(val) if val is not None else None
            except (ValueError, TypeError):
                return None

        return FundamentalReport(
            symbol=resolved.symbol,
            report_date=today,
            pe_ttm=_safe_float("trailingPE"),
            pb=_safe_float("priceToBook"),
            ps_ttm=_safe_float("priceToSalesTrailing12Months"),
            roe=_safe_float("returnOnEquity"),
        )
