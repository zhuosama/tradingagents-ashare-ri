"""
网络超时 & 重试机制验证脚本
验证以下内容：
  1. alpha_vantage_common._make_api_request 使用了 timeout 参数
  2. alpha_vantage_common 在网络超时时触发重试（不超过 3 次）
  3. yf_retry 现在也能重试超时和连接错误
  4. openai_client 默认 timeout=120s，且可被环境变量覆盖
  5. 代理环境变量被正确传递给 requests.get

运行方式（激活虚拟环境后）：
    cd d:/Trading-Agent/TradingAgents
    .venv/Scripts/python.exe test_timeout_retry.py

通过标准：所有测试显示 PASS，无 FAIL
"""

import os, sys, time
from unittest import mock
from dotenv import load_dotenv

load_dotenv()

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def run(name, fn):
    print(f"\n{'─'*60}\nTEST: {name}\n{'─'*60}")
    try:
        detail = fn()
        print(f"{PASS}  {detail}")
        results.append((name, True, detail))
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"{FAIL}  {e}")
        results.append((name, False, str(e)))


# ── T01: _make_api_request 代码中有 timeout= 参数 ──────────────────────────
def t01_alpha_vantage_timeout_in_source():
    import inspect
    from tradingagents.dataflows.alpha_vantage_common import _make_api_request
    src = inspect.getsource(_make_api_request)
    assert "timeout=" in src, "timeout= 参数未出现在 _make_api_request 源码中"
    assert "_DATA_API_TIMEOUT" in src, "_DATA_API_TIMEOUT 变量未使用"
    return "_make_api_request 已包含 timeout= 参数 ✓"


# ── T02: _make_api_request 网络超时时触发重试 ────────────────────────────────
def t02_alpha_vantage_retries_on_timeout():
    import requests
    from tradingagents.dataflows import alpha_vantage_common as av

    # 确保有 API key（可以是假的，因为我们 mock requests.get）
    os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "demo")

    call_count = 0
    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.exceptions.Timeout("Connection timed out")

    with mock.patch("tradingagents.dataflows.alpha_vantage_common.requests.get", fake_get), \
         mock.patch("tradingagents.dataflows.alpha_vantage_common.time.sleep"):  # 跳过等待
        try:
            av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
        except requests.exceptions.Timeout:
            pass  # 预期最终抛出

    expected = len(av._DATA_RETRY_DELAYS) + 1   # 1 initial + N retries
    assert call_count == expected, f"Expected {expected} calls, got {call_count}"
    return f"Timeout 触发 {call_count} 次重试（1 次初始 + {len(av._DATA_RETRY_DELAYS)} 次 backoff）✓"


# ── T03: _make_api_request 连接错误时触发重试 ────────────────────────────────
def t03_alpha_vantage_retries_on_connection_error():
    import requests
    from tradingagents.dataflows import alpha_vantage_common as av

    os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "demo")

    call_count = 0
    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise requests.exceptions.ConnectionError("Connection refused")

    with mock.patch("tradingagents.dataflows.alpha_vantage_common.requests.get", fake_get), \
         mock.patch("tradingagents.dataflows.alpha_vantage_common.time.sleep"):
        try:
            av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
        except requests.exceptions.ConnectionError:
            pass

    expected = len(av._DATA_RETRY_DELAYS) + 1
    assert call_count == expected, f"Expected {expected} calls, got {call_count}"
    return f"ConnectionError 触发重试 ✓ (calls={call_count})"


# ── T04: _make_api_request 5xx 服务器错误触发重试 ───────────────────────────
def t04_alpha_vantage_retries_on_5xx():
    import requests
    from tradingagents.dataflows import alpha_vantage_common as av

    os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "demo")

    call_count = 0
    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        r = mock.Mock()
        r.status_code = 503
        r.raise_for_status = mock.Mock()
        return r

    with mock.patch("tradingagents.dataflows.alpha_vantage_common.requests.get", fake_get), \
         mock.patch("tradingagents.dataflows.alpha_vantage_common.time.sleep"):
        try:
            av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
        except requests.exceptions.HTTPError:
            pass

    expected = len(av._DATA_RETRY_DELAYS) + 1
    assert call_count == expected, f"Expected {expected} calls, got {call_count}"
    return f"503 Server Error 触发重试 ✓ (calls={call_count})"


