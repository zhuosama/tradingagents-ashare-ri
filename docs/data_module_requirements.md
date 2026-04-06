

\## 身份锚定

你现在是一位拥有5年以上量化系统开发经验、精通TradingAgents项目架构、熟悉多数据源适配与缓存机制、追求CI/CD友好与高健壮性的\*\*资深量化后端架构师\*\*。



\## 核心约束（必须严格遵守）

1\. \*\*原生框架无损\*\*：禁止修改TradingAgents原生的`cli/main.py`、`trading\_agents/orchestrator.py`、`llm/`等核心策略/CLI文件，仅重构\*\*数据获取层（Data Layer）\*\*，确保原生短线分支和新增定投分支100%兼容；

2\. \*\*严格分层解耦\*\*：数据层（Data Adapter）、缓存层（Cache Layer）、校验层（Validation Layer）必须完全独立，通过标准化接口交互，绝不能让底层数据源的脏数据污染上层策略逻辑；

3\. \*\*面向对象设计\*\*：所有数据源适配器必须继承统一的`BaseDataAdapter`抽象基类，通过工厂模式（`DataAdapterFactory`）根据标的类型自动路由，预留LOF等复杂标的的扩展接口。



\---



\## 一、数据源工厂模式与分类路由重构

\### 1.1 全局配置与代理注入

\- 新增`config/data\_config.py`文件，统一管理所有数据源配置、代理配置、缓存配置；

\- 必须支持读取环境变量`HTTP\_PROXY`和`HTTPS\_PROXY`，并在所有HTTP请求库（requests/httpx/yfinance/AKShare内部请求）中自动注入代理；

\- 代理配置支持全局开关（`USE\_PROXY`），默认开启，可通过`.env`文件关闭。



\### 1.2 A股标的数据源路由（工厂模式）

\- 首选AKShare（全免费覆盖广），备选Tushare免费版（预留token注入接口，通过`.env`文件读取`TUSHARE\_TOKEN`）；

\- 细分接口路由（严格按标的类型匹配）：

&#x20; | 标的类型 | 首选AKShare接口 | 备选Tushare接口 | 标准输出字段 |

&#x20; | :--- | :--- | :--- | :--- |

&#x20; | 个股 | `ak.stock\_zh\_a\_hist` | `ts.pro\_bar` | `symbol, date, open, high, low, close, volume, amount` |

&#x20; | ETF | `ak.fund\_etf\_hist\_em`（行情）+ `ak.fund\_etf\_basic\_info\_em`（基础信息）+ `ak.fund\_etf\_holdings\_em`（持仓） | `ts.fund\_daily`（行情）+ `ts.fund\_basic`（基础信息） | `symbol, date, open, high, low, close, volume, amount, nav, tracking\_index, inception\_date, management, aum` |

&#x20; | 指数 | `ak.index\_zh\_a\_hist` | `ts.index\_daily` | `symbol, date, open, high, low, close, volume, amount` |

\- 自动降级逻辑：AKShare调用失败（网络/逻辑异常）时，自动切换到Tushare，Tushare也失败则抛出结构化错误。



\### 1.3 非A股标的数据源路由

\- \*\*美股\*\*：首选yfinance，备选Alpha Vantage（免费API，通过`.env`读取`ALPHA\_VANTAGE\_API\_KEY`）；

\- \*\*港股\*\*：首选AKShare港股接口（`ak.stock\_hk\_hist`/`ak.fund\_hk\_etf\_hist\_em`），备选yfinance（使用.HK后缀）；

\- \*\*欧股\*\*：暂不支持，抛出明确提示。



\---



\## 二、最小可验证模块（CI/CD友好）

\### 2.1 验证范围与通过标准

\- 采用\*\*核心模块集成测试\*\*，无需单元测试，仅验证「数据适配器层」输出的标准化DataFrame；

\- \*\*通过标准\*\*：核心字段（`symbol, date, close`）非空率=100%，非核心字段允许为空；测试用例获取最近5个交易日数据，成功返回且不报错即算通过。



\### 2.2 测试脚本交付

