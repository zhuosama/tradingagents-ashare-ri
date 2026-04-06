"""
core/models.py — 标准输出数据模型
====================================
所有适配器向上层返回的唯一契约：
  - OHLCVBar:          单根 K 线（日频）
  - FundamentalReport: 基本面快照

设计原则：
  - 核心字段（OHLCV）非 Optional，校验失败即触发降级
  - 非核心字段（跨市场差异字段）全部 Optional[float]，None 表示数据源不提供
  - 使用 Pydantic v2，model_validator 确保 high >= low 等基础约束
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── K 线模型 ────────────────────────────────────────────────────────────────

class OHLCVBar(BaseModel):
    """单根日频 K 线，所有适配器输出的最小单元。"""

    model_config = ConfigDict(frozen=True)

    symbol:     str    = Field(description="标准化标的代码，如 '510300.SH'")
    trade_date: _date  = Field(description="交易日（北京时间日期）")
    open:       float  = Field(gt=0, description="开盘价")
    high:       float  = Field(gt=0, description="最高价")
    low:        float  = Field(gt=0, description="最低价")
    close:      float  = Field(gt=0, description="收盘价")
    volume:     float  = Field(ge=0, description="成交量（股/份）")

    # 非核心字段：跨市场可为 None
    amount:     Optional[float] = Field(None, description="成交额（元）")
    turnover:   Optional[float] = Field(None, description="换手率（%）")
    # A 股专有
    amplitude:  Optional[float] = Field(None, description="振幅（%）")
    change_pct: Optional[float] = Field(None, description="涨跌幅（%）")

    @model_validator(mode="after")
    def _check_price_order(self) -> "OHLCVBar":
        if self.high < self.low:
            raise ValueError(
                f"high({self.high}) < low({self.low}) for {self.symbol} on {self.trade_date}"
            )
        return self


# ── 基本面模型 ───────────────────────────────────────────────────────────────

class FundamentalReport(BaseModel):
    """
    基本面快照，全字段 Optional（跨市场差异极大）。
    核心字段：symbol + report_date，其余字段 None 表示数据源不覆盖。
    """

    model_config = ConfigDict(frozen=True)

    symbol:      str   = Field(description="标准化标的代码")
    report_date: _date = Field(description="数据快照日期")

    # 估值
    pe_ttm: Optional[float] = Field(None, description="市盈率 TTM")
    pb:     Optional[float] = Field(None, description="市净率")
    ps_ttm: Optional[float] = Field(None, description="市销率 TTM")

    # 规模（ETF/基金专有）
    total_assets: Optional[float] = Field(None, description="基金总资产（亿元）")
    nav:          Optional[float] = Field(None, description="单位净值")
    premium_rate: Optional[float] = Field(None, description="溢价率（%）")

    # 盈利（个股）
    roe:            Optional[float] = Field(None, description="净资产收益率（%）")
    revenue_yoy:    Optional[float] = Field(None, description="营收同比增速（%）")
    net_profit_yoy: Optional[float] = Field(None, description="净利润同比增速（%）")

    # 指数估值（指数标的专有）
    index_pe_percentile: Optional[float] = Field(None, description="PE 历史分位（%）")
    index_pb_percentile: Optional[float] = Field(None, description="PB 历史分位（%）")


# ── 解析结果模型（供 TickerResolver 返回）────────────────────────────────────

class ResolvedTicker(BaseModel):
    """TickerResolver 的输出：标准化代码 + 市场类型分类。"""

    model_config = ConfigDict(frozen=True)

    raw:         str = Field(description="用户原始输入")
    symbol:      str = Field(description="标准化标的代码，如 '510300.SH'")
    market_type: str = Field(
        description=(
            "市场类型，枚举值: "
            "CN_STOCK | CN_ETF | CN_INDEX | HK_STOCK | US_STOCK | EU_STOCK"
        )
    )
    # yfinance 专用符号（如 SH→SS 转换）
    yf_symbol: str = Field(description="yfinance 使用的 ticker，如 '510300.SS'")
