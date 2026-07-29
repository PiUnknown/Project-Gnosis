"""
Groq API wrapper with retry logic and rate limit handling.

Responsibilities:
  - Lazy-initialize the Groq client (avoids import-time overhead)
  - Wrap chat completion in exponential backoff retry
  - Provide a sleep helper for inter-call rate limiting

WHY A WRAPPER INSTEAD OF CALLING GROQ DIRECTLY IN THE AGENT:
The agent should not know which LLM provider is being used. If we
switch from Groq to Anthropic or a local Ollama model, we change
this file, not the agent. The agent calls call_llm() — it does not
know or care what happens inside.

RATE LIMITS (Groq free tier as of 2024):
  30 requests/minute
  100,000 tokens/minute
  6,000 requests/day

Our usage: ~20 calls per pipeline run, ~3000 tokens per call.
Well within limits if we space calls 2.5 seconds apart.
"""

import os
import time
from typing import Optional

GROQ_MODEL = "llama-3.3-70b-versatile"

# Retry configuration
MAX_RETRIES = 4
BASE_DELAY_SECONDS = 1.0    # First retry: 1s. Then 2s, 4s, 8s.

# Inter-call delay to stay under 30 req/min.
# 60s / 30 req = 2s minimum. We use 2.5s for safety margin.
INTER_CALL_DELAY_SECONDS = 2.5

_client = None


def get_client():
    """
    Lazy-initialize the Groq client on first call.

    WHY LAZY:
    Importing this module does not start a network connection or validate
    the API key. The cost is paid only when the first LLM call happens.
    Tests that mock call_llm() never need a real key or network.
    """
    global _client
    if _client is None:
        try:
            from groq import Groq
        except ImportError:
            raise ImportError(
                "groq not installed. Run: pip install groq"
            )

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com "
                "and add it to your .env file: GROQ_API_KEY=gsk_..."
            )

        _client = Groq(api_key=api_key)
    return _client


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = GROQ_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 800
) -> Optional[str]:
    """
    Call the Groq LLM with exponential backoff retry.

    Returns the response text on success, None if all retries failed.

    Retriable errors (backoff and retry):
      - 429 Rate Limit Exceeded
      - 500 / 502 / 503 Server errors

    Non-retriable errors (return None immediately):
      - 400 Bad Request (prompt too long, invalid model)
      - 401 Unauthorized (bad API key)
      - 404 Model not found
      - Network errors (after max retries)
    """
    client = get_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt}
    ]

    delay = BASE_DELAY_SECONDS
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content

        except Exception as exc:
            last_error = exc
            exc_type  = type(exc).__name__.lower()
            exc_str   = str(exc).lower()

            is_rate_limit = (
                "ratelimit" in exc_type
                or "rate_limit" in exc_type
                or "429" in exc_str
                or "rate limit" in exc_str
            )
            is_server_error = (
                "internalserver" in exc_type
                or "500" in exc_str
                or "502" in exc_str
                or "503" in exc_str
            )
            is_retriable = is_rate_limit or is_server_error

            if is_retriable and attempt < MAX_RETRIES - 1:
                label = "Rate limit" if is_rate_limit else "Server error"
                print(
                    f"\n  [Groq] {label} on attempt {attempt + 1}. "
                    f"Retrying in {delay:.0f}s..."
                )
                time.sleep(delay)
                delay *= 2
                continue

            # Non-retriable or exhausted all retries — stop immediately
            break

    print(f"\n  [Groq] Failed: {type(last_error).__name__}: {last_error}")
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
    Reset the cached client. Used in tests to ensure a clean state
    between test runs without leaking client state across tests.
    """
    global _client
    _client = None