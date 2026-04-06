from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional, Union

from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)

logger = logging.getLogger(__name__)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def get_market_type(ticker: str) -> str:
    """
    返回标的的市场类型，使用 TickerResolver。
    返回值: "CN_STOCK" | "CN_ETF" | "CN_INDEX" | "HK_STOCK" | "US_STOCK" | "EU_STOCK"
    """
    try:
        from tradingagents.data.routing.ticker_resolver import TickerResolver
        resolved = TickerResolver.resolve(ticker)
        return resolved.market_type
    except Exception as e:
        logger.warning("Market type resolution failed for %s: %s", ticker, e)
        return "UNKNOWN"


def is_a_share(ticker: str) -> bool:
    """
    判断是否为 A 股标的（包括 CN_STOCK, CN_ETF, CN_INDEX）。
    """
    market = get_market_type(ticker)
    return market.startswith("CN_") and market != "CN_UNKNOWN"


def get_prev_close(ticker: str, trade_date: str) -> Optional[float]:
    """
    获取指定交易日的前收盘价，用于 A 股涨跌停校验。
    通过现有 route_to_vendor 接口获取，不引入新依赖，不修改数据路由。

    yfinance history(end=trade_date) 不含 trade_date 当天，
    最后一行即前一交易日收盘价。
    """
    try:
        from tradingagents.dataflows.interface import route_to_vendor

        # 取 trade_date 前 14 个日历日作为起始，确保覆盖节假日
        trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_date_str = (trade_dt - timedelta(days=14)).strftime("%Y-%m-%d")

        raw = route_to_vendor("get_stock_data", ticker, start_date_str, trade_date)

        # 跳过 # 注释行，解析 CSV
        csv_lines = [l for l in raw.splitlines() if not l.startswith("#") and l.strip()]
        if len(csv_lines) < 2:
            return None

        reader = csv.DictReader(io.StringIO("\n".join(csv_lines)))
        rows = list(reader)
        if not rows:
            return None

        # 取最后一行的 Close 列
        last_row = rows[-1]
        close_str = last_row.get("Close") or last_row.get("close")
        if close_str is None:
            return None

        return float(close_str)
    except Exception as e:
        logger.warning("获取前收盘价失败 %s @ %s: %s", ticker, trade_date, e)
        return None


def get_market_specific_instruction(ticker: str, analyst_role: str = "") -> str:
    """
    根据标的和市场类型返回特定提示词指令。
    仅对 A 股注入额外约束，其他市场返回空字符串。

    Parameters
    ----------
    ticker : str
        标的代码
    analyst_role : str
        分析师角色：可选值 "news", "market", "fundamentals", "trader"
    """
    if not is_a_share(ticker):
        return ""

    base_zh = "你必须用简体中文（zh-CN）输出最终报告，包括所有专业金融术语。"

    # 各角色的 A 股特定指令
    role_instructions = {
        "news": (
            "你是一个深谙A股'政策市'特性的舆情分析师。忽略纳斯达克、美联储等无关外围新闻。"
            "你的核心任务是解读：发改委/证监会政策、央行流动性释放（降准降息）、行业补贴政策、"
            "以及国内机构资金的板块轮动迹象。如果个股无新闻，请从其所属的申万行业宏观政策进行推演。"
        ),
        "market": (
            "你的分析目标是A股市场，这是一个以**散户交易为主导、受T+1交收规则和涨跌幅限制（10%或20%）**的市场。"
            "你的技术分析必须注意："
            "1. 均线突破是否伴随'涨停板'，若涨停则技术形态有效性增强；"
            "2. 缩量跌停或连续一字跌停会导致所有技术指标失真，不可盲目使用RSI超卖抄底；"
            "3. 在设置ATR止损位时，必须考虑到T+1导致当天买入无法卖出的风险，止损建议必须以'次日或波段'为周期。"
        ),
        "fundamentals": (
            "你正在分析中国A股市场的标的。除了常规财务指标，你必须重点评估以下因素："
            "1. 政策导向（该行业是否受国家宏观政策鼓励或打压）；"
            "2. 国企估值逻辑（中特估，若为国企，需关注其分红率提升与资产注入预期）；"
            "3. 业绩预告（A股财报具有季节性炒作特征，需关注财报窗口期的业绩爆雷风险）。"
            "在评估流动性比率时，请结合中国特色重资产国企（如水电、煤炭）主要依赖银行信贷滚动展期的实际情况，"
            "切勿仅因绝对数值低而机械看空。"
        ),
        "trader": (
            "在制定交易计划时，你必须严格遵守A股规则："
            "1. 无法进行日内T+0回转交易；"
            "2. 建仓与平仓价格不得超过昨日收盘价的±10%（主板）或±20%（创业/科创板）；"
            "3. 若标的处于'非交易状态/停牌/ST风险'，必须强制一票否决买入计划并建议空仓；"
            "4. 考虑到A股高波动性，短线请适当放大止损容忍度，或采用分批建仓策略防范假突破。"
        ),
    }

    specific = role_instructions.get(analyst_role, "")
    return f"{base_zh} {specific}".strip()


