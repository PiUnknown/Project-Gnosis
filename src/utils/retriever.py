"""
ChromaDB retrieval interface for Agent 6.

Two responsibilities:
  1. make_collection_name: derives a valid ChromaDB name from owner/repo
  2. CodeRetriever: wraps ChromaDB query API with a clean interface

Agent 5 writes to ChromaDB.
Agent 6 reads via CodeRetriever.
The two agents never import each other. They share state (collection_name)
and disk (the ChromaDB files). The retriever is the contract between them.
"""
import re
from typing import Optional

_INVALID_CHARS = re.compile(r'[^a-zA-Z0-9_-]')
_COLLECTION_NAME_MAX = 63
DEFAULT_CHROMA_DB_PATH = "./chroma_db"


# -----------------------------------------------------------------------
# Collection name
# -----------------------------------------------------------------------

def make_collection_name(owner: str, repo: str) -> str:
    """
    Derive a valid ChromaDB collection name from owner/repo.

    ChromaDB constraints:
      - 3 to 63 characters
      - Alphanumeric, underscore, hyphen only
      - Must start and end with alphanumeric

    "tiangolo/fastapi"       → "gnosis_tiangolo_fastapi"
    "my-org/my.repo.v2"     → "gnosis_my-org_my_repo_v2"
    """
    raw = f"gnosis_{owner}_{repo}"
    sanitized = _INVALID_CHARS.sub('_', raw)

    if len(sanitized) > _COLLECTION_NAME_MAX:
        sanitized = sanitized[:_COLLECTION_NAME_MAX]

    sanitized = sanitized.strip('_-')

    if len(sanitized) < 3:
        sanitized = f"gno_{sanitized}"

    return sanitized


# -----------------------------------------------------------------------
# Retriever
# -----------------------------------------------------------------------

class CodeRetriever:
    """
    Query interface over a ChromaDB collection.

    WHY A CLASS AND NOT A FUNCTION:
    The ChromaDB client and collection objects are created once and
    reused across multiple queries in Agent 6. If we reconnected per
    query, we would pay filesystem and connection overhead on every
    LLM context assembly. A class holds the connection for the full
    lifetime of Agent 6's run.

    Testing: pass _client to inject an ephemeral ChromaDB client
    instead of creating a persistent one. The leading underscore
    signals this parameter is for testing only.
    """

    def __init__(
        self,
        collection_name: str,
        chroma_db_path: str = DEFAULT_CHROMA_DB_PATH,
        _client=None
    ):
        try:
            import chromadb
        except ImportError:
            raise ImportError(
                "chromadb not installed. Run: pip install chromadb"
            )

        self._client = _client or chromadb.PersistentClient(path=chroma_db_path)
        self.collection_name = collection_name

        try:
            self._collection = self._client.get_collection(name=collection_name)
        except Exception:
            raise ValueError(
                f"ChromaDB collection '{collection_name}' not found. "
                f"Run Agent 5 (code_rag) before Agent 6."
            )

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        language: Optional[str] = None,
        symbol_type: Optional[str] = None,
        file_path: Optional[str] = None,
        risk_level: Optional[str] = None,
        raw_filter: Optional[dict] = None
    ) -> list:
        """
        Semantic search over the code vector store.

        Args:
            query_text:  Natural language or code query string
            n_results:   Max chunks to return
            language:    Filter to "Python", "JavaScript", etc.
            symbol_type: Filter to "function", "class", or "module"
            file_path:   Filter to chunks from one specific file
            risk_level:  Filter to "CRITICAL", "HIGH", "MEDIUM", "LOW"
            raw_filter:  Override all above: pass a raw ChromaDB 'where' dict

        Returns:
            list of dicts with keys: content, file_path, symbol_name,
            symbol_type, language, line_start, line_end, complexity,
            risk_level, distance (lower = more similar)

        Returns [] on any failure. Agent 6 must handle empty results.
        """
        if not query_text.strip():
            return []

        total = self.count()
        if total == 0:
            return []

        try:
            from src.utils.embedder import embed_query
            query_embedding = embed_query(query_text)
        except Exception:
            return []

        where = raw_filter or _build_where_filter(
            language=language,
            symbol_type=symbol_type,
            file_path=file_path,
            risk_level=risk_level
        )

        try:
            kwargs = {
                "query_embeddings": [query_embedding],
                "n_results": min(n_results, total),
                "include": ["documents", "metadatas", "distances"]
            }
            if where:
                kwargs["where"] = where

            results = self._collection.query(**kwargs)
        except Exception as exc:
            print(f"\n  [Retriever] Query failed: {exc}")
            return []

        return _parse_results(results)

    def get_file_chunks(self, file_path: str) -> list:
        """
        Return all chunks belonging to one specific file.
        Used by Agent 6 to assemble full file context before LLM call.

        WHY get() INSTEAD OF query():
        get() retrieves by metadata filter without needing a query embedding.
        When we want all chunks for a specific file, we know exactly which
        file — no semantic search needed. get() is faster and deterministic.
        """
        try:
            results = self._collection.get(
                where={"file_path": file_path},
                include=["documents", "metadatas"]
            )
        except Exception:
            return []

        chunks = []
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])

        for doc, meta in zip(docs, metas):
            complexity_raw = meta.get("complexity", -1.0)
            chunks.append({
                **meta,
                "content": doc,
                "distance": 0.0,
                "complexity": None if complexity_raw == -1.0 else complexity_raw,
                "risk_level": None if meta.get("risk_level") == "UNKNOWN"
                              else meta.get("risk_level")
            })

        # Sort by line_start for readable output
        chunks.sort(key=lambda c: c.get("line_start", 0))
        return chunks

    def count(self) -> int:
        try:
            return self._collection.count()
        except Exception:
            return 0


# -----------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------

def _build_where_filter(
    language=None, symbol_type=None, file_path=None, risk_level=None
) -> Optional[dict]:
    """
    Build a ChromaDB 'where' clause from individual field filters.

    Single condition:   {"field": "value"}
    Multiple AND:       {"$and": [{"f1": "v1"}, {"f2": "v2"}]}
    Returns None if no filters → query with no where clause.
    """
    conditions = []
    if language:
        conditions.append({"language": language})
    if symbol_type:
        conditions.append({"symbol_type": symbol_type})
    if file_path:
        conditions.append({"file_path": file_path})
    if risk_level:
        conditions.append({"risk_level": risk_level})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _parse_results(results: dict) -> list:
    """
    Convert ChromaDB query result into a list of clean chunk dicts.

    ChromaDB returns parallel lists wrapped in an outer list
    (one entry per query embedding). We sent one embedding,
    so we unpack [0] from each list.

    Sentinel conversion:
      complexity == -1.0  →  None  (was None before storage)
      risk_level == "UNKNOWN"  →  None
    """
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    chunks = []
    for doc, meta, dist in zip(docs, metas, distances):
        complexity_raw = meta.get("complexity", -1.0)
        risk_raw = meta.get("risk_level", "UNKNOWN")

        chunks.append({
            "content": doc,
            "file_path": meta.get("file_path", ""),
            "symbol_name": meta.get("symbol_name", ""),
            "symbol_type": meta.get("symbol_type", ""),
            "language": meta.get("language", ""),
            "line_start": int(meta.get("line_start", 0)),
            "line_end": int(meta.get("line_end", 0)),
            "complexity": None if complexity_raw == -1.0 else float(complexity_raw),
            "risk_level": None if risk_raw == "UNKNOWN" else risk_raw,
            "distance": float(dist)
        })

    return chunks