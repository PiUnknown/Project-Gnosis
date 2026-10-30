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
import sys
import traceback
from pathlib import PurePosixPath

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.api.job_store import store
from src.api.models import PHASE_PROGRESS
from src.state import ArchaeonState
from src.utils.github_api import parse_github_url, fetch_repo_metadata
from src.utils.token_crypto import decrypt_github_token
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
        persisted_job = store.get(job_id)
        encrypted_token = (
            persisted_job.options.get("github_token_encrypted")
            if persisted_job and persisted_job.options
            else None
        )
        github_token = decrypt_github_token(encrypted_token) if encrypted_token else None
        github_token = github_token or os.getenv("GITHUB_TOKEN")
        max_explanations = options.get("max_explanations", 20)
        skip_llm = options.get("skip_llm", False)
        incremental = options.get("incremental", False)

        state = ArchaeonState(repo_url=repo_url, github_token=github_token, job_id=job_id)
        if incremental:
            state.is_incremental = True
            from src.utils.diff_engine import load_cached_state
            output_dir = options.get("output_dir", "./outputs")
            cached = load_cached_state(output_dir)
            if cached:
                state.previous_state = cached

        owner, repo_name = parse_github_url(repo_url)
        state.owner     = owner
        state.repo_name = repo_name

        # ---- Phase: metadata ----------------------------------------
        _start_phase(job_id, "metadata")
        t_start = log_phase_start("Metadata")
        metadata = fetch_repo_metadata(owner, repo_name, github_token)
        state.default_branch = metadata["default_branch"]
        repo_size_kb = int(metadata.get("size") or 0)
        del metadata
        log_phase_end("Metadata", t_start, objects_cleaned=["Released temporary metadata response"])
        _end_phase(job_id, "metadata")

        # ---- Phase 1: Ingestion ------------------------------------
        _start_phase(job_id, "ingestion")
        t_start = log_phase_start("Ingestion")
        state = ingestion.run(
            state,
            reject_over_max=True,
            repo_size_kb=repo_size_kb,
        )
        log_phase_end("Ingestion", t_start, objects_cleaned=["Released file tree buffers", "Released temporary content buffers"])
        _end_phase(job_id, "ingestion")

        # ---- Phase 2: AST Parser -----------------------------------
        _start_phase(job_id, "ast_parser")
        t_start = log_phase_start("AST Parser")
        state = ast_parser.run(state)
        log_phase_end("AST Parser", t_start, objects_cleaned=["Released temporary AST nodes", "Released tree-sitter syntax trees"])
        _end_phase(job_id, "ast_parser")

        # ---- Phases 3, 4, 5 ----------------------------------------
        # These MUST run sequentially, despite the pipeline summary naming
        # them "parallel agents".
        #
        # WHY: dependency_graph is what decides which files are in scope. It
        # sets state.analyzed_paths / state.files_analyzed in Sampled mode, and
        # complexity_scorer and code_rag both filter on analyzed_paths. Running
        # all three concurrently meant complexity_scorer started before
        # analyzed_paths existed (scoring all 871 code files instead of the 300
        # selected ones) and apply_graph_coupling ran while code_rag was still
        # reading graph_stats. The report then disagreed with itself: "300 files
        # selected" next to 871 complexity rows.
        #
        # The previous 3-way pool bought a little wall-clock time and cost
        # correctness; the phases are now ordered by data dependency.
        _start_phase(job_id, "dependency_graph")
        t_phase_start = log_phase_start("Dependency Graph")
        state = dependency_graph.run(state)
        log_phase_end("Dependency Graph", t_phase_start, objects_cleaned=["Released graph adjacency buffers"])
        _end_phase(job_id, "dependency_graph")

        _start_phase(job_id, "complexity_scorer")
        t_phase_start = log_phase_start("Complexity Scorer")
        state = complexity_scorer.run(state)
        complexity_scorer.apply_graph_coupling(state)
        log_phase_end("Complexity Scorer", t_phase_start, objects_cleaned=["Released complexity intermediates"])
        _end_phase(job_id, "complexity_scorer")

        _start_phase(job_id, "code_rag")
        t_phase_start = log_phase_start("Code RAG")
        state = code_rag.run(state)
        log_phase_end("Code RAG", t_phase_start, objects_cleaned=["Released embedding batches"])
        _end_phase(job_id, "code_rag")

        # ---- Phase 6: Explainability (optional) -------------------
        _start_phase(job_id, "explainability")
        t_start = log_phase_start("Explainability")
        print(f"  [Pipeline] skip_llm={options.get('skip_llm')}  type={type(options.get('skip_llm'))}")
        if not skip_llm:
            state = explainability.run(
                state,
                max_count=max_explanations,
                # Bind job_id here: update_explanation_progress needs
                # (job_id, completed, total) but the agent calls (completed, total).
                progress_callback=lambda completed, total: store.update_explanation_progress(
                    job_id, completed, total
                ),
            )
        else:
            state.explanations_skipped_reason = (
                "AI explanations were disabled for this run (skip_llm=true)"
            )

        # Progress alone cannot distinguish success from a total outage: a run
        # where every LLM call failed used to report 20/20. Record the failures
        # and the provider error so the status endpoint is truthful.
        store.set_explanation_outcome(
            job_id,
            completed=len(state.explanations),
            total=state.explanations_requested or len(state.explanations),
            failed=state.explanations_failed,
            error=state.explanation_error,
        )
        log_phase_end("Explainability", t_start, objects_cleaned=["Released prompt templates", "Released token arrays"])
        _end_phase(job_id, "explainability")

        # ---- Phase 7: Doc Generator --------------------------------
        _start_phase(job_id, "doc_generator")
        t_start = log_phase_start("Document Generator")
        state = doc_generator.run(state)
        log_phase_end("Document Generator", t_start, objects_cleaned=["Released report builders", "Released intermediate markdown components"])
        _end_phase(job_id, "doc_generator")

        # ---- Serialize result --------------------------------------
        result = _serialize_result(job_id, state, skip_llm=skip_llm)
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


