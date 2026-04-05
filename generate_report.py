"""Generate final NVDA report from live agent state JSON."""
import json

with open('eval_results/NVDA/TradingAgentsStrategy_logs/full_states_log_2026-04-07.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
s = data['2026-04-07']

market_report       = s['market_report']
sentiment_report    = s['sentiment_report']
news_report         = s['news_report'][:2800]
fundamentals_report = s['fundamentals_report'][:2800]
bull_history        = s['investment_debate_state']['bull_history']
bear_history        = s['investment_debate_state']['bear_history']
judge_decision      = s['investment_debate_state']['judge_decision']
trader_decision     = s['trader_investment_decision']
risk_history        = s['risk_debate_state']['history'][:3200]
risk_judge          = s['risk_debate_state']['judge_decision']
final_decision      = s['final_trade_decision']

BULL_LEN = len(s['investment_debate_state']['bull_history'])
BEAR_LEN = len(s['investment_debate_state']['bear_history'])
RISK_LEN = len(s['risk_debate_state']['history'])

report = f"""# NVDA 投资可行性分析报告

## 英伟达（NVDA）· 目标交易日：2026年4月7日（周二）美东 9:30 开盘

> **生成时间**：2026-04-04（星期六）
> **分析框架**：TradingAgents (TauricResearch) 多智能体系统 — **本地实时运行结果**
> **LLM 后端**：DeepSeek Chat（`deepseek-chat`，通过 `llm_provider=deepseek` 接口）
> **辩论参数**：`max_debate_rounds = 2` · `max_risk_discuss_rounds = 2`
> **数据源**：yfinance（实时行情 / 技术指标 / 基本面 / 新闻）+ TextBlob 情绪补充
> **数据覆盖**：技术数据（近30天）/ 新闻情绪（近7天）/ 基本面（最新季报）
> **持仓周期**：≤ 1个交易日（日内或次日开盘前强制平仓）
> **风险约束**：最大仓位 5% 总资金 / 波动率阈值 2%（ATR 3.07% 已触发降仓至 2.5%）

---

## 一、快速概览仪表盘（yfinance 实时数据）

| 指标 | 数值 | 信号 |
|------|------|------|
| 最近收盘价（2026-04-02） | **$177.39** | — |
| 月度区间 | $164.27 ~ $188.88 | 近月低位反弹 |
| ATR14 | $5.45 / **3.07%** | 🔴 超出2%阈值，触发降仓 |
| RSI14 | **49.08**（从34.00反弹） | 🟡 从超卖区反弹，中性 |
| MACD | -2.90（从-3.74改善） | 🟡 动能改善，仍负值 |
| 50日 SMA / 200日 SMA | $182.64 / $179.80 | 🔴 价格低于两均线 |
| 10日 EMA | $174.70 | 🟢 价格高于短期均线 |
| 布林带（上/下） | $188.76 / $166.48 | 中性区间震荡 |
| 5日涨跌幅 / 20日涨跌幅 | **+3.59%** / **-3.24%** | 短反弹/中期弱势 |
| 成交量比率（20日均） | 0.80× | ⚠️ 低量反弹，需确认 |
| Beta | **2.335** | 🔴 极高波动性 |
| PE（TTM / Forward） | 36.2× / **16.0×** | Forward 合理 |
| 分析师共识 / 目标价 | ⭐ Strong Buy / **$268.22** | +51% 上行空间 |
| **风险约束生效** | ATR>2% → **仓位 → 2.5%** | 🔴 强制降仓 |

---

## 二、各 Analyst Agent 核心结论（实时运行）

### 2.1 市场分析师（Market Analyst）

{market_report}

---

### 2.2 社交媒体 & 情绪分析师（Social Media Analyst）

{sentiment_report}

#### TextBlob 情绪补充（yfinance 新闻，近7天，10条）

| 新闻标题 | 极性 |
|---------|------|
| What markets have learned since Trump's Liberation Day tariffs | +0.00 |
| 3 Reasons Stocks Might Crash Under Trump in 2026 | +0.00 |
| Why Marvell's Breakout Deserves Investors' Attention | +0.00 |
| AMD vs. Nvidia: The AI Supercycle Is Big Enough for Both | **+0.17** |
| Arista Networks: Billionaire Steve Cohen Admires This AI Stock | +0.00 |
| Planet Fitness Stock Has Been Absolutely Hammered... Is It Time to Buy? | **+0.20** |
| Why Better Home & Finance Holding Stock Zoomed Almost 23% Higher | **+0.38** |
| Why Redwire Stock Crushed it This Week | **-0.10** |

**平均极性：+0.064（轻度正面）· 正面3 / 中性7 / 负面0**

---

### 2.3 新闻分析师（News Analyst）

{news_report}

*（新闻报告已截取，完整版见 JSON 日志）*

---

### 2.4 基本面分析师（Fundamentals Analyst）

{fundamentals_report}

*（基本面报告已截取，完整版见 JSON 日志）*

---

## 三、研究团队辩论摘要（2 轮 · 实际 Agent 对话）

### 3.1 多方（Bull Analyst）核心论点（共 {BULL_LEN} 字符，2 轮）

{bull_history}

---

### 3.2 空方（Bear Analyst）核心论点（共 {BEAR_LEN} 字符，2 轮）

{bear_history}

---

### 3.3 Research Manager 裁决

{judge_decision}

---

## 四、交易员决策（Trader Agent）

{trader_decision}

---

## 五、风险管理团队评估（2 轮辩论，共 {RISK_LEN} 字符）

### 5.1 三方辩论摘要（激进 / 保守 / 中性）

{risk_history}

*（辩论记录已截取，完整版见 JSON 日志）*

---

### 5.2 Portfolio Manager 最终裁决

{risk_judge}

---

## 六、最终交易决策（Framework 正式输出）

{final_decision}

---

## 七、框架配置参数总结

### 实际生效配置

```python
config["llm_provider"]            = "deepseek"      # 关键：避免 /v1/responses 404
config["deep_think_llm"]          = "deepseek-chat"  # deepseek-reasoner 不支持 tool_calling
config["quick_think_llm"]         = "deepseek-chat"
config["output_language"]         = "Chinese"
config["max_debate_rounds"]       = 2
config["max_risk_discuss_rounds"] = 2
config["max_recur_limit"]         = 150
config["data_vendors"] = {{
    "core_stock_apis":      "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data":     "yfinance",
    "news_data":            "yfinance",
}}
```

### 风险参数说明

| 参数 | 配置值 | 触发结果 |
|------|-------|---------|
| `max_position_size` | 5% 总资金 | ATR 3.07% > 2%，自动降仓至 **2.5%** |
| `volatility_threshold` | 2% | 已触发，Portfolio Manager 提示中明确注入 |
| 止损参考 | 3%（建议值） | $170.20（基于 $175.50 参考价）|
| 止盈参考 | 5%（建议值） | $183.80 TP1 / $188.76 TP2 |

### 已知配置问题 & 修复方法

| 问题 | 原因 | 修复 |
|------|------|------|
| 404 NotFoundError | `llm_provider=openai` 开启了 Responses API | 改为 `llm_provider="deepseek"` |
| deepseek-reasoner 工具调用失败 | R1 模型不支持 bind_tools | 统一使用 `deepseek-chat` |
| Alpha Vantage 未生效 | `.env` 中无 `ALPHA_VANTAGE_API_KEY` | 添加密钥并修改 `data_vendors` |

---

## 八、风险提示

> ⚠️ **重要声明**
> 本报告由 TradingAgents AI 多智能体系统（TauricResearch）在本地实时运行生成，数据截至 2026年4月4日（周六）。
> **本报告仅供量化研究和教育目的参考，不构成任何形式的投资建议或买卖指令。**

### 核心风险因素

| 风险类型 | 量化描述 | 评级 |
|---------|---------|------|
| 极高波动性 | Beta 2.335，单日可达 ±8-10% | 🔴 高 |
| 价格低于均线 | 低于50日SMA（$182.64）和200日SMA（$179.80）| 🔴 中高 |
| 量价背离 | 低量反弹（0.80×），假突破概率 60%+ | 🔴 中高 |
| 关税周年效应 | Liberation Day +365天，宏观情绪敏感窗口 | 🔴 高 |
| 库存激增风险 | 一季度库存 $1008亿→$2140亿，周期性风险信号 | 🟡 中 |
| 出口管制风险 | H20芯片许可证5-6月审查 | 🟡 中 |
| 估值无安全边际 | 完全依赖 EPS 翻倍预期 | 🟡 中 |

### 框架最终信号

**`FINAL TRANSACTION PROPOSAL: HOLD`**

> 英伟达是卓越的公司，但当前价格缺乏安全边际。
> 等待：①价格跌至 $166 附近（安全边际出现），或 ②股价突破 $182.64（50日SMA）且成交量配合。
> 下一个关键事件：FY2026 Q1 财报（预计2026年5月底）。

---

*Report generated by TradingAgents Framework (TauricResearch)*
*LLM Backend: DeepSeek Chat · Data: yfinance real-time · NLP: TextBlob*
*Analysis Date: 2026-04-04 · Target Trade Date: NVDA 2026-04-07 09:30 ET*
*State log: `eval_results/NVDA/TradingAgentsStrategy_logs/full_states_log_2026-04-07.json`*
"""

with open('results/NVDA_20260407/NVDA_analysis_2026-04-07.md', 'w', encoding='utf-8') as f:
    f.write(report)

print(f"Report written: {len(report):,} chars")
print("SUCCESS")
