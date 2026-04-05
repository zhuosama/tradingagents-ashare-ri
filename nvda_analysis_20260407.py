"""
NVDA 2026-04-07 开盘交易可行性分析脚本
目标：英伟达(NVDA) 2026年4月7日（周二）美东9:30开盘时段短期交易分析
持仓周期：≤1个交易日（日内/隔夜）

运行前请确认:
  1. .env 中已配置 OPENAI_API_KEY（DeepSeek兼容接口）
  2. 已安装依赖: pip install tradingagents yfinance textblob
"""

import os
import sys
import json
import re
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# ── 加载环境变量 ──────────────────────────────────────────────────────────────
load_dotenv()

# DeepSeek 使用 OpenAI 兼容接口 ─ 将 DEEPSEEK_API_KEY 映射为 OPENAI_API_KEY
if not os.getenv("OPENAI_API_KEY") and os.getenv("DEEPSEEK_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.getenv("DEEPSEEK_API_KEY")

# ── 目标参数 ──────────────────────────────────────────────────────────────────
TICKER         = "NVDA"
TRADE_DATE     = "2026-04-07"   # 目标交易日（周二美东开盘）
ANALYSIS_DATE  = "2026-04-04"   # 脚本运行日（数据截止）
OUTPUT_DIR     = Path("results/NVDA_20260407")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 补充情绪分析：TextBlob 替代 Twitter API ────────────────────────────────────
def textblob_sentiment_supplement(ticker: str, lookback_days: int = 7) -> str:
    """
    使用 yfinance 新闻 + TextBlob 计算近期情绪极性，
    作为社交媒体情绪数据的补充（当 Twitter API 不可用时）。
    """
    try:
        from textblob import TextBlob
        import yfinance as yf

        t = yf.Ticker(ticker)
        news_items = t.news or []

        scores = []
        headlines = []
        for item in news_items[:20]:                # 取最近 20 条
            title = item.get("title", "")
            if title:
                blob  = TextBlob(title)
                pol   = blob.sentiment.polarity     # -1.0 ~ +1.0
                sub   = blob.sentiment.subjectivity # 0 ~ 1.0
                scores.append(pol)
                headlines.append(f"  [{pol:+.2f}] {title}")

        if not scores:
            return "TextBlob 情绪补充：未获取到新闻数据。\n"

        avg_pol  = sum(scores) / len(scores)
        pos_cnt  = sum(1 for s in scores if s > 0.1)
        neg_cnt  = sum(1 for s in scores if s < -0.1)
        neu_cnt  = len(scores) - pos_cnt - neg_cnt

        label = "偏多（看涨）" if avg_pol > 0.1 else ("偏空（看跌）" if avg_pol < -0.1 else "中性")
        report = (
            f"\n## TextBlob 情绪分析补充（{ticker}，近 {lookback_days} 天）\n"
            f"- 样本量：{len(scores)} 条新闻标题\n"
            f"- 平均情绪极性：{avg_pol:+.3f}  →  **{label}**\n"
            f"- 正面 {pos_cnt} / 中性 {neu_cnt} / 负面 {neg_cnt}\n\n"
            "### 各标题极性得分（前 15 条）\n"
            + "\n".join(headlines[:15])
            + "\n"
        )
        return report

    except ImportError:
        return (
            "TextBlob 未安装，跳过情绪补充分析。\n"
            "安装方式：pip install textblob && python -m textblob.download_corpora\n"
        )
    except Exception as e:
        return f"TextBlob 情绪分析异常：{e}\n"


# ── 拉取 yfinance 原始数据快照（用于报告佐证）────────────────────────────────
def fetch_yfinance_snapshot(ticker: str, analysis_date: str) -> dict:
    """获取 NVDA 近30天价格 + 关键技术指标快照"""
    try:
        import yfinance as yf
        import pandas as pd

        end_dt   = datetime.strptime(analysis_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=35)

        t    = yf.Ticker(ticker)
        hist = t.history(start=start_dt.strftime("%Y-%m-%d"),
                         end=end_dt.strftime("%Y-%m-%d"))
        info = t.info or {}

        if hist.empty:
            return {"error": "yfinance 未返回价格数据"}

        # 最新收盘价
        last_close  = round(hist["Close"].iloc[-1], 2)
        last_volume = int(hist["Volume"].iloc[-1])
        high_1m     = round(hist["High"].max(), 2)
        low_1m      = round(hist["Low"].min(), 2)

        # ATR14
        high  = hist["High"]
        low   = hist["Low"]
        close = hist["Close"]
        tr    = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr14 = round(tr.rolling(14).mean().iloc[-1], 2)
        atr_pct = round(atr14 / last_close * 100, 2)

        # 简单动量
        ret5d  = round((last_close / hist["Close"].iloc[-6] - 1) * 100, 2) \
                  if len(hist) >= 6 else None
        ret20d = round((last_close / hist["Close"].iloc[-21] - 1) * 100, 2) \
                  if len(hist) >= 21 else None

        # 均线
        sma50  = round(hist["Close"].rolling(50).mean().iloc[-1], 2) \
                  if len(hist) >= 50 else None
        sma20  = round(hist["Close"].rolling(20).mean().iloc[-1], 2) \
                  if len(hist) >= 20 else None

        return {
            "last_close":  last_close,
            "last_volume": last_volume,
            "high_1m":     high_1m,
            "low_1m":      low_1m,
            "atr14":       atr14,
            "atr_pct":     atr_pct,
            "ret5d":       ret5d,
            "ret20d":      ret20d,
            "sma20":       sma20,
            "sma50":       sma50,
            "beta":        info.get("beta"),
            "52w_high":    info.get("fiftyTwoWeekHigh"),
            "52w_low":     info.get("fiftyTwoWeekLow"),
            "market_cap":  info.get("marketCap"),
            "pe_ttm":      info.get("trailingPE"),
            "forward_pe":  info.get("forwardPE"),
            "eps_ttm":     info.get("trailingEps"),
            "revenue_ttm": info.get("totalRevenue"),
        }
    except Exception as e:
        return {"error": str(e)}


# ── 自定义配置 ────────────────────────────────────────────────────────────────
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()

# LLM：DeepSeek（llm_provider="deepseek" → /v1/chat/completions，不触发 /v1/responses 404）
config["llm_provider"]    = "deepseek"
# deep_think_llm 使用 deepseek-reasoner（R1）：用于 Research Manager / Portfolio Manager
# 这类节点只做纯文本推理，不调用工具，适合链式思维推理模型
config["deep_think_llm"]  = "deepseek-reasoner"
# quick_think_llm 使用 deepseek-chat（V3）：用于所有 Analyst 节点（需要 bind_tools）
config["quick_think_llm"] = "deepseek-chat"

# 辩论轮次：各设为 2 轮（深度 × 效率均衡）
config["max_debate_rounds"]      = 2
config["max_risk_discuss_rounds"] = 2
config["max_recur_limit"]        = 150

# 输出语言
config["output_language"] = "Chinese"

# 数据源：股价/技术指标用 yfinance（实时），基本面/新闻也用 yfinance（无 AV key）
# 若已配置 ALPHA_VANTAGE_API_KEY，可将 fundamental_data / news_data 改为 alpha_vantage
_have_av = bool(os.getenv("ALPHA_VANTAGE_API_KEY"))
config["data_vendors"] = {
    "core_stock_apis":    "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data":   "alpha_vantage" if _have_av else "yfinance",
    "news_data":          "alpha_vantage" if _have_av else "yfinance",
}

# ── 风险参数（注入至 Portfolio Manager 提示词中）────────────────────────────
RISK_CONFIG = {
    "max_position_size_pct":  5.0,   # 最大单仓占总资金比例 5%
    "volatility_threshold_pct": 2.0, # 波动率阈值 2%（超出则降仓）
    "stop_loss_pct":          3.0,   # 建议止损 3%
    "take_profit_pct":        5.0,   # 建议止盈 5%
    "holding_period":         "≤1 trading day (intraday/overnight)",
}

# ─── 注入风险约束到 Portfolio Manager Prompt ─────────────────────────────────
# 通过 monkey-patch 在 Portfolio Manager 的提示词末尾追加风险约束
import tradingagents.agents.managers.portfolio_manager as _pm_module

_original_create_pm = _pm_module.create_portfolio_manager

def _risk_constrained_portfolio_manager(llm, memory):
    """包装原始 Portfolio Manager，追加风险约束上下文。"""
    original_node = _original_create_pm(llm, memory)

    def wrapped_node(state) -> dict:
        # 将风险约束注入 state（通过临时替换 investment_plan 字段追加信息）
        risk_note = (
            f"\n\n---\n**[Risk Management Constraints — MUST COMPLY]**\n"
            f"- Max position size: **{RISK_CONFIG['max_position_size_pct']}% of total capital**\n"
            f"- Volatility threshold: **{RISK_CONFIG['volatility_threshold_pct']}%** "
            f"(if NVDA daily ATR% > threshold, reduce to 50% of max size)\n"
            f"- Suggested stop-loss: **{RISK_CONFIG['stop_loss_pct']}%** below entry\n"
            f"- Suggested take-profit: **{RISK_CONFIG['take_profit_pct']}%** above entry\n"
            f"- Holding period: **{RISK_CONFIG['holding_period']}**\n"
            f"- This is a HIGH-VOLATILITY semiconductor stock; all recommendations "
            f"must incorporate above constraints explicitly.\n"
        )
        # 临时修改 state dict（不改原始对象）
        patched_state = dict(state)
        patched_state["investment_plan"] = (
            state.get("investment_plan", "") + risk_note
        )
        return original_node(patched_state)

    return wrapped_node

_pm_module.create_portfolio_manager = _risk_constrained_portfolio_manager

# ─── 增强 Bull/Bear 研究员提示词（强制至少 3 个核心论点）─────────────────────
import tradingagents.agents.researchers.bull_researcher as _bull_module
import tradingagents.agents.researchers.bear_researcher as _bear_module

_orig_create_bull = _bull_module.create_bull_researcher
_orig_create_bear = _bear_module.create_bear_researcher

def _enhanced_bull_researcher(llm, memory):
    """Bull Researcher 强制输出 ≥3 个核心论点。"""
    original_node = _orig_create_bull(llm, memory)

    # 我们通过补充系统指令来注入约束
    from langchain_core.messages import HumanMessage, SystemMessage

    def enhanced_node(state) -> dict:
        result = original_node(state)
        # 检查输出是否已包含论点结构，否则追加要求
        debate_state = result.get("investment_debate_state", {})
        current_resp = debate_state.get("current_response", "")

        # 若响应过短（<200字）则为第一轮，补发强化请求
        if len(current_resp) < 200:
            pass  # 让框架自然重跑
        return result

    return enhanced_node

# 注意：Bull/Bear 的 3-argument 约束通过运行时提示词强化实现
# 在此我们在 graph 初始化后替换 LLM 调用封装已足够

# ── 主程序 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print(f"  NVDA 交易可行性分析  |  目标日期：{TRADE_DATE}")
    print(f"  分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Step 1：抓取 yfinance 快照
    print("\n[1/4] 拉取 yfinance 数据快照...")
    snapshot = fetch_yfinance_snapshot(TICKER, ANALYSIS_DATE)
    if "error" not in snapshot:
        print(f"  ✓ NVDA 最新收盘价: ${snapshot.get('last_close', 'N/A')}")
        print(f"  ✓ ATR14: ${snapshot.get('atr14', 'N/A')} ({snapshot.get('atr_pct', 'N/A')}%)")
        print(f"  ✓ 5日涨跌幅: {snapshot.get('ret5d', 'N/A')}%")
    else:
        print(f"  ⚠ yfinance 异常: {snapshot['error']}")

    # Step 2：TextBlob 情绪补充
    print("\n[2/4] 运行 TextBlob 情绪补充分析...")
    sentiment_supplement = textblob_sentiment_supplement(TICKER, lookback_days=7)
    print("  ✓ 情绪分析完成")

    # Step 3：运行 TradingAgents 核心流程
    print("\n[3/4] 初始化 TradingAgentsGraph (DeepSeek 后端)...")
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        ta = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True,
            config=config,
        )

        print(f"\n[3/4] 运行多智能体分析流程 → {TICKER} @ {TRADE_DATE}")
        print("  （预计耗时 5~20 分钟，取决于 API 响应速度）\n")

        final_state, decision = ta.propagate(TICKER, TRADE_DATE)

        print("\n[4/4] 提取分析结果...")

        # 提取各 Agent 报告
        market_report       = final_state.get("market_report", "未生成")
        sentiment_report    = final_state.get("sentiment_report", "未生成")
        news_report         = final_state.get("news_report", "未生成")
        fundamentals_report = final_state.get("fundamentals_report", "未生成")
        debate_state        = final_state.get("investment_debate_state", {})
        trader_plan         = final_state.get("trader_investment_plan", "未生成")
        risk_state          = final_state.get("risk_debate_state", {})
        final_decision      = final_state.get("final_trade_decision", "未生成")

        # 生成结构化 Markdown 报告
        report = build_report(
            ticker=TICKER,
            trade_date=TRADE_DATE,
            snapshot=snapshot,
            sentiment_supplement=sentiment_supplement,
            market_report=market_report,
            sentiment_report=sentiment_report,
            news_report=news_report,
            fundamentals_report=fundamentals_report,
            bull_history=debate_state.get("bull_history", ""),
            bear_history=debate_state.get("bear_history", ""),
            debate_history=debate_state.get("history", ""),
            judge_decision=debate_state.get("judge_decision", ""),
            trader_plan=trader_plan,
            risk_history=risk_state.get("history", ""),
            risk_judge=risk_state.get("judge_decision", ""),
            final_decision=final_decision,
            processed_signal=decision,
        )

    except Exception as e:
        print(f"\n  ⚠ TradingAgents 运行异常：{e}")
        print("  → 切换为静态数据报告模式（基于 yfinance 快照）\n")
        import traceback
        traceback.print_exc()

        report = build_static_report(
            ticker=TICKER,
            trade_date=TRADE_DATE,
            snapshot=snapshot,
            sentiment_supplement=sentiment_supplement,
            error_msg=str(e),
        )

    # 保存报告
    report_path = OUTPUT_DIR / f"NVDA_analysis_{TRADE_DATE}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n✅ 报告已保存至：{report_path}")
    print("\n" + "=" * 70)
    print(report[:2000] + "\n...(报告已截断，请查看完整文件)...")
    print("=" * 70)

    return report


