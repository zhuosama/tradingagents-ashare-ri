# TradingAgents — A-Share + DCA Fork

Multi-agent LLM framework for stock analysis and regular-investment research.

> 🚀 **Companion project**: For the production deployment that grew out of this
> research — a 5-agent self-iterating system running autonomously on Chinese
> A-shares since 2026-04-13 — see [**virtual-trader**](https://github.com/zhuosama/virtual-trader).
> This repo is the **research playground**; virtual-trader is the **production system**.

> 📂 **See it run**: Real outputs from this fork are committed under
> [`examples/`](examples/) — including a 7-report multi-agent analysis of
> 蓝光发展 (601298.SH) and a DCA backtest on 中证农业 ETF (159928.SZ).

This workspace is based on `TradingAgents` and currently includes:

- Multi-agent stock analysis with analyst, researcher, trader, risk, and portfolio-manager stages
- Interactive CLI for one-off stock analysis: `tradingagents`
- Interactive CLI for regular-investment / DCA analysis: `tradingagents-ri`
- Multi-provider LLM support: OpenAI, Anthropic, Google, xAI, OpenRouter, DeepSeek, MiMo, Ollama
- A-share support with `AKShare` fundamentals, A-share news routing, and A-share rule validation
- Output language selection, report persistence, and reusable Python API

## Disclaimer

This project is for research and educational use only.

- It is not financial, investment, legal, tax, or trading advice.
- Model outputs can be wrong, incomplete, stale, or internally inconsistent.
- Market data providers can fail, lag, rate-limit, or return partial data.
- You are responsible for validating all conclusions before making any real-money decision.

## What Is In This Repository

The working code lives in this directory:

```text
TradingAgents/
├── tradingagents/              # installable Python package
│   ├── agents/                 # analysts, researchers, trader, risk, managers
│   ├── data/                   # adapters, cache, routing, concurrency
│   ├── dataflows/              # tool-facing data access layer
│   ├── graph/                  # LangGraph orchestration
│   ├── llm_clients/            # provider abstraction and model catalog
│   └── default_config.py       # canonical runtime config
├── cli/                        # Typer + Questionary interactive CLIs
├── tests/                      # pytest suite
├── run_000792sz.py             # example A-share deep analysis script
├── run_601298sh.py             # example A-share deep analysis script
├── run_ri_159928.py            # example DCA script
├── run_ri_600900.py            # example DCA script
├── main.py                     # simple package entry example
└── validate_handoff.py         # focused validation for recent A-share fixes
```

## Key Features

### 1. Multi-agent workflow

`TradingAgentsGraph` runs a staged workflow:

1. Market analyst
2. Social / sentiment analyst
3. News analyst
4. Fundamentals analyst
5. Bull vs bear research debate
6. Trader proposal
7. Aggressive / neutral / conservative risk debate
8. Portfolio-manager final decision

Outputs are persisted as markdown reports and state logs.

### 2. Regular-investment workflow

`tradingagents-ri` provides a separate CLI for DCA / regular-investment analysis and stress scenarios.

### 3. A-share support

This workspace includes explicit A-share handling that is not covered well by the original generic README:

- Preferred ticker formats: `300750.SZ`, `600519.SH`, `159928.SZ`
- A-share fundamentals can use `AKShare`
- A-share news uses a dedicated path and does not fall back to global-news prompts
- Unsafe fabricated A-share news fallback was replaced with a safe structured fallback
- Trader output is validated against A-share constraints such as `T+1`
- Exchange-specific ticker normalization is handled internally for vendors such as `yfinance`

### 4. Multi-provider LLM support

The current codebase supports these providers:

| Provider | Env var | Default / typical base URL |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| Anthropic | `ANTHROPIC_API_KEY` | provider SDK default |
| Google | `GOOGLE_API_KEY` | `https://generativelanguage.googleapis.com/v1` |
| xAI | `XAI_API_KEY` | `https://api.x.ai/v1` |
| OpenRouter | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` |
| DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| MiMo | `MIMO_API_KEY` | `https://token-plan-cn.xiaomimimo.com/v1` |
| Ollama | none | `http://localhost:11434/v1` |

The shared model catalog currently includes `mimo-v2-pro` under provider `mimo`.

## Installation

### Requirements

- Python `>=3.10`
- Recommended: Python `3.13`
- Network access for remote LLM and market-data providers

### Install

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
python -m venv .venv
```

Activate the environment.

PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Bash:

```bash
source .venv/bin/activate
```

Install dependencies and the package:

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## Environment Variables

Create `.env` in the repository root. At minimum, configure the provider you actually use.

```env
OPENAI_API_KEY=
GOOGLE_API_KEY=
ANTHROPIC_API_KEY=
XAI_API_KEY=
OPENROUTER_API_KEY=
DEEPSEEK_API_KEY=
MIMO_API_KEY=
ALPHA_VANTAGE_API_KEY=
TRADINGAGENTS_RESULTS_DIR=./results
LLM_API_TIMEOUT=120
```

Notes:

- `TRADINGAGENTS_RESULTS_DIR` overrides the default output directory.
- `ALPHA_VANTAGE_API_KEY` is only needed when you choose Alpha Vantage.
- `Ollama` does not require an API key.

Security:

- keep real secrets only in local `.env` or your shell environment
- do not commit populated `.env` files
- `.env.example` is a template only and must remain secret-free

## Quick Start

### Interactive stock analysis CLI

```bash
tradingagents
```

Alternative:

```bash
python -m cli.main
```

The CLI lets you choose:

- ticker
- analysis date
- analysts
- research depth
- LLM provider
- quick-thinking model
- deep-thinking model
- output language

### Interactive regular-investment CLI

```bash
tradingagents-ri
```

Alternative:

```bash
python -m cli.regular_investment_cli
```

## Python Usage

### Minimal example

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["output_language"] = "Chinese"

ta = TradingAgentsGraph(debug=False, config=config)
state, decision = ta.propagate("NVDA", "2026-01-15")

print(decision)
```

### A-share example

For A-shares, prefer `AKShare` for fundamentals:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["output_language"] = "Chinese"
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "akshare",
    "news_data": "yfinance",
}

