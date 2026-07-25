import json
import os
from src.state import ArchaeonState
from src.utils.github_api import parse_github_url, fetch_repo_metadata
from src.agents import ingestion
from src.agents import ast_parser


def run_pipeline(repo_url: str, github_token: str = None) -> ArchaeonState:
    state = ArchaeonState(
        repo_url=repo_url,
        github_token=github_token
    )

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

    # --- Agent 1: Ingestion ---
    state = ingestion.run(state)

    # --- Agent 2: AST Parser ---
    state = ast_parser.run(state)

    # --- Agent 3: Dependency Graph (Phase 3) ---
    # state = dependency_graph.run(state)

    # --- Agent 4: Complexity Scorer (Phase 4) ---
    # state = complexity_scorer.run(state)

    # --- Agent 5: Code RAG (Phase 5) ---
    # state = code_rag.run(state)

    # --- Agent 6: Explainability (Phase 6) ---
    # state = explainability.run(state)

    # --- Agent 7: Doc Generator (Phase 7) ---
    # state = doc_generator.run(state)

    return state


def save_manifest(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    os.makedirs(output_dir, exist_ok=True)

    manifest_data = [
        {
            "path": f.path,
            "language": f.language,
            "line_count": f.line_count,
            "size_bytes": f.size_bytes,
            "sha": f.sha
        }
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

    print(f"\n[Orchestrator] Manifest saved → {path}")
    return path


def save_symbol_tables(state: ArchaeonState, output_dir: str = "./outputs") -> str:
    """
    Serialize state.symbol_tables to JSON for inspection.
    This is Phase 2's primary deliverable.
    """
    os.makedirs(output_dir, exist_ok=True)

    output = {}
    for file_path, st in state.symbol_tables.items():
        output[file_path] = {
            "language": st.language,
            "module_docstring": st.module_docstring,
            "parse_error": st.parse_error,
            "parse_error_detail": st.parse_error_detail,
            "functions": [
                {
                    "name": f.name,
                    "params": f.params,
                    "line_start": f.line_start,
                    "line_end": f.line_end,
                    "docstring": f.docstring,
                    "is_async": f.is_async,
                    "is_method": f.is_method
                }
                for f in st.functions
            ],
            "classes": [
                {
                    "name": c.name,
                    "bases": c.bases,
                    "method_names": c.method_names,
                    "line_start": c.line_start,
                    "line_end": c.line_end,
                    "docstring": c.docstring
                }
                for c in st.classes
            ],
            "imports": [
                {
                    "module": i.module,
                    "names": i.names,
                    "is_from_import": i.is_from_import,
                    "is_internal": i.is_internal
                }
                for i in st.imports
            ]
        }

    path = os.path.join(output_dir, "symbol_tables.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2)

    print(f"[Orchestrator] Symbol tables saved → {path}")
    return path