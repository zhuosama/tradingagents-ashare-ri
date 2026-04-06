"""
run_ri_159928.py — 159928.SZ (消费ETF) 完整定投可行性分析
========================================================
运行方式：
    cd d:/Trading-Agent/TradingAgents
    .venv/Scripts/python.exe run_ri_159928.py

输出：
    results/RI_159928_<date>/RI_159928_analysis_<date>.md
"""

import os, sys
sys.path.insert(0, ".")

# ── DeepSeek API Key ──────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "请先设置环境变量 DEEPSEEK_API_KEY，例如：\n"
        "  set DEEPSEEK_API_KEY=sk-xxxxxxx  (Windows CMD)\n"
        "  $env:DEEPSEEK_API_KEY='sk-xxx'   (PowerShell)"
    )

from tradingagents.ri_orchestrator import RIOrchestrator
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config.update({
    "llm_provider":       "deepseek",
    "backend_url":        "https://api.deepseek.com",
    "deep_think_llm":     "deepseek-chat",   # deepseek-reasoner 不支持 tool_calling
    "quick_think_llm":    "deepseek-chat",
    "max_debate_rounds":  1,
    "online_tools":       True,
})
config.setdefault("data_vendors", {})
config["data_vendors"]["fundamental_data"] = "akshare"

print("\n" + "═" * 70)
print("  159928.SZ 消费ETF · 长线定投可行性分析")
print("  模型：DeepSeek-Chat · 回测：月定投 3年 · 数据：yfinance + AKShare")
print("═" * 70)

orchestrator = RIOrchestrator(config=config)
report, report_path = orchestrator.run_analysis(
    ticker="159928.SZ",
    lookback_years=3,
    invest_period="monthly",
    invest_amount=1000.0,
    output_dir="results",
)

print("\n" + "═" * 70)
print(f"  分析完成！AI 信号：{orchestrator._last_decision}")
print(f"  报告路径：{report_path}")
print("═" * 70)

# 打印报告前1500字符
print("\n" + "─" * 70)
print(report[:1500])
print("─" * 70)
