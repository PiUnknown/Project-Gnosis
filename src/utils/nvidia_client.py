"""
src/utils/nvidia_client.py

NVIDIA NIM Serverless Inference client for Project Gnosis.

Replaces src/utils/groq_client.py as the sole LLM provider.
Provides the same public interface so Agent 6 (Explainability) requires
only an import change — no prompt, logic, or behavior changes.

WHY NVIDIA NIM:
NVIDIA NIM exposes serverless LLM inference via an OpenAI-compatible
REST API. The same openai Python SDK used for OpenAI models works here
with a different base_url and API key. No proprietary SDK required.
Model quality is equivalent (same llama-3.3-70b family), with more
generous rate limits than the Groq free tier.

PUBLIC INTERFACE (unchanged from groq_client.py):
  call_llm(system_prompt, user_prompt, ...) -> Optional[str]
  sleep_between_calls(delay)                -> None
  reset_client()                            -> None

CONFIGURATION:
  NVIDIA_API_KEY   (required) — from https://build.nvidia.com
  NVIDIA_BASE_URL  (optional) — defaults to NVIDIA NIM serverless endpoint
  NVIDIA_MODEL     (optional) — defaults to meta/llama-3.3-70b-instruct

RATE LIMITS (NVIDIA NIM free tier):
  40 requests/minute per model
  Retry on 429 with exponential backoff, same as before.
  Inter-call delay reduced to 1.0s (Groq needed 2.5s; NVIDIA is more lenient).
"""

import os
import time
from typing import Optional

# NVIDIA NIM serverless inference endpoint (OpenAI-compatible)
NVIDIA_BASE_URL_DEFAULT = "https://integrate.api.nvidia.com/v1"

# Model: NVIDIA-hosted llama-3.3-70b-instruct
# Same model family as the previous llama-3.3-70b-versatile on Groq.
# "instruct" tuning is equivalent for our use case (following instructions
# to generate technical documentation).
NVIDIA_MODEL_DEFAULT = "meta/llama-3.3-70b-instruct"

# Retry configuration (same policy as groq_client.py)
MAX_RETRIES = 4
BASE_DELAY_SECONDS = 1.0    # First retry: 1s → 2s → 4s → 8s

# Inter-call delay to respect 40 req/min limit.
# 60s / 40 req = 1.5s minimum. 2.0s gives a comfortable safety margin.
# This is lower than the 2.5s used with Groq — NVIDIA's limit is more generous.
INTER_CALL_DELAY_SECONDS = 2.0

_client = None


def get_client():
    """
    Lazy-initialize the OpenAI client pointed at NVIDIA NIM on first call.

    WHY LAZY:
    Importing this module does not start a network connection or validate
    the API key. The cost is paid only when the first LLM call happens.
    Tests that mock call_llm() never need a real key or network.

    WHY openai SDK:
    NVIDIA NIM is OpenAI-API-compatible. The openai package supports any
    OpenAI-compatible endpoint via base_url parameter. No NVIDIA-specific
    SDK is required or maintained.
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
            api_key=api_key
        )
    return _client


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = None,
    temperature: float = 0.1,
    max_tokens: int = 800
) -> Optional[str]:
    """
    Call the NVIDIA NIM LLM with exponential backoff retry.

    Returns the response text on success, None if all retries failed.

    Retriable errors (backoff and retry):
      - 429 Rate Limit Exceeded
      - 500 / 502 / 503 Server errors

    Non-retriable errors (return None immediately):
      - 400 Bad Request (prompt too long, invalid model)
      - 401 Unauthorized (bad API key)
      - 404 Model not found

    The model parameter defaults to NVIDIA_MODEL env var or
    NVIDIA_MODEL_DEFAULT. Passing it explicitly allows per-call
    model overrides without changing global state.
    """
    client = get_client()

    resolved_model = (
        model
        or os.getenv("NVIDIA_MODEL", NVIDIA_MODEL_DEFAULT)
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt}
    ]

    delay      = BASE_DELAY_SECONDS
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=resolved_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=30.0
            )
            return response.choices[0].message.content

        except Exception as exc:
            last_error = exc
            exc_type   = type(exc).__name__.lower()
            exc_str    = str(exc).lower()

            is_rate_limit = (
                "ratelimit"  in exc_type
                or "rate_limit" in exc_type
                or "429"        in exc_str
                or "rate limit" in exc_str
                or "too many"   in exc_str
            )
            is_server_error = (
                "internalserver" in exc_type
                or "500" in exc_str
                or "502" in exc_str
                or "503" in exc_str
            )
            is_timeout = (
                "timeout" in exc_type
                or "timeout" in exc_str
            )
            is_retriable = is_rate_limit or is_server_error or is_timeout

            if is_retriable and attempt < MAX_RETRIES - 1:
                if is_rate_limit:
                    label = "Rate limit"
                elif is_timeout:
                    label = "Timeout"
                else:
                    label = "Server error"
                print(
                    f"\n  [NVIDIA] {label} on attempt {attempt + 1}. "
                    f"Retrying in {delay:.0f}s..."
                )
                time.sleep(delay)
                delay *= 2
                continue

            # Non-retriable or exhausted retries
            break

    print(f"\n  [NVIDIA] Failed: {type(last_error).__name__}: {last_error}")
    return None


def sleep_between_calls(delay: float = INTER_CALL_DELAY_SECONDS) -> None:
    """
    Sleep between consecutive LLM calls to respect the rate limit.

    Call this AFTER each successful call, BEFORE starting the next.
    Skip after the final call in a batch (saves unnecessary waiting).
    """
    time.sleep(delay)


def reset_client() -> None:
    """
    Reset the cached client. Used in tests to ensure clean state
    between test runs without leaking client state across tests.
    """
    global _client
    _client = None