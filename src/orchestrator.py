"""
Orchestrator: runs all 7 agents in sequence and saves all outputs.

All agent imports are at the top level. If an import fails, the error
surfaces immediately at startup rather than partway through a pipeline run.
"""
import json
import os
from src.state import ArchaeonState
from src.utils.github_api import parse_github_url, fetch_repo_metadata
from src.agents import ingestion
from src.agents import ast_parser
from src.agents import dependency_graph
from src.agents import complexity_scorer
from src.agents import code_rag
from src.agents import explainability
from src.agents import doc_generator
from src.utils.metrics import log_phase_start, log_phase_end


def run_pipeline(
    repo_url_or_state,
    github_token: str = None,
    max_explanations: int = 20,
    skip_llm: bool = False,
    on_agent_complete = None
) -> ArchaeonState:
    """
    Run the full 7-agent pipeline.

    Args:
        repo_url_or_state: Public GitHub repository URL or existing ArchaeonState
        github_token:      Optional PAT for higher rate limits
        max_explanations:  Cap on LLM explanation calls (default 20)
        skip_llm:          If True, skip Phase 6 entirely
        on_agent_complete: Optional callback function triggered after each agent boundary
    """
    if isinstance(repo_url_or_state, ArchaeonState):
        state = repo_url_or_state
        if not state.github_token:
            state.github_token = github_token or os.getenv("GITHUB_TOKEN")
    else:
        token = github_token or os.getenv("GITHUB_TOKEN")
        state = ArchaeonState(repo_url=repo_url_or_state, github_token=token)

    if not state.owner or not state.repo_name:
        owner, repo_name = parse_github_url(state.repo_url)
        state.owner     = owner
        state.repo_name = repo_name

    print(f"\n{'=' * 55}")
    print(f"  Project Gnosis — Code Archaeology Agent")
    print(f"  Repository : {state.owner}/{state.repo_name}")
    print(f"{'=' * 55}")

    # --- Metadata Phase ---
    t_start = log_phase_start("Metadata")
    if not state.default_branch:
        print(f"\n[Orchestrator] Fetching repo metadata...")
        metadata = fetch_repo_metadata(state.owner, state.repo_name, state.github_token)
        state.default_branch = metadata["default_branch"]
        print(f"  Default branch: {state.default_branch}")
        print(f"  Repo size:      {metadata.get('size', '?')} KB")
        print(f"  Language:       {metadata.get('language', 'Mixed')}")
        del metadata
    log_phase_end("Metadata", t_start, objects_cleaned=["Released temporary metadata response"])

    # --- Phase 1: Ingestion ---
    t_start = log_phase_start("Ingestion")
    state = ingestion.run(state)
    log_phase_end("Ingestion", t_start, objects_cleaned=["Released file tree buffers", "Released temporary content buffers"])
    if on_agent_complete:
        on_agent_complete(0)

    # --- Phase 2: AST Parser ---
    t_start = log_phase_start("AST Parser")
    state = ast_parser.run(state)
    log_phase_end("AST Parser", t_start, objects_cleaned=["Released temporary AST nodes", "Released tree-sitter syntax trees"])
    if on_agent_complete:
        on_agent_complete(1)

    # --- Phase 3: Dependency Graph ---
    t_start = log_phase_start("Dependency Graph")
    state = dependency_graph.run(state)
    log_phase_end("Dependency Graph", t_start, objects_cleaned=["Released temporary graph structures", "Released topological sort tables"])
    if on_agent_complete:
        on_agent_complete(2)

    # --- Phase 4: Complexity Scorer ---
    t_start = log_phase_start("Complexity Scorer")
    state = complexity_scorer.run(state)
    log_phase_end("Complexity Scorer", t_start, objects_cleaned=["Released radon metrics", "Released complexity scores list"])
    if on_agent_complete:
        on_agent_complete(3)

    # --- Phase 5: Code RAG ---
    t_start = log_phase_start("Code RAG")
    state = code_rag.run(state)
    log_phase_end("Code RAG", t_start, objects_cleaned=["Released embeddings", "Released chunk buffers"])
    if on_agent_complete:
        on_agent_complete(4)

    # --- Phase 6: Explainability ---
    t_start = log_phase_start("Explainability")
    if skip_llm:
        print("\n[Orchestrator] Skipping Phase 6 (--skip-llm)")
    else:
        state = explainability.run(state, max_count=max_explanations)
    log_phase_end("Explainability", t_start, objects_cleaned=["Released prompt templates", "Released token arrays"])
    if on_agent_complete:
        on_agent_complete(5)

    # --- Phase 7: Doc Generator ---
    t_start = log_phase_start("Document Generator")
    state = doc_generator.run(state)
    log_phase_end("Document Generator", t_start, objects_cleaned=["Released report builders", "Released intermediate markdown components"])
    if on_agent_complete:
        on_agent_complete(6)

    return state


# -----------------------------------------------------------------------
# Save functions — one per output file
# -----------------------------------------------------------------------

