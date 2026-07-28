import json
import os
from src.state import ArchaeonState
from src.utils.github_api import parse_github_url, fetch_repo_metadata
from src.agents import ingestion
from src.agents import ast_parser
from src.agents import dependency_graph
from src.agents import complexity_scorer
from src.agents import code_rag


def run_pipeline(repo_url: str, github_token: str = None) -> ArchaeonState:
    state = ArchaeonState(repo_url=repo_url, github_token=github_token)

    owner, repo_name = parse_github_url(repo_url)
    state.owner = owner
    state.repo_name = repo_name

    print(f"\n{'=' * 55}")
    print(f"  Project Gnosis — Code Archaeology Agent")
    print(f"  Repository : {owner}/{repo_name}")
    print(f"{'=' * 55}")

    print(f"\n[Orchestrator] Fetching repo metadata...")
    metadata = fetch_repo_metadata(owner, repo_name, github_token)
    state.default_branch = metadata["default_branch"]
    print(f"  Default branch: {state.default_branch}")
    print(f"  Repo size:      {metadata.get('size', '?')} KB")
    print(f"  Language:       {metadata.get('language', 'Mixed')}")

    state = ingestion.run(state)
    state = ast_parser.run(state)
    state = dependency_graph.run(state)
    state = complexity_scorer.run(state)
    state = code_rag.run(state)

    # state = explainability.run(state)    # Phase 6
    # state = doc_generator.run(state)     # Phase 7

    return state


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
    print(f"[Orchestrator] Manifest saved            → {path}")
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
    print(f"[Orchestrator] Symbol tables saved       → {path}")
    return path


def save_graph_data(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    output = {
        "repo": f"{state.owner}/{state.repo_name}",
        "total_files": state.dependency_graph.number_of_nodes() if state.dependency_graph else 0,
        "total_edges": state.dependency_graph.number_of_edges() if state.dependency_graph else 0,
        "circular_dependency_count": len(state.circular_deps),
        "circular_deps": state.circular_deps,
        "circular_nodes": list(state.circular_nodes),
        "topological_order": state.topological_order,
        "graph_stats": state.graph_stats
    }
    path = os.path.join(output_dir, "graph_data.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)
    print(f"[Orchestrator] Graph data saved          → {path}")
    return path


def save_graph_html(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    from src.utils.graph_utils import generate_graph_html
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "dependency_graph.html")
    generate_graph_html(
        state.dependency_graph, state.graph_stats,
        state.circular_nodes, path
    )
    print(f"[Orchestrator] Dependency graph saved    → {path}")
    return path


def save_complexity_report(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)
    scores = list(state.complexity_scores.values())
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in scores:
        risk_dist[s.risk_level] = risk_dist.get(s.risk_level, 0) + 1
    complexities = [s.avg_complexity for s in scores if s.avg_complexity > 0]
    repo_avg = round(sum(complexities) / len(complexities), 2) if complexities else 0.0
    all_fn = []
    for s in scores:
        for fn_name, complexity in s.function_scores.items():
            all_fn.append({"file": s.file_path, "function": fn_name, "complexity": complexity})
    top_functions = sorted(all_fn, key=lambda x: -x["complexity"])[:10]

    def score_to_dict(s):
        return {
            "file_path": s.file_path, "language": s.language,
            "risk_level": s.risk_level, "risk_reasons": s.risk_reasons,
            "avg_complexity": s.avg_complexity, "max_complexity": s.max_complexity,
            "max_complexity_function": s.max_complexity_function,
            "function_count": s.function_count, "coupling_score": s.coupling_score,
            "undocumented_ratio": s.undocumented_ratio, "line_count": s.line_count,
            "parse_error": s.parse_error, "is_in_circular_dep": s.is_in_circular_dep,
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
    print(f"[Orchestrator] Complexity report saved   → {path}")
    return path


def save_rag_info(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    """
    Write a summary of the RAG collection to outputs.
    Primary deliverable is the ChromaDB collection on disk.
    This JSON is the manifest of what was stored.
    """
    os.makedirs(output_dir, exist_ok=True)

    chunk_count = 0
    if state.chroma_collection_name:
        try:
            from src.utils.retriever import CodeRetriever, DEFAULT_CHROMA_DB_PATH
            retriever = CodeRetriever(
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
    print(f"[Orchestrator] RAG info saved            → {path}")
    return path