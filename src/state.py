from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FileMetadata:
    """Metadata for a single file in the repository."""
    path: str
    language: str
    line_count: int
    size_bytes: int
    sha: str


@dataclass
class ArchaeonState:
    """
    Shared state object passed through the entire agent pipeline.
    Each agent reads from this and writes its output back to it.
    No agent imports another agent. They only interact through this object.
    """

    # --- Input ---
    repo_url: str
    github_token: Optional[str] = None

    # --- Parsed from URL by orchestrator before pipeline starts ---
    owner: str = None
    repo_name: str = None
    default_branch: str = None

    # --- Agent 1: Ingestion ---
    file_manifest: list = field(default_factory=list)   # list[FileMetadata]
    raw_contents: dict = field(default_factory=dict)    # path -> str

    # --- Agent 2: AST Parser (Phase 2) ---
    symbol_tables: dict = field(default_factory=dict)

    # --- Agent 3: Dependency Graph (Phase 3) ---
    dependency_graph: Any = None
    circular_deps: list = field(default_factory=list)

    # --- Agent 4: Complexity Scorer (Phase 4) ---
    complexity_scores: dict = field(default_factory=dict)

    # --- Agent 5: Code RAG (Phase 5) ---
    chroma_collection_name: str = None

    # --- Agent 6: Explainability (Phase 6) ---
    explanations: dict = field(default_factory=dict)

    # --- Agent 7: Doc Generator (Phase 7) ---
    final_doc: str = None
    complexity_report_json: str = None