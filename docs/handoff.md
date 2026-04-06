Project Handoff
1. 当前目标
• 当前正在做什么：修正 A 股支持的两个关键缺陷
1. news_data_tools.py 中的 A 股新闻 fallback 包含硬编码的虚构新闻标题、摘要、事件
2. MarketRuleValidator 的价格校验未生效（prev_close 未传入，validate_price(0, …) 使用占位价格）
• 这一步的最终目标：
1. 将 A 股新闻 fallback 改为非伪造的安全降级输出，明确声明“未获取到实时新闻”，提供结构化分析提示
2. 在现有 pipeline 内获取真实 prev_close，使涨跌停校验真正生效
• 当前卡点：如何在不修改全局数据路由（route_to_vendor、default_config.py、core_stock_tools.py）的前提下，以最小侵入方式获取 prev_close。
2. 项目背景
• 项目名称：TradingAgents（TauricResearch）
• 技术栈：Python、LangChain/LangGraph、akshare（A 股）、yfinance（美股）、pandas、pydantic、backtrader
• 运行环境：Windows 11 Home 10.0.26200
• 操作系统：Windows
• 包管理器/构建工具：pip + pyproject.toml（setuptools）
• 仓库结构概览：
◦ TradingAgents/ – 项目根目录
◦ tradingagents/agents/analysts/ – 各类分析师（news、market、fundamentals、social_media）
◦ tradingagents/agents/utils/ – 工具集（agent_utils、news_data_tools、core_stock_tools…）
◦ tradingagents/agents/trader/ – 交易决策节点
◦ tradingagents/dataflows/ – 数据路由与供应商接口
◦ tradingagents/data/routing/ – 标的解析（TickerResolver）
3. 已完成工作
• 已完成事项 1：修改 news_analyst.py，基于 is_a_share() 动态控制工具暴露
◦ A 股只暴露 get_news，隐藏 get_global_news，防止误用美股宏观新闻
◦ 非 A 股保持原有行为（两个工具都可用）
• 已完成事项 2：在 agent_utils.py 中实现市场感知辅助函数
◦ is_a_share()、get_market_type()、get_market_specific_instruction()
◦ MarketRuleValidator 类（含 T+1 关键词检测、涨跌停校验框架）
• 已完成事项 3：在 trader.py 中接入 MarketRuleValidator
◦ 创建验证器实例 validator = MarketRuleValidator(company_name)
◦ 调用 validator.validate_and_rewrite_plan(result.content) 对交易计划进行规则校验
4. 关键决策与原因
• 决策 1：最小侵入式方案，只修改 P0 文件
◦ 内容：不改动全局数据路由（route_to_vendor）、配置（default_config.py）和核心工具（core_stock_tools.py），仅在 Agent 层做 market‑aware 扩展
◦ 原因：用户明确要求“不破坏美股逻辑”，避免回归风险；A 股支持是增量特性，应优先保证现有美股路径稳定
• 决策 2：使用 is_a_share() 进行市场感知路由
◦ 内容：在 news_analyst.py 中根据 is_a_share(ticker) 决定暴露哪些工具；在 trader.py 中只有 A 股才触发 MarketRuleValidator
◦ 原因：无需修改底层数据供应商选择逻辑，利用现有的 TickerResolver 识别市场类型，实现关注点分离
5. 当前相关文件
• 主要文件：
◦ 路径：TradingAgents/tradingagents/agents/utils/news_data_tools.py
◦ 作用：新闻数据工具集，包含 _get_news_ashare() 函数（当前有硬编码虚构新闻，需重写为安全降级输出）
◦ 路径：TradingAgents/tradingagents/agents/trader/trader.py
◦ 作用：交易决策节点，已接入 MarketRuleValidator 但未传 prev_close，价格校验未生效
• 次要文件：
◦ 路径：TradingAgents/tradingagents/agents/utils/agent_utils.py
◦ 作用：市场感知辅助函数、MarketRuleValidator 类定义（需补充 get_prev_close() 辅助函数）
◦ 路径：TradingAgents/tradingagents/agents/analysts/news_analyst.py
◦ 作用：新闻分析师，已完成工具暴露控制，A 股不会调用 get_global_news
6. 已验证内容
• 已成功执行的命令：未知（尚未运行验证脚本）
• 已通过的测试：未知（尚未运行单元/集成测试）
• 已确认有效的方案：
1. news_analyst.py 的工具暴露控制能阻止 A 股调用 get_global_news
2. MarketRuleValidator 的 T+1 关键词检测能识别“当天买入并卖出”等违规短语
3. is_a_share() 能正确识别 A 股标的（如 000001.SZ）与非 A 股标的（如 AAPL）
7. 未解决问题
• 问题 1：A 股新闻 fallback 包含虚构新闻
◦ 现象：_get_news_ashare() 返回硬编码的模拟新闻标题、摘要、影响分析，伪装成真实报道
◦ 怀疑原因：原实现为快速占位，未考虑“非伪造”要求
◦ 已尝试方案：已设计重写方案，将虚构内容替换为结构化分析提示，明确声明“当前未获取到实时 A 股新闻”
• 问题 2：MarketRuleValidator 价格校验未生效
◦ 现象：validate_and_rewrite_plan() 调用 validate_price(0, date.today())，使用占位价格 0，导致校验跳过
◦ 怀疑原因：未获取真实 prev_close，且未从交易计划文本中提取目标价格
◦ 已尝试方案：已设计 get_prev_close() 辅助函数，通过现有 route_to_vendor("get_stock_data", …) 接口获取前收价；并计划在 validate_and_rewrite_plan() 中使用正则提取计划中的价格，仅当识别到明确价格时才校验
8. 下一步建议
• Step 1：重写 news_data_tools.py 中的 _get_news_ashare()
移除所有虚构新闻条目，改为：
1. 明确声明“当前未获取到实时 A 股新闻”
2. 提供国内宏观/政策/行业关注方向的结构化提示
3. 输出可供 News Analyst 继续分析的政策语境
• Step 2：在 agent_utils.py 中添加 get_prev_close(ticker) 辅助函数
调用现有数据接口 route_to_vendor("get_stock_data", ticker, end_date=昨天) 获取前收价
• Step 3：修改 trader.py 和 MarketRuleValidator
1. trader.py 中调用 get_prev_close(company_name) 并传入 MarketRuleValidator
2. 更新 validate_and_rewrite_plan()，使用正则从计划文本提取价格，仅在识别到价格时进行涨跌停校验
• Step 4：运行最小验证脚本，确认：
◦ A 股 ticker 的 news agent 无法调用 get_global_news
◦ 美股 ticker 仍可正常调用 get_global_news
◦ A 股 trader plan 会被规则校验改写或标注
◦ 美股 trader plan 保持不变
9. 我对后续助手的要求
• 回复语言：中文（简体）
• 代码风格要求：最小改动，保持原有缩进、命名约定
• 注释要求：关键修改处加简短中文注释，说明为何改
• 修改代码前是否先给计划：是，必须列出要改的文件、改什么、为什么改
• 是否优先最小改动：是，严禁扩大改动面，除非能证明必须
• 其他偏好：
1. 保持美股路径零影响（所有改动都通过 is_a_share() 隔离）
2. 不修改 route_to_vendor()、default_config.py、core_stock_tools.py
3. 先实现新闻工具控制 + Trader 校验，Prompt 注入相关改动控制在最小范围
10. 可直接复制给下一位模型的提示词
请基于以上上下文继续工作，先复述你的理解，再给出下一步最优执行方案；如果要改代码，先说明会改哪些文件、为什么改。