"""
core/exceptions.py — 数据模块自定义异常
=========================================
设计原则：
  - 所有异常均携带结构化信息，供 Agent 提示词直接消费，无需解析 traceback
  - 异常层级：InvalidTickerException（输入问题）> DataUnavailableError（数据源问题）
"""

from __future__ import annotations


class InvalidTickerException(Exception):
    """
    代码格式无法识别，或自动修正后调用仍失败。

    Attributes
    ----------
    raw:        用户原始输入
    suggestion: 建议的标准格式（如能推断），否则为空字符串
    reason:     具体原因描述
    """

    def __init__(self, raw: str, suggestion: str = "", reason: str = "") -> None:
        self.raw = raw
        self.suggestion = suggestion
        self.reason = reason

        msg = f"无法识别的标的代码: '{raw}'"
        if suggestion:
            msg += f"  →  建议格式: '{suggestion}'"
        if reason:
            msg += f"  ({reason})"
        super().__init__(msg)

    def to_dict(self) -> dict:
        return {
            "error": "InvalidTickerException",
            "raw": self.raw,
            "suggestion": self.suggestion,
            "reason": self.reason,
        }


class DataUnavailableError(Exception):
    """
    Primary + Fallback 数据源均失败。
    携带结构化错误日志，供上层 Agent 诊断。

    Attributes
    ----------
    symbol:        标准化后的标的代码
    source_errors: {数据源名称: 错误描述}，最多两条（Primary + Fallback）
    """

    def __init__(self, symbol: str, source_errors: dict[str, str]) -> None:
        self.symbol = symbol
        self.source_errors = source_errors

        details = "; ".join(f"[{src}] {err}" for src, err in source_errors.items())
        super().__init__(f"数据获取失败 '{symbol}': {details}")

    def to_dict(self) -> dict:
        return {
            "error": "DataUnavailableError",
            "symbol": self.symbol,
            "source_errors": self.source_errors,
        }


class DataValidationError(Exception):
    """
    数据通过网络获取成功，但核心字段校验失败（如收盘价空值率 > 0%）。
    触发降级逻辑，与网络异常同等对待。

    Attributes
    ----------
    source:    数据源名称
    symbol:    标的代码
    field:     导致失败的字段名
    detail:    具体校验描述
    """

    def __init__(self, source: str, symbol: str, field: str, detail: str) -> None:
        self.source = source
        self.symbol = symbol
        self.field = field
        self.detail = detail
        super().__init__(
            f"[{source}] '{symbol}' 数据校验失败 — 字段 '{field}': {detail}"
        )