ta = TradingAgentsGraph(debug=False, config=config)
state, decision = ta.propagate("300750.SZ", "2026-04-06")

print(decision)
```

### MiMo example

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "mimo"
config["deep_think_llm"] = "mimo-v2-pro"
config["quick_think_llm"] = "mimo-v2-pro"
config["backend_url"] = "https://token-plan-cn.xiaomimimo.com/v1"
config["output_language"] = "Chinese"
config["max_debate_rounds"] = 5
config["max_risk_discuss_rounds"] = 3
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "akshare",
    "news_data": "yfinance",
}

ta = TradingAgentsGraph(debug=False, config=config)
state, decision = ta.propagate("300750.SZ", "2026-04-06")
print(decision)
```

## Recommended Config Patterns

### OpenAI

```python
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-5.4"
config["quick_think_llm"] = "gpt-5.4-mini"
config["backend_url"] = "https://api.openai.com/v1"
```

### DeepSeek

```python
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-reasoner"
config["quick_think_llm"] = "deepseek-chat"
config["backend_url"] = "https://api.deepseek.com/v1"
```

If you encounter tool-calling instability on a given setup, fall back to:

```python
config["deep_think_llm"] = "deepseek-chat"
config["quick_think_llm"] = "deepseek-chat"
```

### MiMo

```python
config["llm_provider"] = "mimo"
config["deep_think_llm"] = "mimo-v2-pro"
config["quick_think_llm"] = "mimo-v2-pro"
config["backend_url"] = "https://token-plan-cn.xiaomimimo.com/v1"
```