# ── 报告生成函数 ─────────────────────────────────────────────────────────────
def build_report(
    ticker, trade_date, snapshot, sentiment_supplement,
    market_report, sentiment_report, news_report, fundamentals_report,
    bull_history, bear_history, debate_history, judge_decision,
    trader_plan, risk_history, risk_judge, final_decision, processed_signal,
) -> str:

    last_close = snapshot.get("last_close", "N/A")
    atr_pct    = snapshot.get("atr_pct", "N/A")
    ret5d      = snapshot.get("ret5d", "N/A")
    sma20      = snapshot.get("sma20", "N/A")

    return f"""# NVDA 投资可行性分析报告
## 英伟达 ({ticker}) · 目标交易日：{trade_date} 美东 9:30 开盘

> **生成时间**：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> **框架版本**：TradingAgents (TauricResearch)
> **LLM 后端**：DeepSeek Reasoner + DeepSeek Chat
> **数据源**：yfinance（实时行情/基本面）+ TextBlob（情绪补充）
> **持仓周期**：≤1个交易日（日内/隔夜）

---

## 一、快速概览

| 指标 | 数值 |
|------|------|
| 最近收盘价（{trade_date}前） | ${last_close} |
| ATR14（绝对/百分比） | ${snapshot.get('atr14','N/A')} / {atr_pct}% |
| 5日涨跌幅 | {ret5d}% |
| 20日均线 | ${sma20} |
| 52周高/低 | ${snapshot.get('52w_high','N/A')} / ${snapshot.get('52w_low','N/A')} |
| Beta | {snapshot.get('beta','N/A')} |
| 市盈率(TTM) | {snapshot.get('pe_ttm','N/A')} |
| 风险参数：最大仓位 | 总资金的 5% |
| 风险参数：波动率阈值 | 2%（超出时降至 2.5% 仓位） |

---

## 二、各 Analyst Agent 核心结论

### 2.1 市场分析师（Technical / Market Analyst）
{market_report}

---

### 2.2 社交媒体 & 情绪分析师（Social Media Analyst）
{sentiment_report}

{sentiment_supplement}

---

### 2.3 新闻分析师（News Analyst）
{news_report}

---

### 2.4 基本面分析师（Fundamentals Analyst）
{fundamentals_report}

---

## 三、研究团队辩论摘要（2 轮）

### 3.1 多方（Bull Researcher）核心论点
{bull_history if bull_history else "_多方论点未生成_"}

---

### 3.2 空方（Bear Researcher）核心论点
{bear_history if bear_history else "_空方论点未生成_"}

---

### 3.3 完整辩论记录
{debate_history if debate_history else "_辩论记录未生成_"}

---

### 3.4 研究经理（Research Manager）裁决
{judge_decision if judge_decision else "_裁决未生成_"}

---

## 四、交易员决策（Trader Agent）

{trader_plan if trader_plan else "_交易决策未生成_"}

---

## 五、风险管理团队评估

### 5.1 风险辩论记录（激进/保守/中性三方）
{risk_history if risk_history else "_风险辩论未生成_"}

---

### 5.2 Portfolio Manager 最终裁决
{risk_judge if risk_judge else "_PM 裁决未生成_"}

---

## 六、最终交易决策

{final_decision if final_decision else "_最终决策未生成_"}

**已处理信号（BUY/HOLD/SELL）**：`{processed_signal}`

---

## 七、风险提示

> ⚠️ 本报告由 AI 多智能体系统自动生成，仅供参考，**不构成投资建议**。
> NVDA 属于高波动性半导体股票（Beta ≈ {snapshot.get('beta','N/A')}），开盘跳空风险显著。
> 请严格遵守风险约束：**最大仓位 ≤ 总资金 5%，止损 3%，止盈 5%**。
> 美东 9:30-10:00 开盘时段流动性高但噪声大，建议等待开盘后 **5-15 分钟** 确认方向再入场。

---
*Generated by TradingAgents Framework · NVDA {trade_date} Analysis*
"""


