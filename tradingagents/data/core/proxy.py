"""
core/proxy.py — 全局代理配置
================================
从环境变量读取代理，统一注入各 HTTP 客户端。

支持的环境变量（标准 Unix 代理约定）：
  HTTP_PROXY  / http_proxy
  HTTPS_PROXY / https_proxy
  NO_PROXY    / no_proxy

使用方式::

    from tradingagents.data.core.proxy import get_proxy_config, apply_requests_proxy

    cfg = get_proxy_config()

    # requests session
    session = requests.Session()
    apply_requests_proxy(session, cfg)

    # httpx client
    client = httpx.Client(**cfg.httpx_kwargs())

    # yfinance（通过环境变量传递，yf 内部自动读取）
    cfg.apply_env()   # 写回环境变量，供不接受显式代理的库使用
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ProxyConfig:
    """不可变代理配置对象，由 get_proxy_config() 工厂生成。"""

    http_proxy:  Optional[str]
    https_proxy: Optional[str]
    no_proxy:    Optional[str]

    @property
    def enabled(self) -> bool:
        return bool(self.http_proxy or self.https_proxy)

    def requests_proxies(self) -> dict[str, str]:
        """返回适合 requests.Session.proxies 的字典。"""
        proxies: dict[str, str] = {}
        if self.http_proxy:
            proxies["http"] = self.http_proxy
        if self.https_proxy:
            proxies["https"] = self.https_proxy
        return proxies

    def httpx_kwargs(self) -> dict:
        """返回适合 httpx.Client(**kwargs) 的关键字参数。"""
        if not self.enabled:
            return {}
        # httpx 用单个 proxies dict
        proxies: dict[str, str] = {}
        if self.http_proxy:
            proxies["http://"] = self.http_proxy
        if self.https_proxy:
            proxies["https://"] = self.https_proxy
        return {"proxies": proxies}

    def apply_env(self) -> None:
        """
        将代理配置写回当前进程环境变量。
        适用于内部直接读取环境变量的库（如 yfinance、akshare 底层 requests）。
        若值为 None 则不覆盖已有的环境变量。
        """
        if self.http_proxy:
            os.environ.setdefault("HTTP_PROXY",  self.http_proxy)
            os.environ.setdefault("http_proxy",  self.http_proxy)
        if self.https_proxy:
            os.environ.setdefault("HTTPS_PROXY", self.https_proxy)
            os.environ.setdefault("https_proxy", self.https_proxy)
        if self.no_proxy:
            os.environ.setdefault("NO_PROXY",  self.no_proxy)
            os.environ.setdefault("no_proxy",  self.no_proxy)


def get_proxy_config() -> ProxyConfig:
    """
    从当前进程环境变量构造 ProxyConfig。
    大写优先，小写次之（符合 Unix 惯例）。
    """
    def _get(upper: str, lower: str) -> Optional[str]:
        return os.environ.get(upper) or os.environ.get(lower) or None

    return ProxyConfig(
        http_proxy=_get("HTTP_PROXY",  "http_proxy"),
        https_proxy=_get("HTTPS_PROXY", "https_proxy"),
        no_proxy=_get("NO_PROXY",    "no_proxy"),
    )


def apply_requests_proxy(session, cfg: Optional[ProxyConfig] = None) -> None:
    """
    便捷函数：将代理注入 requests.Session 对象。
    cfg 为 None 时自动从环境变量读取。
    """
    import requests  # 延迟导入，避免模块加载时强依赖

    if cfg is None:
        cfg = get_proxy_config()
    if cfg.enabled:
        session.proxies.update(cfg.requests_proxies())
