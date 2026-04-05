"""
最小化 DeepSeek 诊断测试脚本
用途：在不运行完整 TradingAgents 流程的情况下，验证所有 DeepSeek 调用场景

运行方式：
    cd d:/Trading-Agent/TradingAgents
    .venv/Scripts/python.exe test_deepseek_reasoner.py

通过标准：所有测试显示 PASS，无 FAIL
"""

import os
import sys
import time

# ── 加载环境变量 ───────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

# ── 映射 DeepSeek key → OPENAI_API_KEY (供 LangChain ChatOpenAI 读取) ──────────
_ds_key = os.getenv("DEEPSEEK_API_KEY")
if not _ds_key:
    print("FAIL  .env 中未找到 DEEPSEEK_API_KEY，请先配置")
    sys.exit(1)
os.environ["OPENAI_API_KEY"] = _ds_key

# 开启框架调试日志
os.environ["TRADINGAGENTS_DEBUG"] = "1"

import logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
# 静音无关的 httpx/httpcore 噪声
for noisy in ("httpx", "httpcore", "openai._base_client"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

results: list[tuple[str, bool, str]] = []


def run(name: str, fn):
    """执行一个测试用例，捕获异常并记录结果。"""
    print(f"\n{'─'*60}")
    print(f"TEST: {name}")
    print('─'*60)
    try:
        detail = fn()
        print(f"{PASS}  {detail}")
        results.append((name, True, detail))
    except Exception as exc:
        print(f"{FAIL}  {exc}")
        results.append((name, False, str(exc)))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1: 原生 OpenAI SDK — deepseek-chat 纯文本
# ══════════════════════════════════════════════════════════════════════════════
def t1_sdk_chat_plain():
    import openai
    client = openai.OpenAI(api_key=_ds_key, base_url="https://api.deepseek.com/v1")
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Reply with exactly: SDK_CHAT_OK"}],
        max_tokens=20,
    )
    content = resp.choices[0].message.content
    assert "SDK_CHAT_OK" in content, f"Unexpected: {content!r}"
    return f"content={content!r}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2: 原生 OpenAI SDK — deepseek-chat 工具调用
# ══════════════════════════════════════════════════════════════════════════════
def t2_sdk_chat_tools():
    import openai
    client = openai.OpenAI(api_key=_ds_key, base_url="https://api.deepseek.com/v1")
    tools = [{
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "Get stock price",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    }]
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Get the price of NVDA"}],
        tools=tools,
        max_tokens=100,
    )
    tc = resp.choices[0].message.tool_calls
    assert tc, "No tool_calls returned"
    assert tc[0].function.name == "get_price"
    return f"tool={tc[0].function.name}  args={tc[0].function.arguments}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3: 原生 OpenAI SDK — deepseek-reasoner 纯文本
# ══════════════════════════════════════════════════════════════════════════════
def t3_sdk_reasoner_plain():
    import openai
    client = openai.OpenAI(api_key=_ds_key, base_url="https://api.deepseek.com/v1")
    resp = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[{"role": "user", "content": "Reply with exactly: SDK_REASONER_OK"}],
        max_tokens=2000,
    )
    msg = resp.choices[0].message
    content = msg.content
    reasoning_len = len(getattr(msg, "reasoning_content", "") or "")
    assert content, f"Empty content!  reasoning_len={reasoning_len}"
    assert "SDK_REASONER_OK" in content, f"Unexpected: {content!r}"
    return f"content={content!r}  reasoning_chars={reasoning_len}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4: 原生 OpenAI SDK — deepseek-reasoner 工具调用
# ══════════════════════════════════════════════════════════════════════════════
def t4_sdk_reasoner_tools():
    import openai
    client = openai.OpenAI(api_key=_ds_key, base_url="https://api.deepseek.com/v1")
    tools = [{
        "type": "function",
        "function": {
            "name": "analyze_stock",
            "description": "Analyze a stock",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    }]
    resp = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[{"role": "user", "content": "Analyze NVDA using analyze_stock"}],
        tools=tools,
        max_tokens=2000,
    )
    tc = resp.choices[0].message.tool_calls
    assert tc, "No tool_calls returned"
    assert tc[0].function.name == "analyze_stock"
    reasoning_len = len(getattr(resp.choices[0].message, "reasoning_content", "") or "")
    return f"tool={tc[0].function.name}  reasoning_chars={reasoning_len}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5: LangChain ChatOpenAI (deepseek provider) — deepseek-chat 纯文本
# ══════════════════════════════════════════════════════════════════════════════
def t5_lc_chat_plain():
    from tradingagents.llm_clients import create_llm_client
    client = create_llm_client(provider="deepseek", model="deepseek-chat")
    llm = client.get_llm()
    result = llm.invoke("Reply with exactly: LC_CHAT_OK")
    assert isinstance(result.content, str), f"content is {type(result.content)}"
    assert "LC_CHAT_OK" in result.content, f"Unexpected: {result.content!r}"
    return f"content={result.content!r}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6: LangChain ChatOpenAI (deepseek provider) — deepseek-chat + bind_tools
# ══════════════════════════════════════════════════════════════════════════════
def t6_lc_chat_tools():
    from langchain_core.tools import tool
    from tradingagents.llm_clients import create_llm_client

    @tool
    def get_stock_price(symbol: str) -> str:
        """Return the current price of a stock given its ticker symbol."""
        return f"${symbol} = 177.39"

    client = create_llm_client(provider="deepseek", model="deepseek-chat")
    llm = client.get_llm()
    llm_with_tools = llm.bind_tools([get_stock_price])
    result = llm_with_tools.invoke("What is the price of NVDA?")
    assert result.tool_calls, f"No tool_calls.  content={result.content!r}"
    tc = result.tool_calls[0]
    assert tc["name"] == "get_stock_price"
    return f"tool={tc['name']}  args={tc['args']}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7: LangChain ChatOpenAI (deepseek provider) — deepseek-reasoner 纯文本
