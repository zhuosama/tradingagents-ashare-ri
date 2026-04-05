"""
TradingAgents DeepSeek 接入验证脚本
运行前确保：
  1. .venv 已激活
  2. .env 文件含 DEEPSEEK_API_KEY
"""
import os
import sys
from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# 验证密钥加载
api_key = os.getenv("DEEPSEEK_API_KEY", "")
if not api_key:
    print("[ERROR] DEEPSEEK_API_KEY 未加载，请检查 .env 文件")
    sys.exit(1)
print(f"[OK] DEEPSEEK_API_KEY 已加载: {api_key[:8]}...")

# 验证模块导入
try:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
    print("[OK] tradingagents 模块导入成功")
except ImportError as e:
    print(f"[ERROR] 模块导入失败: {e}")
    sys.exit(1)

# 配置 DeepSeek
import copy
config = copy.deepcopy(DEFAULT_CONFIG)
config["llm_provider"] = "deepseek"
config["deep_think_llm"] = "deepseek-reasoner"   # R1 推理模型做深度分析
config["quick_think_llm"] = "deepseek-chat"       # V3 做快速分析，更省钱
config["max_debate_rounds"] = 1                   # 测试阶段减少轮数
config["max_risk_discuss_rounds"] = 1
config["online_tools"] = False                    # 不联网，只用 yfinance

print("[INFO] 配置信息：")
print(f"  Provider  : {config['llm_provider']}")
print(f"  Deep LLM  : {config['deep_think_llm']}")
print(f"  Quick LLM : {config['quick_think_llm']}")
print(f"  辩论轮数  : {config['max_debate_rounds']}")

print("\n[INFO] 初始化 TradingAgentsGraph...")
try:
    ta = TradingAgentsGraph(
        selected_analysts=["market", "fundamentals"],  # 只选两个分析师，加快测试
        debug=True,
        config=config,
    )
    print("[OK] 图初始化成功")
except Exception as e:
    print(f"[ERROR] 初始化失败: {e}")
    sys.exit(1)

print("\n[INFO] 开始分析 AAPL 2024-01-15...")
print("       预计耗时 2-5 分钟（多个 Agent 顺序调用）\n")

try:
    state, decision = ta.propagate("AAPL", "2024-01-15")
    print("\n" + "=" * 60)
    print("最终交易决策：")
    print("=" * 60)
    print(decision)
    print("=" * 60)
    print("\n[SUCCESS] 验证完成！TradingAgents + DeepSeek 运行正常")
except Exception as e:
    print(f"\n[ERROR] 运行失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
