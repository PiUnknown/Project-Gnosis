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

    # --- Agent 2: AST Parser ---
    symbol_tables: dict = field(default_factory=dict)   # path -> SymbolTable

    # --- Agent 3: Dependency Graph ---
    dependency_graph: Any = None                             # nx.DiGraph
    circular_deps: list = field(default_factory=list)        # list of cycles (list of lists)
    circular_nodes: set = field(default_factory=set)         # all file paths in any cycle
    graph_stats: dict = field(default_factory=dict)          # path -> per-file metrics dict
    topological_order: list = field(default_factory=list)    # suggested reading order

    # --- Agent 4: Complexity Scorer (Phase 4) ---
    complexity_scores: dict = field(default_factory=dict)

    # --- Agent 5: Code RAG (Phase 5) ---
    chroma_collection_name: str = None

    # --- Agent 6: Explainability (Phase 6) ---
    explanations: dict = field(default_factory=dict)

    # --- Agent 7: Doc Generator (Phase 7) ---
    final_doc: str = None
    complexity_report_json: str = None