\- \*\*`test\_fast.py`（开发环境快速验证）\*\*：仅测2个标的，10秒内完成：

&#x20; 1. 沪深300 ETF（510300.SH，A股ETF）

&#x20; 2. 苹果股票（AAPL，美股个股）

\- \*\*`test\_full.py`（生产环境全量验证）\*\*：覆盖各市场各类型标的各1个：

&#x20; 1. 510300.SH（A股ETF）

&#x20; 2. 000001.SZ（A股个股）

&#x20; 3. 000300.SH（A股指数）

&#x20; 4. AAPL（美股个股）

&#x20; 5. 00700.HK（港股个股）



\---



\## 三、标的代码预校验与自动修正（防呆设计）

\### 3.1 预校验与自动补全规则

必须在`utils/ticker\_validator.py`中实现，优先尝试自动修正，提升Agent智能化体验：

| 输入示例 | 正则识别逻辑 | 自动修正结果 |

| :--- | :--- | :--- |

| 510300 | 纯数字且以51/56开头 → 沪市ETF | 510300.SH |

| 159928 | 纯数字且以15开头 → 深市ETF | 159928.SZ |

| 000001 | 纯数字且以00/30开头 → 深市个股 | 000001.SZ |

| 00700 | 纯数字且以00开头 → 港股 | 00700.HK |

| AAPL | 纯字母/字母+数字 → 美股 | AAPL |

| 510300.SH | 已带后缀 → 直接通过 | 510300.SH |



\### 3.2 自定义异常

\- 新增`exceptions/data\_exceptions.py`，定义`InvalidTickerException`、`DataFetchException`、`DataValidationException`等结构化异常；

\- 自动修正后依然调用失败时，抛出带有清晰建议的异常（如：`InvalidTickerException("无法识别标的代码，请检查格式，建议格式：510300.SH/AAPL/00700.HK")`）。



\---



\## 四、异常处理与降级逻辑（高健壮性）

\### 4.1 双重降级触发条件

同时满足以下任一条件即触发降级：

1\. \*\*网络异常\*\*：HTTP 4xx/5xx、Timeout、ConnectionError；

2\. \*\*数据逻辑异常\*\*：返回空表、核心字段缺失率>0%。



\### 4.2 降级层级与字段统一映射

\- \*\*降级层级\*\*：最多1次自动降级（Primary → Fallback → Raise Error），层级过多会导致Agent响应超时；

\- \*\*字段统一映射\*\*：强制要求所有数据源适配器在内部完成清洗，向上层统一输出\*\*标准字段名\*\*（如AKShare的“代码”→“symbol”，“日期”→“date”，“收盘价”→“close”），绝不能让底层脏字典污染策略逻辑。



\---



\## 五、本地缓存机制（核心需求，防封禁+极速响应）

\### 5.1 缓存方案与TTL设置

\- 使用`diskcache`库（轻量级、持久化、支持并发锁）+ SQLite存储，无需额外安装Redis；

\- TTL设置：

&#x20; | 数据类型 | TTL | 说明 |

&#x20; | :--- | :--- | :--- |

&#x20; | 基础信息/持仓 | 7天 | 低频更新，避免频繁调用 |

&#x20; | 日线行情 | 缓存至下一个交易日9:30前 | 中频更新，交易日9:30后自动失效 |

\- 缓存键设计：`{adapter\_type}:{symbol}:{data\_type}:{start\_date}:{end\_date}`（如`akshare\_etf:159928.SZ:quote:20230406:20260405`）。



\### 5.2 跨平台路径处理

\- 强制使用`pathlib.Path`处理所有缓存文件和日志路径，缓存目录默认放在项目根目录的`.cache/tradingagents\_data`下；

\- 所有文件读写强制指定`encoding='utf-8'`，避免Windows/macOS/Linux编码差异。



\---



\## 六、输出兼容性与批量支持

\### 6.1 标准数据结构

\- 使用`pydantic`定义`StandardQuoteData`、`StandardFundamentalData`等标准数据模型，使用`Optional\[float]`容忍跨市场数据差异（如美股无龙虎榜数据，该字段即为`None`）；