def _serialize_result(job_id: str, state: ArchaeonState, skip_llm: bool = False) -> dict:
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
    #
    # WHY SCORED FILES: this sits next to ``total_files`` (= files_analyzed),
    # so the counts must share that denominator. Counting the manifest mixed
    # sampled and unsampled files and produced e.g. 871 language files beside
    # "total_files": 300. Scored files are the ones the report describes; the
    # manifest is only a fallback when scoring produced nothing.
    lang_counts: dict = {}
    for score in state.complexity_scores.values():
        lang = getattr(score, "language", None) or "Unknown"
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    if not lang_counts:
        for f in state.file_manifest:
            if f.language not in ("Markdown", "YAML", "TOML", "Unknown"):
                lang_counts[f.language] = lang_counts.get(f.language, 0) + 1
    lang_counts = dict(
        sorted(lang_counts.items(), key=lambda item: item[1], reverse=True)
    )

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
    graph_nodes = []
    graph_links = []
    if state.dependency_graph:
        for node in state.dependency_graph.nodes():
            complexity_score = state.complexity_scores.get(node)
            risk_level = complexity_score.risk_level if complexity_score else "LOW"
            graph_nodes.append({
                "id": node,
                "path": node,
                "file": PurePosixPath(node).name,
                "risk": risk_level,
                "imported_by": state.dependency_graph.in_degree(node),
                "imports": state.dependency_graph.out_degree(node),
            })
            dependency_rows.append({
                "file": PurePosixPath(node).name,
                "path": node,
                "imported_by": state.dependency_graph.in_degree(node),
                "imports": state.dependency_graph.out_degree(node),
                "risk": risk_level,
            })
        dependency_rows.sort(key=lambda r: r["imported_by"], reverse=True)
        graph_links = [
            {"source": source, "target": target}
            for source, target in state.dependency_graph.edges()
        ]

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

    # Explainability outcome — a job can complete with missing explanations,
    # and that must be visible rather than inferred from an empty map.
    if skip_llm or state.explanations_skipped_reason:
        explanation_status = "skipped"
    elif state.explanations_failed:
        explanation_status = "partial" if state.explanations else "failed"
    elif state.explanations:
        explanation_status = "complete"
    else:
        explanation_status = "skipped" if not state.explanations_requested else "failed"

    reading_order = state.topological_order or []

    return {
        "job_id": job_id,
        "repo": f"{state.owner}/{state.repo_name}",
        "branch": state.default_branch or "main",
        "onboarding_doc": state.final_doc or "",
        "file_explanations_md": state.file_explanations_doc or "",
        "agent_context": state.agent_context_md or "",
        "analysis_mode": state.analysis_mode,
        "files_discovered": state.files_discovered,
        "files_analyzed": state.files_analyzed,
        "skip_llm": skip_llm,
        "summary": {
            "total_files": state.files_analyzed,
            "files_discovered": state.files_discovered,
            "files_analyzed": state.files_analyzed,
            "files_with_content": state.files_with_content,
            "analysis_mode": state.analysis_mode,
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
            "import_edges": (
                state.dependency_graph.number_of_edges()
                if state.dependency_graph else 0
            ),
            "circular_dep_count": len(state.circular_deps),
            "circular_deps_truncated": state.circular_deps_truncated,
            "risk_distribution": risk_dist,
            "files_explained": len(state.explanations),
            "explained": len(state.explanations),
            "top_complex_functions": top_fns,
        },
        # Explicit explainability outcome. `explanation_status` is one of:
        #   "complete" — every selected file was explained
        #   "partial"  — some explanations are missing
        #   "failed"   — files were attempted but none produced an explanation
        #   "skipped"  — the phase did not run (skip_llm or a setup problem)
        "explanation_status": explanation_status,
        "explanations_requested": state.explanations_requested,
        "explanations_failed": state.explanations_failed,
        "explanation_error": state.explanation_error,
        "explanations_skipped_reason": state.explanations_skipped_reason,
        "complexity_report": {
            "critical_and_high": critical_high,
            "circular_deps": state.circular_deps,
            "circular_deps_truncated": state.circular_deps_truncated,
        },
        "graph_summary": {
            "top_files_by_indegree": top_files,
            "topological_order_available": bool(state.topological_order),
            "reading_order_top_10": state.topological_order[:10]
        },
        "explanations": state.explanations,
        # frontend-required fields:
        "dependency_rows": dependency_rows[:10],
        "graph_data": {
            "nodes": graph_nodes,
            "links": graph_links,
            "edges": [[link["source"], link["target"]] for link in graph_links],
            "in_degree": {node["id"]: node["imported_by"] for node in graph_nodes},
            "out_degree": {node["id"]: node["imports"] for node in graph_nodes},
            "circular_deps": state.circular_deps,
            "circular_deps_truncated": state.circular_deps_truncated,
            "topological_order": reading_order,
        },
        "reading_order": reading_order[:10],
        "complexity_rows": complexity_rows,
        "complexity_report_json": state.complexity_report_json or "{}",
        "circular_deps": state.circular_deps,
        "circular_deps_truncated": state.circular_deps_truncated,
    }
