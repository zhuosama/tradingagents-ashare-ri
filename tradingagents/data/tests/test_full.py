"""
tests/test_full.py — 生产环境全覆盖集成测试
=============================================
范围：各市场各类型标的各 1 个，验证路由链与降级逻辑
  T10: CN_STOCK  — 601298.SH  青岛港（已知可用）
  T11: CN_ETF    — 510300.SH  沪深300ETF
  T12: CN_ETF    — 159928.SZ  消费ETF（深交所）
  T13: CN_INDEX  — 000300.SH  沪深300指数
  T14: HK_STOCK  — 00700.HK   腾讯
  T15: US_STOCK  — AAPL       苹果
  T16: EU_STOCK  — SAP.DE     SAP（德交所）
  T17: 基本面快照 — 510300.SH  ETF基本面
  T18: 批量并发  — 3 个 CN 标的并发拉取
  T19: 降级逻辑  — 验证 DataUnavailableError 结构

通过标准：
  - 核心字段非空率 = 100%（同 test_fast.py）
  - source_errors 包含双源信息（T19）

运行方式::
  cd TradingAgents
  .venv/Scripts/python -m pytest tradingagents/data/tests/test_full.py -v --timeout=120
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.data import DataRouter
from tradingagents.data.batch.concurrent_fetcher import fetch_ohlcv_batch
from tradingagents.data.core.exceptions import DataUnavailableError, InvalidTickerException
from tradingagents.data.core.models import FundamentalReport, OHLCVBar

_END   = date.today()
_START = _END - timedelta(days=10)


@pytest.fixture(scope="module")
def router():
    return DataRouter()


def _assert_bars_valid(bars: list[OHLCVBar], label: str) -> None:
    assert len(bars) >= 1, f"[{label}] 返回空列表"
    for bar in bars:
        for field in ("open", "high", "low", "close", "volume"):
            val = getattr(bar, field)
            assert val is not None and not math.isnan(val) and val >= 0, \
                f"[{label}] {bar.date}.{field} 校验失败: {val}"
    print(f"\n[{label}] OK — {len(bars)} bars")


# ── 市场覆盖 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ticker,label", [
    ("601298.SH", "T10/CN_STOCK/青岛港"),
    ("510300.SH", "T11/CN_ETF/沪深300ETF"),
    ("159928.SZ", "T12/CN_ETF/消费ETF"),
    ("000300.SH", "T13/CN_INDEX/沪深300指数"),
    ("00700.HK",  "T14/HK_STOCK/腾讯"),
    ("AAPL",      "T15/US_STOCK/苹果"),
    ("SAP.DE",    "T16/EU_STOCK/SAP"),
])
def test_ohlcv_all_markets(router, ticker, label):
    bars = router.get_ohlcv(ticker, _START, _END)
    _assert_bars_valid(bars, label)


# ── 基本面快照 ────────────────────────────────────────────────────────────────

def test_fundamental_cn_etf(router):
    """T17: ETF 基本面不抛异常，symbol 字段正确"""
    report: FundamentalReport = router.get_fundamental("510300.SH")
    assert report.symbol == "510300.SH"
    assert report.report_date is not None
    print(f"\n[T17] nav={report.nav}, total_assets={report.total_assets}")


def test_fundamental_us_stock(router):
    """T17b: 美股基本面（PE/PB 来自 yfinance info）"""
    report: FundamentalReport = router.get_fundamental("AAPL")
    assert report.symbol == "AAPL"
    # pe_ttm 对美股应有值，但不强制（yfinance info 字段偶发缺失）
    print(f"\n[T17b] pe_ttm={report.pe_ttm}, pb={report.pb}")


# ── 批量并发 ──────────────────────────────────────────────────────────────────

def test_batch_ohlcv(router):
    """T18: 3 个 A 股标的并发拉取"""
    tickers = ["510300.SH", "159928.SZ", "600519.SH"]
    results = fetch_ohlcv_batch(router, tickers, _START, _END, max_workers=3)

    assert set(results.keys()) == set(tickers), "返回 key 应与输入 tickers 一致"
    for ticker, value in results.items():
        if isinstance(value, Exception):
            pytest.fail(f"batch fetch failed for {ticker}: {value}")
        _assert_bars_valid(value, f"T18/{ticker}")


# ── 降级逻辑验证 ──────────────────────────────────────────────────────────────

def test_fallback_structure_on_both_fail(router):
    """
    T19: 模拟 Primary + Fallback 均失败，验证 DataUnavailableError 携带双源信息。
    使用 patch 避免真实网络请求。
    """
    from tradingagents.data.core.exceptions import DataValidationError

    with patch(
        "tradingagents.data.adapters.akshare_adapter.AKShareAdapter._fetch_ohlcv",
        side_effect=DataValidationError("akshare", "510300.SH", "bars", "mock empty"),
    ), patch(
        "tradingagents.data.adapters.yfinance_adapter.YFinanceAdapter._fetch_ohlcv",
        side_effect=DataValidationError("yfinance", "510300.SH", "bars", "mock empty"),
    ):
        with pytest.raises(DataUnavailableError) as exc_info:
            router.get_ohlcv("510300.SH", _START, _END)

    err: DataUnavailableError = exc_info.value
    assert "akshare"  in err.source_errors, "source_errors 应包含 akshare 的错误"
    assert "yfinance" in err.source_errors, "source_errors 应包含 yfinance 的错误"
    print(f"\n[T19] DataUnavailableError.source_errors={err.source_errors}")


def test_invalid_ticker_raises(router):
    """T19b: 无效 ticker 应抛 InvalidTickerException，不触发网络请求"""
    with pytest.raises(InvalidTickerException):
        router.get_ohlcv("INVALID???TICKER", _START, _END)
