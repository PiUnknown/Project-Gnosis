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
import re
import time
import concurrent.futures
from typing import Optional

from openai import OpenAI

MODEL_NAME = "nvidia/nemotron-3-embed-1b"
EMBEDDING_DIM = 2048
BATCH_SIZE = 50
INTER_BATCH_DELAY = 0.5
DEFAULT_MAX_CONCURRENT_BATCHES = 2
MAX_CONCURRENT_BATCHES = 4

# NVIDIA NIM's text-embedding endpoint inspects the input for inline image
# data and rejects the entire request when it finds one:
#
#   400 invalid_request_error: image inputs require VLM serving to be
#   enabled on this server
#
# Code chunks routinely contain `data:image/...;base64,...` payloads (inline
# SVG/PNG assets in JS/TS/JSX, CSS-in-JS, Rust templates, test fixtures).
# A base64 blob has no value for a code embedding, so replace it with a short
# marker before the request. The original text is still stored in ChromaDB as
# the chunk document; only the embedding input is sanitized.
_IMAGE_DATA_URI_RE = re.compile(
    r"data:image/[A-Za-z0-9.+-]+"
    r"(?:;[A-Za-z0-9=.+-]+)*"
    r"(?:;base64)?"
    r",[^\s\"'`)<>\]]*",
    re.IGNORECASE,
)
IMAGE_DATA_PLACEHOLDER = "[inline image data omitted]"

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


def sanitize_for_embedding(text: str) -> str:
    """
    Replace inline image data URIs with a short marker.

    The hosted embedding model is text-only. Its server treats any string
    containing a `data:image/...` URI as a multimodal request and rejects the
    whole batch with HTTP 400. The URI itself carries no useful code meaning,
    so stripping it keeps the surrounding code embeddable.
    """
    if not isinstance(text, str) or "data:image/" not in text.lower():
        return text
    return _IMAGE_DATA_URI_RE.sub(IMAGE_DATA_PLACEHOLDER, text)


def _create_embeddings(client, inputs: list, input_type: str):
    """Issue one embeddings request with the settings this model expects."""
    return client.embeddings.create(
        model=MODEL_NAME,
        input=inputs,
        encoding_format="float",
        extra_body={"input_type": input_type, "truncate": "END"}
    )


def _embed_batch_item_by_item(client, batch: list, batch_num: int, exc: Exception) -> list:
    """
    Last-resort path after a 400 that survives sanitizing.

    Embeds each item on its own so a single unsupported chunk cannot fail the
    whole pipeline. Items the server still refuses are embedded from a neutral
    placeholder so the returned vector list stays aligned with the input list.
    """
    if getattr(exc, "status_code", None) != 400 and "400" not in str(exc):
        raise exc

    print(
        f"\n  [Embedder] Batch {batch_num} rejected even after sanitizing "
        f"({exc}); retrying item by item."
    )
    embeddings = []
    for offset, text in enumerate(batch):
        try:
            response = _create_embeddings(client, [text], "passage")
        except Exception as item_exc:
            print(
                f"\n  [Embedder] Batch {batch_num} item {offset} could not be "
                f"embedded ({item_exc}); using placeholder vector."
            )
            response = _create_embeddings(
                client, [IMAGE_DATA_PLACEHOLDER], "passage"
            )
        embeddings.append(response.data[0].embedding)
        time.sleep(0.05)
    return embeddings


def _embed_batch_with_retry(client, batch: list, batch_num: int) -> list:
    """Embed one batch, retaining retry and single-item fallback behavior."""
    try:
        response = _create_embeddings(client, batch, "passage")
    except Exception as exc:
        print(
            f"\n  [Embedder] Batch {batch_num} failed: {exc}. "
            "Retrying once..."
        )
        time.sleep(2)
        try:
            response = _create_embeddings(client, batch, "passage")
        except Exception as retry_exc:
            return _embed_batch_item_by_item(
                client, batch, batch_num, retry_exc
            )

    sorted_data = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]


def embed_texts(texts: list) -> list:
    """
    Embed a list of strings (code chunks) using NVIDIA's nemotron-3-embed-1b endpoint.
    Returns list[list[float]] of the same length and order as input.
    Uses input_type="passage" for storage/indexing.
    """
    if not texts:
        return []

    client = get_client()
    total_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE
    try:
        max_concurrent = int(
            os.getenv(
                "NVIDIA_EMBED_MAX_CONCURRENCY",
                str(DEFAULT_MAX_CONCURRENT_BATCHES),
            )
        )
    except ValueError:
        max_concurrent = DEFAULT_MAX_CONCURRENT_BATCHES
    max_concurrent = max(1, min(MAX_CONCURRENT_BATCHES, max_concurrent, total_batches))

    batches = [
        [sanitize_for_embedding(text) for text in texts[start:start + BATCH_SIZE]]
        for start in range(0, len(texts), BATCH_SIZE)
    ]
    embeddings_by_batch = [None] * total_batches
    futures = {}
    completed_chunks = 0

    # Keep requests slightly paced while allowing a small number to overlap.
    # This shortens wall time for network-bound batches without creating an
    # unbounded burst against the hosted embedding service.
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_concurrent
    ) as executor:
        for index, batch in enumerate(batches):
            future = executor.submit(
                _embed_batch_with_retry,
                client,
                batch,
                index + 1,
            )
            futures[future] = index
            if index + 1 < total_batches:
                time.sleep(INTER_BATCH_DELAY)

        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            batch_embeddings = future.result()
            embeddings_by_batch[index] = batch_embeddings
            completed_chunks += len(batch_embeddings)
            print(
                f"\r  [Embedder] Batch {index + 1}/{total_batches} complete "
                f"({completed_chunks}/{len(texts)} chunks embedded)",
                end="",
                flush=True,
            )

    all_embeddings = [
        embedding
        for batch_embeddings in embeddings_by_batch
        for embedding in batch_embeddings
    ]

    print()
    return all_embeddings


def embed_query(query: str) -> list:
    """
    Embed a single query string for retrieval using NVIDIA's nemotron-3-embed-1b endpoint.

    Uses input_type="query" (asymmetric model — must differ from passage).
    Returns [0.0] * EMBEDDING_DIM on empty input or API failure as a safe
    fallback so a transient error never crashes the pipeline.
    """
    if not query or not query.strip():
        return [0.0] * EMBEDDING_DIM

    client = get_client()
    try:
        response = _create_embeddings(
            client, [sanitize_for_embedding(query)], "query"
        )
        return response.data[0].embedding
    except Exception as exc:
        print(f"  [Embedder] Query embedding failed: {exc}")
        return [0.0] * EMBEDDING_DIM


def reset_client() -> None:
    """Reset the cached client. Used in tests."""
    global _client
    _client = None
