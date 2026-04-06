"""
batch/concurrent_fetcher.py — 并发批量数据获取
================================================
基于 ThreadPoolExecutor（非 asyncio），原因：
  - AKShare / yfinance 底层均为同步 requests，asyncio 包装会引入隐患
  - ThreadPoolExecutor 在 Windows 上行为更稳定
  - GIL 对 I/O 密集型任务无影响，并发效果等同

使用示例::

    from tradingagents.data.batch.concurrent_fetcher import fetch_ohlcv_batch
    from tradingagents.data import DataRouter
    from datetime import date

    router = DataRouter()
    results = fetch_ohlcv_batch(
        router,
        tickers=["510300.SH", "159928.SZ", "AAPL"],
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        max_workers=4,
    )
    # results: {"510300.SH": list[OHLCVBar] | Exception, ...}
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Union

from ..core.models import FundamentalReport, OHLCVBar

logger = logging.getLogger(__name__)

# 默认并发数：避免过多并发触发 AKShare 限流
_DEFAULT_MAX_WORKERS = 4


def fetch_ohlcv_batch(
    router,
    tickers: list[str],
    start: date,
    end: date,
    max_workers: int = _DEFAULT_MAX_WORKERS,
) -> dict[str, Union[list[OHLCVBar], Exception]]:
    """
    并发批量获取多个标的的 OHLCV 数据。

    Parameters
    ----------
    router     : DataRouter 实例
    tickers    : 原始 ticker 列表（支持混合格式）
    start, end : 日期区间
    max_workers: 最大并发线程数，默认 4

    Returns
    -------
    dict，key 为原始 ticker，value 为 list[OHLCVBar] 或捕获的 Exception。
    调用方自行判断 isinstance(value, Exception) 决定如何处理失败项。
    """
    results: dict[str, Union[list[OHLCVBar], Exception]] = {}

    def _fetch_one(ticker: str):
        return ticker, router.get_ohlcv(ticker, start, end)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(future_map):
            raw_ticker = future_map[future]
            try:
                ticker, bars = future.result()
                results[ticker] = bars
                logger.debug("fetch_ohlcv_batch OK: %s (%d bars)", ticker, len(bars))
            except Exception as e:
                results[raw_ticker] = e
                logger.warning("fetch_ohlcv_batch FAIL: %s — %s", raw_ticker, e)

    return results


def fetch_fundamental_batch(
    router,
    tickers: list[str],
    max_workers: int = _DEFAULT_MAX_WORKERS,
) -> dict[str, Union[FundamentalReport, Exception]]:
    """
    并发批量获取多个标的的基本面快照。

    Returns
    -------
    dict，key 为原始 ticker，value 为 FundamentalReport 或 Exception。
    """
    results: dict[str, Union[FundamentalReport, Exception]] = {}

    def _fetch_one(ticker: str):
        return ticker, router.get_fundamental(ticker)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(future_map):
            raw_ticker = future_map[future]
            try:
                ticker, report = future.result()
                results[ticker] = report
                logger.debug("fetch_fundamental_batch OK: %s", ticker)
            except Exception as e:
                results[raw_ticker] = e
                logger.warning("fetch_fundamental_batch FAIL: %s — %s", raw_ticker, e)

    return results