\- 上层策略/Agent只需处理标准模型，无需关心底层数据源。



\### 6.2 批量并发封装

\- 底层函数设计为支持单标的，但在`utils/batch\_fetcher.py`中提供基于`ThreadPoolExecutor`的批量并发封装器，支持同时获取多个标的的数据；

\- 并发数默认限制为5，可通过配置调整，避免触发API封禁。



\---



\## 七、环境与依赖约束

\### 7.1 Python版本与依赖锁定

\- 明确锁定Python 3.10 \~ 3.12；

\- 在`requirements.txt`中严格锁定次版本号，防止上游API变更：

&#x20; ```txt

&#x20; akshare\~=1.12.0

&#x20; yfinance\~=0.2.40

&#x20; tushare\~=1.2.95

&#x20; diskcache\~=5.6.3

&#x20; pydantic\~=2.7.0

&#x20; pandas\~=2.2.0

&#x20; python-dotenv\~=1.0.0

&#x20; ```



\### 7.2 跨平台兼容

\- 所有路径处理使用`pathlib.Path`，绝不使用硬编码的`/`或`\\`；

\- 所有文件读写强制指定`encoding='utf-8'`。



\---



\## 交付物清单（按优先级排序）

1\. \*\*完整的重构后代码目录结构\*\*（清晰标注新增/修改的文件）；

2\. \*\*所有新增/修改的文件的完整代码\*\*（可直接复制替换，关键处标注【重构说明】）；

3\. \*\*`test\_fast.py`和`test\_full.py`测试脚本\*\*；

4\. \*\*更新后的`.env.example`文件\*\*（包含所有新增的环境变量配置）；

5\. \*\*更新后的`requirements.txt`文件\*\*；

6\. \*\*一份重构说明文档\*\*，列出所有变更点、根因、解决思路；

7\. \*\*修正后的159928.SZ定投可行性分析报告\*\*（无N/A、无错误提示）。



\---



\## 验证步骤（Claude Code必须先自行验证再交付）

1\. 先运行`test\_fast.py`，确保快速验证通过；

2\. 再运行`test\_full.py`，确保全量验证通过；

3\. 最后分别启动原生短线分支（`tradingagents`）和新增定投分支（`tradingagents-ri`），验证159928.SZ和AAPL的分析流程均正常，无数据缺失报错。

# Role
You are a senior backend engineer and AI systems architect working inside the `TradingAgents` repository. Your task is to adapt the existing system for the Chinese A-share market based on the findings in `TradingAgents/docs/optimiz.md`, while preserving full compatibility for US/global markets.

# Primary Architecture Constraint
Do NOT create a separate standalone A-share workflow, duplicate graph, or independent end-to-end module tree for the Chinese market.

You must keep the existing long-term / short-term framework, graph orchestration, agent pipeline, and decision chain intact, and extend them with market-aware routing.

The required architecture is:
1. Reuse the current long-term and short-term analysis framework.
2. Reuse the current ticker/market resolution mechanism already present in the repository.
3. Extend the existing pipeline so that different markets are handled through conditional routing, validator hooks, prompt injection, or strategy-style dispatch.
4. A-share instruments must use A-share-specific data routing, trading rule validation, and prompt constraints.
5. US/global instruments must continue using the current implementations unless a change is explicitly required for shared infrastructure.
6. The final architecture must be “one framework, multiple market behaviors”, not “two independent systems”.

If you find yourself designing a separate A-share graph, isolated A-share agent pipeline, or a parallel `china_*` / `ashare_*` end-to-end system, stop and refactor back to market-aware extension within the existing pipeline.

# Required Context Inspection
Before planning any code changes, inspect and reason from these files first:

- `TradingAgents/docs/optimiz.md`
- `TradingAgents/tradingagents/agents/analysts/news_analyst.py`
- `TradingAgents/tradingagents/agents/analysts/market_analyst.py`
- `TradingAgents/tradingagents/agents/analysts/fundamentals_analyst.py`
- `TradingAgents/tradingagents/agents/trader/trader.py`
- `TradingAgents/tradingagents/agents/utils/agent_utils.py`
- `TradingAgents/tradingagents/agents/utils/news_data_tools.py`
- `TradingAgents/tradingagents/dataflows/interface.py`
- `TradingAgents/tradingagents/data/routing/ticker_resolver.py`
- `TradingAgents/tradingagents/default_config.py`

