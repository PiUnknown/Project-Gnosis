"""
Agent 5: Code RAG Agent

Reads from state:  symbol_tables, raw_contents, complexity_scores,
                   file_manifest, owner, repo_name
Writes to state:   chroma_collection_name

Steps:
1. Derive ChromaDB collection name from repo identity
2. Delete existing collection if present (ensures clean re-runs)
3. Produce all chunks from all chunkable files
4. Embed chunks in batches
5. Store in ChromaDB with metadata
6. Write collection name to state
"""
import os

from src.state import ArchaeonState
from src.utils.chunker import make_chunks
from src.utils.embedder import embed_texts
from src.utils.retriever import make_collection_name, DEFAULT_CHROMA_DB_PATH

CHUNKABLE_LANGUAGES = frozenset({'Python', 'JavaScript', 'TypeScript'})
CHROMA_BATCH_SIZE = 500   # chunks per ChromaDB add() call


def run(state: ArchaeonState) -> ArchaeonState:
    print(f"\n[Agent 5: Code RAG]")

    try:
        import chromadb
    except ImportError:
        raise ImportError("chromadb not installed. Run: pip install chromadb")

    # ----------------------------------------------------------------
    # Step 1: Setup ChromaDB collection
    # ----------------------------------------------------------------
    collection_name = make_collection_name(state.owner, state.repo_name, state.job_id)
    chroma_path = DEFAULT_CHROMA_DB_PATH
    print(f"  Collection name  : {collection_name}")
    print(f"  ChromaDB path    : {chroma_path}")

    os.makedirs(chroma_path, exist_ok=True)
    client = chromadb.PersistentClient(path=chroma_path)

    # Delete and recreate on re-runs.
    # WHY DELETE INSTEAD OF UPSERT:
    # A re-run may reflect a changed filter list or file cap. Upserting
    # would leave stale chunks from files no longer in the manifest.
    # Deleting guarantees the collection exactly reflects this run.
    # Cost: re-embedding all chunks. Acceptable at this scale.
    try:
        client.delete_collection(name=collection_name)
        print(f"  Existing collection deleted (re-run)")
    except Exception:
        pass

    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
        # cosine similarity for text: measures angle between vectors,
        # not magnitude. Two paraphrases score high even if one is long.
    )

    # ----------------------------------------------------------------
    # Step 2: Produce chunks
    # ----------------------------------------------------------------
    print(f"\n  Chunking files...")

    all_chunks = []
    total_files = len(state.symbol_tables)
    skipped = 0

    for idx, (file_path, symbol_table) in enumerate(state.symbol_tables.items()):
        print(f"\r  Chunking: {idx + 1}/{total_files}", end="", flush=True)

        lang = symbol_table.language

        if lang not in CHUNKABLE_LANGUAGES:
            skipped += 1
            continue

        if symbol_table.parse_error:
            # Don't chunk files with syntax errors.
            # Malformed source produces malformed chunks.
            # Bad chunks add noise to the vector space and lower
            # retrieval precision for all future queries.
            skipped += 1
            continue

        raw_content = state.raw_contents.get(file_path, "")
        if not raw_content:
            skipped += 1
            continue

        complexity_score = state.complexity_scores.get(file_path)

        chunks = make_chunks(
            file_path=file_path,
            language=lang,
            raw_content=raw_content,
            symbol_table=symbol_table,
            complexity_score=complexity_score
        )
        all_chunks.extend(chunks)

    print()
    print(f"  Files chunked    : {total_files - skipped}")
    print(f"  Files skipped    : {skipped}")
    print(f"  Total chunks     : {len(all_chunks)}")

    if not all_chunks:
        print("  [WARNING] No chunks produced.")
        state.chroma_collection_name = collection_name
        return state

    # ----------------------------------------------------------------
    # Step 3: Embed
    # ----------------------------------------------------------------
    print(f"\n  Embedding chunks...")
    texts = [chunk.content for chunk in all_chunks]
    embeddings = embed_texts(texts)

    # ----------------------------------------------------------------
    # Step 4: Store in ChromaDB
    # ----------------------------------------------------------------
    print(f"\n  Storing in ChromaDB...")
    total_stored = 0

    for batch_start in range(0, len(all_chunks), CHROMA_BATCH_SIZE):
        batch_chunks = all_chunks[batch_start:batch_start + CHROMA_BATCH_SIZE]
        batch_embeddings = embeddings[batch_start:batch_start + CHROMA_BATCH_SIZE]

        collection.add(
            ids=[c.chunk_id for c in batch_chunks],
            embeddings=batch_embeddings,
            documents=[c.content for c in batch_chunks],
            metadatas=[_to_metadata(c) for c in batch_chunks]
        )
        total_stored += len(batch_chunks)
        print(f"\r  Stored: {total_stored}/{len(all_chunks)}", end="", flush=True)

    print()

    # ----------------------------------------------------------------
    # Step 5: Write to state
    # ----------------------------------------------------------------
    state.chroma_collection_name = collection_name
    _print_summary(all_chunks, total_stored)
    return state


def _to_metadata(chunk) -> dict:
    """
    Convert CodeChunk to ChromaDB metadata dict.

    ChromaDB metadata values must be str, int, float, or bool. Never None.
    Sentinel values for None fields:
      complexity  → -1.0     (all real complexity scores are >= 1.0)
      risk_level  → "UNKNOWN"
    These sentinels are converted back to None in retriever._parse_results.
    """
    return {
        "file_path": chunk.file_path,
        "symbol_name": chunk.symbol_name,
        "symbol_type": chunk.symbol_type,
        "language": chunk.language,
        "line_start": chunk.line_start,
        "line_end": chunk.line_end,
        "complexity": float(chunk.complexity) if chunk.complexity is not None else -1.0,
        "risk_level": chunk.risk_level if chunk.risk_level is not None else "UNKNOWN"
    }


def _print_summary(all_chunks: list, stored: int) -> None:
    type_dist: dict = {}
    lang_dist: dict = {}

    for c in all_chunks:
        type_dist[c.symbol_type] = type_dist.get(c.symbol_type, 0) + 1
        lang_dist[c.language] = lang_dist.get(c.language, 0) + 1

    print(f"\n[Agent 5: Code RAG] Done")
    print(f"  Total stored     : {stored}")

    print(f"\n  By chunk type:")
    for ctype, count in sorted(type_dist.items(), key=lambda x: -x[1]):
        bar = "█" * min(count // max(1, stored // 40), 25)
        print(f"    {ctype:<12} {bar} {count}")

    print(f"\n  By language:")
    for lang, count in sorted(lang_dist.items(), key=lambda x: -x[1]):
        print(f"    {lang:<15} {count}")