# ── T05: 401 不触发重试 ──────────────────────────────────────────────────────
def t05_alpha_vantage_no_retry_on_401():
    import requests
    from tradingagents.dataflows import alpha_vantage_common as av

    os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "demo")

    call_count = 0
    def fake_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = mock.Mock()
        resp.status_code = 401
        http_err = requests.exceptions.HTTPError("401 Unauthorized", response=resp)
        resp.raise_for_status.side_effect = http_err
        return resp

    with mock.patch("tradingagents.dataflows.alpha_vantage_common.requests.get", fake_get), \
         mock.patch("tradingagents.dataflows.alpha_vantage_common.time.sleep"):
        try:
            av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
        except requests.exceptions.HTTPError:
            pass

    assert call_count == 1, f"401 不应重试，但调用了 {call_count} 次"
    return f"401 Unauthorized 不触发重试 ✓ (calls={call_count})"


# ── T06: yf_retry 现在处理 ConnectionError ──────────────────────────────────
def t06_yf_retry_handles_connection_error():
    import requests
    from tradingagents.dataflows.stockstats_utils import yf_retry

    call_count = 0
    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise requests.exceptions.ConnectionError("Network unreachable")
        return "success"

    with mock.patch("tradingagents.dataflows.stockstats_utils.time.sleep"):
        result = yf_retry(flaky, max_retries=3, base_delay=1.0)

    assert result == "success", f"Expected 'success', got {result!r}"
    assert call_count == 3, f"Expected 3 calls, got {call_count}"
    return f"yf_retry ConnectionError 重试后成功 ✓ (attempts={call_count})"


# ── T07: yf_retry 处理 Timeout ───────────────────────────────────────────────
def t07_yf_retry_handles_timeout():
    import requests
    from tradingagents.dataflows.stockstats_utils import yf_retry

    call_count = 0
    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise requests.exceptions.Timeout("Read timed out")
        return "ok"

    with mock.patch("tradingagents.dataflows.stockstats_utils.time.sleep"):
        result = yf_retry(flaky, max_retries=2, base_delay=1.0)

    assert result == "ok"
    return f"yf_retry Timeout 重试后成功 ✓ (attempts={call_count})"


# ── T08: openai_client 默认 timeout=120 ─────────────────────────────────────
def t08_llm_client_default_timeout():
    # 确保没有用户覆盖
    os.environ.pop("LLM_API_TIMEOUT", None)
    # 重新导入以反映环境变量
    import importlib
    import tradingagents.llm_clients.openai_client as oc
    importlib.reload(oc)

    assert oc._LLM_API_TIMEOUT == 120, f"Expected 120, got {oc._LLM_API_TIMEOUT}"
    return f"默认 LLM_API_TIMEOUT={oc._LLM_API_TIMEOUT}s ✓"


# ── T09: LLM_API_TIMEOUT 环境变量生效 ───────────────────────────────────────
def t09_llm_timeout_env_override():
    import importlib
    os.environ["LLM_API_TIMEOUT"] = "180"
    import tradingagents.llm_clients.openai_client as oc
    importlib.reload(oc)

    assert oc._LLM_API_TIMEOUT == 180, f"Expected 180, got {oc._LLM_API_TIMEOUT}"

    # Restore
    os.environ.pop("LLM_API_TIMEOUT", None)
    importlib.reload(oc)
    return "LLM_API_TIMEOUT=180 环境变量覆盖生效 ✓"


# ── T10: get_llm() 将 timeout 注入 ChatOpenAI kwargs ────────────────────────
def t10_llm_client_injects_timeout():
    import importlib
    os.environ.pop("LLM_API_TIMEOUT", None)
    import tradingagents.llm_clients.openai_client as oc
    importlib.reload(oc)

    # Patch NormalizedChatOpenAI so we can inspect what kwargs were passed
    captured = {}
    class FakeLLM:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    with mock.patch.object(oc, "NormalizedChatOpenAI", FakeLLM):
        # Need a real client instance — DeepSeek key not required for this test
        os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")
        client = oc.OpenAIClient(model="deepseek-chat", provider="deepseek")
        client.get_llm()

    assert "timeout" in captured, "timeout 未被注入到 ChatOpenAI kwargs"
    assert captured["timeout"] == 120, f"Expected timeout=120, got {captured['timeout']}"
    return f"get_llm() 注入 timeout={captured['timeout']}s ✓"