You must align the implementation plan with the real repository structure. Do not invent duplicate abstractions if the project already has a routing or config mechanism that should be reused.

# Design Principles
1. Follow the Open-Closed Principle.
2. Prefer minimal, composable extensions over invasive rewrites.
3. Reuse existing market classification helpers such as `TickerResolver` or `ResolvedTicker.market_type` where available.
4. Avoid hardcoding raw `.SH` / `.SZ` suffix checks everywhere if a repository-native market classification mechanism already exists.
5. Isolate A-share-specific behavior behind small reusable helpers, validators, or routers.
6. Do not break or weaken current US/global behavior.
7. If prompt localization is changed, integrate with the existing `output_language` / `get_language_instruction()` mechanism when possible.

# Goal
Upgrade the existing TradingAgents system so that the same long-term / short-term analysis pipeline can first classify the market of the instrument, then invoke the correct market-specific:
- news routing
- prompt constraints
- trading-rule validation
while keeping the original framework structure intact.

# Key Problems To Solve
According to `optimiz.md`, the current system has three major adaptation gaps for A-shares:

1. News misrouting:
   A-share symbols may receive irrelevant US/global news, causing hallucinated sentiment and macro conclusions.

2. Trading-rule mismatch:
   Technical and trader outputs may recommend plans that violate A-share rules such as T+1 and daily price limits.

3. Prompt and domain mismatch:
   Reports for A-shares may contain English or mixed-language output, and some prompts still apply US-centric valuation/execution assumptions to Chinese SOEs and policy-driven sectors.

# Implementation Tasks

## Task 1: A-share News Routing Fix (P0)
Problem:
The news analysis path currently risks exposing A-share instruments to irrelevant US/global news.

Required implementation direction:
- Keep the existing news analysis pipeline and existing news agent.
- Do NOT create a separate A-share-only news agent graph.
- Instead, make the existing news flow market-aware.

Required behavior:
1. Detect whether the current instrument is A-share-related by using the repository’s existing market classification mechanism.
2. If the instrument is A-share-related, route news retrieval through an A-share-safe path:
   - preferred: domestic stock-specific news
   - fallback 1: Chinese macro/policy news
   - fallback 2: Chinese industry / sector news
3. For A-shares, NEVER fallback to US/global macro news.
4. For US/global tickers, preserve current behavior.

Implementation guidance:
- Check whether the best implementation point is:
  - conditional tool exposure in `news_analyst.py`
  - a market-aware wrapper in `news_data_tools.py`
  - or a market-aware router in `dataflows/interface.py`
- Prefer the narrowest and most maintainable implementation that fixes A-share news contamination without disturbing non-A-share behavior.
- If no exact A-share stock-news API already exists in the codebase, create a clean market-aware abstraction and explicit fallback ordering. Do not fake unavailable APIs.

Acceptance criteria:
- A-share instruments must not receive US/global macro news fallback.
- US/global instruments must keep their current behavior.
- The existing news-analysis pipeline remains intact, only extended with market-aware routing.

## Task 2: A-share Trading Rule Validator (P1)
Problem:
The trader and technical outputs may produce plans that are infeasible in A-shares.

Required implementation direction:
- Keep the current trader and technical analysis flow.
- Add market-aware validation into the existing pipeline.
- Do NOT create a separate A-share trader module unless a small reusable validator/helper is needed.

Required behavior:
1. Create a deterministic validator utility, for example `MarketRuleValidator`, or a repository-consistent equivalent.
2. Inject this validator into the existing trader post-processing or decision output stage.
3. The validator must be market-aware:
   - ignore or bypass US/global instruments
   - enforce constraints for A-share instruments
