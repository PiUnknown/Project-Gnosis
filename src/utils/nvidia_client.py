"""
src/utils/nvidia_client.py

NVIDIA NIM Serverless Inference client for Project Gnosis.

PUBLIC INTERFACE:
  call_llm(system_prompt, user_prompt, ...) -> Optional[str]
  sleep_between_calls(delay)               -> None
  reset_client()                           -> None

CONFIGURATION:
  NVIDIA_API_KEY   (required) — from https://build.nvidia.com
  NVIDIA_BASE_URL  (optional) — defaults to NVIDIA NIM serverless endpoint
  NVIDIA_MODEL     (optional) — overrides NVIDIA_MODEL_DEFAULT at runtime

MODEL CHOICE:
  Default: meta/llama-3.1-8b-instruct
  The 8B model responds in 5-15s on NVIDIA NIM free tier.
  The 70B model responds in 60-270s on cold starts.
  For code explanation the quality difference is small — the 70B advantage
  is in nuanced multi-step reasoning, not in describing what a function does.
  Switch to meta/llama-3.3-70b-instruct via NVIDIA_MODEL env var if needed.

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

# Default: Meta Llama 3.2 11B Vision Instruct (fast, direct, robust architecture explanations).
# Override at runtime with NVIDIA_MODEL env var if needed.
NVIDIA_MODEL_DEFAULT = "meta/llama-3.2-11b-vision-instruct"

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
        print(f"  [NVIDIA] Model  : {os.getenv('NVIDIA_MODEL', NVIDIA_MODEL_DEFAULT)}")
        print(f"  [NVIDIA] Timeout: {PER_CALL_TIMEOUT_SECONDS}s per call")

    return _client


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.1,
    max_tokens: int = 800
) -> Optional[str]:
    """
    Call the NVIDIA NIM LLM with per-call timeout and exponential backoff.

    Returns the response text on success, None if all retries fail.

    Timeout is passed directly to create() — this is the only reliable
    way to apply it in the OpenAI SDK. Setting it on the client constructor
    can be overridden by the SDK's internal timeout wrapping.

    Retriable errors: 429, 5xx, timeout.
    Non-retriable: 400, 401, 404.
    """
    client         = get_client()
    resolved_model = model or os.getenv("NVIDIA_MODEL", NVIDIA_MODEL_DEFAULT)
    messages       = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt}
    ]

    prompt_chars = len(system_prompt) + len(user_prompt)
    delay        = BASE_DELAY_SECONDS
    last_error   = None

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
            tokens_used = getattr(
                getattr(response, 'usage', None), 'total_tokens', '?'
            )
            cleaned = sanitize_llm_output(content)
            print(
                f"  [NVIDIA] [OK] {elapsed:.1f}s  "
                f"tokens={tokens_used}  "
                f"response={len(cleaned or '')}chars"
            )
            return cleaned

        except Exception as exc:
            elapsed   = time.time() - t_start
            exc_type  = type(exc).__name__
            exc_str   = str(exc).lower()

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

            last_error = exc

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
                f"  [NVIDIA] [FAIL] {label} - giving up after "
                f"{attempt + 1} attempt(s) ({elapsed:.1f}s). "
                f"{exc_type}: {exc}"
            )
            break

    return None


def sleep_between_calls(delay: float = INTER_CALL_DELAY_SECONDS) -> None:
    """Sleep between consecutive LLM calls to respect the rate limit."""
    time.sleep(delay)


def reset_client() -> None:
    """Reset the cached client. Used in tests."""
    global _client
    _client = None