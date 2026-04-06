"""
tradingagents.data — 统一数据基建包
=====================================
对外唯一入口：DataRouter（工厂模式，自动路由数据源与降级）

快速使用::

    from tradingagents.data import DataRouter
    router = DataRouter()
    bars = router.get_ohlcv("510300.SH", start=date(2024,1,1), end=date(2024,12,31))
"""

from .routing.data_router import DataRouter

__all__ = ["DataRouter"]
