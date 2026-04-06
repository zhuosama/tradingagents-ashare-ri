"""
core/base_adapter.py — 数据适配器抽象基类
==========================================
所有具体适配器（AKShare / yfinance / ...）必须继承此类。

职责分工：
  BaseDataAdapter  →  缓存查询、字段校验、_safe_call 容错
  子类 _fetch_*    →  网络请求 + 字段映射（只返回标准模型，禁止向上暴露原始 dict）

降级触发条件（双重）：
  1. 网络异常（Timeout / ConnectionError / HTTP 4xx-5xx）
  2. 数据逻辑异常（返回空列表 / 核心价格字段含 None / NaN）

降级层级：最多 1 次（由 DataRouter 负责，BaseAdapter 只负责识别和上报）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from ..cache.disk_cache import DiskCache
from .exceptions import DataValidationError
from .models import FundamentalReport, OHLCVBar, ResolvedTicker
from .proxy import ProxyConfig, get_proxy_config

logger = logging.getLogger(__name__)

# 核心 OHLCV 字段（非空率必须 = 100%）
_REQUIRED_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")


class BaseDataAdapter(ABC):
    """
    数据适配器抽象基类。

    Parameters
    ----------
    cache  : DiskCache，由 DataRouter 统一注入（跨适配器共享同一缓存实例）
    proxy  : ProxyConfig，None 时自动从环境变量读取
    source_name : str，日志/错误报告中显示的数据源名称（如 "akshare"）
    """

    #: 子类声明自己支持哪些 market_type，DataRouter 据此路由
    SUPPORTED_MARKETS: frozenset[str] = frozenset()

    def __init__(
        self,
        cache: DiskCache,
        proxy: Optional[ProxyConfig] = None,
        source_name: str = "unknown",
    ) -> None:
        self._cache = cache
        self._proxy = proxy or get_proxy_config()
        self._source = source_name
        # 将代理写入环境变量，供底层 requests/httpx 自动读取
        if self._proxy.enabled:
            self._proxy.apply_env()

    # ── 对外统一接口（策略层只调这两个）────────────────────────────────────

    def get_ohlcv(
        self,
        resolved: ResolvedTicker,
        start: date,
        end: date,
    ) -> list[OHLCVBar]:
        """
        获取日频 OHLCV 数据。
        流程：查缓存 → 未命中则 _fetch_ohlcv → 校验 → 写缓存 → 返回
        """
        # 1. 查缓存
        cached = self._cache.get_ohlcv(resolved.symbol, start, end)
        if cached is not None:
            return cached

        # 2. 网络获取（子类实现）
        bars = self._fetch_ohlcv(resolved, start, end)

        # 3. 校验
        self._validate_ohlcv(resolved.symbol, bars)

        # 4. 写缓存
        self._cache.set_ohlcv(resolved.symbol, start, end, bars)

        return bars

    def get_fundamental(self, resolved: ResolvedTicker) -> FundamentalReport:
        """
        获取基本面快照。
        流程：查缓存 → 未命中则 _fetch_fundamental → 写缓存 → 返回
        """
        today = date.today()
        cached = self._cache.get_fundamental(resolved.symbol, today)
        if cached is not None:
            return cached

        report = self._fetch_fundamental(resolved)
        self._cache.set_fundamental(resolved.symbol, today, report)
        return report

    # ── 子类必须实现 ─────────────────────────────────────────────────────────

    @abstractmethod
    def _fetch_ohlcv(
        self,
        resolved: ResolvedTicker,
        start: date,
        end: date,
    ) -> list[OHLCVBar]:
        """
        真正的网络请求 + 字段映射。
        - 必须返回 list[OHLCVBar]（可为空列表，校验在 BaseAdapter 完成）
        - 发生网络/解析异常时直接 raise，由 _safe_call 捕获
        - 绝不向上层暴露原始 dict / DataFrame 字段名
        """
        ...

    @abstractmethod
    def _fetch_fundamental(self, resolved: ResolvedTicker) -> FundamentalReport:
        """同上，网络请求 + 字段映射，返回 FundamentalReport。"""
        ...

    # ── 内部校验 ─────────────────────────────────────────────────────────────

    def _validate_ohlcv(self, symbol: str, bars: list[OHLCVBar]) -> None:
        """
        校验核心字段：
          - 列表不为空
          - 每根 K 线的 open/high/low/close/volume 均非 None（Pydantic 已保证类型，
            此处额外检查 NaN）
        触发 DataValidationError 即降级（与网络异常同等对待）。
        """
        import math

        if not bars:
            raise DataValidationError(
                source=self._source,
                symbol=symbol,
                field="bars",
                detail="返回空列表，无交易数据",
            )

        for bar in bars:
            for field_name in _REQUIRED_OHLCV_FIELDS:
                val = getattr(bar, field_name)
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    raise DataValidationError(
                        source=self._source,
                        symbol=symbol,
                        field=field_name,
                        detail=f"第 {bar.trade_date} 条数据核心字段 '{field_name}' 为 None/NaN",
                    )

    # ── 静态容错包装（供 DataRouter 调用）───────────────────────────────────

    @staticmethod
    def safe_call(fn, *args, **kwargs) -> tuple[Optional[object], Optional[str]]:
        """
        调用 fn(*args, **kwargs)，捕获所有异常。

        Returns
        -------
        (result, None)   : 成功
        (None, error_str): 失败（网络 / 数据校验 / 其他）

        DataRouter 据此判断是否触发 Fallback。
        """
        try:
            return fn(*args, **kwargs), None
        except Exception as e:
            logger.warning("[safe_call] %s: %s", type(e).__name__, e)
            return None, f"{type(e).__name__}: {e}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(source={self._source})"
