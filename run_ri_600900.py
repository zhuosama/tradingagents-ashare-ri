"""
run_ri_600900.py — 600900.SH 长江电力 · 长线投资可行性分析
============================================================
数据层：使用新重构的 tradingagents.data.DataRouter（CN_STOCK → AKShare Primary）
回测层：复用 ri_orchestrator.DCABacktester
AI 层：复用 TradingAgentsGraph（market + news + fundamentals 三路分析师）

运行方式：
    cd d:/Trading-Agent/TradingAgents
    .venv/Scripts/python.exe run_ri_600900.py

输出：
    results/RI_600900_<YYYYMMDD>/RI_600900_analysis_<YYYY-MM-DD>.md
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, ".")

# ── 日志 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING,
                    format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

# ── DeepSeek Key ──────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "请先设置环境变量 DEEPSEEK_API_KEY，例如：\n"
        "  set DEEPSEEK_API_KEY=sk-xxxxxxx  (Windows CMD)\n"
        "  $env:DEEPSEEK_API_KEY='sk-xxx'   (PowerShell)"
    )

# ── 标的配置 ──────────────────────────────────────────────────────────────────
TICKER          = "600900.SH"   # 长江电力
LOOKBACK_YEARS  = 5             # 5年回测（电力股适合更长维度）
INVEST_PERIOD   = "monthly"     # 月定投
INVEST_AMOUNT   = 1000.0        # 每月 ¥1000
OUTPUT_DIR      = "results"

# ── LLM 配置 ──────────────────────────────────────────────────────────────────
from tradingagents.default_config import DEFAULT_CONFIG

CONFIG = DEFAULT_CONFIG.copy()
CONFIG.update({
    "llm_provider":      "deepseek",
    "backend_url":       "https://api.deepseek.com",
    "deep_think_llm":    "deepseek-chat",
    "quick_think_llm":   "deepseek-chat",
    "max_debate_rounds": 1,
    "online_tools":      True,
})
CONFIG.setdefault("data_vendors", {})
CONFIG["data_vendors"]["fundamental_data"] = "akshare"

# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd

from tradingagents.data import DataRouter
from tradingagents.ri_orchestrator import DCABacktester, PERIOD_CONFIG


def bars_to_dataframe(bars) -> pd.DataFrame:
    """
    将 list[OHLCVBar] 转换为 DCABacktester 兼容的 DataFrame。
    DCABacktester 需要列：'日期'（datetime）和 '收盘'（float）。
    """
    rows = [{"日期": b.trade_date, "收盘": b.close} for b in bars]
    df = pd.DataFrame(rows)
    df["日期"] = pd.to_datetime(df["日期"])
    return df.sort_values("日期").reset_index(drop=True)


def fetch_stock_fundamental_text(ticker: str, router: DataRouter) -> str:
    """
    获取 600900.SH 基本面快照，格式化为 Markdown 文本。
    字段来自 AKShare stock_a_lg_indicator，缺失字段以 N/A 显示。
    """
    try:
        report = router.get_fundamental(ticker)
        lines = [
            f"## 长江电力（{ticker}）基本面快照",
            f"",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 数据日期 | {report.report_date} |",
            f"| 市盈率 TTM | {f'{report.pe_ttm:.2f}' if report.pe_ttm else 'N/A'} |",
            f"| 市净率 | {f'{report.pb:.2f}' if report.pb else 'N/A'} |",
            f"| 净资产收益率 | {f'{report.roe:.2%}' if report.roe else 'N/A'} |",
            f"| 营收同比 | {f'{report.revenue_yoy:.2%}' if report.revenue_yoy else 'N/A'} |",
            f"| 净利润同比 | {f'{report.net_profit_yoy:.2%}' if report.net_profit_yoy else 'N/A'} |",
            f"",
            f"> 数据源：AKShare stock_a_lg_indicator（若字段为 N/A 表示当前版本接口未返回该字段）",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.warning("基本面获取失败: %s", e)
        return f"基本面数据获取失败：{e}"


def run_all_backtests(price_df: pd.DataFrame,
                      lookback_years: int,
                      invest_period: str,
                      invest_amount: float) -> dict:
    """运行主回测 + 两个极端场景压测。"""
    backtester = DCABacktester(price_df, invest_amount, invest_period)
    results = {}

    end_dt   = datetime.now()
    main_start = end_dt - timedelta(days=lookback_years * 365)
    results["main"] = backtester.run(main_start, end_dt,
                                     label=f"近{lookback_years}年主回测")

    # 熊市压测：2022 年
    bear_start = datetime(2022, 1, 1)
    bear_end   = datetime(2022, 12, 31)
    results["bear_2022"] = backtester.run(bear_start, bear_end, label="2022年A股熊市压测")

    # 利率压测：2023-2024 低利率窗口（电力股对利率敏感）
    rate_start = datetime(2023, 1, 1)
    rate_end   = datetime(2024, 12, 31)
    results["rate_2023_2024"] = backtester.run(rate_start, rate_end, label="2023-2024低利率窗口")

    return results


def fmt_backtest(r: dict) -> str:
    if not r or "error" in r:
        return f"> ⚠ {r.get('error', '数据不足')}"
    lines = [
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 回测区间 | {r['start_date']} ~ {r['end_date']} |",
        f"| 定投周期 | {r['period']} · 每期 ¥{r['invest_amount_per_period']:.0f} |",
        f"| 总投入 | ¥{r['total_invested_cny']:,.2f} |",
        f"| 期末市值 | ¥{r['final_portfolio_value_cny']:,.2f} |",
        f"| **累计收益率** | **{r['total_return_pct']:+.2f}%** |",
        f"| 年化收益率 (CAGR) | {r['cagr_pct']:+.2f}% |",
        f"| 最大回撤 | {r['max_drawdown_pct']:.2f}% |",
        f"| 定投均价 | ¥{r['avg_cost']:.3f} |",
        f"| 期末价格 | ¥{r['final_price']:.3f} |",
        f"| 成本平滑效果 | 定投均价{'低于' if r['cost_vs_final_pct'] < 0 else '高于'}期末价 {abs(r['cost_vs_final_pct']):.2f}% |",
        f"| **定投胜率** | **{r['win_rate_pct']:.1f}%** |",
        f"| 一次性买入收益 | {r['lump_sum_return_pct']:+.2f}% |",
        f"| **定投 vs 一次性** | **{r['dca_vs_lump_sum_pct']:+.2f}%** |",
    ]
    return "\n".join(lines)


def run_agent_analysis(ticker: str, analysis_date: str) -> tuple[dict, str]:
    """调用 TradingAgentsGraph 进行定性多智能体分析。"""
    try:
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        from tradingagents.dataflows.config import set_config

        set_config(CONFIG)
        ta = TradingAgentsGraph(
            selected_analysts=["market", "news", "fundamentals"],
            debug=False,
            config=CONFIG,
            callbacks=[],
        )
        final_state, decision = ta.propagate(ticker, analysis_date)
        return final_state, decision
    except Exception as e:
        logger.error("AI 分析失败: %s", e)
        return {}, f"ERROR: {e}"


def build_report(ticker: str,
                 lookback_years: int,
                 invest_period: str,
                 invest_amount: float,
                 analysis_date: str,
                 fundamental_text: str,
                 backtest_results: dict,
                 agent_state: dict,
                 ai_decision: str) -> str:

    period_label = PERIOD_CONFIG.get(invest_period, {}).get("label", invest_period)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    market_rpt  = agent_state.get("market_report",        "_未生成_")
    news_rpt    = agent_state.get("news_report",           "_未生成_")
    fund_rpt    = agent_state.get("fundamentals_report",   "_未生成_")
    debate      = agent_state.get("investment_debate_state", {})
    bull_h      = debate.get("bull_history", "")
    bear_h      = debate.get("bear_history", "")
    judge_d     = debate.get("judge_decision", "")
    trader_plan = agent_state.get("trader_investment_plan", "_未生成_")
    risk_state  = agent_state.get("risk_debate_state", {})
    risk_h      = risk_state.get("history", "")
    risk_judge  = risk_state.get("judge_decision", "")
    final_dec   = agent_state.get("final_trade_decision",  "_未生成_")

    main_bt        = backtest_results.get("main", {})
    bear_bt        = backtest_results.get("bear_2022", {})
    rate_bt        = backtest_results.get("rate_2023_2024", {})

    return f"""# {ticker} 长江电力 · 长线投资可行性分析报告

