"""
601298.SH (青岛港国际) 深度分析脚本
研究深度：Deep (max_debate_rounds=5)
数据源：yfinance (价格/技术/新闻) + AKShare (财务三表)
LLM：DeepSeek (deepseek-reasoner + deepseek-chat)
输出：results/601298SH_20260407/

运行方式：
    cd d:/Trading-Agent/TradingAgents
    .venv/Scripts/python.exe run_601298sh.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# ── 环境变量 ──────────────────────────────────────────────────────────────────
load_dotenv()
if not os.getenv("OPENAI_API_KEY") and os.getenv("DEEPSEEK_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.getenv("DEEPSEEK_API_KEY")

# ── 参数 ──────────────────────────────────────────────────────────────────────
TICKER        = "601298.SH"
TRADE_DATE    = "2026-04-07"    # 目标交易日（下周一 A 股开盘）
ANALYSIS_DATE = "2026-04-04"    # 数据截止日（上周五）
OUTPUT_DIR    = Path("results/601298SH_20260407")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 配置 ──────────────────────────────────────────────────────────────────────
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"]            = "deepseek"
config["deep_think_llm"]          = "deepseek-reasoner"
config["quick_think_llm"]         = "deepseek-chat"
config["max_debate_rounds"]       = 5   # Deep
config["max_risk_discuss_rounds"] = 5   # Deep
config["max_recur_limit"]         = 200
config["output_language"]         = "Chinese"
config["data_vendors"] = {
    "core_stock_apis":      "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data":     "akshare",   # ← AKShare 提供 A 股财务三表
    "news_data":            "yfinance",
}


# ── yfinance 价格快照 ─────────────────────────────────────────────────────────
def fetch_snapshot(ticker: str, analysis_date: str) -> dict:
    """使用 yfinance 拉取价格快照（601298.SH → 601298.SS 自动转换）."""
    try:
        import yfinance as yf
        import pandas as pd
        from tradingagents.dataflows.stockstats_utils import normalize_ticker_yf

        yf_ticker = normalize_ticker_yf(ticker)
        end_dt   = datetime.strptime(analysis_date, "%Y-%m-%d")
        start_dt = end_dt - pd.DateOffset(days=60)

        t    = yf.Ticker(yf_ticker)
        hist = t.history(start=start_dt.strftime("%Y-%m-%d"),
                         end=end_dt.strftime("%Y-%m-%d"))
        info = t.info or {}

        if hist.empty:
            return {"error": f"yfinance 未返回价格数据 ({yf_ticker})"}

        last_close  = round(float(hist["Close"].iloc[-1]), 3)
        last_volume = int(hist["Volume"].iloc[-1])
        high_1m     = round(float(hist["High"].max()), 3)
        low_1m      = round(float(hist["Low"].min()), 3)

        # ATR14
        high  = hist["High"]
        low   = hist["Low"]
        close = hist["Close"]
        tr    = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr14   = round(float(tr.rolling(14).mean().iloc[-1]), 3)
        atr_pct = round(atr14 / last_close * 100, 2)

        ret5d  = round((last_close / float(hist["Close"].iloc[-6])  - 1) * 100, 2) if len(hist) >= 6  else None
        ret20d = round((last_close / float(hist["Close"].iloc[-21]) - 1) * 100, 2) if len(hist) >= 21 else None
        sma20  = round(float(hist["Close"].rolling(20).mean().iloc[-1]), 3) if len(hist) >= 20 else None
        sma50  = round(float(hist["Close"].rolling(50).mean().iloc[-1]), 3) if len(hist) >= 50 else None

        cap = info.get("marketCap")
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
            "52w_high":    info.get("fiftyTwoWeekHigh"),
            "52w_low":     info.get("fiftyTwoWeekLow"),
            "market_cap":  cap,
            "cap_str":     f"{cap/1e8:.0f} 亿" if cap else "N/A",
            "pe_ttm":      info.get("trailingPE"),
            "forward_pe":  info.get("forwardPE"),
            "eps_ttm":     info.get("trailingEps"),
            "company_name": info.get("longName", "青岛港国际"),
        }
    except Exception as e:
        return {"error": str(e)}


# ── 报告生成 ──────────────────────────────────────────────────────────────────
def build_report(ticker, trade_date, snapshot, final_state, decision) -> str:
    lc    = snapshot.get("last_close", "N/A")
    atr   = snapshot.get("atr14", "N/A")
    atr_p = snapshot.get("atr_pct", "N/A")
    r5    = snapshot.get("ret5d", "N/A")
    sma20 = snapshot.get("sma20", "N/A")
    sma50 = snapshot.get("sma50", "N/A")
    cap_str = snapshot.get("cap_str", "N/A")
    name  = snapshot.get("company_name", "青岛港国际")

    market_report       = final_state.get("market_report", "_未生成_")
    sentiment_report    = final_state.get("sentiment_report", "_未生成_")
    news_report         = final_state.get("news_report", "_未生成_")
    fundamentals_report = final_state.get("fundamentals_report", "_未生成_")
    debate_state        = final_state.get("investment_debate_state", {})
    trader_plan         = final_state.get("trader_investment_plan", "_未生成_")
    risk_state          = final_state.get("risk_debate_state", {})
    final_decision      = final_state.get("final_trade_decision", "_未生成_")

    bull_history   = debate_state.get("bull_history", "")
    bear_history   = debate_state.get("bear_history", "")
    debate_history = debate_state.get("history", "")
    judge_decision = debate_state.get("judge_decision", "")
    risk_history   = risk_state.get("history", "")
    risk_judge     = risk_state.get("judge_decision", "")

    return f"""# 601298.SH 投资分析报告
