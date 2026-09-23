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
  NVIDIA_API_KEY (required) — from https://build.nvidia.com /
  Azure App Service Application Settings (Configuration → Environment variables)
"""

import os
import time
from typing import Optional

from openai import OpenAI

MODEL_NAME = "nvidia/nv-embed-v1"
EMBEDDING_DIM = 4096
BATCH_SIZE = 50
INTER_BATCH_DELAY = 0.5

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

_client = None


def get_client() -> Optional[OpenAI]:
    """
    Lazy-initialize OpenAI client pointed at NVIDIA NIM embedding API.
    Uses the same pattern as src/utils/nvidia_client.py.
    """
    global _client
    if _client is None:
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "NVIDIA_API_KEY is not set. "
                "Set it in Azure App Service Application Settings "
                "(Configuration → Environment variables) or your local "
                "environment: NVIDIA_API_KEY=nvapi-..."
            )
        _client = OpenAI(api_key=api_key, base_url=NVIDIA_BASE_URL)
    return _client


def embed_texts(texts: list) -> list:
    """
    Embed a list of strings (code chunks) using NVIDIA's nv-embed-v1 endpoint.
    Returns list[list[float]] of the same length and order as input.
    Uses input_type="passage" for storage/indexing.
    """
    if not texts:
        return []

    client = get_client()
    all_embeddings = []
    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num in range(1, total_batches + 1):
        start = (batch_num - 1) * BATCH_SIZE
        batch = texts[start:start + BATCH_SIZE]

        try:
            response = client.embeddings.create(
                model=MODEL_NAME,
                input=batch,
                encoding_format="float",
                extra_body={"input_type": "passage", "truncate": "END"}
            )
        except Exception as exc:
            print(
                f"\n  [Embedder] Batch {batch_num} failed: {exc}. "
                f"Retrying once..."
            )
            time.sleep(2)
            try:
                response = client.embeddings.create(
                    model=MODEL_NAME,
                    input=batch,
                    encoding_format="float",
                    extra_body={"input_type": "passage", "truncate": "END"}
                )
            except Exception:
                raise

        # Sort by index to guarantee embeddings[i] aligns with texts[i]
        # even if the API returns items out of order.
        sorted_data = sorted(response.data, key=lambda x: x.index)
        all_embeddings.extend(item.embedding for item in sorted_data)

        print(
            f"\r  [Embedder] Batch {batch_num}/{total_batches} "
            f"({len(all_embeddings)}/{len(texts)} chunks embedded)",
            end="", flush=True
        )

        if batch_num < total_batches:
            time.sleep(INTER_BATCH_DELAY)

    print()
    return all_embeddings


def embed_query(query: str) -> list:
    """
    Embed a single query string for retrieval using NVIDIA's nv-embed-v1 endpoint.

    Uses input_type="query" (asymmetric model — must differ from passage).
    Returns [0.0] * EMBEDDING_DIM on empty input or API failure as a safe
    fallback so a transient error never crashes the pipeline.
    """
    if not query or not query.strip():
        return [0.0] * EMBEDDING_DIM

    client = get_client()
    try:
        response = client.embeddings.create(
            model=MODEL_NAME,
            input=[query],
            encoding_format="float",
            extra_body={"input_type": "query", "truncate": "END"}
        )
        return response.data[0].embedding
    except Exception as exc:
        print(f"  [Embedder] Query embedding failed: {exc}")
        return [0.0] * EMBEDDING_DIM


def reset_client() -> None:
    """Reset the cached client. Used in tests."""
    global _client
    _client = None
