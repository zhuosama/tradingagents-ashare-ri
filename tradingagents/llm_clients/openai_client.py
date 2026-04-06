import os
import time
import logging
from typing import Any, Optional

from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model

logger = logging.getLogger(__name__)

# ── kwargs forwarded from user config to ChatOpenAI ──────────────────────────
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort",
    "api_key", "callbacks", "http_client", "http_async_client",
)

# Default LLM request timeout (seconds). Override via LLM_API_TIMEOUT env var.
_LLM_API_TIMEOUT = int(os.getenv("LLM_API_TIMEOUT", "120"))

# ── provider registry (base_url, env_var_for_api_key) ────────────────────────
_PROVIDER_CONFIG = {
    "xai":        ("https://api.x.ai/v1",                          "XAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1",                 "OPENROUTER_API_KEY"),
    "ollama":     ("http://localhost:11434/v1",                     None),
    "deepseek":   ("https://api.deepseek.com/v1",                  "DEEPSEEK_API_KEY"),
    "mimo":       ("https://token-plan-cn.xiaomimimo.com/v1",      "MIMO_API_KEY"),
}

# ── deepseek-reasoner (R1) specific settings ─────────────────────────────────
# R1 requires a larger token budget because thinking tokens count toward max_tokens.
# We enforce a minimum of 4 000 tokens so the model always has room to reply after
# its chain-of-thought reasoning.
_REASONER_MODELS = frozenset({"deepseek-reasoner"})
_REASONER_MIN_MAX_TOKENS = 4_000

# ── exponential-backoff retry settings ───────────────────────────────────────
# Retry on transient HTTP errors (rate-limit / server / network) with 1-2-4 s
# back-off delays. Non-retryable errors (auth, bad request, …) propagate
# immediately.
_RETRY_DELAYS: tuple[int, ...] = (1, 2, 4)
_RETRYABLE_HTTP_CODES = frozenset({"429", "500", "502", "503", "504"})
_RETRYABLE_ERROR_KEYWORDS = ("Timeout", "timeout", "ConnectionError", "Connection")


def _is_retryable(exc: Exception) -> bool:
    err = str(exc)
    return any(code in err for code in _RETRYABLE_HTTP_CODES) or any(
        kw in err for kw in _RETRYABLE_ERROR_KEYWORDS
    )


