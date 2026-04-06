from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import pandas as pd

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor

logger = logging.getLogger(__name__)


def _to_6digit_code(ticker: str) -> str:
    """将 000001.SZ / 600519.SH / 600519.SS 统一转为 6 位纯数字代码。"""
    code = ticker.strip().upper()
    if "." in code:
        code = code.split(".")[0]
    return code


def _safe_fallback(ticker: str, start_date: str, end_date: str) -> str:
    """
    安全降级输出：明确声明未获取到实时新闻，提供结构化分析提示。
    严禁伪造任何新闻内容，不回退到 US/全球新闻。
    """
    lines = [
        f"## {ticker} A 股新闻（{start_date} 至 {end_date}）",
        "",
        "**⚠ 数据说明：当前未获取到实时 A 股新闻。**",
        "A 股专用新闻接口暂时不可用，以下内容为结构化分析提示，不含任何真实或虚构的新闻报道。",
        "",
        "---",
        "",
        "### 请重点关注以下 A 股舆情维度（需人工或接入专用数据源后补充）：",
        "",
        "1. **个股公告**：定期报告（季报/半年报/年报）、重大事项公告、停复牌公告",
        "2. **监管动态**：证监会/交易所对该标的或所属行业的最新监管表态",
        "3. **货币与流动性**：央行 MLF/LPR 调整、降准降息预期对板块的传导",
        "4. **产业政策**：发改委/工信部等部委对所属行业的补贴、限制或鼓励政策",
        "5. **资金面**：北向资金对该标的或板块的增减持动向、两融余额变化",
        "",
        "---",
        "",
        f"**分析建议**：在缺乏实时新闻的情况下，请结合 {ticker} 的基本面报告与技术面分析，",
        "对已知的宏观政策方向和行业周期位置进行定性判断，并在结论中明确标注新闻数据缺失的局限性。",
        f"分析日期范围：{start_date} 至 {end_date}",
        "",
    ]
    return "\n".join(lines)


def _get_news_ashare(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    A 股新闻获取：优先使用 AKShare 东方财富个股新闻接口，
    网络/依赖失败时降级到安全 fallback，严禁回退到 US/全球新闻，严禁伪造内容。
    """
    code = _to_6digit_code(ticker)

    try:
        import akshare as ak  # 懒加载，不强制全局依赖

        df = ak.stock_news_em(symbol=code)

        if df is None or df.empty:
            logger.info("stock_news_em(%s) 返回空，使用安全 fallback", ticker)
            return _safe_fallback(ticker, start_date, end_date)

        # 按日期过滤，仅保留 [start_date, end_date] 范围内的新闻
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
            df["_pub_dt"] = pd.to_datetime(df["发布时间"], errors="coerce")
            df = df[(df["_pub_dt"] >= start_dt) & (df["_pub_dt"] <= end_dt)].drop(
                columns=["_pub_dt"]
            )
        except Exception as filter_err:
            logger.warning("日期过滤失败，返回全量新闻: %s", filter_err)

        if df.empty:
            logger.info("stock_news_em(%s) 在 %s~%s 范围内无新闻，使用安全 fallback", ticker, start_date, end_date)
            return _safe_fallback(ticker, start_date, end_date)

        # 格式化为 Markdown（与 yfinance 新闻格式对齐）
        lines = [f"## {ticker} A 股新闻（{start_date} 至 {end_date}）\n"]
        for _, row in df.iterrows():
            title = row.get("新闻标题", "（无标题）")
            content = row.get("新闻内容", "")
            source = row.get("文章来源", "未知来源")
            pub_time = row.get("发布时间", "")
            link = row.get("新闻链接", "")

            lines.append(f"### {title}（来源：{source}，{pub_time}）")
            if content:
                lines.append(content)
            if link:
                lines.append(f"链接：{link}")
            lines.append("")

        return "\n".join(lines)

    except ImportError:
        logger.warning("akshare 未安装，使用安全 fallback")
        return _safe_fallback(ticker, start_date, end_date)
    except Exception as e:
        logger.warning("stock_news_em(%s) 失败: %s，使用安全 fallback", ticker, e)
        return _safe_fallback(ticker, start_date, end_date)


def _get_global_news_ashare(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 5,
) -> str:
    """
    A 股宏观/行业新闻（占位实现）。
    应接入国内宏观政策、行业新闻源。
    """
    # TODO: 接入真实国内宏观新闻源
    return (
        "## A 股宏观与行业新闻（占位）\n\n"
        "**注意**：国内宏观新闻源正在建设中。\n\n"
        "当前 A 股分析应重点关注以下国内政策与行业动态：\n"
        "1. **货币政策**：央行 MLF/LPR 调整、降准降息预期\n"
        "2. **财政政策**：专项债发行、产业补贴、税收优惠\n"
        "3. **监管动态**：证监会发布会、交易所新规、IPO 节奏\n"
        "4. **行业政策**：新能源车补贴、半导体国产化、消费刺激\n"
        "5. **资金面**：北向资金流向、两融余额、公募发行\n\n"
        "请结合当前宏观经济周期与产业轮动特征进行定性分析。\n"
    )


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    # 懒加载避免与 agent_utils 的循环导入
    from tradingagents.agents.utils.agent_utils import is_a_share  # noqa: PLC0415
    # 市场感知路由：A 股使用专用路径，禁止回退到全球新闻
    if is_a_share(ticker):
        return _get_news_ashare(ticker, start_date, end_date)

    # 非 A 股走原有路由
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor.
    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back (default 7)
        limit (int): Maximum number of articles to return (default 5)
    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)
