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
    job_id: Optional[str] = None

    def __post_init__(self):
        if not self.job_id:
            import uuid
            self.job_id = str(uuid.uuid4())

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

    # --- Agent 4: Complexity Scorer ---
    complexity_scores: dict = field(default_factory=dict)

    # --- Agent 5: Code RAG ---
    chroma_collection_name: str = None

    # --- Agent 6: Explainability ---
    explanations: dict = field(default_factory=dict)

    # --- Agent 7: Doc Generator ---
    final_doc: str = None
    file_explanations_doc: Optional[str] = None
    file_explanations_json: Optional[str] = None
    agent_context_md: str = None            # agent_context.md (AI coding agent-oriented)
    complexity_report_json: str = None

    # --- Repository Analysis Tiers ---
    analysis_mode: str = "Full"
    files_discovered: int = 0
    files_analyzed: int = 0
    analyzed_paths: Optional[set] = None