# ══════════════════════════════════════════════════════════════════════════════
def t7_lc_reasoner_plain():
    from tradingagents.llm_clients import create_llm_client
    client = create_llm_client(provider="deepseek", model="deepseek-reasoner")
    llm = client.get_llm()
    result = llm.invoke("Reply with exactly: LC_REASONER_OK")
    assert isinstance(result.content, str), f"content is {type(result.content)}"
    assert result.content.strip(), "content is empty (token budget exhausted?)"
    assert "LC_REASONER_OK" in result.content, f"Unexpected: {result.content!r}"
    usage = result.response_metadata.get("token_usage", {})
    return f"content={result.content!r}  tokens={usage}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8: LangChain ChatOpenAI (deepseek provider) — deepseek-reasoner + bind_tools
# ══════════════════════════════════════════════════════════════════════════════
def t8_lc_reasoner_tools():
    from langchain_core.tools import tool
    from tradingagents.llm_clients import create_llm_client

    @tool
    def get_fundamentals(ticker: str) -> str:
        """Return fundamental data for a stock."""
        return f"{ticker}: PE=36, ROE=101%"

    client = create_llm_client(provider="deepseek", model="deepseek-reasoner")
    llm = client.get_llm()
    llm_with_tools = llm.bind_tools([get_fundamentals])
    result = llm_with_tools.invoke("Get fundamentals for NVDA")
    assert result.tool_calls, f"No tool_calls.  content={result.content!r}"
    tc = result.tool_calls[0]
    assert tc["name"] == "get_fundamentals"
    return f"tool={tc['name']}  args={tc['args']}"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9: 重试机制验证 — 模拟 429 应被重试，401 不应重试
# ══════════════════════════════════════════════════════════════════════════════
def t9_retry_logic():
    from tradingagents.llm_clients.openai_client import _is_retryable

    class FakeExc(Exception):
        pass

    retryable_cases = ["429 rate limit", "502 Bad Gateway", "503 Service Unavailable", "Timeout exceeded", "ConnectionError"]
    non_retryable_cases = ["401 Unauthorized", "400 Bad Request", "404 Not Found", "Invalid API key"]

    for msg in retryable_cases:
        assert _is_retryable(FakeExc(msg)), f"Should be retryable: {msg!r}"
    for msg in non_retryable_cases:
        assert not _is_retryable(FakeExc(msg)), f"Should NOT be retryable: {msg!r}"

    return f"retryable={len(retryable_cases)} cases ✓  non-retryable={len(non_retryable_cases)} cases ✓"


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10: 确认旧配置 (llm_provider=openai) 不再触发 404
# ══════════════════════════════════════════════════════════════════════════════
def t10_wrong_provider_detection():
    """
    旧配置 llm_provider='openai' + DeepSeek key 会发送到 /v1/responses 端点
    (use_responses_api=True)，DeepSeek 返回 404。
    本测试验证使用 llm_provider='deepseek' 时不再触发此问题。
    """
    from tradingagents.llm_clients import create_llm_client

    # 正确配置：deepseek provider
    client = create_llm_client(provider="deepseek", model="deepseek-chat")
    llm = client.get_llm()

    # 验证 use_responses_api 被显式设为 False（不是 None，不是 True）
    use_resp = getattr(llm, "use_responses_api", None)
    assert use_resp is False, (
        f"use_responses_api={use_resp!r} — expected False. "
        "True or None could activate /v1/responses and cause 404 on DeepSeek."
    )

    # 验证 base_url 正确
    actual_base = str(getattr(llm, "openai_api_base", "") or "")
    assert "deepseek.com" in actual_base, f"Wrong base_url: {actual_base!r}"

    return f"use_responses_api=False (explicit) ✓  base_url={actual_base!r}"


# ══════════════════════════════════════════════════════════════════════════════
# 运行所有测试
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "═"*60)
    print("  DeepSeek Reasoner Diagnostic Test Suite")
    print("  TradingAgents · DeepSeek API Compatibility")
    print("═"*60)

    run("T01 | SDK deepseek-chat plain text",         t1_sdk_chat_plain)
    run("T02 | SDK deepseek-chat tool calling",       t2_sdk_chat_tools)
    run("T03 | SDK deepseek-reasoner plain text",     t3_sdk_reasoner_plain)
    run("T04 | SDK deepseek-reasoner tool calling",   t4_sdk_reasoner_tools)
    run("T05 | LangChain deepseek-chat plain",        t5_lc_chat_plain)
    run("T06 | LangChain deepseek-chat bind_tools",   t6_lc_chat_tools)
    run("T07 | LangChain deepseek-reasoner plain",    t7_lc_reasoner_plain)
    run("T08 | LangChain deepseek-reasoner bind_tools", t8_lc_reasoner_tools)
    run("T09 | Retry logic (_is_retryable)",          t9_retry_logic)
    run("T10 | Provider config (no 404 regression)",  t10_wrong_provider_detection)

    # ── 汇总 ──────────────────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    print("\n" + "═"*60)
    print(f"  Results: {passed} passed / {failed} failed / {len(results)} total")
    print("═"*60)
    for name, ok, detail in results:
        status = PASS if ok else FAIL
        print(f"  {status}  {name}")
        if not ok:
            print(f"         └─ {detail}")
    print()

    if failed:
        sys.exit(1)
