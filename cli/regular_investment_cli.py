"""
regular_investment_cli.py — 定投分析专属交互式 CLI
==================================================
【新增模块】feature/regular-investment 分支专属文件
入口命令：tradingagents-ri

设计原则
--------
- 完全独立：不修改任何原生 cli/main.py 或 cli/steps.py
- 风格一致：复用 cli/utils.py 中的 select_llm_provider / select_deep_thinking_agent 等函数
- 独立流程：定投专属的 7 步交互式问卷，基于 questionary + Rich 终端 UI

交互步骤
--------
  Step 1  选择投资标的类型（ETF / 宽基指数 / 行业指数 / 个股）
  Step 2  输入标的代码（默认 159928.SZ）
  Step 3  选择定投周期（月定投 / 双周定投 / 周定投）
  Step 4  选择回测年限（1 / 3 / 5 / 10 年）
  Step 5  选择研究深度（Medium / High）
  Step 6  选择 LLM 提供商（复用 cli/utils.py）
  Step 7  确认配置 → 启动分析

依赖
----
  pip install akshare questionary rich typer python-dotenv
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import typer
import questionary
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich import box

load_dotenv()

# ── 复用原生工具函数（不修改原文件） ──────────────────────────────────────
from cli.utils import (
    select_llm_provider,
    select_shallow_thinking_agent,
    select_deep_thinking_agent,
)

console = Console()

# ── Typer App ──────────────────────────────────────────────────────────────
app = typer.Typer(
    name="TradingAgents-RI",
    help="TradingAgents 定投分析 CLI：ETF / 指数 长线定投可行性分析",
    add_completion=False,
)

# ── 常量 ──────────────────────────────────────────────────────────────────

TARGET_TYPES = [
    ("消费类ETF / 宽基ETF（如 159928.SZ 消费ETF，510300.SH 沪深300ETF）", "etf"),
    ("宽基指数（如 000300 沪深300，000905 中证500）", "broad_index"),
    ("行业指数（如 399006 创业板指，000932 中证消费）", "sector_index"),
    ("A股个股（如 601298.SH 青岛港）", "stock"),
]

DEFAULT_TICKER_MAP = {
    "etf":          "159928.SZ",
    "broad_index":  "000300.SH",
    "sector_index": "000932.SH",
    "stock":        "601298.SH",
}

PERIOD_OPTIONS = [
    ("月定投 — 每月固定日期投入（最常见，适合工薪族）", "monthly"),
    ("双周定投 — 每两周投入，比月定投更平滑", "biweekly"),
    ("周定投 — 每周投入，成本平滑效果最强", "weekly"),
]

BACKTEST_YEARS = [
    ("近 1 年（快速验证，数据充分）", 1),
    ("近 3 年（覆盖牛熊转换，推荐）", 3),
    ("近 5 年（覆盖完整市场周期）", 5),
    ("近 10 年（长期历史，数据可能不完整）", 10),
]

DEPTH_OPTIONS = [
    ("Medium — 3 轮辩论，适合快速评估", 3),
    ("High   — 5 轮辩论，深度研究（推荐）", 5),
]

INVEST_AMOUNT_OPTIONS = [
    ("每期 ¥500（适合轻仓试水）", 500.0),
    ("每期 ¥1,000（标准定投金额）", 1000.0),
    ("每期 ¥2,000（中等仓位）", 2000.0),
    ("每期 ¥5,000（重仓定投）", 5000.0),
    ("自定义金额", -1.0),
]

_QUESTIONARY_STYLE = questionary.Style([
    ("selected",     "fg:cyan noinherit"),
    ("highlighted",  "fg:cyan noinherit"),
    ("pointer",      "fg:cyan noinherit"),
    ("checkbox-selected", "fg:cyan"),
])


# ── Welcome Banner ────────────────────────────────────────────────────────

def _print_banner() -> None:
    console.print()
    console.print(Panel(
        "[bold cyan]TradingAgents · 定投可行性分析系统[/bold cyan]\n\n"
        "[dim]feature/regular-investment 分支 · 独立模块，不影响原生短线分析[/dim]\n\n"
        "  命令：[green]tradingagents-ri[/green]   ←  定投分析\n"
        "  命令：[yellow]tradingagents[/yellow]      ←  原生短线交易分析（不受影响）",
        title="[bold]欢迎使用[/bold]",
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()


# ── 各步骤交互函数 ────────────────────────────────────────────────────────

def _step_target_type() -> str:
    """Step 1: 选择投资标的类型。"""
    console.print(Rule("[bold cyan]Step 1 / 7  — 选择投资标的类型[/bold cyan]", style="cyan"))
    choice = questionary.select(
        "请选择定投标的类型：",
        choices=[questionary.Choice(d, value=v) for d, v in TARGET_TYPES],
        instruction="\n- 上下方向键选择 · Enter 确认",
        style=_QUESTIONARY_STYLE,
    ).ask()
    if not choice:
        console.print("[red]未选择标的类型，退出。[/red]")
        raise typer.Exit(1)
    return choice


def _step_ticker(target_type: str) -> str:
    """Step 2: 输入标的代码。"""
    console.print(Rule("[bold cyan]Step 2 / 7  — 输入标的代码[/bold cyan]", style="cyan"))
    default = DEFAULT_TICKER_MAP.get(target_type, "159928.SZ")
    ticker = questionary.text(
        f"请输入标的代码（直接按 Enter 使用默认值 [{default}]）：",
        default=default,
        validate=lambda x: len(x.strip()) >= 4 or "请输入有效的标的代码（如 159928.SZ）",
        style=_QUESTIONARY_STYLE,
    ).ask()
    if not ticker:
        ticker = default
    return ticker.strip().upper()


def _step_period() -> str:
    """Step 3: 选择定投周期。"""
    console.print(Rule("[bold cyan]Step 3 / 7  — 选择定投周期[/bold cyan]", style="cyan"))
    choice = questionary.select(
        "请选择定投周期：",
        choices=[questionary.Choice(d, value=v) for d, v in PERIOD_OPTIONS],
        instruction="\n- 上下方向键选择 · Enter 确认",
        default=PERIOD_OPTIONS[0][1],
        style=_QUESTIONARY_STYLE,
    ).ask()
    if not choice:
        return "monthly"
    return choice


def _step_invest_amount() -> float:
    """Step 4a: 选择每期定投金额。"""
    console.print(Rule("[bold cyan]Step 4a / 7  — 选择每期定投金额[/bold cyan]", style="cyan"))
    choice = questionary.select(
        "请选择每期定投金额：",
        choices=[questionary.Choice(d, value=v) for d, v in INVEST_AMOUNT_OPTIONS],
        instruction="\n- 上下方向键选择 · Enter 确认",
        style=_QUESTIONARY_STYLE,
    ).ask()
    if choice == -1.0 or choice is None:
        raw = questionary.text(
            "请输入自定义金额（元，如 3000）：",
            validate=lambda x: x.replace(".", "").isdigit() or "请输入有效数字",
            style=_QUESTIONARY_STYLE,
        ).ask()
        return float(raw) if raw else 1000.0
    return float(choice)


def _step_backtest_years() -> int:
    """Step 4b: 选择回测年限。"""
    console.print(Rule("[bold cyan]Step 4b / 7  — 选择回测年限[/bold cyan]", style="cyan"))
    choice = questionary.select(
        "请选择历史回测年限：",
        choices=[questionary.Choice(d, value=v) for d, v in BACKTEST_YEARS],
        instruction="\n- 上下方向键选择 · Enter 确认",
        default=BACKTEST_YEARS[1][1],
        style=_QUESTIONARY_STYLE,
    ).ask()
    if choice is None:
        return 3
    return int(choice)


def _step_depth() -> int:
    """Step 5: 选择研究深度。"""
    console.print(Rule("[bold cyan]Step 5 / 7  — 选择研究深度[/bold cyan]", style="cyan"))
    choice = questionary.select(
        "请选择 AI 研究深度（决定辩论轮数）：",
        choices=[questionary.Choice(d, value=v) for d, v in DEPTH_OPTIONS],
        instruction="\n- 上下方向键选择 · Enter 确认",
        default=DEPTH_OPTIONS[1][1],
        style=_QUESTIONARY_STYLE,
    ).ask()
    if choice is None:
        return 5
    return int(choice)


def _step_llm() -> dict:
    """Step 6: 选择 LLM 提供商及模型（复用原生 cli/utils.py 函数）。"""
    console.print(Rule("[bold cyan]Step 6 / 7  — 选择 LLM 提供商[/bold cyan]", style="cyan"))
    provider_name, backend_url = select_llm_provider()
    provider_lower = provider_name.lower()

    console.print(Rule("[bold cyan]Step 6b/7  — 选择快速思考模型[/bold cyan]", style="cyan"))
    quick_llm = select_shallow_thinking_agent(provider_lower)

    console.print(Rule("[bold cyan]Step 6c/7  — 选择深度推理模型[/bold cyan]", style="cyan"))
    deep_llm = select_deep_thinking_agent(provider_lower)

    return {
        "provider": provider_lower,
        "backend_url": backend_url,
        "quick_llm": quick_llm,
        "deep_llm": deep_llm,
    }


def _step_output_language() -> str:
    """Step 7a: 选择报告输出语言。"""
    console.print(Rule("[bold cyan]Step 7 / 7  — 选择报告语言[/bold cyan]", style="cyan"))
    choice = questionary.select(
        "请选择报告输出语言：",
        choices=[
            questionary.Choice("中文（Chinese）- 推荐", value="Chinese"),
            questionary.Choice("English", value="English"),
        ],
        style=_QUESTIONARY_STYLE,
    ).ask()
    return choice or "Chinese"


def _confirm_config(config_summary: dict) -> bool:
    """展示配置摘要并确认。"""
    console.print()
    console.print(Rule("[bold green]配置确认[/bold green]", style="green"))

    table = Table(box=box.ROUNDED, border_style="green", show_header=True)
    table.add_column("配置项", style="bold cyan", min_width=16)
    table.add_column("值", style="white")

    for k, v in config_summary.items():
        table.add_row(k, str(v))

    console.print(table)
    console.print()

    confirmed = questionary.confirm(
        "以上配置是否正确？确认后将启动定投分析（预计 15~40 分钟）",
        default=True,
        style=_QUESTIONARY_STYLE,
    ).ask()

    return confirmed if confirmed is not None else False


# ── 主执行函数 ─────────────────────────────────────────────────────────────

def _run_ri_analysis(selections: dict) -> None:
    """根据用户选择构建 config 并调用 RIOrchestrator。"""
    from tradingagents.ri_orchestrator import RIOrchestrator
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"]            = selections["provider"]
    config["deep_think_llm"]          = selections["deep_llm"]
    config["quick_think_llm"]         = selections["quick_llm"]
    config["backend_url"]             = selections["backend_url"]
    config["max_debate_rounds"]       = selections["depth"]
    config["max_risk_discuss_rounds"] = selections["depth"]
    config["max_recur_limit"]         = 200
    config["output_language"]         = selections["language"]
    config["data_vendors"] = {
        "core_stock_apis":      "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data":     "akshare",
        "news_data":            "yfinance",
    }

    # 处理 provider 特殊配置
    provider = selections["provider"]
    if provider == "openai":
        config["openai_reasoning_effort"] = "high"
    elif provider == "anthropic":
        config["anthropic_effort"] = "high"
    elif provider == "google":
        config["google_thinking_level"] = "high"

    console.print()
    console.print(Panel(
        f"[bold green]✓ 正在启动定投分析...[/bold green]\n\n"
        f"  标的：[yellow]{selections['ticker']}[/yellow]\n"
        f"  策略：[cyan]{selections['period']}[/cyan] · 每期 ¥{selections['invest_amount']:.0f}\n"
        f"  回测：近 [cyan]{selections['backtest_years']} 年[/cyan]（含极端场景压测）\n"
        f"  AI：[magenta]{selections['provider'].title()}[/magenta] · "
        f"Deep={selections['deep_llm']} · Quick={selections['quick_llm']}",
        border_style="green",
        padding=(1, 2),
    ))

    orchestrator = RIOrchestrator(config=config)

    start_time = time.time()
    try:
        report_text, report_path = orchestrator.run_analysis(
            ticker=selections["ticker"],
            lookback_years=selections["backtest_years"],
            invest_period=selections["period"],
            invest_amount=selections["invest_amount"],
            analysis_date=datetime.now().strftime("%Y-%m-%d"),
            output_dir="results",
            target_type=selections["target_type"],
        )

        elapsed = time.time() - start_time
        console.print()
        console.print(Panel(
            f"[bold green]✅ 分析完成！耗时 {elapsed / 60:.1f} 分钟[/bold green]\n\n"
            f"  报告路径：[yellow]{report_path}[/yellow]\n\n"
            f"  **最终信号（仅供参考）**：[bold cyan]{orchestrator._last_decision}[/bold cyan]\n\n"
            f"  ⚠️ 本报告由 AI 生成，不构成投资建议，实际交易需自行承担风险",
            border_style="green",
            padding=(1, 2),
        ))

    except Exception as e:
        import traceback
        console.print(f"\n[bold red]分析过程中发生异常：{e}[/bold red]")
        traceback.print_exc()
        raise typer.Exit(1)


# ── Typer 入口命令 ────────────────────────────────────────────────────────

@app.command()
def main():
    """
    TradingAgents 定投可行性分析 CLI

    运行交互式问卷，收集定投标的、周期、回测年限、LLM 配置后，
    自动启动 DCA 历史回测 + AI 多智能体分析，生成结构化可行性报告。

    示例：
        tradingagents-ri            # 完整交互式流程
    """
    _print_banner()

    # Step 1: 标的类型
    target_type = _step_target_type()

    # Step 2: 标的代码
    ticker = _step_ticker(target_type)

    # Step 3: 定投周期
    period = _step_period()

    # Step 4a: 每期金额
    invest_amount = _step_invest_amount()

    # Step 4b: 回测年限
    backtest_years = _step_backtest_years()

    # Step 5: 研究深度
    depth = _step_depth()

    # Step 6: LLM
    llm_config = _step_llm()

    # Step 7: 输出语言
    language = _step_output_language()

    # 汇总配置
    period_label_map = {"monthly": "月定投", "biweekly": "双周定投", "weekly": "周定投"}
    selections = {
        "ticker":         ticker,
        "target_type":    target_type,
        "period":         period,
        "invest_amount":  invest_amount,
        "backtest_years": backtest_years,
        "depth":          depth,
        "language":       language,
        **llm_config,
    }

    config_summary = {
        "标的代码":    ticker,
        "定投周期":    period_label_map.get(period, period),
        "每期金额":    f"¥{invest_amount:.0f}",
        "回测年限":    f"{backtest_years} 年",
        "研究深度":    f"{'Medium' if depth == 3 else 'High'} ({depth} 轮辩论)",
        "LLM 提供商":  llm_config["provider"].title(),
        "深度推理模型": llm_config["deep_llm"],
        "快速思考模型": llm_config["quick_llm"],
        "报告语言":    language,
    }

    confirmed = _confirm_config(config_summary)
    if not confirmed:
        console.print("\n[yellow]已取消，未启动分析。[/yellow]")
        raise typer.Exit(0)

    _run_ri_analysis(selections)


if __name__ == "__main__":
    app()
