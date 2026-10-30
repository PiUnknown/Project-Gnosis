"""
src/utils/nvidia_client.py

NVIDIA NIM Serverless Inference client for Project Gnosis.

PUBLIC INTERFACE:
  call_llm(system_prompt, user_prompt, ...) -> Optional[str]
  sleep_between_calls(delay)               -> None
  reset_client()                           -> None

CONFIGURATION:
  NVIDIA_API_KEY       (required) — from https://build.nvidia.com
  NVIDIA_BASE_URL      (optional) — defaults to NVIDIA NIM serverless endpoint
  NVIDIA_MODEL         (optional) — overrides NVIDIA_MODEL_DEFAULT at runtime
  NVIDIA_MODEL_FALLBACKS (optional) — comma-separated models to try, in order,
                                       when the primary model fails

MODEL CHOICE:
  Default: poolside/laguna-xs-2.1
  NVIDIA retires NIM models on a rolling basis — every model in the old default
  chain (meta/llama-3.2-11b-vision-instruct, meta/llama-3.1-*, qwen2.5-coder,
  gemma-3, phi-4) now returns 404 (function removed) or 410 (end of life).
  A retired model breaks explanation generation with no visible error, so the
  default must be a model verified against the live catalogue, and a fallback
  chain must exist for the next retirement.

  poolside/laguna-xs-2.1 is a code-specialised model that answers in 2-4s on
  the free tier and reliably emits a complete ~300-token explanation. The
  larger options are much slower (llama-3.2-90b: ~340s) or spend the whole
  max_tokens budget on hidden reasoning and return empty content
  (minimax/minimax-m3.1-flash, nvidia/nemotron-3.5-lightning).

FAILURE BEHAVIOUR:
  call_llm returns None on failure by default. Pass raise_on_failure=True to
  raise LLMUnavailableError with the underlying provider message instead —
  used by agents that must report *why* no output was produced.

TIMEOUT:
  120s read timeout per call. Covers NVIDIA free tier cold starts (~60-90s)
  with a safety margin, while still terminating if the API is truly hung.
  Timeout is set per-call on create() — this is more reliable than setting
  it on the client constructor, which the OpenAI SDK may override internally.
"""

import os
import re
import time
from typing import Optional

NVIDIA_BASE_URL_DEFAULT = "https://integrate.api.nvidia.com/v1"

# Default: Poolside Laguna XS 2.1 — code-specialised, 2-4s per explanation on
# the free tier. Override at runtime with the NVIDIA_MODEL env var.
NVIDIA_MODEL_DEFAULT = "poolside/laguna-xs-2.1"

# Tried in order when the primary model is unavailable or returns nothing.
# NVIDIA retires NIM models without notice, so a dead primary must degrade to
# a working model rather than silently producing zero explanations.
# Override at runtime with the comma-separated NVIDIA_MODEL_FALLBACKS env var.
NVIDIA_MODEL_FALLBACKS_DEFAULT = (
    "meta/llama-3.2-90b-vision-instruct",
)


class LLMUnavailableError(RuntimeError):
    """
    Raised by call_llm(raise_on_failure=True) when every configured model
    failed. The message carries the last provider error verbatim so callers
    can surface it in job results and reports.
    """


MAX_RETRIES        = 2     # fail fast: 2 attempts max
BASE_DELAY_SECONDS = 1.0

# Option B: 120s per-call read timeout.
# Covers NVIDIA cold starts without blocking indefinitely.
# Set per-call on create(), not on the client constructor.
PER_CALL_TIMEOUT_SECONDS = 120.0

# Inter-call delay to respect rate limits
INTER_CALL_DELAY_SECONDS = 2.0

_client = None


