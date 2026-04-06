"""
ri_orchestrator.py — 定投专属多智能体编排器
============================================
【新增模块】feature/regular-investment 分支专属文件
本文件不修改任何原生代码，仅对 TradingAgentsGraph 进行封装与扩展。

核心逻辑
--------
1. 使用 ri_fundamental 拉取 ETF/指数全维度数据
2. 运行 DCA (Dollar-Cost Averaging) 历史回测，输出可量化指标
3. 调用原生 TradingAgentsGraph 进行定性多智能体分析
4. 将定量回测 + 定性 AI 分析合并为结构化《可行性分析报告》

DCA 回测指标
-----------
  - 累计收益率 / 年化收益率
  - 最大回撤（组合价值）
  - 定投胜率（持有期内盈利月数占比）
  - 定投 vs 一次性买入收益对比
  - 成本平滑效果（定投均价 vs 期末价格对比）
  - 极端场景压测：2022熊市 / 2024消费回调
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from tradingagents.dataflows.ri_fundamental import (
    get_etf_snapshot,
    get_etf_holdings,
    get_etf_price_history,
    get_etf_dividends,
    get_full_etf_report,
    get_stock_price_history,
    get_full_stock_report,
    get_full_index_report,
)
from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


# ── 定投周期配置 ─────────────────────────────────────────────────────────────

PERIOD_CONFIG = {
    "monthly":   {"label": "月定投",  "days": 30,  "periods_per_year": 12},
    "biweekly":  {"label": "双周定投", "days": 14,  "periods_per_year": 26},
    "weekly":    {"label": "周定投",   "days": 7,   "periods_per_year": 52},
}


# ── DCA 回测引擎 ─────────────────────────────────────────────────────────────

class DCABacktester:
    """Dollar-Cost Averaging 历史回测引擎。"""

    def __init__(self,
                 price_df: pd.DataFrame,
                 invest_amount: float = 1000.0,
                 invest_period: str = "monthly"):
        """
        price_df : pd.DataFrame，必须含列 '日期'(datetime) 和 '收盘'(float)
        invest_amount : 每期定投金额（元）
        invest_period : 'monthly' | 'biweekly' | 'weekly'
        """
        self.invest_amount = invest_amount
        self.invest_period = invest_period
        self.period_days = PERIOD_CONFIG[invest_period]["days"]
        self.periods_per_year = PERIOD_CONFIG[invest_period]["periods_per_year"]

        # 确保日期列为 datetime 类型并排序
        df = price_df.copy()
        date_col = "日期" if "日期" in df.columns else "Date"
        if date_col not in df.columns:
            date_col = df.columns[0]
        _dates = pd.to_datetime(df[date_col], errors="coerce")
        if _dates.dt.tz is not None:
            _dates = _dates.dt.tz_localize(None)
        df[date_col] = _dates
        df = df.dropna(subset=[date_col]).sort_values(date_col)

        close_col = "收盘" if "收盘" in df.columns else "Close"
        if close_col not in df.columns:
            # 尝试找价格列
            for c in df.columns:
                if df[c].dtype in (float, "float64", "float32"):
                    close_col = c
                    break

        df = df.rename(columns={date_col: "date", close_col: "close"})
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"])
        self.price_df = df[["date", "close"]].reset_index(drop=True)

    def _get_invest_dates(self, start_date: datetime,
                           end_date: datetime) -> list[datetime]:
        """按定投周期生成投资日期列表（取交易日内最近一个日期）。"""
        trading_dates = set(self.price_df["date"].dt.date)
        invest_dates = []
        current = start_date
        while current <= end_date:
            # 找到 current 之后最近的交易日（向后滚动最多7天）
            for offset in range(8):
                candidate = (current + timedelta(days=offset)).date()
                if candidate in trading_dates:
                    invest_dates.append(datetime.combine(candidate, datetime.min.time()))
                    break
            current += timedelta(days=self.period_days)
        return invest_dates

    def run(self,
            start_date: datetime,
            end_date: datetime,
            label: str = "主回测") -> dict:
        """运行 DCA 回测，返回结果字典。"""
        df = self.price_df
        df_period = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()

        if df_period.empty or len(df_period) < 2:
            return {"error": f"价格数据不足（{label}），无法回测"}

        invest_dates = self._get_invest_dates(start_date, end_date)
        if not invest_dates:
            return {"error": f"回测区间内无定投日（{label}）"}

        # ── 逐期模拟买入 ──────────────────────────────────────────────
        records = []
        total_shares = 0.0
        total_invested = 0.0

        for inv_date in invest_dates:
            # 找到当日或最近一个交易日价格
            mask = df_period["date"] <= pd.Timestamp(inv_date)
            if not mask.any():
                continue
            price_row = df_period[mask].iloc[-1]
            price = price_row["close"]
            shares_bought = self.invest_amount / price
            total_shares += shares_bought
            total_invested += self.invest_amount
            records.append({
                "date": price_row["date"],
                "price": price,
                "shares_bought": shares_bought,
                "total_shares": total_shares,
                "total_invested": total_invested,
                "portfolio_value": total_shares * price,
            })

        if not records:
            return {"error": f"没有有效买入记录（{label}）"}

        rec_df = pd.DataFrame(records)
        final_price = df_period["close"].iloc[-1]
        final_value = total_shares * final_price
        total_return_pct = (final_value / total_invested - 1) * 100

        # 年化收益率（CAGR）
        years = (end_date - start_date).days / 365
        cagr = (final_value / total_invested) ** (1 / max(years, 0.1)) - 1 if years > 0 else 0

        # 最大回撤（组合价值，使用已记录的 portfolio_value）
        pv = rec_df["portfolio_value"]
        roll_max = pv.cummax()
        drawdown = (pv - roll_max) / roll_max.replace(0, float("nan"))
        max_drawdown_pct = drawdown.min() * 100 if not drawdown.isna().all() else 0.0

        # 定投均价 & 成本平滑
        avg_cost = total_invested / total_shares
        cost_vs_final = (final_price / avg_cost - 1) * 100

        # 胜率（期末价格 > 该期买入价格的频率）
        win_count = (rec_df["price"] < final_price).sum()
        win_rate = win_count / len(rec_df) * 100

        # 一次性买入对比
        lump_sum_shares = total_invested / df_period["close"].iloc[0]
        lump_sum_value = lump_sum_shares * final_price
        lump_sum_return = (lump_sum_value / total_invested - 1) * 100
        outperform_lump = total_return_pct - lump_sum_return

        return {
            "label": label,
            "period": PERIOD_CONFIG[self.invest_period]["label"],
            "invest_amount_per_period": self.invest_amount,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "total_periods": len(records),
            "total_invested_cny": round(total_invested, 2),
            "final_portfolio_value_cny": round(final_value, 2),
            "total_return_pct": round(total_return_pct, 2),
            "cagr_pct": round(cagr * 100, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "avg_cost": round(avg_cost, 4),
            "final_price": round(final_price, 4),
            "cost_vs_final_pct": round(cost_vs_final, 2),
            "win_rate_pct": round(win_rate, 2),
            "lump_sum_return_pct": round(lump_sum_return, 2),
            "dca_vs_lump_sum_pct": round(outperform_lump, 2),
        }


# ── 主编排器 ─────────────────────────────────────────────────────────────────

class RIOrchestrator:
    """
    定投分析主编排器。
    调用链：ETF 数据 → DCA 回测 → AI 多智能体定性分析 → 合并报告
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or DEFAULT_CONFIG.copy()
        # 定投分析强制使用 AKShare 获取财务数据
        self.config.setdefault("data_vendors", {})
        self.config["data_vendors"]["fundamental_data"] = "akshare"
        self._last_decision: str = "N/A"   # 保存最后一次 AI 信号，供 CLI 读取

    @staticmethod
    def _provider_label(config: Dict[str, Any]) -> str:
        provider = str(config.get("llm_provider", "N/A")).title()
        deep = config.get("deep_think_llm", "N/A")
        quick = config.get("quick_think_llm", "N/A")
        return f"{provider} · Deep={deep} · Quick={quick}"

    # ── 公开入口 ─────────────────────────────────────────────────────────

    def run_analysis(
        self,
        ticker: str,
        lookback_years: int = 3,
        invest_period: str = "monthly",
        invest_amount: float = 1000.0,
        analysis_date: str = None,
        output_dir: str = "results",
        target_type: str = "etf",
        callbacks=None,
    ) -> Tuple[str, str]:
        """
        运行完整定投分析。

        Returns
        -------
        (report_text, report_file_path)
        """
        if analysis_date is None:
            analysis_date = datetime.now().strftime("%Y-%m-%d")

        logger.info("=== 定投分析启动：%s  %s  %s年回测 ===",
                    ticker, PERIOD_CONFIG[invest_period]["label"], lookback_years)

        # ── Step 1: 拉取标的基础数据 ──────────────────────────────────
        _type_label = {"etf": "ETF", "stock": "个股", "broad_index": "宽基指数", "sector_index": "行业指数"}.get(target_type, "标的")
        print(f"\n[1/4] 拉取 {ticker} {_type_label}基础数据...")
        print("    · 正在抓取基础信息、历史行情和基础摘要...")
        etf_data_text = self._fetch_instrument_data(ticker, target_type, lookback_years, analysis_date)
        print(f"  ✓ {_type_label}数据获取完成")

        # ── Step 2: DCA 历史回测 ───────────────────────────────────────
        print(f"\n[2/4] 运行 DCA 历史回测（{lookback_years}年，含极端场景）...")
        print("    · 正在准备历史价格序列并构建定投回测窗口...")
        backtest_results = self._run_all_backtests(
            ticker, lookback_years, invest_period, invest_amount, target_type
        )
        print("  ✓ 回测计算完成")

        # ── Step 3: AI 多智能体定性分析 ───────────────────────────────
        print(f"\n[3/4] 启动 AI 多智能体定性分析（{self._provider_label(self.config)}）...")
        print("    · 正在初始化 Analyst Team → Research Team → Trader → Risk Management")
        agent_state, ai_decision = self._run_agent_analysis(
            ticker, analysis_date, callbacks
        )
        self._last_decision = ai_decision
        print(f"  ✓ AI 分析完成，信号：{ai_decision}")

        # ── Step 4: 生成综合报告 ───────────────────────────────────────
        print(f"\n[4/4] 生成《定投可行性分析报告》...")
        report = self._build_report(
            ticker=ticker,
            lookback_years=lookback_years,
            invest_period=invest_period,
            invest_amount=invest_amount,
            analysis_date=analysis_date,
            etf_data_text=etf_data_text,
            backtest_results=backtest_results,
            agent_state=agent_state,
            ai_decision=ai_decision,
            target_type=target_type,
        )

        # 保存报告
        code = ticker.split(".")[0]
        safe_date = analysis_date.replace("-", "")
        dir_path = Path(output_dir) / f"RI_{code}_{safe_date}"
        dir_path.mkdir(parents=True, exist_ok=True)
        report_file = dir_path / f"RI_{code}_analysis_{analysis_date}.md"
        report_file.write_text(report, encoding="utf-8")
        print(f"\n  ✅ 报告已保存：{report_file}")

        return report, str(report_file)

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _fetch_instrument_data(self, ticker: str, target_type: str,
                                lookback_years: int, analysis_date: str) -> str:
        """按 target_type 分发到对应数据获取函数。"""
        try:
            if target_type == "stock":
                return get_full_stock_report(ticker, lookback_years, analysis_date)
            elif target_type in ("broad_index", "sector_index"):
                return get_full_index_report(ticker, lookback_years, analysis_date)
            else:  # "etf" 及兜底
                return get_full_etf_report(ticker, lookback_years, analysis_date)
        except Exception as e:
            logger.warning("Instrument data fetch failed (%s): %s", target_type, e)
            return f"标的数据获取失败（{target_type}）：{e}"

    def _run_all_backtests(self,
                            ticker: str,
                            lookback_years: int,
                            invest_period: str,
                            invest_amount: float,
                            target_type: str = "etf") -> dict:
        """运行主回测 + 两个极端场景压测。"""
        results = {}

        # 获取历史价格：个股走 stock_zh_a_hist，ETF/指数走 fund_etf_hist_em
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=lookback_years * 365 + 90)  # 多取3个月缓冲
        if target_type == "stock":
            hist = get_stock_price_history(
                ticker,
                start_dt.strftime("%Y%m%d"),
                end_dt.strftime("%Y%m%d"),
            )
        else:
            hist = get_etf_price_history(
                ticker,
                start_dt.strftime("%Y%m%d"),
                end_dt.strftime("%Y%m%d"),
            )

        if hist is None or hist.empty:
            logger.warning("No price history for backtest: %s", ticker)
            return {"error": "价格数据不足，无法进行回测"}

        backtester = DCABacktester(hist, invest_amount, invest_period)

        # 主回测（近 lookback_years 年）
        main_start = end_dt - timedelta(days=lookback_years * 365)
        results["main"] = backtester.run(main_start, end_dt,
                                          label=f"近{lookback_years}年主回测")

        # 极端场景1: 2022年熊市（2022-01-01 ~ 2022-12-31）
        bear_start = datetime(2022, 1, 1)
        bear_end   = datetime(2022, 12, 31)
        if bear_start >= start_dt:
            results["bear_2022"] = backtester.run(
                bear_start, bear_end, label="2022年熊市压测"
            )

        # 极端场景2: 2024年消费回调（2024-01-01 ~ 2024-09-30）
        cons_start = datetime(2024, 1, 1)
        cons_end   = datetime(2024, 9, 30)
        if cons_start >= start_dt:
            results["consumer_2024"] = backtester.run(
                cons_start, cons_end, label="2024年消费回调压测"
            )

        return results

    def _run_agent_analysis(self, ticker: str,
                             analysis_date: str,
                             callbacks=None) -> Tuple[dict, str]:
        """调用原生 TradingAgentsGraph 进行定性分析。"""
        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.dataflows.config import set_config

            set_config(self.config)

            ta = TradingAgentsGraph(
                selected_analysts=["market", "news", "fundamentals"],
                debug=False,
                config=self.config,
                callbacks=callbacks or [],
            )
            init_agent_state = ta.propagator.create_initial_state(ticker, analysis_date)
            args = ta.propagator.get_graph_args()

            stage_labels = {
                "market_report": "市场技术分析师已完成",
                "news_report": "新闻分析师已完成",
                "fundamentals_report": "基本面分析师已完成",
                "investment_plan": "研究团队辩论与经理裁决已完成",
                "trader_investment_plan": "交易员计划已完成",
                "final_trade_decision": "风控与组合经理最终裁决已完成",
            }
            announced = {key: False for key in stage_labels}
            start_ts = time.time()
            last_heartbeat = start_ts
            final_state = None

            for chunk in ta.graph.stream(init_agent_state, **args):
                final_state = chunk

                for key, label in stage_labels.items():
                    if not announced[key] and chunk.get(key):
                        print(f"    · {label}")
                        announced[key] = True

                now = time.time()
                if now - last_heartbeat >= 20:
                    elapsed = int(now - start_ts)
                    print(f"    · 多智能体分析进行中，已运行 {elapsed} 秒，请稍候...")
                    last_heartbeat = now

            if not final_state:
                raise RuntimeError("多智能体分析未返回任何结果")

            decision = ta.process_signal(final_state["final_trade_decision"])
            return final_state, decision

        except Exception as e:
            logger.warning("Agent analysis failed: %s", e)
            return {}, f"ERROR: {e}"

    def _build_report(self,
                       ticker: str,
                       lookback_years: int,
                       invest_period: str,
                       invest_amount: float,
                       analysis_date: str,
                       etf_data_text: str,
                       backtest_results: dict,
                       agent_state: dict,
                       ai_decision: str,
                       target_type: str = "etf") -> str:
        """合并所有分析结果，生成完整 Markdown 报告。"""

        period_label = PERIOD_CONFIG.get(invest_period, {}).get("label", invest_period)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        instrument_label = {"etf": "ETF", "stock": "A股个股", "broad_index": "宽基指数", "sector_index": "行业指数"}.get(target_type, "标的")

        # 从 agent_state 提取各模块报告
        market_rpt   = agent_state.get("market_report", "_未生成_")
        news_rpt     = agent_state.get("news_report", "_未生成_")
        fund_rpt     = agent_state.get("fundamentals_report", "_未生成_")
        debate       = agent_state.get("investment_debate_state", {})
        bull_h       = debate.get("bull_history", "")
        bear_h       = debate.get("bear_history", "")
        debate_h     = debate.get("history", "")
        judge_d      = debate.get("judge_decision", "")
        trader_plan  = agent_state.get("trader_investment_plan", "_未生成_")
        risk_state   = agent_state.get("risk_debate_state", {})
        risk_h       = risk_state.get("history", "")
        risk_judge   = risk_state.get("judge_decision", "")
        final_dec    = agent_state.get("final_trade_decision", "_未生成_")

        # ── 格式化回测结果 ──────────────────────────────────────────
        def fmt_backtest(r: dict) -> str:
            if not r or "error" in r:
                return f"> ⚠ {r.get('error', '数据不足')}"
            lines = [
                f"| 指标 | 数值 |",
                f"|------|------|",
                f"| 回测区间 | {r['start_date']} ~ {r['end_date']} |",
                f"| 定投周期 | {r['period']} · 每期 ¥{r['invest_amount_per_period']:.0f} |",
                f"| 总投入 | ¥{r['total_invested_cny']:,.2f} |",
                f"| 期末市值 | ¥{r['final_portfolio_value_cny']:,.2f} |",
                f"| **累计收益率** | **{r['total_return_pct']:+.2f}%** |",
                f"| 年化收益率 (CAGR) | {r['cagr_pct']:+.2f}% |",
                f"| 最大回撤 | {r['max_drawdown_pct']:.2f}% |",
                f"| 定投均价 | ¥{r['avg_cost']:.4f} |",
                f"| 期末价格 | ¥{r['final_price']:.4f} |",
                f"| 成本平滑效果 | 定投均价{'低于' if r['cost_vs_final_pct'] < 0 else '高于'}期末价 {abs(r['cost_vs_final_pct']):.2f}% |",
                f"| **定投胜率** | **{r['win_rate_pct']:.1f}%**（买入批次中盈利占比）|",
                f"| 一次性买入收益 | {r['lump_sum_return_pct']:+.2f}% |",
                f"| **定投 vs 一次性** | **{r['dca_vs_lump_sum_pct']:+.2f}%**（正值=定投占优）|",
            ]
            return "\n".join(lines)

        main_bt    = backtest_results.get("main", {})
        bear_bt    = backtest_results.get("bear_2022", {})
        cons_bt    = backtest_results.get("consumer_2024", {})

        report = f"""# {ticker.upper()} 定投可行性分析报告

## {instrument_label}概览

> **生成时间**：{now_str}
> **框架**：TradingAgents (TauricResearch) · 定投分支 feature/regular-investment
> **LLM**：{self.config.get('llm_provider', 'N/A').title()} — {self.config.get('deep_think_llm', 'N/A')}
> **数据源**：AKShare（ETF基础/持仓）+ yfinance（行情备用）+ TradingAgents AI 分析
> **分析日期**：{analysis_date}
> **定投策略**：{period_label} · 每期 ¥{invest_amount:.0f} · 回测 {lookback_years} 年

---

## 一、{instrument_label}基础数据

{etf_data_text}

---

## 二、DCA 定投历史回测

### 2.1 主回测（近 {lookback_years} 年）

{fmt_backtest(main_bt)}

---

### 2.2 极端场景压测一：2022 年 A 股熊市

{fmt_backtest(bear_bt)}

---

### 2.3 极端场景压测二：2024 年消费板块回调

{fmt_backtest(cons_bt)}

---

## 三、AI 多智能体定性分析

### 3.1 市场技术分析师报告
{market_rpt}

---

### 3.2 新闻分析师报告
{news_rpt}

---

### 3.3 基本面分析师报告（成分股基本面）
{fund_rpt}

---

### 3.4 研究团队辩论摘要

#### 多方核心论点
{bull_h or "_多方论点未生成_"}

#### 空方核心论点
{bear_h or "_空方论点未生成_"}

#### 完整辩论记录
{debate_h or "_辩论记录未生成_"}

#### 研究经理裁决
{judge_d or "_裁决未生成_"}

---

### 3.5 交易员建议（转化为定投视角）
{trader_plan or "_未生成_"}

---

### 3.6 风险管理辩论
{risk_h or "_风险辩论未生成_"}

#### Portfolio Manager 最终裁决
{risk_judge or "_PM裁决未生成_"}

---

## 四、综合定投可行性结论

### AI 系统最终信号：`{ai_decision}`

### 定投可行性综合评分参考

| 维度 | 关键指标 | 说明 |
|------|---------|------|
| 回测收益 | {main_bt.get('cagr_pct', 'N/A')}% (CAGR) | 近{lookback_years}年年化收益 |
| 最大回撤 | {main_bt.get('max_drawdown_pct', 'N/A')}% | 区间内最深回撤 |
| 定投胜率 | {main_bt.get('win_rate_pct', 'N/A')}% | 买入批次中盈利比例 |
| 成本平滑 | {main_bt.get('cost_vs_final_pct', 'N/A')}% | 定投均价 vs 期末价格 |
| 熊市表现 | {bear_bt.get('total_return_pct', 'N/A')}% | 2022年全年回测 |
| AI信号 | {ai_decision} | 多智能体综合判断 |

{final_dec or "_最终决策未生成_"}

---

## 五、风险提示

> ⚠️ **本报告由 AI 多智能体系统自动生成，仅供参考，不构成任何投资建议。**
>
> - 历史回测结果不代表未来收益，过去表现不保证未来。
> - ETF 投资面临市场风险，包括但不限于：指数下跌风险、流动性风险、跟踪误差风险、ETF 折溢价风险。
> - A 股市场存在涨跌停限制（±10%）及流动性波动，定投不能完全规避系统性风险。
> - 请结合个人财务状况、风险承受能力和投资目标进行独立判断。
> - **本分析基于TradingAgents研究框架生成，不构成任何投资建议，实际交易需自行承担风险。**

---
*Generated by TradingAgents RI Module · {ticker.upper()} · {analysis_date}*
"""
        return report
