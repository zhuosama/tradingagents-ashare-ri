import functools
import time
import json

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    is_a_share,
    get_prev_close,
    MarketRuleValidator,
)


def create_trader(llm, memory):
    def trader_node(state, name):
        company_name = state["company_of_interest"]
        trade_date = state["trade_date"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        if past_memories:
            for i, rec in enumerate(past_memories, 1):
                past_memory_str += rec["recommendation"] + "\n\n"
        else:
            past_memory_str = "No past memories found."

        # 市场感知指令
        from tradingagents.agents.utils.agent_utils import get_market_specific_instruction
        market_instruction = get_market_specific_instruction(company_name, analyst_role="trader")

        context = {
            "role": "user",
            "content": f"Based on a comprehensive analysis by a team of analysts, here is an investment plan tailored for {company_name}. {instrument_context} This plan incorporates insights from current technical market trends, macroeconomic indicators, and social media sentiment. Use this plan as a foundation for evaluating your next trading decision.\n\nProposed Investment Plan: {investment_plan}\n\nLeverage these insights to make an informed and strategic decision.",
        }

        system_base = f"""You are a trading agent analyzing market data to make investment decisions. Based on your analysis, provide a specific recommendation to buy, sell, or hold. End with a firm decision and always conclude your response with 'FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**' to confirm your recommendation. Apply lessons from past decisions to strengthen your analysis. Here are reflections from similar situations you traded in and the lessons learned: {past_memory_str}"""

        if market_instruction:
            system_base += f"\n\n{market_instruction}"

        messages = [
            {
                "role": "system",
                "content": system_base,
            },
            context,
        ]

        result = llm.invoke(messages)

        # A 股交易规则校验：获取真实前收价以启用涨跌停校验
        prev_close = get_prev_close(company_name, trade_date) if is_a_share(company_name) else None
        validator = MarketRuleValidator(company_name, prev_close=prev_close)
        validated_plan = validator.validate_and_rewrite_plan(result.content)

        return {
            "messages": [result],
            "trader_investment_plan": validated_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
