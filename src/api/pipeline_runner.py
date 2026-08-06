"""
API-specific pipeline runner.

Calls all 7 agents in sequence, updating job state between each agent
so the status endpoint can report meaningful progress.

WHY NOT USE orchestrator.run_pipeline():
The orchestrator is a clean sequential function with no side effects.
Adding status-callback parameters to it would couple the orchestrator
to the API layer, violating the separation between the pipeline and
its delivery mechanism. The API runner duplicates the agent call
sequence (7 lines) in exchange for the ability to interleave job
store updates without touching the orchestrator.
"""
import os
import traceback
from pathlib import PurePosixPath

from src.api.job_store import store
from src.api.models import PHASE_PROGRESS
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


def run(job_id: str, repo_url: str, options: dict) -> None:
    """
    Execute the full pipeline for one job.

    Runs synchronously in a background thread.
    Updates job_store at each phase boundary.
    On success: calls store.finish() with serialized result.
    On failure: calls store.fail() with the error message.

    Never raises — all exceptions are caught and stored as job errors.
    """
    store.start(job_id)

    try:
        # ---- Setup state -------------------------------------------
        github_token = options.get("github_token") or os.getenv("GITHUB_TOKEN")
        max_explanations = options.get("max_explanations", 20)
        skip_llm = options.get("skip_llm", False)

        state = ArchaeonState(repo_url=repo_url, github_token=github_token, job_id=job_id)
        owner, repo_name = parse_github_url(repo_url)
        state.owner     = owner
        state.repo_name = repo_name

        # ---- Phase: metadata ----------------------------------------
        _start_phase(job_id, "metadata")
        t_start = log_phase_start("Metadata")
        metadata = fetch_repo_metadata(owner, repo_name, github_token)
        state.default_branch = metadata["default_branch"]
        del metadata
        log_phase_end("Metadata", t_start, objects_cleaned=["Released temporary metadata response"])
        _end_phase(job_id, "metadata")

        # ---- Phase 1: Ingestion ------------------------------------
        _start_phase(job_id, "ingestion")
        t_start = log_phase_start("Ingestion")
        state = ingestion.run(state)
        log_phase_end("Ingestion", t_start, objects_cleaned=["Released file tree buffers", "Released temporary content buffers"])
        _end_phase(job_id, "ingestion")

        # ---- Phase 2: AST Parser -----------------------------------
        _start_phase(job_id, "ast_parser")
        t_start = log_phase_start("AST Parser")
        state = ast_parser.run(state)
        log_phase_end("AST Parser", t_start, objects_cleaned=["Released temporary AST nodes", "Released tree-sitter syntax trees"])
        _end_phase(job_id, "ast_parser")

        # ---- Phase 3: Dependency Graph -----------------------------
        _start_phase(job_id, "dependency_graph")
        t_start = log_phase_start("Dependency Graph")
        state = dependency_graph.run(state)
        log_phase_end("Dependency Graph", t_start, objects_cleaned=["Released temporary graph structures", "Released topological sort tables"])
        _end_phase(job_id, "dependency_graph")

        # ---- Phase 4: Complexity Scorer ----------------------------
        _start_phase(job_id, "complexity_scorer")
        t_start = log_phase_start("Complexity Scorer")
        state = complexity_scorer.run(state)
        log_phase_end("Complexity Scorer", t_start, objects_cleaned=["Released radon metrics", "Released complexity scores list"])
        _end_phase(job_id, "complexity_scorer")

        # ---- Phase 5: Code RAG ------------------------------------
        _start_phase(job_id, "code_rag")
        t_start = log_phase_start("Code RAG")
        state = code_rag.run(state)
        log_phase_end("Code RAG", t_start, objects_cleaned=["Released embeddings", "Released chunk buffers"])
        _end_phase(job_id, "code_rag")

        # ---- Phase 6: Explainability (optional) -------------------
        _start_phase(job_id, "explainability")
        t_start = log_phase_start("Explainability")
        print(f"  [Pipeline] skip_llm={options.get('skip_llm')}  type={type(options.get('skip_llm'))}")
        if not skip_llm:
            state = explainability.run(state, max_count=max_explanations)
        log_phase_end("Explainability", t_start, objects_cleaned=["Released prompt templates", "Released token arrays"])
        _end_phase(job_id, "explainability")

        # ---- Phase 7: Doc Generator --------------------------------
        _start_phase(job_id, "doc_generator")
        t_start = log_phase_start("Document Generator")
        state = doc_generator.run(state)
        log_phase_end("Document Generator", t_start, objects_cleaned=["Released report builders", "Released intermediate markdown components"])
        _end_phase(job_id, "doc_generator")

        # ---- Serialize result --------------------------------------
        result = _serialize_result(job_id, state)
        store.finish(job_id, result)

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        detail    = traceback.format_exc()
        print(f"\n[Pipeline] Job {job_id} failed: {error_msg}")
        print(detail)
        store.fail(job_id, error=error_msg)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _start_phase(job_id: str, phase: str) -> None:
    progress = PHASE_PROGRESS.get(phase, 0)
    store.update_phase(job_id, phase, progress)
    print(f"\n[API Pipeline:{job_id[:8]}] Starting phase: {phase}")


