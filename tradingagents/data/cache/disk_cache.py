"""
cache/disk_cache.py — SQLite 持久化缓存层
==========================================
基于 diskcache 封装，支持：
  - TTL 分级：基础信息 7 天 / 日线行情至次日开盘前
  - 跨分支共享：默认目录 ~/.tradingagents/cache/
  - 环境变量覆盖：TRADINGAGENTS_CACHE_DIR
  - 并发安全：diskcache 内部使用 SQLite WAL 模式，多进程安全

缓存 Key 约定：
  OHLCV:       "ohlcv:{symbol}:{start}:{end}"
  Fundamental: "fundamental:{symbol}:{report_date}"
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import diskcache

logger = logging.getLogger(__name__)

# ── TTL 常量 ────────────────────────────────────────────────────────────────

TTL_FUNDAMENTAL_SECS = 7 * 24 * 3600          # 基础信息 / 持仓：7 天
TTL_OHLCV_SECS       = 1 * 24 * 3600          # 日线默认 TTL（实际由 _ohlcv_ttl() 动态计算）

# A 股开盘时间（北京时间 09:30）
_CN_MARKET_OPEN_HOUR   = 9
_CN_MARKET_OPEN_MINUTE = 30


def _ohlcv_ttl() -> int:
    """
    计算日线行情 TTL：距离下一个交易日 09:30（北京时间）的秒数。
    粗略实现：若当前为非交易时段，缓存到今日 09:30；
    若已过 09:30 则缓存到明日 09:30。
    实际交易日历判断由调用方根据业务需要扩展。
    """
    now = datetime.now()
    next_open = now.replace(
        hour=_CN_MARKET_OPEN_HOUR,
        minute=_CN_MARKET_OPEN_MINUTE,
        second=0,
        microsecond=0,
    )
    if now >= next_open:
        next_open += timedelta(days=1)
    ttl = int((next_open - now).total_seconds())
    return max(ttl, 60)   # 至少 60 秒，防止 TTL=0


def _default_cache_dir() -> Path:
    """
    默认缓存目录：~/.tradingagents/cache/
    可通过环境变量 TRADINGAGENTS_CACHE_DIR 覆盖（支持容器化部署）。
    """
    env_dir = os.environ.get("TRADINGAGENTS_CACHE_DIR", "")
    if env_dir:
        base = Path(env_dir)
    else:
        base = Path.home() / ".tradingagents" / "cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


class DiskCache:
    """
    diskcache.Cache 的薄封装，提供 TTL 分级语义。

    Parameters
    ----------
    cache_dir : Path, optional
        缓存根目录。默认由 _default_cache_dir() 决定。
    size_limit : int
        最大磁盘占用字节，默认 2 GB。
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        size_limit: int = 2 * 1024 ** 3,
    ) -> None:
        self._dir = cache_dir or _default_cache_dir()
        self._cache = diskcache.Cache(
            str(self._dir),
            size_limit=size_limit,
            eviction_policy="least-recently-used",
        )
        logger.debug("DiskCache initialized at %s", self._dir)

    # ── 通用读写 ─────────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        value = self._cache.get(key, default=None)
        if value is not None:
            logger.debug("Cache HIT: %s", key)
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._cache.set(key, value, expire=ttl)
        logger.debug("Cache SET: %s (TTL=%ds)", key, ttl)

    def delete(self, key: str) -> None:
        self._cache.delete(key)

    def clear(self) -> None:
        """清空全部缓存（测试 / 强制刷新用）。"""
        self._cache.clear()
        logger.info("DiskCache cleared at %s", self._dir)

    # ── 语义化快捷方法 ────────────────────────────────────────────────────────

    def get_ohlcv(self, symbol: str, start: date, end: date) -> Optional[Any]:
        return self.get(self._ohlcv_key(symbol, start, end))

    def set_ohlcv(self, symbol: str, start: date, end: date, value: Any) -> None:
        self.set(self._ohlcv_key(symbol, start, end), value, ttl=_ohlcv_ttl())

    def get_fundamental(self, symbol: str, report_date: date) -> Optional[Any]:
        return self.get(self._fundamental_key(symbol, report_date))

    def set_fundamental(self, symbol: str, report_date: date, value: Any) -> None:
        self.set(
            self._fundamental_key(symbol, report_date),
            value,
            ttl=TTL_FUNDAMENTAL_SECS,
        )

    # ── Key 构造 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _ohlcv_key(symbol: str, start: date, end: date) -> str:
        return f"ohlcv:{symbol}:{start.isoformat()}:{end.isoformat()}"

    @staticmethod
    def _fundamental_key(symbol: str, report_date: date) -> str:
        return f"fundamental:{symbol}:{report_date.isoformat()}"

    def __repr__(self) -> str:
        return f"DiskCache(dir={self._dir}, size={len(self._cache)})"