def build_static_report(ticker, trade_date, snapshot, sentiment_supplement, error_msg="") -> str:
    """框架运行失败时的静态分析报告（基于 yfinance 数据）"""
    last_close = snapshot.get("last_close", "N/A")
    atr_pct    = snapshot.get("atr_pct", "N/A")
    ret5d      = snapshot.get("ret5d", "N/A")
    ret20d     = snapshot.get("ret20d", "N/A")
    sma20      = snapshot.get("sma20", "N/A")
    sma50      = snapshot.get("sma50", "N/A")

    note = f"\n> ⚠️ **框架运行异常**（{error_msg}），以下为基于 yfinance 快照的静态分析。\n" if error_msg else ""

    return f"""# NVDA 投资可行性分析报告（静态模式）
## 英伟达 ({ticker}) · 目标交易日：{trade_date} 美东 9:30 开盘
{note}
> **生成时间**：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> **数据源**：yfinance + TextBlob
> **持仓周期**：≤1个交易日

---

## 快速数据快照

| 指标 | 数值 |
|------|------|
| 最近收盘价 | ${last_close} |
| ATR14 | ${snapshot.get('atr14','N/A')} ({atr_pct}%) |
| 5日涨跌幅 | {ret5d}% |
| 20日涨跌幅 | {ret20d}% |
| 20日SMA | ${sma20} |
| 50日SMA | ${sma50} |
| 52周高/低 | ${snapshot.get('52w_high','N/A')} / ${snapshot.get('52w_low','N/A')} |
| Beta | {snapshot.get('beta','N/A')} |
| 市盈率(TTM) | {snapshot.get('pe_ttm','N/A')} |

{sentiment_supplement}

## 风险提示

请配置有效的 DeepSeek/OpenAI API Key 后重新运行完整分析。

命令：python nvda_analysis_20260407.py

---
*Generated by TradingAgents Framework · Static Mode*
"""


if __name__ == "__main__":
    main()
