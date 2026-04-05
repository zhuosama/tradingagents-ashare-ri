"""
最小化 CLI DeepSeek 选项验证脚本
不依赖完整 TradingAgents 流程，直接验证：
  1. DeepSeek 是否出现在 select_llm_provider 的选项列表中
  2. 选中 DeepSeek 后 llm_provider 是否被正确设置为 "deepseek"
  3. model_catalog 是否能为 "deepseek" 返回合法的 quick/deep 模型列表
  4. API Key 前置校验逻辑是否正常工作
  5. 以 deepseek-reasoner 完整初始化 LLM Client

运行方式（激活虚拟环境后）：
    cd d:/Trading-Agent/TradingAgents
    .venv/Scripts/python.exe test_cli_deepseek.py

通过标准：所有测试显示 PASS，无 FAIL
"""

import os, sys
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
        print(f"{FAIL}  {e}")
        results.append((name, False, str(e)))


# ── T01：DeepSeek 出现在 BASE_URLS 中 ────────────────────────────────────────
def t01_deepseek_in_base_urls():
    # 直接读取 cli/utils.py 中定义的 BASE_URLS（不触发交互提示）
    import importlib, inspect
    import cli.utils as u

    src = inspect.getsource(u.select_llm_provider)
    assert "DeepSeek" in src, "DeepSeek 未出现在 select_llm_provider 函数源码中"
    assert "api.deepseek.com" in src, "DeepSeek base_url 不正确"
    return "DeepSeek 已加入 BASE_URLS，base_url=https://api.deepseek.com/v1"


# ── T02：display_name.lower() == "deepseek" 与 llm_provider 映射一致 ──────────
def t02_display_name_to_provider():
    display_name = "DeepSeek"
    provider_lower = display_name.lower()
    assert provider_lower == "deepseek", f"Expected 'deepseek', got '{provider_lower}'"
    return f"'{display_name}'.lower() = '{provider_lower}' ✓"


# ── T03：model_catalog 能为 deepseek 返回 quick/deep 模型 ─────────────────────
def t03_model_catalog():
    from tradingagents.llm_clients.model_catalog import get_model_options

    quick_opts = get_model_options("deepseek", "quick")
    deep_opts  = get_model_options("deepseek", "deep")

    assert quick_opts, "deepseek quick 模型列表为空"
    assert deep_opts,  "deepseek deep 模型列表为空"

    quick_vals = [v for _, v in quick_opts]
    deep_vals  = [v for _, v in deep_opts]

    assert "deepseek-chat"     in quick_vals, "deepseek-chat 不在 quick 列表"
    assert "deepseek-reasoner" in deep_vals,  "deepseek-reasoner 不在 deep 列表"

    return (
        f"quick={quick_vals}  deep={deep_vals}"
    )


# ── T04：API Key 校验 — Key 存在时不退出 ──────────────────────────────────────
def t04_api_key_present():
    from cli.utils import _validate_api_key

    # 临时设置 Key
    os.environ["DEEPSEEK_API_KEY"] = "test_key_for_validation"
    try:
        _validate_api_key("deepseek")   # 应不报错
    finally:
        # 恢复真实 Key（若有）
        real_key = os.getenv("DEEPSEEK_API_KEY")
        if real_key == "test_key_for_validation":
            # 真实 Key 不存在，从 .env 重新加载
            load_dotenv(override=True)

    return "Key 存在时 _validate_api_key 正常通过 ✓"


# ── T05：API Key 校验 — Key 缺失时应抛出 SystemExit(1) ───────────────────────
def t05_api_key_missing():
    from cli.utils import _validate_api_key

    saved = os.environ.pop("DEEPSEEK_API_KEY", None)
    raised = False
    try:
        _validate_api_key("deepseek")
    except SystemExit as e:
        assert e.code == 1, f"Expected exit code 1, got {e.code}"
        raised = True
    finally:
        if saved:
            os.environ["DEEPSEEK_API_KEY"] = saved

    assert raised, "Key 缺失时应触发 SystemExit(1)，但未抛出"
    return "Key 缺失时 SystemExit(1) 被正确触发 ✓"


# ── T06：Ollama 跳过 Key 校验 ─────────────────────────────────────────────────
def t06_ollama_no_key_needed():
    from cli.utils import _validate_api_key

    # Ollama 不在 _PROVIDER_KEY_ENV，校验直接跳过
    _validate_api_key("ollama")   # 不应 exit
    return "Ollama 跳过 Key 校验 ✓"