def _debug_enabled() -> bool:
    return os.getenv("TRADINGAGENTS_DEBUG", "").lower() in ("1", "true", "yes")


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with three enhancements over the stock class:

    1. **Content normalisation** – strips provider-specific block formats
       (OpenAI Responses API, Google Gemini typed blocks) so every downstream
       agent always receives a plain string.
    2. **Exponential-backoff retry** – transparently retries on transient API
       errors (rate-limit 429, server 5xx, network timeouts) with delays of
       1 s → 2 s → 4 s before giving up.
    3. **Debug logging** – when ``TRADINGAGENTS_DEBUG=1`` is set in the
       environment, logs each attempt's model name, attempt number, and result
       length at the DEBUG level.
    """

    def invoke(self, input, config=None, **kwargs):
        debug = _debug_enabled()
        model_name = getattr(self, "model_name", "unknown")
        max_attempts = len(_RETRY_DELAYS) + 1
        last_exc: Exception | None = None

        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                if debug:
                    logger.debug(
                        "[LLM] attempt=%d/%d  model=%s",
                        attempt, max_attempts, model_name,
                    )
                result = normalize_content(super().invoke(input, config, **kwargs))
                if debug:
                    content_len = len(str(getattr(result, "content", "")))
                    logger.debug(
                        "[LLM] OK  attempt=%d  response_chars=%d",
                        attempt, content_len,
                    )
                return result

            except Exception as exc:
                last_exc = exc
                if debug:
                    logger.debug(
                        "[LLM] error  attempt=%d  retryable=%s  exc=%s",
                        attempt, _is_retryable(exc), exc,
                    )
                # Propagate immediately when the error is not transient or we
                # have exhausted all retries (delay is None on the last pass).
                if not _is_retryable(exc) or delay is None:
                    raise
                logger.warning(
                    "[LLM] Transient error – retrying in %d s (attempt %d/%d): %s",
                    delay, attempt, len(_RETRY_DELAYS), exc,
                )
                time.sleep(delay)

        raise last_exc  # type: ignore[misc]


class OpenAIClient(BaseLLMClient):
    """LLM client for OpenAI, Ollama, OpenRouter, xAI, and DeepSeek.

    All providers except native OpenAI use the standard Chat Completions
    endpoint (``/v1/chat/completions``).  Native OpenAI uses the Responses API
    (``/v1/responses``) to support ``reasoning_effort`` uniformly across all
    model families (GPT-4.1, GPT-5).

    DeepSeek notes
    ──────────────
    * Set ``llm_provider = "deepseek"`` in config – **not** ``"openai"``.
      Using ``"openai"`` activates ``use_responses_api=True``, which routes
      requests to ``/v1/responses``.  DeepSeek exposes only
      ``/v1/chat/completions``, so every call returns HTTP 404.

    * ``deepseek-reasoner`` (R1) supports both plain text generation **and**
      function / tool calling.  Its thinking tokens count toward ``max_tokens``,
      so a minimum budget of 4 000 tokens is enforced automatically when no
      explicit ``max_tokens`` is provided.

    * ``deepseek-reasoner`` is best reserved for ``deep_think_llm``
      (Research Manager, Portfolio Manager – high-stakes decisions that benefit
      from chain-of-thought).  Use ``deepseek-chat`` for ``quick_think_llm``
      (Analyst loops that call tools many times – speed and cost matter more).
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _is_reasoner(self) -> bool:
        return self.model in _REASONER_MODELS

    # ── public API ───────────────────────────────────────────────────────────

    def get_llm(self) -> Any:
        """Return a configured ``NormalizedChatOpenAI`` instance."""
        self.warn_if_unknown_model()
        llm_kwargs: dict[str, Any] = {"model": self.model}

        # ── resolve base URL and API key for the chosen provider ─────────────
        if self.provider in _PROVIDER_CONFIG:
            base_url, api_key_env = _PROVIDER_CONFIG[self.provider]
            llm_kwargs["base_url"] = base_url
            if api_key_env:
                api_key = os.environ.get(api_key_env)
                if api_key:
                    llm_kwargs["api_key"] = api_key
            else:
                # Ollama does not require an API key
                llm_kwargs["api_key"] = "ollama"
        elif self.base_url:
            # Caller supplied a custom base URL (e.g. self-hosted endpoint)
            llm_kwargs["base_url"] = self.base_url

        # ── forward user-supplied kwargs ─────────────────────────────────────
        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # ── apply default LLM timeout unless caller already set one ──────────
        if "timeout" not in llm_kwargs:
            llm_kwargs["timeout"] = _LLM_API_TIMEOUT

        # ── deepseek-reasoner: guarantee an adequate token budget ─────────────
        # R1 thinking tokens are deducted from max_tokens before the model can
        # write its final answer.  Without a floor, a low or unset limit causes
        # the model to exhaust tokens during reasoning and return empty content.
        if self._is_reasoner() and "max_tokens" not in llm_kwargs:
            llm_kwargs["max_tokens"] = _REASONER_MIN_MAX_TOKENS

        # ── Responses API: native OpenAI only ────────────────────────────────
        # Third-party providers (deepseek, xai, ollama, openrouter) implement
        # only the Chat Completions standard (/v1/chat/completions).
        # Sending use_responses_api=True routes to /v1/responses which they
        # don't support → HTTP 404.
        # We set the flag explicitly (True/False) rather than leaving it None
        # so LangChain's auto-detection cannot accidentally enable the wrong
        # endpoint for a provider in a future package update.
        llm_kwargs["use_responses_api"] = (self.provider == "openai")

        return NormalizedChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model name against the known catalog for this provider."""
        return validate_model(self.provider, self.model)
