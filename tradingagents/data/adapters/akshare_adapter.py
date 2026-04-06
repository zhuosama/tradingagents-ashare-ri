"""
adapters/akshare_adapter.py — AKShare 数据适配器
==================================================
支持的市场类型：
  CN_STOCK  : ak.stock_zh_a_hist
  CN_ETF    : ak.fund_etf_hist_em
  CN_INDEX  : ak.index_zh_a_hist
  HK_STOCK  : ak.stock_hk_hist

字段映射（AKShare → 标准 OHLCVBar）：
  AKShare 列名因接口不同而不同，统一在 _FIELD_MAP_* 中处理。

AKShare 版本兼容性：
  - 锁定 1.18.51，所有函数调用前均通过 hasattr 检查
  - hasattr 检查失败时抛出 DataValidationError，触发降级
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd

from ..core.base_adapter import BaseDataAdapter
from ..core.exceptions import DataValidationError
from ..core.models import FundamentalReport, OHLCVBar, ResolvedTicker

logger = logging.getLogger(__name__)


# ── 字段映射表 ───────────────────────────────────────────────────────────────
# AKShare 各接口返回的列名不统一，在此集中管理

# stock_zh_a_hist / fund_etf_hist_em / index_zh_a_hist
_FIELD_MAP_CN = {
    "日期":   "date",
    "开盘":   "open",
    "最高":   "high",
    "最低":   "low",
    "收盘":   "close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "振幅":   "amplitude",
    "涨跌幅": "change_pct",
}

# stock_hk_hist
_FIELD_MAP_HK = {
    "日期":   "date",
    "开盘":   "open",
    "最高":   "high",
    "最低":   "low",
    "收盘":   "close",
    "成交量": "volume",
    "成交额": "amount",
    "涨跌幅": "change_pct",
}


def _df_to_bars(df: pd.DataFrame, symbol: str, field_map: dict) -> list[OHLCVBar]:
    """
    将 AKShare 返回的 DataFrame 按字段映射转换为 list[OHLCVBar]。
    无法映射的列静默忽略；核心字段缺失由 base_adapter 校验捕获。
    """
    df = df.rename(columns=field_map)
    bars: list[OHLCVBar] = []

    for _, row in df.iterrows():
        try:
            bars.append(OHLCVBar(
                symbol=symbol,
                trade_date=pd.to_datetime(row["date"]).date(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                amount=float(row["amount"])   if "amount"    in row.index and pd.notna(row.get("amount"))   else None,
                turnover=float(row["turnover"]) if "turnover"  in row.index and pd.notna(row.get("turnover")) else None,
                amplitude=float(row["amplitude"]) if "amplitude" in row.index and pd.notna(row.get("amplitude")) else None,
                change_pct=float(row["change_pct"]) if "change_pct" in row.index and pd.notna(row.get("change_pct")) else None,
            ))
        except Exception as e:
            logger.warning("跳过行 %s: %s", row.get("date", "?"), e)

    return bars


def _parse_code(symbol: str) -> tuple[str, str]:
    """
    '510300.SH' → ('510300', 'sh')
    '159928.SZ' → ('159928', 'sz')
    """
    code, exch = symbol.rsplit(".", 1)
    return code, exch.lower()


class AKShareAdapter(BaseDataAdapter):
    """
    AKShare 数据适配器。
    Primary 数据源：CN_STOCK / CN_ETF / CN_INDEX / HK_STOCK
    """

    SUPPORTED_MARKETS = frozenset({"CN_STOCK", "CN_ETF", "CN_INDEX", "HK_STOCK"})

    def __init__(self, cache, proxy=None) -> None:
        super().__init__(cache=cache, proxy=proxy, source_name="akshare")
        # 延迟导入：避免模块加载时触发 akshare 初始化（较慢）
        self._ak = None

    def _get_ak(self):
        """懒加载 akshare，仅在首次请求时导入。"""
        if self._ak is None:
            import akshare as ak
            self._ak = ak
        return self._ak

    def _check_func(self, func_name: str):
        """
        检查 AKShare 是否存在指定函数（版本兼容性防护）。
        不存在则抛 DataValidationError，触发降级到 yfinance。
        """
        ak = self._get_ak()
        if not hasattr(ak, func_name):
            raise DataValidationError(
                source=self._source,
                symbol="",
                field=func_name,
                detail=f"当前 AKShare 版本不支持函数 '{func_name}'，请检查版本锁定",
            )
        return getattr(ak, func_name)

    # ── OHLCV 获取 ───────────────────────────────────────────────────────────

    def _fetch_ohlcv(
        self,
        resolved: ResolvedTicker,
        start: date,
        end: date,
    ) -> list[OHLCVBar]:
        match resolved.market_type:
            case "CN_STOCK":
                return self._fetch_cn_stock(resolved.symbol, start, end)
            case "CN_ETF":
                return self._fetch_cn_etf(resolved.symbol, start, end)
            case "CN_INDEX":
                return self._fetch_cn_index(resolved.symbol, start, end)
            case "HK_STOCK":
                return self._fetch_hk_stock(resolved.symbol, start, end)
            case _:
                raise DataValidationError(
                    source=self._source,
                    symbol=resolved.symbol,
                    field="market_type",
                    detail=f"AKShareAdapter 不支持 market_type='{resolved.market_type}'",
                )

    def _fetch_cn_stock(self, symbol: str, start: date, end: date) -> list[OHLCVBar]:
        fn = self._check_func("stock_zh_a_hist")
        code, _ = _parse_code(symbol)
        df = fn(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="hfq",   # 后复权，适合回测
        )
        if df is None or df.empty:
            raise DataValidationError(self._source, symbol, "bars", "返回空 DataFrame")
        return _df_to_bars(df, symbol, _FIELD_MAP_CN)

    def _fetch_cn_etf(self, symbol: str, start: date, end: date) -> list[OHLCVBar]:
        fn = self._check_func("fund_etf_hist_em")
        code, _ = _parse_code(symbol)
        df = fn(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="hfq",
        )
        if df is None or df.empty:
            raise DataValidationError(self._source, symbol, "bars", "返回空 DataFrame")
        return _df_to_bars(df, symbol, _FIELD_MAP_CN)

    def _fetch_cn_index(self, symbol: str, start: date, end: date) -> list[OHLCVBar]:
        fn = self._check_func("index_zh_a_hist")
        code, _ = _parse_code(symbol)
        df = fn(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            raise DataValidationError(self._source, symbol, "bars", "返回空 DataFrame")
        return _df_to_bars(df, symbol, _FIELD_MAP_CN)

    def _fetch_hk_stock(self, symbol: str, start: date, end: date) -> list[OHLCVBar]:
        fn = self._check_func("stock_hk_hist")
        code, _ = _parse_code(symbol)
        df = fn(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="hfq",
        )
        if df is None or df.empty:
            raise DataValidationError(self._source, symbol, "bars", "返回空 DataFrame")
        return _df_to_bars(df, symbol, _FIELD_MAP_HK)

    # ── 基本面获取 ───────────────────────────────────────────────────────────

    def _fetch_fundamental(self, resolved: ResolvedTicker) -> FundamentalReport:
        """
        基本面数据：按市场类型分发。
        所有字段均 Optional；获取失败的字段静默置 None（不触发降级）。
        """
        today = date.today()

        match resolved.market_type:
            case "CN_ETF":
                return self._fetch_etf_fundamental(resolved.symbol, today)
            case "CN_STOCK":
                return self._fetch_stock_fundamental(resolved.symbol, today)
            case "CN_INDEX":
                return self._fetch_index_fundamental(resolved.symbol, today)
            case _:
                # HK_STOCK 等暂无基本面实现，返回空报告
                return FundamentalReport(symbol=resolved.symbol, report_date=today)

    def _fetch_etf_fundamental(self, symbol: str, today: date) -> FundamentalReport:
        """ETF：净值 + 规模（fund_etf_spot_em）。"""
        code, _ = _parse_code(symbol)
        nav: Optional[float] = None
        total_assets: Optional[float] = None

        try:
            fn = self._check_func("fund_etf_spot_em")
            df = fn()
            if df is not None and not df.empty:
                row = df[df["代码"] == code]
                if not row.empty:
                    nav = float(row.iloc[0].get("最新价", 0) or 0) or None
                    # 规模单位：亿元
                    total_assets_raw = row.iloc[0].get("基金规模(亿元)", None)
                    total_assets = float(total_assets_raw) if total_assets_raw else None
        except Exception as e:
            logger.warning("ETF fundamental (spot) failed for %s: %s", symbol, e)

        return FundamentalReport(
            symbol=symbol,
            report_date=today,
            nav=nav,
            total_assets=total_assets,
        )

    def _fetch_stock_fundamental(self, symbol: str, today: date) -> FundamentalReport:
        """
        个股估值 + 财务指标，使用两个 AKShare 1.18.51 可用接口：
          - stock_zh_valuation_baidu : PE TTM / PB（实时，百度财经数据）
          - stock_financial_analysis_indicator : ROE / 营收增速 / 净利润增速（季报）
        """
        import datetime as _dt
        code, _ = _parse_code(symbol)
        pe_ttm: Optional[float] = None
        pb: Optional[float] = None
        roe: Optional[float] = None
        revenue_yoy: Optional[float] = None
        net_profit_yoy: Optional[float] = None

        # ── PE TTM（stock_zh_valuation_baidu）────────────────────────────
        try:
            fn_val = self._check_func("stock_zh_valuation_baidu")
            df_pe = fn_val(symbol=code, indicator="市盈率(TTM)")
            if df_pe is not None and not df_pe.empty:
                pe_ttm = float(df_pe.iloc[-1]["value"]) or None
        except Exception as e:
            logger.warning("PE TTM failed for %s: %s", symbol, e)

        # ── PB（stock_zh_valuation_baidu）────────────────────────────────
        try:
            fn_val = self._check_func("stock_zh_valuation_baidu")
            df_pb = fn_val(symbol=code, indicator="市净率")
            if df_pb is not None and not df_pb.empty:
                pb = float(df_pb.iloc[-1]["value"]) or None
        except Exception as e:
            logger.warning("PB failed for %s: %s", symbol, e)

        # ── ROE / 营收增速 / 净利润增速（stock_financial_analysis_indicator）──
        try:
            fn_fin = self._check_func("stock_financial_analysis_indicator")
            start_year = str(today.year - 1)
            df_fin = fn_fin(symbol=code, start_year=start_year)
            if df_fin is not None and not df_fin.empty:
                latest = df_fin.iloc[-1]
                def _safe(col):
                    v = latest.get(col)
                    try:
                        return float(v) if v is not None else None
                    except (ValueError, TypeError):
                        return None
                roe            = _safe("净资产收益率(%)")
                revenue_yoy    = _safe("主营业务收入增长率(%)")
                net_profit_yoy = _safe("净利润增长率(%)")
        except Exception as e:
            logger.warning("Financial indicator failed for %s: %s", symbol, e)

        return FundamentalReport(
            symbol=symbol,
            report_date=today,
            pe_ttm=pe_ttm,
            pb=pb,
            roe=roe,
            revenue_yoy=revenue_yoy,
            net_profit_yoy=net_profit_yoy,
        )

    def _fetch_index_fundamental(self, symbol: str, today: date) -> FundamentalReport:
        """指数：PE/PB 历史分位（index_value_hist_funddata_em）。"""
        code, _ = _parse_code(symbol)
        pe_ttm: Optional[float] = None
        index_pe_percentile: Optional[float] = None

        try:
            fn = self._check_func("index_value_hist_funddata_em")
            df = fn(symbol=code, indicator="市盈率(TTM)")
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                pe_ttm = float(latest.get("value", 0) or 0) or None
        except Exception as e:
            logger.warning("Index fundamental (PE) failed for %s: %s", symbol, e)

        return FundamentalReport(
            symbol=symbol,
            report_date=today,
            pe_ttm=pe_ttm,
            index_pe_percentile=index_pe_percentile,
        )
