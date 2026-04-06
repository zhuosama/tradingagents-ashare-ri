from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
    is_a_share,
    get_market_specific_instruction,
)
from tradingagents.dataflows.config import get_config


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        instrument_context = build_instrument_context(ticker)

        # 市场感知工具选择

        if is_a_share(ticker):
            # A 股：只提供个股新闻，禁用全球新闻工具，提供国内宏观占位
            from tradingagents.agents.utils.news_data_tools import get_news
            tools = [get_news]
            # 注：不在工具列表中暴露 get_global_news
            market_instruction = get_market_specific_instruction(ticker, "news")
            system_message = (
                market_instruction
                + " 请调用 get_news 工具获取该标的的相关新闻，并在此基础上撰写一份综合舆情分析报告。"
                "报告须完整涵盖以下四个部分："
                "（1）舆情全貌：基于获取到的个股新闻，或在新闻不足时转为分析国内宏观政策、监管动态和行业动向，梳理当前市场信息全貌；"
                "（2）可执行判断：结合 A 股「政策市」特点，明确指出短期催化剂、潜在利多/利空方向和建议重点关注的风险因素；"
                "（3）局限性声明：明确说明数据来源的局限性——若实时个股新闻不足，须注明该局限对判断可信度的影响，不得以无依据推断代替实证；"
                "（4）末尾汇总表格：附一张 Markdown 表格，归纳关键舆情事件、影响方向（利多/利空/中性）及风险等级（高/中/低），便于交易团队快速阅读。"
            )
        else:
            # 非 A 股：保持原有行为
            from tradingagents.agents.utils.news_data_tools import get_news, get_global_news
            tools = [get_news, get_global_news]
            system_message = (
                "You are a news researcher tasked with analyzing recent news and trends over the past week. Please write a comprehensive report of the current state of the world that is relevant for trading and macroeconomics. Use the available tools: get_news(query, start_date, end_date) for company-specific or targeted news searches, and get_global_news(curr_date, look_back_days, limit) for broader macroeconomic news. Provide specific, actionable insights with supporting evidence to help traders make informed decisions."
                + """ Make sure to append a Markdown table at the end of the report to organize key points in the report, organized and easy to read."""
                + get_language_instruction()
            )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "news_report": report,
        }

    return news_analyst_node
