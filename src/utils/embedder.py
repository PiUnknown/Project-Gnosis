"""
src/utils/embedder.py

NVIDIA NIM Serverless Embedding client for Project Gnosis.

Computes text and code embeddings via NVIDIA's hosted embedding endpoint
(OpenAI-compatible embeddings endpoint).

PUBLIC INTERFACE:
  embed_texts(texts: list) -> list[list[float]]
  embed_query(query: str)  -> list[float]
  reset_client()           -> None

CONFIGURATION:
  NVIDIA_API_KEY          (required) — from https://build.nvidia.com
  NVIDIA_BASE_URL         (optional) — defaults to https://integrate.api.nvidia.com/v1
  NVIDIA_EMBEDDING_MODEL  (optional) — defaults to nvidia/llama-nemotron-embed-vl-1b-v2
"""

import os
import time
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

NVIDIA_BASE_URL_DEFAULT = "https://integrate.api.nvidia.com/v1"
NVIDIA_EMBEDDING_MODEL_DEFAULT = "nvidia/llama-nemotron-embed-vl-1b-v2"

# Batching to respect API payload limits
BATCH_SIZE = 32
PER_CALL_TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0

# Default dimension for nvidia/llama-nemotron-embed-vl-1b-v2
EMBEDDING_DIM = 2048

_client = None


def get_client():
    """
    Lazy-initialize OpenAI client pointed at NVIDIA NIM embedding API.
    Uses the same pattern as src/utils/nvidia_client.py.
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
                "and add it to your environment: NVIDIA_API_KEY=nvapi-..."
            )

        base_url = os.getenv("NVIDIA_BASE_URL", NVIDIA_BASE_URL_DEFAULT)
        _client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            max_retries=0
        )
    return _client


def _call_embedding_api(texts: List[str], input_type: str = "passage") -> List[List[float]]:
    """
    Call NVIDIA NIM embedding API for a single batch of texts with retries and exponential backoff.
    """
    client = get_client()
    model_name = os.getenv("NVIDIA_EMBEDDING_MODEL", NVIDIA_EMBEDDING_MODEL_DEFAULT)
    delay = BASE_DELAY_SECONDS

    # Truncate overly long text snippets to prevent token limit overflow
    MAX_CHARS_PER_TEXT = 8000
    cleaned_texts = [
        (t[:MAX_CHARS_PER_TEXT] if isinstance(t, str) else str(t)[:MAX_CHARS_PER_TEXT]) or " "
        for t in texts
    ]

    for attempt in range(MAX_RETRIES):
        t_start = time.time()
        try:
            # Try with extra_body for NVIDIA models supporting input_type, fallback if unsupported
            try:
                response = client.embeddings.create(
                    input=cleaned_texts,
                    model=model_name,
                    extra_body={"input_type": input_type, "truncate": "END"},
                    timeout=PER_CALL_TIMEOUT_SECONDS
                )
            except Exception as exc:
                if "extra_body" in str(exc).lower() or "unexpected" in str(exc).lower():
                    response = client.embeddings.create(
                        input=cleaned_texts,
                        model=model_name,
                        timeout=PER_CALL_TIMEOUT_SECONDS
                    )
                else:
                    raise exc

            # Sort by index to preserve exact input ordering
            sorted_data = sorted(response.data, key=lambda x: x.index)
            embeddings = [item.embedding for item in sorted_data]
            return embeddings

        except Exception as exc:
            elapsed = time.time() - t_start
            exc_str = str(exc).lower()
            is_retriable = (
                "timeout" in exc_str
                or "429" in exc_str
                or "rate" in exc_str
                or "500" in exc_str
                or "502" in exc_str
                or "503" in exc_str
            )

            if is_retriable and attempt < MAX_RETRIES - 1:
                logger.warning(
                    f"[Embedder] Retryable error ({exc}) on attempt {attempt + 1}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay *= 2
                continue

            logger.error(f"[Embedder] Embedding API failed on attempt {attempt + 1}: {exc}")
            raise exc

    raise RuntimeError(f"[Embedder] Failed to generate embeddings after {MAX_RETRIES} attempts.")


def embed_texts(texts: list) -> list:
    """
    Embed a list of strings using NVIDIA's hosted embedding endpoint.
    Returns list[list[float]].

    Batches requests to BATCH_SIZE to respect API payload and token limits.
    Same length and ordering as input: texts[i] -> embeddings[i].
    """
    if not texts:
        return []

    all_embeddings = []
    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch = texts[batch_start:batch_start + BATCH_SIZE]
        current_batch = batch_start // BATCH_SIZE + 1

        print(
            f"\r  [Embedder] Batch {current_batch}/{total_batches} "
            f"({len(all_embeddings)}/{len(texts)} done)",
            end="", flush=True
        )

        batch_embeddings = _call_embedding_api(batch, input_type="passage")
        all_embeddings.extend(batch_embeddings)

    print()
    return all_embeddings


def embed_query(query: str) -> list:
    """
    Embed a single query string for retrieval using NVIDIA's hosted embedding endpoint.

    Uses the same model as embed_texts with input_type='query'.
    """
    if not query or not query.strip():
        dim = int(os.getenv("EMBEDDING_DIM", EMBEDDING_DIM))
        return [0.0] * dim

    embeddings = _call_embedding_api([query.strip()], input_type="query")
    if embeddings and len(embeddings) > 0:
        return embeddings[0]

    dim = int(os.getenv("EMBEDDING_DIM", EMBEDDING_DIM))
    return [0.0] * dim


def reset_client() -> None:
    """Reset the cached client. Used in tests."""
    global _client
    _client = None