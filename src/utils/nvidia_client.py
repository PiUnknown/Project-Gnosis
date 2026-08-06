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
  NVIDIA_MODEL     (optional) — defaults to meta/llama-3.3-70b-instruct

TIMEOUT DESIGN:
  The OpenAI SDK default timeout is 10 minutes. On Azure App Service, a
  blocked worker thread causes the health check to fail and the container
  to restart — silently, with no Python exception.

  We set explicit timeouts at the client level:
    connect : 15s  — time to establish TCP connection to NVIDIA
    read    : 90s  — time to receive the full response body
    write   : 15s  — time to send the request body
    pool    : 10s  — time to acquire a connection from the pool

  90s read covers slow NVIDIA responses on the free tier without blocking
  the Azure worker long enough to trigger a health-check restart (~230s).
  If NVIDIA does not respond within 90s, httpx raises ReadTimeout, which
  is caught and treated as a retriable error.
"""

import os
import time
from typing import Optional

NVIDIA_BASE_URL_DEFAULT = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL_DEFAULT    = "meta/llama-3.3-70b-instruct"

MAX_RETRIES          = 4
BASE_DELAY_SECONDS   = 1.0

# Inter-call delay — 2.0s gives comfortable margin under NVIDIA's 40 req/min
INTER_CALL_DELAY_SECONDS = 2.0

# Timeout values in seconds
_TIMEOUT_CONNECT = 15.0
_TIMEOUT_READ    = 90.0
_TIMEOUT_WRITE   = 15.0
_TIMEOUT_POOL    = 10.0

_client = None


def get_client():
    """
    Lazy-initialize the OpenAI client pointed at NVIDIA NIM on first call.

    WHY EXPLICIT TIMEOUT ON THE CLIENT:
    The OpenAI SDK default is httpx.Timeout(None) — no timeout at all.
    On Azure App Service, a thread blocked waiting for a network response
    causes the health check to eventually fail and the container to restart.
    No Python exception is raised. The process just disappears. Setting
    explicit timeouts converts silent hangs into catchable exceptions.
    """
    global _client
    if _client is None:
        try:
            import httpx
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

        timeout = httpx.Timeout(
            connect=_TIMEOUT_CONNECT,
            read=_TIMEOUT_READ,
            write=_TIMEOUT_WRITE,
            pool=_TIMEOUT_POOL
        )

        _client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout
        )
        print(f"  [NVIDIA] Client initialised → {base_url}")
        print(f"  [NVIDIA] Timeout: connect={_TIMEOUT_CONNECT}s  "
              f"read={_TIMEOUT_READ}s  write={_TIMEOUT_WRITE}s")

    return _client


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.1,
    max_tokens: int = 800
) -> Optional[str]:
    """
    Call the NVIDIA NIM LLM with explicit timeout and exponential backoff.

    Returns the response text on success, None if all retries fail.

    Retriable errors:
      - 429 Rate Limit Exceeded
      - 500 / 502 / 503 Server errors
      - httpx.TimeoutException (read/connect timeout — most common hang cause)

    Non-retriable errors (return None immediately):
      - 400 Bad Request
      - 401 Unauthorized
      - 404 Model not found
    """
    client         = get_client()
    resolved_model = model or os.getenv("NVIDIA_MODEL", NVIDIA_MODEL_DEFAULT)
    messages       = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt}
    ]

    prompt_chars = len(system_prompt) + len(user_prompt)

    delay      = BASE_DELAY_SECONDS
    last_error = None

    for attempt in range(MAX_RETRIES):
        t_start = time.time()
        print(
            f"  [NVIDIA] → attempt {attempt + 1}/{MAX_RETRIES}  "
            f"model={resolved_model}  "
            f"prompt={prompt_chars}chars  "
            f"max_tokens={max_tokens}"
        )

        try:
            response = client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            elapsed = time.time() - t_start
            content = response.choices[0].message.content
            tokens_used = getattr(
                getattr(response, 'usage', None), 'total_tokens', '?'
            )
            print(
                f"  [NVIDIA] ✓ {elapsed:.1f}s  "
                f"tokens={tokens_used}  "
                f"response={len(content or '')}chars"
            )
            return content

        except Exception as exc:
            elapsed    = time.time() - t_start
            exc_type   = type(exc).__name__
            exc_str    = str(exc).lower()

            is_timeout = (
                "timeout"   in exc_type.lower()
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
                    f"  [NVIDIA] ✗ {label} on attempt {attempt + 1} "
                    f"(after {elapsed:.1f}s). "
                    f"Retrying in {delay:.0f}s... | {exc_type}: {exc}"
                )
                time.sleep(delay)
                delay *= 2
                continue

            # Non-retriable or all retries exhausted
            print(
                f"  [NVIDIA] ✗ {label} — giving up after "
                f"{attempt + 1} attempt(s) ({elapsed:.1f}s). "
                f"{exc_type}: {exc}"
            )
            break

    return None


def sleep_between_calls(delay: float = INTER_CALL_DELAY_SECONDS) -> None:
    """Sleep between consecutive LLM calls to respect the rate limit."""
    print(f"  [NVIDIA] sleeping {delay}s between calls...")
    time.sleep(delay)


def reset_client() -> None:
    """Reset the cached client. Used in tests."""
    global _client
    _client = None