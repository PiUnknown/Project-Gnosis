import json
import os
from src.state import ArchaeonState
from src.utils.github_api import parse_github_url, fetch_repo_metadata
from src.agents import ingestion


def run_pipeline(repo_url: str, github_token: str = None) -> ArchaeonState:
    """
    Master pipeline orchestrator.
    Initializes state, parses the URL, then calls agents in sequence.

    Currently active: Agent 1 (Ingestion).
    Agents 2-7 will be uncommented as phases are completed.
    """

    # Initialize shared state
    state = ArchaeonState(
        repo_url=repo_url,
        github_token=github_token
    )

    # Parse URL into owner + repo name
    owner, repo_name = parse_github_url(repo_url)
    state.owner = owner
    state.repo_name = repo_name

    print(f"\n{'=' * 55}")
    print(f"  Project Gnosis — Code Archaeology Agent")
    print(f"  Repository : {owner}/{repo_name}")
    print(f"{'=' * 55}")

    # Fetch repo metadata to get default branch
    print(f"\n[Orchestrator] Fetching repo metadata...")
    metadata = fetch_repo_metadata(owner, repo_name, github_token)
    state.default_branch = metadata["default_branch"]
    print(f"  Default branch: {state.default_branch}")
    print(f"  Repo size:      {metadata.get('size', '?')} KB")
    print(f"  Language:       {metadata.get('language', 'Mixed')}")

    # --- Agent 1: Ingestion ---
    state = ingestion.run(state)

    # --- Agent 2: AST Parser (Phase 2) ---
    # state = ast_parser.run(state)

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
    """
    Serialize state.file_manifest to JSON and save to disk.
    This is Phase 1's primary deliverable.
    """
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

    # Also write a quick language summary at the top level
    lang_counts: dict[str, int] = {}
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