def sanitize_llm_output(content: Optional[str]) -> Optional[str]:
    """
    Sanitize raw LLM response by stripping chain-of-thought, reasoning tags,
    and conversational preambles.
    """
    if not content:
        return content

    text = content.strip()

    # 1. Strip XML thinking/thought blocks (e.g. <thought>...</thought>, <think>...</think>, <reasoning>...</reasoning>)
    text = re.sub(
        r"<(?:thought|think|reasoning|scratchpad)[^>]*>.*?</(?:thought|think|reasoning|scratchpad)>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # 2. Strip standalone unclosed/orphaned tags
    text = re.sub(r"</?(?:thought|think|reasoning|scratchpad)[^>]*>", "", text, flags=re.IGNORECASE)

    # 3. Strip markdown reasoning headers (e.g. "**Thinking Process:** ...", "### Thought: ...")
    text = re.sub(
        r"(?im)^\s*(?:#+\s*)?(?:\*{1,2}|_{1,2})?(?:thinking process|thought|reasoning|internal analysis|step-by-step analysis)(?:\*{1,2}|_{1,2})?:?.*?(?=\n\n|\Z)",
        "",
        text
    )

    # 4. Strip conversational intro preambles on the first line
    text = re.sub(
        r"(?im)^\s*(?:here(?:'s| is) (?:the|a) (?:technical |code )?explanation(?: of| for|:)?|sure,? here(?:'s| is) (?:the|a) (?:technical |code )?explanation(?: of| for|:)?|below is (?:the|a) (?:technical |code )?explanation(?: of| for|:)?).*?\n+",
        "",
        text
    )

    return text.strip()


def get_client():
    """
    Lazy-initialize the OpenAI client pointed at NVIDIA NIM on first call.
    No timeout on the client itself — timeout is applied per create() call.
    """
    global _client
    if _client is None:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai package not installed. Run: pip install openai"
            )

        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "NVIDIA_API_KEY is not set. "
                "Get a free API key at https://build.nvidia.com "
                "and add it to your .env file: NVIDIA_API_KEY=nvapi-..."
            )

        base_url = os.getenv("NVIDIA_BASE_URL", NVIDIA_BASE_URL_DEFAULT)

        _client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0
        )
        print(f"  [NVIDIA] Client initialised -> {base_url}")
        print(f"  [NVIDIA] Models : {' -> '.join(_configured_models())}")
        print(f"  [NVIDIA] Timeout: {PER_CALL_TIMEOUT_SECONDS}s per call")

    return _client


