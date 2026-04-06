# TradingAgents 项目状态快照

> 生成时间：2026-04-05  
> 用途：数据模块重构前的开发进度存档

---

## 一、已完成的功能模块

### 1. A 股数据修复（601298.SH 青岛港）
- **问题根因**：yfinance 不识别 `.SH` 后缀（上交所），需转换为 `.SS`
- **修复文件**：
  - `tradingagents/dataflows/stockstats_utils.py` — 新增 `normalize_ticker_yf()`，`.SH` → `.SS`
  - `tradingagents/dataflows/y_finance.py` — 所有 6 处 `yf.Ticker()` 调用均应用 normalize
  - `tradingagents/dataflows/akshare_fundamentals.py` — 新增 AKShare 财务报表适配器
  - `tradingagents/dataflows/interface.py` — 注册 `akshare` 为 fundamental_data 供应商
  - `tradingagents/default_config.py` — 注释更新：`# Options: alpha_vantage, yfinance, akshare`
- **验证结果**：601298.SH 分析报告已生成，AI 信号 SELL，路径 `results/601298SH_20260407/`

### 2. feature/regular-investment 分支 — 长线定投模块

#### 新增文件（禁止与原框架文件混淆）
| 文件 | 说明 |
|------|------|
| `tradingagents/dataflows/ri_fundamental.py` | ETF/指数基础数据适配器（AKShare + yfinance 备用） |
| `tradingagents/ri_orchestrator.py` | DCA 回测引擎 + AI 多智能体编排器 |
| `cli/regular_investment_cli.py` | 7步交互式 CLI，入口 `tradingagents-ri` |
| `test_ri_fundamental.py` | 数据适配器验证脚本（T01~T08） |
| `run_ri_159928.py` | 159928.SZ 完整分析运行脚本 |

#### pyproject.toml 唯一变更
```toml
[project.scripts]
tradingagents = "cli.main:app"
tradingagents-ri = "cli.regular_investment_cli:app"   # 仅新增此行
```

#### 已确认的开发规范
- **禁止修改**：`cli/main.py`、`cli/steps.py`、`tradingagents/graph/trading_graph.py`、`tradingagents/dataflows/interface.py`（原生接口层）
- 定投模块所有新代码必须位于独立文件中，不得污染原框架
- AKShare API 调用必须通过 `_ak_safe()` 包装，任何 AttributeError / 网络异常均优雅降级

#### 验证结果（2026-04-05）
- `test_ri_fundamental.py`：**8/8 PASS**
- 159928.SZ 完整分析：AI 信号 **SELL**，报告 `results/RI_159928_20260405/`

#### DCA 回测关键数据（159928.SZ，月定投¥1000，近3年）
| 指标 | 数值 |
|------|------|
| 累计收益率 | -10.54% |
| CAGR | -3.64% |
| 最大回撤 | -2.34% |
| 定投均价 | ¥0.835 |
| 期末价格 | ¥0.747 |
| 定投胜率 | 8.3% |
| 定投 vs 一次性 | **+18.45%**（一次性-28.99%） |

---

## 二、已知技术约束

| 约束 | 说明 |
|------|------|
| yfinance A 股 ticker | 上交所必须用 `.SS`，深交所 `.SZ` 正常 |
| DeepSeek tool_calling | `deepseek-reasoner` 不支持 tool_calling，统一使用 `deepseek-chat` |
| AKShare 版本 | 当前 1.18.51，多个 ETF 相关函数缺失（`fund_etf_portfolio_hold_em` 等），均已通过 `_ak_safe()` 优雅处理 |
| AKShare 网络 | `fund_etf_hist_em` 等接口有概率 Connection abort，已配置 yfinance 备用 |
| LLM 配置 | `llm_provider="deepseek"`，`backend_url="https://api.deepseek.com"` |

---

## 三、下一步：数据模块重构

### 重构目标（待细化）
- 统一数据访问层，消除 `y_finance.py` / `akshare_fundamentals.py` / `ri_fundamental.py` 之间的重复逻辑
- 标准化 ticker 规范化流程（目前 `normalize_ticker_yf` 散落在多处）
- 改善 AKShare 连接稳定性（重试机制、超时配置）

### 重构前的注意事项
1. `ri_fundamental.py` 是定投分支专属，重构时保持其独立性
2. `normalize_ticker_yf` 需要提取为公共工具函数
3. `_ak_safe()` 模式可推广为通用数据源容错装饰器
4. AKShare 版本升级前，所有函数调用需保留 hasattr 检查或 try/except

---

## 四、当前 Git 状态

- 活跃分支：`feature/regular-investment`
- 原框架分支：`main`（未动）
- 本次会话未执行 `git commit`（代码均在工作区）

---

*本文件由会话快照生成，仅供数据模块重构参考，不作为正式文档维护。*