def _end_phase(job_id: str, phase: str) -> None:
    store.complete_phase(job_id, phase)


def _serialize_result(job_id: str, state: ArchaeonState) -> dict:
    """
    Convert ArchaeonState to a JSON-serializable result dict.

    Only serializes what the API client needs.
    NetworkX graphs, tree-sitter objects, and ChromaDB handles
    are not included — they are not serializable and not useful
    to a remote client.
    """
    # Risk distribution
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for score in state.complexity_scores.values():
        risk_dist[score.risk_level] = risk_dist.get(score.risk_level, 0) + 1

    # Language breakdown
    lang_counts: dict = {}
    for f in state.file_manifest:
        if f.language not in ("Markdown", "YAML", "TOML", "Unknown"):
            lang_counts[f.language] = lang_counts.get(f.language, 0) + 1

    # Top 10 most complex functions
    all_fns = []
    for score in state.complexity_scores.values():
        for fn_name, complexity in score.function_scores.items():
            all_fns.append({
                "file": score.file_path,
                "function": fn_name,
                "complexity": complexity
            })
    top_fns = sorted(all_fns, key=lambda x: -x["complexity"])[:10]

    # Graph summary (top 10 files by in-degree)
    top_files = sorted(
        [
            {
                "file": PurePosixPath(p).name,
                "path": p,
                "in_degree": s["in_degree"],
                "out_degree": s["out_degree"],
                "risk": state.complexity_scores.get(p, None) and
                        state.complexity_scores[p].risk_level
            }
            for p, s in state.graph_stats.items()
        ],
        key=lambda x: -(x["in_degree"] or 0)
    )[:10]

    # Complexity report (CRITICAL + HIGH only to keep size reasonable)
    critical_high = []
    for score in state.complexity_scores.values():
        if score.risk_level in ("CRITICAL", "HIGH"):
            critical_high.append({
                "file_path": score.file_path,
                "risk_level": score.risk_level,
                "risk_reasons": score.risk_reasons,
                "avg_complexity": score.avg_complexity,
                "max_complexity": score.max_complexity,
                "max_complexity_function": score.max_complexity_function,
                "coupling_score": score.coupling_score,
                "parse_error": score.parse_error,
                "is_in_circular_dep": score.is_in_circular_dep
            })

    dependency_rows = []
    if state.dependency_graph:
        for node in state.dependency_graph.nodes():
            complexity_score = state.complexity_scores.get(node)
            risk_level = complexity_score.risk_level if complexity_score else "LOW"
            dependency_rows.append({
                "file": PurePosixPath(node).name,
                "path": node,
                "imported_by": state.dependency_graph.in_degree(node),
                "imports": state.dependency_graph.out_degree(node),
                "risk": risk_level,
            })
        dependency_rows.sort(key=lambda r: r["imported_by"], reverse=True)

    complexity_rows = []
    for path, scores in state.complexity_scores.items():
        complexity_rows.append({
            "file": PurePosixPath(path).name,
            "path": path,
            "risk": scores.risk_level,
            "avg_cc": scores.avg_complexity,
            "max_cc": scores.max_complexity,
            "worst_fn": scores.max_complexity_function,
            "coupling": scores.coupling_score,
            "flags": scores.risk_reasons,
        })

    reading_order = state.topological_order or []

    return {
        "job_id": job_id,
        "repo": f"{state.owner}/{state.repo_name}",
        "branch": state.default_branch or "main",
        "onboarding_doc": state.final_doc or "",
        "summary": {
            "total_files": len(state.file_manifest),
            "language_breakdown": lang_counts,
            "total_functions": sum(
                len(st.functions) for st in state.symbol_tables.values()
            ),
            "total_classes": sum(
                len(st.classes) for st in state.symbol_tables.values()
            ),
            "total_import_edges": (
                state.dependency_graph.number_of_edges()
                if state.dependency_graph else 0
            ),
            "circular_dep_count": len(state.circular_deps),
            "risk_distribution": risk_dist,
            "files_explained": len(state.explanations),
            "top_complex_functions": top_fns,
        },
        "complexity_report": {
            "critical_and_high": critical_high,
            "circular_deps": state.circular_deps,
        },
        "graph_summary": {
            "top_files_by_indegree": top_files,
            "topological_order_available": bool(state.topological_order),
            "reading_order_top_10": state.topological_order[:10]
        },
        "explanations": state.explanations,
        # frontend-required fields:
        "dependency_rows": dependency_rows[:10],
        "reading_order": reading_order[:10],
        "complexity_rows": complexity_rows,
        "complexity_report_json": state.complexity_report_json or "{}",
        "circular_deps": state.circular_deps,
    }