def _configured_models(explicit_model: Optional[str] = None) -> list:
    """
    Ordered list of models to attempt: the primary model, then fallbacks.

    Primary resolution order: explicit_model arg -> NVIDIA_MODEL env -> default.
    Fallbacks come from NVIDIA_MODEL_FALLBACKS (comma-separated) or the built-in
    tuple. Duplicates are collapsed so a misconfigured env cannot double latency.
    """
    primary = explicit_model or os.getenv("NVIDIA_MODEL") or NVIDIA_MODEL_DEFAULT

    raw_fallbacks = os.getenv("NVIDIA_MODEL_FALLBACKS")
    if raw_fallbacks is None:
        fallbacks = list(NVIDIA_MODEL_FALLBACKS_DEFAULT)
    else:
        fallbacks = [m.strip() for m in raw_fallbacks.split(",") if m.strip()]

    ordered = [primary]
    for candidate in fallbacks:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _is_model_unavailable(exc: Exception) -> bool:
    """
    True when the provider says the model itself does not exist or has been
    retired. These are permanent for the current process, so retrying the same
    model is pointless — move straight to the next fallback.
    """
    exc_type = type(exc).__name__.lower()
    exc_str = str(exc).lower()
    return (
        "notfound" in exc_type
        or "404" in exc_str
        or "410" in exc_str
        or "gone" in exc_str
        or "not found" in exc_str
        or "end of life" in exc_str
        or "does not exist" in exc_str
    )


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.1,
    max_tokens: int = 800,
    raise_on_failure: bool = False
) -> Optional[str]:
    """
    Call the NVIDIA NIM LLM with per-call timeout, exponential backoff, and a
    fallback chain across configured models.

    Returns the response text on success. On total failure, returns None — or
    raises LLMUnavailableError when raise_on_failure=True, so the caller can
    report the real provider error instead of silently producing nothing.

    Timeout is passed directly to create() — this is the only reliable
    way to apply it in the OpenAI SDK. Setting it on the client constructor
    can be overridden by the SDK's internal timeout wrapping.

    Retriable errors (same model): 429, 5xx, timeout.
    Non-retriable (skip to next model): 400, 401, 404, 410 — and empty output,
    which usually means a reasoning model spent the whole budget on hidden
    tokens.
    """
    client = get_client()
    models = _configured_models(model)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt}
    ]

    prompt_chars = len(system_prompt) + len(user_prompt)
    last_error = "no model produced output"

    for model_index, resolved_model in enumerate(models):
        if model_index > 0:
            print(
                f"  [NVIDIA] Switching to fallback model "
                f"{model_index}/{len(models) - 1}: {resolved_model}"
            )

        delay = BASE_DELAY_SECONDS

        for attempt in range(MAX_RETRIES):
            t_start = time.time()
            print(
                f"  [NVIDIA] -> attempt {attempt + 1}/{MAX_RETRIES}  "
                f"model={resolved_model}  "
                f"prompt={prompt_chars}chars  "
                f"timeout={PER_CALL_TIMEOUT_SECONDS}s"
            )

            try:
                response = client.chat.completions.create(
                    model=resolved_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=PER_CALL_TIMEOUT_SECONDS   # Option B: applied here
                )
                elapsed     = time.time() - t_start
                content     = response.choices[0].message.content
                finish      = getattr(response.choices[0], "finish_reason", "?")
                tokens_used = getattr(
                    getattr(response, 'usage', None), 'total_tokens', '?'
                )
                cleaned = sanitize_llm_output(content)

                if not cleaned:
                    # Empty content with finish_reason=length means the model
                    # burned the budget on hidden reasoning. Retrying the same
                    # model will do the same thing.
                    last_error = (
                        f"{resolved_model}: empty completion "
                        f"(finish_reason={finish}, tokens={tokens_used})"
                    )
                    print(
                        f"  [NVIDIA] [FAIL] Empty completion from {resolved_model} "
                        f"after {elapsed:.1f}s (finish_reason={finish}, "
                        f"tokens={tokens_used})"
                    )
                    break

                print(
                    f"  [NVIDIA] [OK] {elapsed:.1f}s  "
                    f"tokens={tokens_used}  "
                    f"response={len(cleaned or '')}chars  "
                    f"finish={finish}"
                )
                if model_index > 0:
                    print(
                        f"  [NVIDIA] [INFO] Answer produced by fallback model "
                        f"{resolved_model}; primary model is unavailable. "
                        f"Consider updating NVIDIA_MODEL."
                    )
                return cleaned

            except Exception as exc:
                elapsed   = time.time() - t_start
                exc_type  = type(exc).__name__
                exc_str   = str(exc).lower()

                if _is_model_unavailable(exc):
                    last_error = f"{resolved_model}: {exc_type}: {exc}"
                    print(
                        f"  [NVIDIA] [FAIL] Model unavailable: {exc_type}. "
                        f"Skipping remaining retries for {resolved_model}."
                    )
                    break

                is_timeout = (
                    "timeout"    in exc_type.lower()
                    or "timeout" in exc_str
                )
                is_rate_limit = (
                    "ratelimit"  in exc_type.lower()
                    or "rate_limit" in exc_type.lower()
                    or "429"        in exc_str
                    or "rate limit" in exc_str
                    or "too many"   in exc_str
                )
                is_server_error = (
                    "internalserver" in exc_type.lower()
                    or "500" in exc_str
                    or "502" in exc_str
                    or "503" in exc_str
                )
                is_retriable = is_timeout or is_rate_limit or is_server_error

                if is_timeout:
                    label = f"Timeout after {elapsed:.1f}s"
                elif is_rate_limit:
                    label = "Rate limit"
                elif is_server_error:
                    label = "Server error"
                else:
                    label = "Error"

                last_error = f"{resolved_model}: {exc_type}: {exc}"

                if is_retriable and attempt < MAX_RETRIES - 1:
                    print(
                        f"  [NVIDIA] [FAIL] {label} on attempt {attempt + 1} "
                        f"(after {elapsed:.1f}s). "
                        f"Retrying in {delay:.0f}s... | {exc_type}: {exc}"
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue

                print(
                    f"  [NVIDIA] [FAIL] {label} - giving up on "
                    f"{resolved_model} after {attempt + 1} attempt(s) "
                    f"({elapsed:.1f}s). {exc_type}: {exc}"
                )
                break

    print(f"  [NVIDIA] [FAIL] All {len(models)} configured model(s) failed. {last_error}")
    if raise_on_failure:
        raise LLMUnavailableError(last_error)
    return None


def sleep_between_calls(delay: float = INTER_CALL_DELAY_SECONDS) -> None:
    """Sleep between consecutive LLM calls to respect the rate limit."""
    time.sleep(delay)


def reset_client() -> None:
    """Reset the cached client. Used in tests."""
    global _client
    _client = None