"""
routing/data_router.py — 数据路由工厂（对外唯一入口）
=======================================================
职责：
  1. 接收原始 ticker 字符串，调用 TickerResolver 标准化
  2. 根据 market_type 选择 Primary 适配器
  3. 最多 1 次自动降级（Primary 失败 → Fallback → raise DataUnavailableError）
  4. 管理适配器实例与缓存（单例模式，跨调用共享）

降级链：
  CN_STOCK / CN_ETF / CN_INDEX → AKShare  ➜ yfinance
  HK_STOCK                     → AKShare  ➜ yfinance
  US_STOCK / EU_STOCK          → yfinance ➜ (无 Fallback，直接 raise)

环境变量：
  TRADINGAGENTS_CACHE_DIR : 覆盖缓存目录（默认 ~/.tradingagents/cache/）
  HTTP_PROXY / HTTPS_PROXY : 全局代理

使用示例::

    from tradingagents.data import DataRouter
    from datetime import date

    router = DataRouter()
    bars = router.get_ohlcv("510300", date(2024, 1, 1), date(2024, 12, 31))
    report = router.get_fundamental("AAPL")
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from ..adapters.akshare_adapter import AKShareAdapter
from ..adapters.yfinance_adapter import YFinanceAdapter
from ..cache.disk_cache import DiskCache
from ..core.base_adapter import BaseDataAdapter
from ..core.exceptions import DataUnavailableError, InvalidTickerException
from ..core.models import FundamentalReport, OHLCVBar, ResolvedTicker
from ..core.proxy import ProxyConfig, get_proxy_config
from .ticker_resolver import TickerResolver

logger = logging.getLogger(__name__)


# ── 降级链配置 ───────────────────────────────────────────────────────────────
# market_type → (primary_adapter_class, fallback_adapter_class | None)
_FALLBACK_CHAIN: dict[str, tuple[type, Optional[type]]] = {
    "CN_STOCK": (AKShareAdapter, YFinanceAdapter),
    "CN_ETF":   (AKShareAdapter, YFinanceAdapter),
    "CN_INDEX": (AKShareAdapter, YFinanceAdapter),
    "HK_STOCK": (AKShareAdapter, YFinanceAdapter),
    "US_STOCK": (YFinanceAdapter, None),
    "EU_STOCK": (YFinanceAdapter, None),
}


class DataRouter:
    """
    数据路由工厂，系统唯一对外接口。

    Parameters
    ----------
    cache_dir : Path, optional
        缓存目录。None 时优先读取 TRADINGAGENTS_CACHE_DIR 环境变量，
        再退回 ~/.tradingagents/cache/
    proxy : ProxyConfig, optional
        代理配置。None 时自动从环境变量读取。
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        proxy: Optional[ProxyConfig] = None,
    ) -> None:
        self._proxy = proxy or get_proxy_config()
        self._cache = DiskCache(cache_dir=cache_dir)
        # 适配器实例池（按类型懒创建，跨请求复用）
        self._adapters: dict[type, BaseDataAdapter] = {}

    # ── 对外接口 ─────────────────────────────────────────────────────────────

    def get_ohlcv(
        self,
        raw_ticker: str,
        start: date,
        end: date,
    ) -> list[OHLCVBar]:
        """
        获取日频 OHLCV 数据，自动路由 + 最多 1 次降级。

        Parameters
        ----------
        raw_ticker : 任意格式，如 '510300' / '510300.SH' / 'AAPL' / '00700.HK'
        start, end : 日期区间（含两端）

        Raises
        ------
        InvalidTickerException  : ticker 无法识别且无法自动修正
        DataUnavailableError    : Primary + Fallback 均失败
        """
        resolved = self._resolve(raw_ticker)
        return self._call_with_fallback(
            resolved,
            method="get_ohlcv",
            kwargs={"resolved": resolved, "start": start, "end": end},
        )

    def get_fundamental(self, raw_ticker: str) -> FundamentalReport:
        """
        获取基本面快照，自动路由 + 最多 1 次降级。

        Raises
        ------
        InvalidTickerException  : ticker 无法识别
        DataUnavailableError    : Primary + Fallback 均失败
        """
        resolved = self._resolve(raw_ticker)
        return self._call_with_fallback(
            resolved,
            method="get_fundamental",
            kwargs={"resolved": resolved},
        )

    # ── 内部路由逻辑 ──────────────────────────────────────────────────────────

    def _resolve(self, raw_ticker: str) -> ResolvedTicker:
        """调用 TickerResolver，InvalidTickerException 直接向上传播。"""
        return TickerResolver.resolve(raw_ticker)

    def _call_with_fallback(
        self,
        resolved: ResolvedTicker,
        method: str,
        kwargs: dict,
    ):
        """
        按降级链调用适配器，最多 1 次降级。
        """
        market_type = resolved.market_type
        if market_type not in _FALLBACK_CHAIN:
            raise DataUnavailableError(
                symbol=resolved.symbol,
                source_errors={"router": f"未配置市场类型 '{market_type}' 的降级链"},
            )

        primary_cls, fallback_cls = _FALLBACK_CHAIN[market_type]
        source_errors: dict[str, str] = {}

        # Primary
        primary = self._get_adapter(primary_cls)
        result, err = BaseDataAdapter.safe_call(
            getattr(primary, method), **kwargs
        )
        if result is not None:
            return result
        source_errors[primary._source] = err or "unknown error"
        logger.warning(
            "[DataRouter] %s Primary(%s) 失败，尝试 Fallback: %s",
            method, primary._source, err,
        )

        # Fallback（最多 1 次）
        if fallback_cls is None:
            raise DataUnavailableError(symbol=resolved.symbol, source_errors=source_errors)

        fallback = self._get_adapter(fallback_cls)
        result, err = BaseDataAdapter.safe_call(
            getattr(fallback, method), **kwargs
        )
        if result is not None:
            logger.info(
                "[DataRouter] %s Fallback(%s) 成功: %s",
                method, fallback._source, resolved.symbol,
            )
            return result

        source_errors[fallback._source] = err or "unknown error"
        raise DataUnavailableError(symbol=resolved.symbol, source_errors=source_errors)

    def _get_adapter(self, cls: type) -> BaseDataAdapter:
        """懒创建并缓存适配器实例（同一类型全局单例）。"""
        if cls not in self._adapters:
            self._adapters[cls] = cls(cache=self._cache, proxy=self._proxy)
        return self._adapters[cls]

    def clear_cache(self) -> None:
        """清空本地缓存（开发调试 / 强制刷新用）。"""
        self._cache.clear()
        logger.info("DataRouter: cache cleared")

    def __repr__(self) -> str:
        return f"DataRouter(cache={self._cache}, proxy_enabled={self._proxy.enabled})"