4. At minimum, validate:
   - T+1 awareness: do not allow same-day buy-and-sell logic to be presented as directly executable
   - daily price limit bounds based on previous close
   - board-specific limits when the codebase can infer them safely
5. If invalid trade prices or impossible same-day exit instructions appear, rewrite, reject, or flag the plan before final output.

Minimum pricing rules:
- Main board: +/-10%
- STAR Market / ChiNext: +/-20% if board inference is reliable
- If board inference is not reliable, implement a conservative fallback and document it in code comments

Acceptance criteria:
- US/global tickers remain unaffected.
- A-share plans cannot contain obviously invalid execution prices.
- A-share outputs acknowledge T+1 where relevant.
- The original trader pipeline remains the same, only extended with validation hooks.

## Task 3: Prompt Localization and A-share Domain Injection (P1)
Problem:
A-share reports still contain English or mixed-language phrasing, and some prompts apply US market assumptions to Chinese stocks.

Required implementation direction:
- Keep the existing analyst/trader agents.
- Add market-aware prompt extensions inside the current prompt-building logic.
- Do NOT create a separate set of duplicated agents just for A-shares.

Required behavior:
1. Update the existing prompts for at least:
   - News Analyst
   - Fundamentals Analyst
   - Market / Technical Analyst
   - Trader
2. For A-share tasks, dynamically append a strict language rule:
   `You must output the final report entirely in Simplified Chinese (zh-CN), including all professional financial terms.`
3. Reuse the repository’s existing output language config path where possible.
4. Inject A-share-specific domain instructions for the existing agents:

Fundamentals Analyst:
- consider Chinese SOE valuation logic
- consider policy support and high-dividend characteristics
- do not mechanically penalize heavy-asset SOEs for low current ratio when operating cash flow and financing structure justify it
- consider earnings-preannouncement and policy-cycle effects common in A-shares

News Analyst:
- focus on Chinese macro policy, CSRC/NDRC/PBOC signals, industry subsidies, domestic sector rotation
- if stock-specific news is sparse, reason from domestic industry and policy context only

Market / Technical Analyst:
- account for T+1 and price-limit structure
- do not use naive same-day ATR stop-loss logic for newly opened A-share positions
- recognize that limit-up / limit-down and one-word boards can distort standard indicators

Trader:
- produce execution plans that are feasible in A-shares
- reject same-day round-trip logic
- prefer phased entries, next-day execution framing, and realistic A-share constraints when relevant

Acceptance criteria:
- A-share final reports are fully in Simplified Chinese.
- US/global reports retain their current behavior unless changed by shared global config.
- The existing agent set remains in place, only extended with market-aware prompt rules.

# Testing Requirements
Add focused automated tests for the market-aware extensions.

At minimum include:
1. News routing tests
   - A-share instrument uses domestic-only routing
   - US/global instrument keeps existing routing behavior

2. Market rule validator tests
   - US/global ticker bypasses validation
   - A-share prices outside +/-10% are rejected, normalized, or flagged
   - T+1-invalid same-day exit logic is flagged

3. Prompt behavior tests if the repository has an appropriate existing test style
   - A-share prompt gets Chinese output rule and domain instructions
   - US/global prompt remains unchanged unless intended

Prefer small deterministic unit tests over heavy integration tests.

# Execution Workflow
1. First inspect the required files.
2. Then provide a concise architecture summary of the current system.
3. Explicitly explain how you will preserve the original long-term / short-term framework and extend it through market-aware dispatch instead of creating a separate A-share subsystem.
4. List the exact files you plan to modify and why.
5. Wait for my confirmation before making any edits.
6. After confirmation, implement the changes in small, reviewable steps.
7. Add or update tests.
8. Run relevant tests and summarize:
   - what changed
   - why US/global compatibility is preserved
   - any remaining limitations

# Mandatory Pre-Edit Output
Before editing any code, you must provide:
1. A short summary of the current architecture
2. A short explanation of the market-aware extension pattern you will use
3. The exact files you plan to modify
4. A short explanation of why this approach preserves the original long-term / short-term framework and avoids splitting the system into separate market-specific pipelines

Do not edit any file until I confirm.



