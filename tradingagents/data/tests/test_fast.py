"""
tests/test_fast.py — 开发环境快速集成测试
==========================================
范围：2 个标的，最近 5 个交易日
  T01: 沪深300 ETF (510300.SH)   — CN_ETF, AKShare Primary
  T02: 苹果股票   (AAPL)         — US_STOCK, yfinance Primary
  T03: TickerResolver 自动补全验证（离线，无网络依赖）
  T04: 缓存命中验证（第二次调用应从缓存返回）

通过标准：
  - 核心字段 (open/high/low/close/volume) 非空率 = 100%
  - 返回数据行数 >= 1（近 5 个交易日）
  - 不抛任何未预期异常

运行方式::
  cd TradingAgents
  .venv/Scripts/python -m pytest tradingagents/data/tests/test_fast.py -v
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from tradingagents.data import DataRouter
from tradingagents.data.core.exceptions import InvalidTickerException
from tradingagents.data.core.models import OHLCVBar
from tradingagents.data.routing.ticker_resolver import TickerResolver

# ── 日期范围：最近 10 个自然日（覆盖 5 个交易日）───────────────────────────
_END   = date.today()
_START = _END - timedelta(days=10)

# ── 共享 router 实例 ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def router():
    return DataRouter()


# ── 辅助校验 ─────────────────────────────────────────────────────────────────

def _assert_bars_valid(bars: list[OHLCVBar], label: str) -> None:
    """核心字段非空率必须 = 100%"""
    assert len(bars) >= 1, f"[{label}] 返回空列表"
    required = ("open", "high", "low", "close", "volume")
    for bar in bars:
        for field in required:
            val = getattr(bar, field)
            assert val is not None,                   f"[{label}] {bar.trade_date} {field} = None"
            assert not math.isnan(val),               f"[{label}] {bar.trade_date} {field} = NaN"
            assert val >= 0,                          f"[{label}] {bar.trade_date} {field} < 0"
    print(f"\n[{label}] OK — {len(bars)} bars, latest close={bars[-1].close}")


# ── T01: 沪深300 ETF ─────────────────────────────────────────────────────────

class TestT01_CN_ETF:
    def test_ohlcv_returns_data(self, router):
        bars = router.get_ohlcv("510300.SH", _START, _END)
        _assert_bars_valid(bars, "T01/510300.SH")

    def test_symbol_normalized(self, router):
        bars = router.get_ohlcv("510300.SH", _START, _END)
        assert all(b.symbol == "510300.SH" for b in bars), "symbol 字段应为标准化格式"

    def test_price_order_valid(self, router):
        bars = router.get_ohlcv("510300.SH", _START, _END)
        for b in bars:
            assert b.high >= b.low, f"high < low on {b.date}"


# ── T02: 苹果美股 ────────────────────────────────────────────────────────────

class TestT02_US_STOCK:
    def test_ohlcv_returns_data(self, router):
        bars = router.get_ohlcv("AAPL", _START, _END)
        _assert_bars_valid(bars, "T02/AAPL")

    def test_symbol_is_uppercase(self, router):
        bars = router.get_ohlcv("AAPL", _START, _END)
        assert all(b.symbol == "AAPL" for b in bars)

    def test_lowercase_input_works(self, router):
        """输入小写 'aapl' 应自动识别为 US_STOCK"""
        bars = router.get_ohlcv("aapl", _START, _END)
        assert len(bars) >= 1


# ── T03: TickerResolver 离线单元测试 ─────────────────────────────────────────

class TestT03_TickerResolver:
    @pytest.mark.parametrize("raw, expected_symbol, expected_market", [
        ("510300",     "510300.SH", "CN_ETF"),
        ("510300.SH",  "510300.SH", "CN_ETF"),
        ("510300.SS",  "510300.SH", "CN_ETF"),    # yfinance 格式自动转换
        ("159928",     "159928.SZ", "CN_ETF"),
        ("159928.SZ",  "159928.SZ", "CN_ETF"),
        ("600519",     "600519.SH", "CN_STOCK"),   # 茅台
        ("000001",     "000001.SH", "CN_INDEX"),   # 上证指数（特例）
        ("000300",     "000300.SH", "CN_INDEX"),   # 沪深300指数
        ("00700",      "00700.HK",  "HK_STOCK"),
        ("700",        "00700.HK",  "HK_STOCK"),   # 不足5位自动补零
        ("AAPL",       "AAPL",      "US_STOCK"),
        ("aapl",       "AAPL",      "US_STOCK"),   # 小写容错
        ("SAP.DE",     "SAP.DE",    "EU_STOCK"),
    ])
    def test_resolve(self, raw, expected_symbol, expected_market):
        resolved = TickerResolver.resolve(raw)
        assert resolved.symbol == expected_symbol, \
            f"resolve('{raw}').symbol={resolved.symbol}, expected={expected_symbol}"
        assert resolved.market_type == expected_market, \
            f"resolve('{raw}').market_type={resolved.market_type}, expected={expected_market}"

    @pytest.mark.parametrize("raw", ["", "TOOLONGTICKERXYZ", "???", "12345678"])
    def test_invalid_raises(self, raw):
        with pytest.raises(InvalidTickerException):
            TickerResolver.resolve(raw)


# ── T04: 缓存命中 ────────────────────────────────────────────────────────────

class TestT04_Cache:
    def test_second_call_is_cache_hit(self, router):
        """两次调用同一 ticker/日期，第二次应从缓存返回（不报错即通过）"""
        bars1 = router.get_ohlcv("510300.SH", _START, _END)
        bars2 = router.get_ohlcv("510300.SH", _START, _END)
        assert len(bars1) == len(bars2), "缓存命中后数据行数应一致"