## Data Routing

The framework separates provider routing by category:

```python
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}
```

You can also override individual tools through `tool_vendors`.

Current practical guidance:

- US / global equities: `yfinance` is the simplest default
- A-share fundamentals: prefer `akshare`
- Alpha Vantage: use only if you explicitly want that provider and have a key

## Output Structure

By default, analysis output is written under:

```text
results/
```

Typical stock-analysis output:

```text
results/<TICKER>/<YYYY-MM-DD>/
├── message_tool.log
└── reports/
    ├── market_report.md
    ├── sentiment_report.md
    ├── news_report.md
    ├── fundamentals_report.md
    ├── investment_plan.md
    ├── trader_investment_plan.md
    └── final_trade_decision.md
```

Typical regular-investment output:

```text
results/RI_<TICKER>_<YYYYMMDD>/
└── RI_<TICKER>_analysis_<YYYY-MM-DD>.md
```

State logs may also be written under:

```text
eval_results/<TICKER>/TradingAgentsStrategy_logs/
```

## Example Scripts In This Workspace

These scripts reflect current local usage patterns:

- `run_000792sz.py`
- `run_601298sh.py`
- `run_ri_159928.py`
- `run_ri_600900.py`
- `validate_handoff.py`

They are useful as concrete references for:

- Chinese output
- A-share fundamentals via `AKShare`
- deeper debate depth
- custom report generation

## Running Tests

Run the main test suite:

```bash
pytest tests/
```

Useful focused tests:

```bash
pytest tests/test_model_validation.py
pytest tests/test_ashare_rules.py
pytest tests/test_google_api_key.py
```

Local validation scripts:

```bash
python validate_handoff.py
python test_deepseek.py
python test_deepseek_reasoner.py
python test_ri_fundamental.py
```

## A-share Notes

Important A-share behavior in the current code:

- Use explicit symbols such as `300750.SZ` and `600519.SH`
- Internally, vendor adapters may convert Shanghai symbols to `.SS` for `yfinance`
- News handling for A-shares is isolated from global-news prompts
- Trader output may be annotated or constrained by A-share rule validation
- Reports may mention `T+1`, price-limit rules, suspension, delisting risk, and `ST` conditions

This means A-share analysis is intentionally more conservative than generic US-equity flows.

## Troubleshooting

### Missing API key

The CLI validates provider-specific API keys before starting. If you choose `mimo`, you must have:

```env
MIMO_API_KEY=...
```

### Empty or partial data

Common causes:

- provider rate limits
- unavailable vendor endpoint
- market holiday / non-trading date
- unsupported symbol format

For A-shares:

- prefer `.SZ` / `.SH` symbols
- prefer `akshare` for fundamentals

### Slow runs

Deep research settings can be slow because the system performs:

- multiple analyst passes
- researcher debate rounds
- risk debate rounds
- repeated tool calls

Reduce runtime by lowering:

- `max_debate_rounds`
- `max_risk_discuss_rounds`
- selected analysts

## License

This repository includes an Apache 2.0 license. See [LICENSE](LICENSE).

In practical terms:

- you may use, modify, and distribute the code under Apache 2.0 terms
- you must preserve required notices and license text
- the software is provided on an `AS IS` basis, without warranties

## Copyright And Attribution

- Original framework: Tauric Research / TradingAgents
- This workspace contains additional local modifications for provider support, A-share handling, and regular-investment workflows

If you redistribute modified versions, keep:

- the Apache 2.0 license text
- any required attribution and notice files
- a clear statement of your own modifications

Third-party provider names, exchange names, and product names remain the property of their respective owners.

## Citation

If this project helps your work, cite the original TradingAgents paper:

```bibtex
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
  title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
  author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
  year={2025},
  eprint={2412.20138},
  archivePrefix={arXiv},
  primaryClass={q-fin.TR},
  url={https://arxiv.org/abs/2412.20138}
}
```