# ── T11: 代理环境变量被传递给 requests.get ───────────────────────────────────
def t11_proxy_forwarded_to_requests():
    import requests
    from tradingagents.dataflows import alpha_vantage_common as av

    os.environ["ALPHA_VANTAGE_API_KEY"] = "demo"
    os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

    captured_kwargs = {}
    def fake_get(*args, **kwargs):
        captured_kwargs.update(kwargs)
        # Return a successful mock response
        resp = mock.Mock()
        resp.status_code = 200
        resp.raise_for_status = mock.Mock()
        resp.text = '{"data": "ok"}'
        return resp

    try:
        with mock.patch("tradingagents.dataflows.alpha_vantage_common.requests.get", fake_get):
            av._make_api_request("TIME_SERIES_DAILY", {"symbol": "AAPL"})
    finally:
        os.environ.pop("HTTPS_PROXY", None)

    proxies = captured_kwargs.get("proxies") or {}
    assert proxies.get("https") == "http://127.0.0.1:7890", (
        f"代理未被正确传递: proxies={proxies!r}"
    )
    timeout = captured_kwargs.get("timeout")
    assert timeout == av._DATA_API_TIMEOUT, f"timeout={timeout!r}，期望 {av._DATA_API_TIMEOUT}"
    return f"代理 {proxies} 与 timeout={timeout} 均正确传递 ✓"


# ── T12: DATA_API_TIMEOUT 环境变量生效 ──────────────────────────────────────
def t12_data_api_timeout_env_override():
    import importlib
    os.environ["DATA_API_TIMEOUT"] = "90"
    import tradingagents.dataflows.alpha_vantage_common as av
    importlib.reload(av)

    assert av._DATA_API_TIMEOUT == 90, f"Expected 90, got {av._DATA_API_TIMEOUT}"

    # Restore
    os.environ.pop("DATA_API_TIMEOUT", None)
    importlib.reload(av)
    return "DATA_API_TIMEOUT=90 环境变量覆盖生效 ✓"


# ── 执行 ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*60)
    print("  Network Timeout & Retry Validation Test Suite")
    print("  TradingAgents · Task 4 Fix Verification")
    print("═"*60)

    run("T01 | _make_api_request timeout 参数已添加",         t01_alpha_vantage_timeout_in_source)
    run("T02 | Alpha Vantage Timeout 触发重试",               t02_alpha_vantage_retries_on_timeout)
    run("T03 | Alpha Vantage ConnectionError 触发重试",       t03_alpha_vantage_retries_on_connection_error)
    run("T04 | Alpha Vantage 503 触发重试",                   t04_alpha_vantage_retries_on_5xx)
    run("T05 | Alpha Vantage 401 不触发重试",                 t05_alpha_vantage_no_retry_on_401)
    run("T06 | yf_retry 处理 ConnectionError",               t06_yf_retry_handles_connection_error)
    run("T07 | yf_retry 处理 Timeout",                       t07_yf_retry_handles_timeout)
    run("T08 | LLM 默认 timeout=120s",                       t08_llm_client_default_timeout)
    run("T09 | LLM_API_TIMEOUT 环境变量覆盖",                 t09_llm_timeout_env_override)
    run("T10 | get_llm() 注入 timeout 到 ChatOpenAI",        t10_llm_client_injects_timeout)
    run("T11 | 代理变量传递给 requests.get",                  t11_proxy_forwarded_to_requests)
    run("T12 | DATA_API_TIMEOUT 环境变量覆盖",                t12_data_api_timeout_env_override)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    print("\n" + "═"*60)
    print(f"  Results: {passed} passed / {failed} failed / {len(results)} total")
    print("═"*60)
    for name, ok, detail in results:
        print(f"  {PASS if ok else FAIL}  {name}")
        if not ok:
            print(f"         └─ {detail}")
    print()
    sys.exit(0 if failed == 0 else 1)