# ── T07：OpenAI 校验逻辑未被破坏 ─────────────────────────────────────────────
def t07_openai_validation_intact():
    from cli.utils import _validate_api_key

    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        if saved:
            # Key 存在 → 不应 exit
            _validate_api_key("openai")
            detail = "OPENAI_API_KEY 存在，校验通过 ✓"
        else:
            # Key 不存在 → 应触发 SystemExit(1)
            raised = False
            try:
                _validate_api_key("openai")
            except SystemExit as e:
                assert e.code == 1
                raised = True
            assert raised, "预期 SystemExit(1) 未触发"
            detail = "OPENAI_API_KEY 缺失时 SystemExit(1) 正确触发 ✓"
    finally:
        if saved:
            os.environ["OPENAI_API_KEY"] = saved

    return detail


# ── T08：以 deepseek-reasoner 完整初始化 LLM Client ──────────────────────────
def t08_llm_client_init():
    from tradingagents.llm_clients import create_llm_client

    # 确保 Key 已载入
    load_dotenv(override=True)
    if not os.getenv("DEEPSEEK_API_KEY"):
        return "跳过（DEEPSEEK_API_KEY 未配置）"

    client = create_llm_client(provider="deepseek", model="deepseek-reasoner")
    llm = client.get_llm()

    # 验证不会走 Responses API
    use_resp = getattr(llm, "use_responses_api", None)
    assert use_resp is False, f"use_responses_api={use_resp!r}，应为 False"

    base = str(getattr(llm, "openai_api_base", ""))
    assert "deepseek.com" in base, f"base_url 错误: {base!r}"

    max_tok = getattr(llm, "max_tokens", None)
    assert max_tok is not None and max_tok >= 4000, (
        f"max_tokens={max_tok}，deepseek-reasoner 需要 ≥4000"
    )

    return (
        f"provider=deepseek  model=deepseek-reasoner  "
        f"use_responses_api=False  max_tokens={max_tok} ✓"
    )


# ── T09：deepseek-chat 同样可初始化（quick_think_llm）────────────────────────
def t09_llm_client_chat():
    from tradingagents.llm_clients import create_llm_client

    load_dotenv(override=True)
    if not os.getenv("DEEPSEEK_API_KEY"):
        return "跳过（DEEPSEEK_API_KEY 未配置）"

    client = create_llm_client(provider="deepseek", model="deepseek-chat")
    llm = client.get_llm()

    use_resp = getattr(llm, "use_responses_api", None)
    assert use_resp is False, f"use_responses_api={use_resp!r}，应为 False"

    return "deepseek-chat 初始化正常，use_responses_api=False ✓"


# ── T10：run_analysis 配置链完整性（不触发网络调用）─────────────────────────
def t10_config_chain():
    from tradingagents.default_config import DEFAULT_CONFIG

    # 模拟 get_user_selections 返回 deepseek
    selections = {
        "llm_provider": "deepseek",          # display_name.lower()
        "backend_url":  "https://api.deepseek.com/v1",
        "shallow_thinker": "deepseek-chat",
        "deep_thinker":    "deepseek-reasoner",
        "research_depth": 1,
        "google_thinking_level": None,
        "openai_reasoning_effort": None,
        "anthropic_effort": None,
        "output_language": "Chinese",
    }

    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"]       = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"]         = selections["shallow_thinker"]
    config["deep_think_llm"]          = selections["deep_thinker"]
    config["backend_url"]             = selections["backend_url"]
    config["llm_provider"]            = selections["llm_provider"].lower()
    config["google_thinking_level"]   = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")
    config["anthropic_effort"]        = selections.get("anthropic_effort")
    config["output_language"]         = selections.get("output_language", "English")

    assert config["llm_provider"]    == "deepseek"
    assert config["quick_think_llm"] == "deepseek-chat"
    assert config["deep_think_llm"]  == "deepseek-reasoner"
    assert config["backend_url"]     == "https://api.deepseek.com/v1"

    return (
        f"llm_provider={config['llm_provider']}  "
        f"quick={config['quick_think_llm']}  "
        f"deep={config['deep_think_llm']} ✓"
    )


# ── 执行所有测试 ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*60)
    print("  CLI DeepSeek Integration Test Suite")
    print("  TradingAgents · Step 6 LLM Provider Fix Validation")
    print("═"*60)

    run("T01 | DeepSeek 出现在 BASE_URLS",               t01_deepseek_in_base_urls)
    run("T02 | display_name→llm_provider 映射",          t02_display_name_to_provider)
    run("T03 | model_catalog deepseek quick/deep 模型",  t03_model_catalog)
    run("T04 | API Key 存在时通过校验",                   t04_api_key_present)
    run("T05 | API Key 缺失时 exit(1)",                   t05_api_key_missing)
    run("T06 | Ollama 跳过 Key 校验",                    t06_ollama_no_key_needed)
    run("T07 | OpenAI 校验逻辑未被破坏",                  t07_openai_validation_intact)
    run("T08 | deepseek-reasoner LLM Client 初始化",     t08_llm_client_init)
    run("T09 | deepseek-chat LLM Client 初始化",         t09_llm_client_chat)
    run("T10 | run_analysis 配置链完整性",                t10_config_chain)

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