> **生成时间**：{now_str}
> **框架**：TradingAgents (TauricResearch) · 定投分支 feature/regular-investment
> **数据基建**：tradingagents.data.DataRouter v1（AKShare Primary → yfinance Fallback）
> **LLM**：{CONFIG.get('llm_provider', 'N/A').title()} — {CONFIG.get('deep_think_llm', 'N/A')}
> **分析日期**：{analysis_date}
> **定投策略**：{period_label} · 每期 ¥{invest_amount:.0f} · 回测 {lookback_years} 年

---

## 一、公司基本面数据

{fundamental_text}

---

## 二、DCA 定投历史回测

### 2.1 主回测（近 {lookback_years} 年）

{fmt_backtest(main_bt)}

---

### 2.2 极端场景压测一：2022 年 A 股熊市

{fmt_backtest(bear_bt)}

---

### 2.3 极端场景压测二：2023-2024 低利率窗口（利率敏感性检验）

{fmt_backtest(rate_bt)}

---

## 三、AI 多智能体定性分析

### 3.1 市场技术分析师报告

{market_rpt}

---

### 3.2 新闻舆情分析师报告

{news_rpt}

---

### 3.3 基本面分析师报告

{fund_rpt}

---

### 3.4 多空辩论

**多方论点：**

{bull_h}