## {name} · 目标交易日：{trade_date}

> **生成时间**：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> **框架**：TradingAgents (TauricResearch) · 研究深度：Deep (5 轮辩论)
> **LLM**：DeepSeek Reasoner + DeepSeek Chat
> **数据源**：yfinance（行情/技术/新闻）+ AKShare（财务三表）

---

## 一、数据快照

| 指标 | 数值 |
|------|------|
| 最近收盘价 | ¥{lc} |
| ATR14 | ¥{atr} ({atr_p}%) |
| 5日涨跌幅 | {r5}% |
| 20日均线 | ¥{sma20} |
| 50日均线 | ¥{sma50} |
| 近60日最高/最低 | ¥{snapshot.get('high_1m','N/A')} / ¥{snapshot.get('low_1m','N/A')} |
| 52周高/低 | ¥{snapshot.get('52w_high','N/A')} / ¥{snapshot.get('52w_low','N/A')} |
| 市值 | {cap_str} |
| 市盈率(TTM) | {snapshot.get('pe_ttm','N/A')} |

---

## 二、各 Analyst Agent 核心结论

### 2.1 市场分析师
{market_report}

---

### 2.2 社交媒体 & 情绪分析师
{sentiment_report}

---

### 2.3 新闻分析师
{news_report}

---

### 2.4 基本面分析师
{fundamentals_report}

---

## 三、研究团队辩论（Deep · 5 轮）

### 3.1 多方核心论点
{bull_history or "_多方论点未生成_"}

---

### 3.2 空方核心论点
{bear_history or "_空方论点未生成_"}

---

### 3.3 完整辩论记录
{debate_history or "_辩论记录未生成_"}

---

### 3.4 研究经理裁决
{judge_decision or "_裁决未生成_"}

---

## 四、交易员决策
{trader_plan or "_交易决策未生成_"}

---

## 五、风险管理团队评估

### 5.1 风险辩论记录（5 轮）
{risk_history or "_风险辩论未生成_"}

---

### 5.2 Portfolio Manager 最终裁决
{risk_judge or "_PM 裁决未生成_"}

---

## 六、最终交易决策
{final_decision or "_最终决策未生成_"}

**最终信号（BUY / HOLD / SELL）**：`{decision}`

---

## 七、风险提示

> ⚠️ 本报告由 AI 多智能体系统自动生成，仅供参考，**不构成任何投资建议**。
> A 股市场存在涨跌停限制（±10%），流动性、监管政策、北向资金等因素对短期价格影响显著。
> 请结合宏观政策、行业景气周期及个人风险承受能力进行独立判断。

---
*本分析基于TradingAgents研究框架生成，不构成任何投资建议，实际交易需自行承担风险*

*Generated by TradingAgents Framework · 601298.SH {trade_date} Deep Analysis*
"""


# ── 主程序 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print(f"  601298.SH (青岛港国际) 深度分析")
    print(f"  目标日期：{TRADE_DATE}  |  研究深度：Deep (5轮)")
    print(f"  财务数据：AKShare（资产负债表 / 利润表 / 现金流量表）")
    print(f"  运行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Step 1: 数据快照
    print("\n[1/3] 拉取 yfinance 价格快照...")
    snapshot = fetch_snapshot(TICKER, ANALYSIS_DATE)
    if "error" not in snapshot:
        print(f"  ✓ 最新收盘价: ¥{snapshot.get('last_close', 'N/A')}")
        print(f"  ✓ ATR14: ¥{snapshot.get('atr14', 'N/A')} ({snapshot.get('atr_pct', 'N/A')}%)")
        print(f"  ✓ 5日涨跌幅: {snapshot.get('ret5d', 'N/A')}%")
        print(f"  ✓ 市值: {snapshot.get('cap_str', 'N/A')}")
    else:
        print(f"  ⚠ yfinance 异常: {snapshot['error']}")

    # Step 2: TradingAgents 核心流程
    print("\n[2/3] 初始化 TradingAgentsGraph (DeepSeek · Deep)...")
    print("  → 财务三表由 AKShare 提供（已修复 A 股财务数据抓取问题）")
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        ta = TradingAgentsGraph(
            selected_analysts=["market", "social", "news", "fundamentals"],
            debug=True,
            config=config,
        )

        print(f"\n  → 启动多智能体分析：{TICKER} @ {TRADE_DATE}")
        print("  → 预计耗时 15~40 分钟（Deep 模式，5 轮辩论）\n")

        final_state, decision = ta.propagate(TICKER, TRADE_DATE)

        print("\n[3/3] 生成报告...")
        report = build_report(TICKER, TRADE_DATE, snapshot, final_state, decision)
        success = True

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n  ⚠ 框架异常：{e}")
        report = (
            f"# 601298.SH 分析报告（框架异常）\n\n"
            f"> 异常信息：{e}\n\n"
            f"## 数据快照\n\n{snapshot}\n"
        )
        decision = "ERROR"
        success = False

    # Step 3: 保存报告
    report_path = OUTPUT_DIR / f"601298SH_analysis_{TRADE_DATE}.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\n{'✅' if success else '⚠'} 报告已保存：{report_path}")
    print(f"  最终信号：{decision}")
    print("\n" + "=" * 70)
    if success:
        print(report[:1500] + "\n...(已截断，请查看完整文件)")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
