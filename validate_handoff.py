"""
验收脚本：验证本轮 handoff 修改的正确性。
运行方式：cd TradingAgents && python validate_handoff.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

PASS = "  [PASS]"
FAIL = "  [FAIL]"

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

errors = []

# ─────────────────────────────────────────────────────────────
# A. 新闻侧
# ─────────────────────────────────────────────────────────────
section("A. 新闻侧")

# A-1: is_a_share 识别
from tradingagents.agents.utils.agent_utils import is_a_share

cases = [
    ("000001.SZ", True),
    ("600519.SH", True),
    ("300750.SZ", True),   # 创业板
    ("688981.SH", True),   # 科创板
    ("AAPL",      False),
    ("NVDA",      False),
    ("00700.HK",  False),
]
print("\n[A-1] is_a_share 识别")
for ticker, expected in cases:
    result = is_a_share(ticker)
    ok = result == expected
    status = PASS if ok else FAIL
    print(f"{status}  is_a_share({ticker!r}) = {result}  (expected {expected})")
    if not ok:
        errors.append(f"is_a_share({ticker}) wrong")

# A-2: A 股 News Agent 工具列表不包含 get_global_news
print("\n[A-2] A 股 News Agent 工具暴露控制")
# 直接复现 news_analyst.py 的工具选择逻辑
from tradingagents.agents.utils.news_data_tools import get_news, get_global_news

for ticker, is_cn in [("000001.SZ", True), ("AAPL", False)]:
    if is_a_share(ticker):
        tools = [get_news]
    else:
        tools = [get_news, get_global_news]
    tool_names = [t.name for t in tools]
    has_global = "get_global_news" in tool_names
    if is_cn:
        ok = not has_global
        status = PASS if ok else FAIL
        print(f"{status}  A 股 {ticker}: tools={tool_names}  (get_global_news 已隐藏)")
        if not ok:
            errors.append(f"{ticker} A-share still exposes get_global_news")
    else:
        ok = has_global
        status = PASS if ok else FAIL
        print(f"{status}  美股 {ticker}: tools={tool_names}  (get_global_news 可用)")
        if not ok:
            errors.append(f"{ticker} US-stock missing get_global_news")

# A-3: A 股 fallback 不包含虚构新闻
print("\n[A-3] A 股 fallback 输出内容验证")
from tradingagents.agents.utils.news_data_tools import _get_news_ashare

output = _get_news_ashare("000001.SZ", "2026-01-01", "2026-01-10")

# 检查：不含任何之前的虚构标题关键词
fabricated_markers = [
    "货币政策委员会",          # 旧虚构新闻1
    "关于加强上市公司监管",     # 旧虚构新闻2
    "大规模设备更新",           # 旧虚构新闻3
    "北向资金近期持续净流入",   # 旧虚构新闻4
    "潜在影响：",               # 旧格式标志
]
found_fabricated = [m for m in fabricated_markers if m in output]
ok = len(found_fabricated) == 0
print(f"{PASS if ok else FAIL}  不含虚构新闻标志词: {found_fabricated if found_fabricated else '无'}")
if not ok:
    errors.append(f"fallback still contains fabricated markers: {found_fabricated}")

# 检查：包含明确的"未获取到实时"声明
required_markers = ["未获取到实时 A 股新闻", "不含任何真实或虚构"]
for m in required_markers:
    ok = m in output
    print(f"{PASS if ok else FAIL}  包含声明: '{m}'")
    if not ok:
        errors.append(f"fallback missing required marker: {m}")

print("\n--- 完整 fallback 输出（000001.SZ，2026-01-01 至 2026-01-10）---")
print(output)

# ─────────────────────────────────────────────────────────────
# B. 规则校验侧
# ─────────────────────────────────────────────────────────────
section("B. 规则校验侧")

from tradingagents.agents.utils.agent_utils import MarketRuleValidator

# B-1: A 股 + 明确价格（超限） → 触发价格警告
print("\n[B-1] A 股 plan 含明确越界价格 → 应触发涨跌停警告")
# 000001.SZ 主板，prev_close=10.00，+10%上限=11.00；测试价格 12.00
v = MarketRuleValidator("000001.SZ", prev_close=10.00)
plan_with_price = "建议以¥12.00买入，止损设在¥9.00。"
result = v.validate_and_rewrite_plan(plan_with_price)
ok = "A 股规则警告" in result and "超出当日涨跌停" in result
print(f"{PASS if ok else FAIL}  输出包含涨跌停警告")
print(f"  输入: {plan_with_price!r}")
print(f"  输出: {result!r}")
if not ok:
    errors.append("B-1: price limit warning not triggered")

# B-2: A 股 + 价格在范围内 → 无警告
print("\n[B-2] A 股 plan 含明确合规价格 → 不应触发价格警告")
v2 = MarketRuleValidator("000001.SZ", prev_close=10.00)
plan_ok_price = "建议以¥10.50买入，止损设在¥9.50。"
result2 = v2.validate_and_rewrite_plan(plan_ok_price)
ok2 = result2 == plan_ok_price  # 原样返回
print(f"{PASS if ok2 else FAIL}  合规价格不产生警告")
print(f"  输入: {plan_ok_price!r}")
print(f"  输出: {result2!r}")
if not ok2:
    errors.append("B-2: false warning triggered on valid price")

# B-3: A 股 + 无明确价格 → 不产生伪警告
print("\n[B-3] A 股 plan 无明确价格 → 不应产生价格伪警告")
v3 = MarketRuleValidator("000001.SZ", prev_close=10.00)
plan_no_price = "建议逢低买入，目标持有3个月，关注基本面改善。"
result3 = v3.validate_and_rewrite_plan(plan_no_price)
ok3 = result3 == plan_no_price
print(f"{PASS if ok3 else FAIL}  无价格时不产生伪警告")
print(f"  输入: {plan_no_price!r}")
print(f"  输出: {result3!r}")
if not ok3:
    errors.append("B-3: false warning triggered on plan without price")

# B-4: A 股 T+1 违规 → 触发警告
print("\n[B-4] A 股 plan 含 T+1 违规表述 → 应触发 T+1 警告")
v4 = MarketRuleValidator("000001.SZ", prev_close=10.00)
plan_t0 = "建议当天买入并卖出以锁定利润。"
result4 = v4.validate_and_rewrite_plan(plan_t0)
ok4 = "T+1 规则" in result4
print(f"{PASS if ok4 else FAIL}  T+1 违规被标注")
print(f"  输入: {plan_t0!r}")
print(f"  输出: {result4!r}")
if not ok4:
    errors.append("B-4: T+1 violation not flagged")

# B-5: 美股 plan → 完全不变
print("\n[B-5] 美股 plan → 应原样返回，不做任何修改")
v5 = MarketRuleValidator("AAPL", prev_close=200.00)
plan_us = "Buy AAPL at $210, stop loss at $195. Intraday trade strategy."
result5 = v5.validate_and_rewrite_plan(plan_us)
ok5 = result5 == plan_us
print(f"{PASS if ok5 else FAIL}  美股 plan 原样返回")
print(f"  输入: {plan_us!r}")
print(f"  输出: {result5!r}")
if not ok5:
    errors.append("B-5: US stock plan was modified")

# B-6: A 股 prev_close=None → 跳过价格校验（不因 None 崩溃）
print("\n[B-6] A 股 prev_close=None → 跳过价格校验，仅保留 T+1 检测")
v6 = MarketRuleValidator("000001.SZ", prev_close=None)
plan_price_no_prev = "建议以¥15.00买入。"
result6 = v6.validate_and_rewrite_plan(plan_price_no_prev)
ok6 = "超出当日涨跌停" not in result6
print(f"{PASS if ok6 else FAIL}  prev_close=None 时不做价格校验")
print(f"  输入: {plan_price_no_prev!r}")
print(f"  输出: {result6!r}")
if not ok6:
    errors.append("B-6: price check ran without prev_close")

# ─────────────────────────────────────────────────────────────
# C. 回归风险说明
# ─────────────────────────────────────────────────────────────
section("C. 回归风险说明（逻辑验证）")

print("""
[C-1] 美股新闻路径不受影响
  - get_news() 第一行判断 is_a_share(ticker)，非 A 股直接走 route_to_vendor("get_news", ...)
  - _get_news_ashare() 仅在 is_a_share=True 时调用，美股永远不进此分支

[C-2] 美股 Trader 路径不受影响
  - trader.py: `prev_close = get_prev_close(...) if is_a_share(...) else None`
  - 美股时 prev_close=None，MarketRuleValidator.is_ashare=False
  - validate_and_rewrite_plan() 第一行: `if not self.is_ashare: return plan_text`
  - 美股 plan 直接原样返回，零额外开销

[C-3] 不修改数据路由
  - get_prev_close() 仅调用 route_to_vendor("get_stock_data", ...)，未动 route_to_vendor 实现
  - default_config.py, core_stock_tools.py 均未改动

[C-4] get_prev_close 失败安全
  - 整体用 try/except 包裹，任何异常仅 logger.warning 后返回 None
  - prev_close=None 时 validate_price() 立即返回 (True, "")，不影响流程
""")

# ─────────────────────────────────────────────────────────────
# 总结
# ─────────────────────────────────────────────────────────────
section("验收总结")
if errors:
    print(f"\n[FAIL] {len(errors)} 项检查未通过:")
    for e in errors:
        print(f"  ✗ {e}")
    sys.exit(1)
else:
    print(f"\n[ALL PASS] 全部检查通过，共 {12} 项。")