class MarketRuleValidator:
    """
    A 股交易规则验证器。
    仅对 A 股标的生效，非 A 股标的直接跳过验证。
    """

    def __init__(self, ticker: str, prev_close: Optional[float] = None):
        self.ticker = ticker
        self.market_type = get_market_type(ticker)
        self.is_ashare = self.market_type.startswith("CN_")
        self.prev_close = prev_close

        # 根据代码推断板块（简化逻辑）
        self._board_limit = self._infer_price_limit()

    def _infer_price_limit(self) -> float:
        """
        推断涨跌停限制比例。
        主板：10%，创业板/科创板（代码 3/688 开头）：20%。
        无法确定时保守使用 10%。
        """
        if not self.is_ashare:
            return 0.0

        code_part = self.ticker.split(".")[0] if "." in self.ticker else self.ticker
        if len(code_part) == 6:
            if code_part.startswith(("3", "688")):
                return 20.0
        return 10.0

    def validate_price(self, price: float, trade_date: Union[str, date, datetime]) -> tuple[bool, str]:
        """
        验证价格是否在当日涨跌停范围内。
        返回 (是否有效, 错误信息)。
        若 prev_close 未提供，跳过价格验证。
        """
        if not self.is_ashare or self.prev_close is None:
            return True, ""

        limit_pct = self._board_limit
        lower = self.prev_close * (1 - limit_pct / 100)
        upper = self.prev_close * (1 + limit_pct / 100)

        if price < lower or price > upper:
            return False, (
                f"价格 ¥{price:.2f} 超出当日涨跌停范围（前收 ¥{self.prev_close:.2f}，"
                f"限制 ±{limit_pct}% → [{lower:.2f}, {upper:.2f}]）。"
            )
        return True, ""

    def validate_t1_plan(self, plan_text: str) -> tuple[bool, str]:
        """
        验证交易计划是否违反 T+1 规则。
        检查是否有明显的同一天买入并卖出的逻辑。
        返回 (是否合规, 警告信息)。
        """
        if not self.is_ashare:
            return True, ""

        # 简单关键词检测（可扩展为更复杂的 NLP）
        lower_text = plan_text.lower()
        t1_phrases = [
            "buy and sell the same day",
            "intraday trade",
            "t+0",
            "当天买入并卖出",
            "日内交易",
            "当日回转",
        ]
        for phrase in t1_phrases:
            if phrase in lower_text:
                return False, f"交易计划可能违反 A 股 T+1 规则（检测到 '{phrase}'）。"

        # 停牌 / ST / 退市风险防御性检测
        suspension_phrases = [
            "停牌",
            "暂停交易",
            "*st",
            "＊st",
            "退市风险",
            "被暂停上市",
        ]
        for phrase in suspension_phrases:
            if phrase in lower_text:
                return False, (
                    f"交易计划涉及高风险状态标的（检测到 '{phrase}'）。"
                    "请确认该标的当前未处于停牌、ST 或退市风险状态，必要时建议空仓观望。"
                )

        return True, ""

    def validate_and_rewrite_plan(self, plan_text: str) -> str:
        """
        验证并可能重写交易计划，使其符合 A 股规则。
        价格校验：用正则从计划文本提取明确价格（¥XX 或 XX元），
        仅在识别到价格且 prev_close 已知时才校验，避免误判。
        """
        if not self.is_ashare:
            return plan_text

        t1_ok, t1_msg = self.validate_t1_plan(plan_text)

        # 从计划文本提取明确标注的价格（如 ¥15.30 或 15.30元）
        price_pattern = re.compile(
            r'(?:¥|￥)\s*(\d+\.?\d*)|(\d+\.?\d*)\s*(?:元|yuan)',
            re.IGNORECASE,
        )
        price_warnings = []
        if self.prev_close is not None:
            for m in price_pattern.finditer(plan_text):
                val_str = m.group(1) or m.group(2)
                try:
                    price = float(val_str)
                    ok, msg = self.validate_price(price, date.today())
                    if not ok:
                        price_warnings.append(msg)
                except ValueError:
                    pass

        if t1_ok and not price_warnings:
            return plan_text

        warnings = price_warnings[:]
        if not t1_ok:
            warnings.append(t1_msg)

        # 在计划末尾追加警告，不修改原始计划内容
        warning_block = "\n\n**A 股规则警告**: " + "；".join(warnings)
        return plan_text + warning_block


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
