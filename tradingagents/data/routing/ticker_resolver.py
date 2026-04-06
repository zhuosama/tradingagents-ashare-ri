"""
routing/ticker_resolver.py — 标的代码识别、自动补全与校验
============================================================
设计原则（原则三：防呆设计）：
  1. 优先尝试自动修正，失败才抛异常
  2. 使用 Python 3.10+ match-case 语法
  3. 输出 ResolvedTicker（不可变），包含 yfinance 专用 symbol

支持的输入格式：
  纯数字
    6位：按首位数字区分 个股 / ETF / 指数（沪深）
    5位：港股
  纯字母：美股
  带后缀：
    .SH / .SS → 上交所（.SS 为 yfinance 格式，统一标准化为 .SH 对外）
    .SZ       → 深交所
    .HK       → 港股
    .DE .L .PA .AS → 欧股
    无后缀字母 → 美股

市场类型枚举（market_type 字段）：
  CN_STOCK | CN_ETF | CN_INDEX | HK_STOCK | US_STOCK | EU_STOCK
"""

from __future__ import annotations

import re
from typing import Optional

from ..core.exceptions import InvalidTickerException
from ..core.models import ResolvedTicker


# ── 正则预编译 ───────────────────────────────────────────────────────────────

_RE_6DIGIT  = re.compile(r"^\d{6}$")
_RE_HK_DIGITS = re.compile(r"^\d{1,5}$")        # 港股：1-5 位纯数字（如 700 / 00700）
_RE_ALPHA   = re.compile(r"^[A-Za-z]{1,6}$")    # 纯字母：美股
_RE_WITH_SUFFIX = re.compile(
    r"^(\d+|[A-Za-z]+)\.([A-Za-z]{1,3})$"       # 带后缀，如 510300.SH
)

# 欧股后缀集合
_EU_SUFFIXES = {"DE", "L", "PA", "AS", "MI", "MC", "BR", "LS", "VI", "WA"}

# ── A 股代码分类规则（6 位数字）────────────────────────────────────────────
# 规则来源：沪深交易所代码分配惯例
_CN_ETF_PREFIXES_SH   = ("510", "511", "512", "513", "515", "516", "517", "518", "588")
_CN_ETF_PREFIXES_SZ   = ("159",)
_CN_INDEX_CODES_SH    = ("000001",)             # 上证指数（特例）
_CN_INDEX_PREFIXES_SH = ("000", "399")          # 其余 000/399 开头为指数


def _classify_6digit(code: str) -> tuple[str, str, str]:
    """
    根据 6 位纯数字代码推断交易所与类型。
    返回 (market_type, exchange_suffix, yf_suffix)
    exchange_suffix: 'SH' | 'SZ'
    yf_suffix:       'SS' | 'SZ'（yfinance 用 .SS 表示上交所）
    """
    # 特例：上证指数
    if code in _CN_INDEX_CODES_SH:
        return "CN_INDEX", "SH", "SS"

    # ETF — 上交所
    if any(code.startswith(p) for p in _CN_ETF_PREFIXES_SH):
        return "CN_ETF", "SH", "SS"

    # ETF — 深交所
    if any(code.startswith(p) for p in _CN_ETF_PREFIXES_SZ):
        return "CN_ETF", "SZ", "SZ"

    # 指数（000/399 开头）
    if any(code.startswith(p) for p in _CN_INDEX_PREFIXES_SH):
        return "CN_INDEX", "SH", "SS"

    # 个股：6 开头 → 上交所；0/3 开头 → 深交所
    if code.startswith("6"):
        return "CN_STOCK", "SH", "SS"
    if code.startswith(("0", "3")):
        return "CN_STOCK", "SZ", "SZ"

    # 兜底：无法确定，抛异常
    raise InvalidTickerException(
        raw=code,
        reason=f"6 位代码 '{code}' 首位 '{code[0]}' 无法匹配已知分类规则",
    )