**空方论点：**

{bear_h}

**辩论裁决：**

{judge_d}

---

### 3.5 交易员投资计划

{trader_plan}

---

### 3.6 风险委员会

{risk_h}

**风险裁决：**

{risk_judge}

---

### 3.7 最终交易决策

{final_dec}

---

## 四、综合结论

> **AI 信号**：`{ai_decision}`

### 长线投资关键维度评估

| 维度 | 评分依据 |
|------|----------|
| 业务护城河 | 水电资源垄断性强，装机容量全球前列，收入可预期 |
| 股息政策 | 承诺高比例分红，适合长期持有 |
| 利率敏感性 | 高负债率 + 高分红特性，对无风险利率变动较敏感 |
| 定投适合度 | 见 DCA 回测数据 |
| 数据来源 | AKShare（Primary）+ yfinance（Fallback）+ DeepSeek AI |

---

*报告由 TradingAgents 自动生成，仅供学习研究，不构成投资建议。*
"""


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    analysis_date = datetime.now().strftime("%Y-%m-%d")

    print("\n" + "═" * 70)
    print("  600900.SH 长江电力 · 长线投资可行性分析")
    print(f"  模型：DeepSeek-Chat · 回测：{LOOKBACK_YEARS}年 · 数据：DataRouter v1")
    print("═" * 70)

    # Step 1: 初始化 DataRouter，拉取历史行情
    print(f"\n[1/4] 初始化 DataRouter，拉取 {TICKER} 近 {LOOKBACK_YEARS+1} 年历史行情...")
    router = DataRouter()

    from datetime import date as _date
    end_date   = _date.today()
    start_date = end_date.replace(year=end_date.year - LOOKBACK_YEARS - 1)  # 多一年缓冲

    bars = router.get_ohlcv(TICKER, start_date, end_date)
    print(f"  ✓ 获取 {len(bars)} 根 K 线，首根：{bars[0].trade_date}，末根：{bars[-1].trade_date}")

    price_df = bars_to_dataframe(bars)

    # Step 2: 基本面快照
    print(f"\n[2/4] 获取基本面数据...")
    fundamental_text = fetch_stock_fundamental_text(TICKER, router)
    print("  ✓ 基本面数据获取完成")

    # Step 3: DCA 回测
    print(f"\n[3/4] 运行 DCA 历史回测（含极端场景压测）...")
    backtest_results = run_all_backtests(
        price_df, LOOKBACK_YEARS, INVEST_PERIOD, INVEST_AMOUNT
    )
    main_bt = backtest_results.get("main", {})
    if "error" not in main_bt:
        print(f"  ✓ 主回测完成：累计收益 {main_bt['total_return_pct']:+.2f}%，"
              f"CAGR {main_bt['cagr_pct']:+.2f}%，胜率 {main_bt['win_rate_pct']:.1f}%")
    else:
        print(f"  ⚠ 主回测失败：{main_bt['error']}")

    # Step 4: AI 多智能体定性分析
    print(f"\n[4/4] 启动 AI 多智能体分析（market + news + fundamentals）...")
    agent_state, ai_decision = run_agent_analysis(TICKER, analysis_date)
    print(f"  ✓ AI 分析完成，信号：{ai_decision}")

    # 生成并保存报告
    report = build_report(
        ticker=TICKER,
        lookback_years=LOOKBACK_YEARS,
        invest_period=INVEST_PERIOD,
        invest_amount=INVEST_AMOUNT,
        analysis_date=analysis_date,
        fundamental_text=fundamental_text,
        backtest_results=backtest_results,
        agent_state=agent_state,
        ai_decision=ai_decision,
    )

    code = TICKER.split(".")[0]
    safe_date = analysis_date.replace("-", "")
    dir_path = Path(OUTPUT_DIR) / f"RI_{code}_{safe_date}"
    dir_path.mkdir(parents=True, exist_ok=True)
    report_file = dir_path / f"RI_{code}_analysis_{analysis_date}.md"
    report_file.write_text(report, encoding="utf-8")

    print("\n" + "═" * 70)
    print(f"  分析完成！AI 信号：{ai_decision}")
    print(f"  报告路径：{report_file}")
    print("═" * 70)
    print("\n" + "─" * 70)
    print(report[:2000])
    print("─" * 70)


if __name__ == "__main__":
    main()
