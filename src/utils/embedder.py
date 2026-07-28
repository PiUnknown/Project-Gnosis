"""
Embedding model wrapper.

Model: sentence-transformers/all-MiniLM-L6-v2
  - 384-dimensional vectors
  - Runs locally: no API calls, no cost, works offline
  - Fast on CPU (~0.5s per batch of 64 texts)
  - Strong general-purpose semantic similarity

Upgrade path to a code-specific model (v2):
  Change MODEL_NAME to "nomic-ai/nomic-embed-code" or
  "Salesforce/codet5p-110m-embedding". Everything else stays the same.
"""

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
BATCH_SIZE = 64

_model = None


def get_model():
    """
    Lazy-load the model on first call.

    WHY LAZY:
    Loading the model takes 1-3 seconds and ~80MB of RAM. If we loaded
    at import time, every `import embedder` in any test file would
    trigger this wait — even tests that don't use the embedder.
    Lazy loading defers the cost to the first actual embedding call.
    """
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            print(f"\n  [Embedder] Loading {MODEL_NAME}...")
            _model = SentenceTransformer(MODEL_NAME)
            print(f"  [Embedder] Ready. Dim={EMBEDDING_DIM}")
        except ImportError:
            raise ImportError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
    return _model


def embed_texts(texts: list) -> list:
    """
    Embed a list of strings. Returns list[list[float]].

    Batches to BATCH_SIZE to control memory usage.
    Shows progress for runs with many chunks.

    Same length as input: texts[i] → embeddings[i].
    """
    if not texts:
        return []

    model = get_model()
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

        # .encode() returns numpy array; .tolist() gives plain Python floats
        batch_embeddings = model.encode(batch, show_progress_bar=False)
        all_embeddings.extend(batch_embeddings.tolist())

    print()
    return all_embeddings


def embed_query(query: str) -> list:
    """
    Embed a single query string for retrieval.

    Uses the same model as embed_texts: cosine similarity is only
    meaningful when query and documents live in the same vector space.
    """
    if not query.strip():
        return [0.0] * EMBEDDING_DIM

    model = get_model()
    embedding = model.encode([query], show_progress_bar=False)
    return embedding[0].tolist()