def save_manifest(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    manifest_data = [
        {"path": f.path, "language": f.language,
         "line_count": f.line_count, "size_bytes": f.size_bytes, "sha": f.sha}
        for f in state.file_manifest
    ]
    lang_counts: dict = {}
    for f in state.file_manifest:
        lang_counts[f.language] = lang_counts.get(f.language, 0) + 1
    output = {
        "repo": f"{state.owner}/{state.repo_name}",
        "branch": state.default_branch,
        "total_files": len(manifest_data),
        "files_with_content": len(state.raw_contents),
        "language_breakdown": lang_counts,
        "files": manifest_data
    }
    path = os.path.join(output_dir, "file_manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"[Orchestrator] file_manifest.json       → {path}")
    return path


def save_symbol_tables(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    output = {}
    for file_path, st in state.symbol_tables.items():
        output[file_path] = {
            "language": st.language,
            "module_docstring": st.module_docstring,
            "parse_error": st.parse_error,
            "parse_error_detail": st.parse_error_detail,
            "functions": [
                {"name": f.name, "params": f.params,
                 "line_start": f.line_start, "line_end": f.line_end,
                 "docstring": f.docstring, "is_async": f.is_async,
                 "is_method": f.is_method}
                for f in st.functions
            ],
            "classes": [
                {"name": c.name, "bases": c.bases,
                 "method_names": c.method_names,
                 "line_start": c.line_start, "line_end": c.line_end,
                 "docstring": c.docstring}
                for c in st.classes
            ],
            "imports": [
                {"module": i.module, "names": i.names,
                 "is_from_import": i.is_from_import,
                 "is_internal": i.is_internal}
                for i in st.imports
            ]
        }
    path = os.path.join(output_dir, "symbol_tables.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"[Orchestrator] symbol_tables.json       → {path}")
    return path


def save_graph_data(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    output = {
        "repo": f"{state.owner}/{state.repo_name}",
        "total_files": state.dependency_graph.number_of_nodes()
                       if state.dependency_graph else 0,
        "total_edges": state.dependency_graph.number_of_edges()
                       if state.dependency_graph else 0,
        "circular_dependency_count": len(state.circular_deps),
        "circular_deps": state.circular_deps,
        "circular_nodes": list(state.circular_nodes),
        "topological_order": state.topological_order,
        "graph_stats": state.graph_stats
    }
    path = os.path.join(output_dir, "graph_data.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"[Orchestrator] graph_data.json          → {path}")
    return path


def save_graph_html(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    from src.utils.graph_utils import generate_graph_html
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "dependency_graph.html")
    generate_graph_html(
        state.dependency_graph, state.graph_stats,
        state.circular_nodes, path
    )
    print(f"[Orchestrator] dependency_graph.html    → {path}")
    return path


def save_complexity_report(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    scores    = list(state.complexity_scores.values())
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in scores:
        risk_dist[s.risk_level] = risk_dist.get(s.risk_level, 0) + 1
    complexities = [s.avg_complexity for s in scores if s.avg_complexity > 0]
    repo_avg     = round(sum(complexities) / len(complexities), 2) if complexities else 0.0
    all_fn       = []
    for s in scores:
        for fn_name, c in s.function_scores.items():
            all_fn.append({"file": s.file_path, "function": fn_name, "complexity": c})
    top_functions = sorted(all_fn, key=lambda x: -x["complexity"])[:10]

    def score_to_dict(s):
        return {
            "file_path": s.file_path, "language": s.language,
            "risk_level": s.risk_level, "risk_reasons": s.risk_reasons,
            "avg_complexity": s.avg_complexity, "max_complexity": s.max_complexity,
            "max_complexity_function": s.max_complexity_function,
            "function_count": s.function_count, "coupling_score": s.coupling_score,
            "undocumented_ratio": s.undocumented_ratio, "line_count": s.line_count,
            "parse_error": s.parse_error,
            "is_in_circular_dep": s.is_in_circular_dep,
            "function_scores": s.function_scores
        }

    files_by_risk: dict = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
    for s in sorted(scores, key=lambda x: -x.max_complexity):
        files_by_risk[s.risk_level].append(score_to_dict(s))

    output = {
        "repo": f"{state.owner}/{state.repo_name}",
        "summary": {
            "files_analyzed": len(scores),
            "risk_distribution": risk_dist,
            "avg_complexity_across_repo": repo_avg,
            "top_complex_functions": top_functions
        },
        "files_by_risk": files_by_risk
    }
    path = os.path.join(output_dir, "complexity_report.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"[Orchestrator] complexity_report.json   → {path}")
    return path


def save_rag_info(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    chunk_count = 0
    if state.chroma_collection_name:
        try:
            from src.utils.retriever import CodeRetriever, DEFAULT_CHROMA_DB_PATH
            retriever   = CodeRetriever(
                state.chroma_collection_name,
                chroma_db_path=DEFAULT_CHROMA_DB_PATH
            )
            chunk_count = retriever.count()
        except Exception:
            pass
    output = {
        "repo": f"{state.owner}/{state.repo_name}",
        "collection_name": state.chroma_collection_name,
        "chroma_db_path": "./chroma_db",
        "total_chunks": chunk_count
    }
    path = os.path.join(output_dir, "rag_info.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"[Orchestrator] rag_info.json            → {path}")
    return path


def save_explanations(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    output = {
        "repo": f"{state.owner}/{state.repo_name}",
        "files_explained": len(state.explanations),
        "explanations": state.explanations
    }
    path = os.path.join(output_dir, "explanations.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, ensure_ascii=False)
    print(f"[Orchestrator] explanations.json        → {path}")
    return path


def save_onboarding_doc(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    """
    Write state.final_doc to onboarding.md.
    This is Project Gnosis's primary deliverable.
    """
    os.makedirs(output_dir, exist_ok=True)
    if not state.final_doc:
        print("[Orchestrator] No document to save (doc_generator may not have run)")
        return ""
    path = os.path.join(output_dir, "onboarding.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(state.final_doc)
    print(f"[Orchestrator] onboarding.md            → {path}")
    return path