def _resolve_with_suffix(code_part: str, suffix: str) -> ResolvedTicker:
    """处理带后缀的输入，如 '510300.SH'、'AAPL.US'（容错）。"""
    suffix_upper = suffix.upper()

    match suffix_upper:
        case "SH" | "SS":
            # 上交所：统一对外用 .SH，yfinance 用 .SS
            if _RE_6DIGIT.match(code_part):
                market_type, _, _ = _classify_6digit(code_part)
                return ResolvedTicker(
                    raw=f"{code_part}.{suffix}",
                    symbol=f"{code_part}.SH",
                    market_type=market_type,
                    yf_symbol=f"{code_part}.SS",
                )
            raise InvalidTickerException(
                raw=f"{code_part}.{suffix}",
                reason="上交所后缀 (.SH/.SS) 需配合 6 位数字代码",
            )

        case "SZ":
            if _RE_6DIGIT.match(code_part):
                market_type, _, _ = _classify_6digit(code_part)
                # 深交所无 000xxx 指数代码（SZ 指数均为 399xxx）；
                # _classify_6digit 的 "000" 前缀规则是针对上交所的，
                # 对 SZ 后缀需修正：000xxx.SZ 均为主板个股。
                if market_type == "CN_INDEX" and code_part.startswith("0"):
                    market_type = "CN_STOCK"
                return ResolvedTicker(
                    raw=f"{code_part}.{suffix}",
                    symbol=f"{code_part}.SZ",
                    market_type=market_type,
                    yf_symbol=f"{code_part}.SZ",
                )
            raise InvalidTickerException(
                raw=f"{code_part}.{suffix}",
                reason="深交所后缀 (.SZ) 需配合 6 位数字代码",
            )

        case "HK":
            # 港股：5 位或 4 位数字
            padded = code_part.zfill(5)   # 700 → 00700，00700 → 00700
            return ResolvedTicker(
                raw=f"{code_part}.{suffix}",
                symbol=f"{padded}.HK",
                market_type="HK_STOCK",
                yf_symbol=f"{padded}.HK",
            )

        case s if s in _EU_SUFFIXES:
            symbol = f"{code_part.upper()}.{suffix_upper}"
            return ResolvedTicker(
                raw=f"{code_part}.{suffix}",
                symbol=symbol,
                market_type="EU_STOCK",
                yf_symbol=symbol,
            )

        case _:
            raise InvalidTickerException(
                raw=f"{code_part}.{suffix}",
                suggestion=f"{code_part}.SH / {code_part}.SZ / {code_part}.HK",
                reason=f"未知后缀 '.{suffix}'",
            )


class TickerResolver:
    """
    标的代码解析器（无状态，所有方法为 staticmethod）。

    使用方式::

        resolved = TickerResolver.resolve("510300")
        # ResolvedTicker(symbol='510300.SH', market_type='CN_ETF', yf_symbol='510300.SS')

        resolved = TickerResolver.resolve("00700.HK")
        # ResolvedTicker(symbol='00700.HK', market_type='HK_STOCK', ...)
    """

    @staticmethod
    def resolve(raw: str) -> ResolvedTicker:
        """
        解析标的代码，返回标准化 ResolvedTicker。
        失败时抛出 InvalidTickerException（含建议）。
        """
        s = raw.strip()
        if not s:
            raise InvalidTickerException(raw=raw, reason="输入为空字符串")

        # 已带后缀（最常见分支，优先处理）
        m = _RE_WITH_SUFFIX.match(s)
        if m:
            return _resolve_with_suffix(m.group(1), m.group(2))

        upper = s.upper()

        # 6 位纯数字：A 股（自动补全交易所）
        if _RE_6DIGIT.match(s):
            market_type, exch, yf_exch = _classify_6digit(s)
            return ResolvedTicker(
                raw=raw,
                symbol=f"{s}.{exch}",
                market_type=market_type,
                yf_symbol=f"{s}.{yf_exch}",
            )

        # 1-5 位纯数字：港股（6 位分支已在上方处理）
        if _RE_HK_DIGITS.match(s):
            padded = s.zfill(5)
            return ResolvedTicker(
                raw=raw,
                symbol=f"{padded}.HK",
                market_type="HK_STOCK",
                yf_symbol=f"{padded}.HK",
            )

        # 纯字母（1-6 位）：美股
        if _RE_ALPHA.match(s):
            return ResolvedTicker(
                raw=raw,
                symbol=upper,
                market_type="US_STOCK",
                yf_symbol=upper,
            )

        # 兜底：无法识别
        raise InvalidTickerException(
            raw=raw,
            suggestion="示例: '510300.SH' / '00700.HK' / 'AAPL'",
            reason="格式不匹配任何已知规则",
        )
