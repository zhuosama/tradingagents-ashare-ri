# Examples — Real Multi-Agent Analysis Outputs

These are real outputs from running this fork on Chinese A-share market.
They are committed verbatim (only path/account scrubbing) so readers can see
what the multi-agent pipeline actually produces, end-to-end.

| Example | Type | Stock | Highlight |
|---|---|---|---|
| [`a-share-analysis-601298.SH/`](a-share-analysis-601298.SH/) | Deep stock analysis | 蓝光发展 (601298.SH) | 7 reports across 5 agents + 3-perspective risk debate. The system correctly flagged the stock as "avoid/sell" in light of its non-trading / potential delisting status — a real test of the framework's ability to refuse to invent value where data is absent. |
| [`dca-analysis-RI-159928/`](dca-analysis-RI-159928/) | Regular-investment (DCA) | 159928.SZ — 中证农业 ETF | Output of the `tradingagents-ri` CLI (added in this fork). Monthly DCA, ¥1000/期, 3-year backtest. Demonstrates the regular-investment workflow on top of the original framework. |

## Why include these in the repo

The original TradingAgents framework can be run by anyone. What this fork
adds is **A-share-specific routing, MiMo provider integration, and a
regular-investment (DCA) workflow**. These two examples are concrete
evidence that those additions actually work end-to-end on real Chinese
market tickers, not just unit tests.

For the production deployment that grew out of this research — a 5-agent
self-iterating system running autonomously since 2026-04-13 — see
[virtual-trader](https://github.com/zhuosama/virtual-trader).

## What was scrubbed

- No API keys / tokens / passwords were ever in these files (verified via grep).
- Stock symbols are public market identifiers — kept as-is.
- Analysis dates are kept (2026-04-05) so reproducibility is honest.
- The 12+ other tickers we ran (`results/000100.SZ`, `RI_600900_*`, etc.) are
  excluded via `.gitignore` to keep the repo focused; these two are the
  representative samples.

## Re-running

```bash
# A-share deep analysis (replicate 601298.SH example)
python run_601298sh.py

# DCA / regular-investment (replicate 159928 example)
python run_ri_159928.py

# Generic deep-analysis CLI
tradingagents

# Regular-investment CLI
tradingagents-ri
```

Output directory is configurable via `TRADINGAGENTS_RESULTS_DIR`
environment variable (default: `./results`).
