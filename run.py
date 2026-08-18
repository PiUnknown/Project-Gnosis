"""
run.py — Project Gnosis entry point.

All 7 phases run in sequence. Outputs are written to --output directory.
Primary deliverable: onboarding.md

Usage:
  python run.py --url https://github.com/psf/black
  python run.py --url https://github.com/tiangolo/fastapi --max-explain 10
  python run.py --url https://github.com/realpython/codetiming --skip-llm
  python run.py --url https://github.com/tiangolo/fastapi --test-rag
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import os
import argparse
from dotenv import load_dotenv

from src.orchestrator import (
    run_pipeline,
    save_manifest,
    save_symbol_tables,
    save_graph_data,
    save_graph_html,
    save_complexity_report,
    save_rag_info,
    save_explanations,
    save_onboarding_doc,
    save_file_explanations_doc,
    save_file_explanations_json
)

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Project Gnosis — Code Archaeology Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline with LLM explanations (requires NVIDIA_API_KEY in .env)
  python run.py --url https://github.com/psf/black

  # Skip LLM calls (faster, no API key needed)
  python run.py --url https://github.com/realpython/codetiming --skip-llm

  # Limit LLM explanations to preserve free-tier quota
  python run.py --url https://github.com/tiangolo/fastapi --max-explain 5

  # Skip the pyvis HTML (faster on large repos)
  python run.py --url https://github.com/psf/black --no-html

  # Run 3 test retrieval queries after the pipeline completes
  python run.py --url https://github.com/realpython/codetiming --test-rag
        """
    )
    parser.add_argument(
        "--url", required=True,
        help="GitHub repository URL (public repos only in v1)"
    )
    parser.add_argument(
        "--output", default="./outputs",
        help="Directory to save all output files (default: ./outputs)"
    )
    parser.add_argument(
        "--no-html", action="store_true",
        help="Skip pyvis dependency_graph.html generation"
    )
    parser.add_argument(
        "--skip-llm", action="store_true",
        help="Skip Phase 6 (Explainability). Produces doc without explanations."
    )
    parser.add_argument(
        "--max-explain", type=int, default=20,
        help="Max files to explain via LLM (default: 20, NVIDIA free tier limit)"
    )
    parser.add_argument(
        "--test-rag", action="store_true",
        help="Run 3 test retrieval queries after pipeline completes"
    )
    args = parser.parse_args()

    # Environment validation
    github_token = os.getenv("GITHUB_TOKEN")
    nvidia_key   = os.getenv("NVIDIA_API_KEY")

    if not github_token:
        print("[INFO] No GITHUB_TOKEN in .env. Using unauthenticated mode.")
        print("       Limited to 60 GitHub API requests/hour.")
        print("       Add GITHUB_TOKEN to .env for 5000/hour.\n")

    if not nvidia_key and not args.skip_llm:
        print("[INFO] No NVIDIA_API_KEY in .env.")
        print("       Phase 6 (Explainability) will be skipped.")
        print("       Get a free key at https://build.nvidia.com")
        print("       Add NVIDIA_API_KEY=nvapi_... to your .env file.\n")
        args.skip_llm = True

    # Pre-validate repository size
    try:
        from src.utils.github_api import parse_github_url, fetch_repo_metadata, fetch_file_tree
        from src.utils.filters import should_include_file
        
        print("[Orchestrator] Validating repository size...")
        owner, repo_name = parse_github_url(args.url)
        metadata = fetch_repo_metadata(owner, repo_name, github_token)
        default_branch = metadata.get("default_branch", "main")
        tree_entries = fetch_file_tree(owner, repo_name, default_branch, github_token)
        filtered_files = [
            entry for entry in tree_entries 
            if should_include_file(entry["path"], entry.get("size", 0))
        ]
        
        max_sampled = int(os.getenv("MAX_SAMPLED_ANALYSIS_FILES", 3000))
        if len(filtered_files) > max_sampled:
            print(f"[ERROR] Repository {owner}/{repo_name} exceeds the maximum file limit of {max_sampled} files (found {len(filtered_files)}). Analysis rejected.")
            sys.exit(1)
        print(f"[Orchestrator] Validation complete. Found {len(filtered_files)} files. Proceeding with analysis.\n")
    except Exception as exc:
        print(f"[ERROR] Failed to validate repository size: {exc}")
        sys.exit(1)

    # Run the pipeline
    state = run_pipeline(
        args.url,
        github_token=github_token,
        max_explanations=args.max_explain,
        skip_llm=args.skip_llm
    )

    # Save all outputs
    print(f"\n[Orchestrator] Saving outputs to {args.output}/")
    print("-" * 55)
    save_manifest(state, args.output)
    save_symbol_tables(state, args.output)
    save_graph_data(state, args.output)
    save_complexity_report(state, args.output)
    save_rag_info(state, args.output)
    save_explanations(state, args.output)
    save_file_explanations_doc(state, args.output)
    save_file_explanations_json(state, args.output)
    doc_path = save_onboarding_doc(state, args.output)

    if not args.no_html:
        save_graph_html(state, args.output)

    # Final summary
    G = state.dependency_graph
    scores    = list(state.complexity_scores.values())
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in scores:
        risk_dist[s.risk_level] = risk_dist.get(s.risk_level, 0) + 1

    print(f"\n{'=' * 55}")
    print(f"  Project Gnosis — Complete")
    print(f"  Repository     : {state.owner}/{state.repo_name}")
    print(f"  Files analyzed : {len(state.file_manifest)}")
    print(f"  Import edges   : {G.number_of_edges() if G else 0}")
    print(f"  Circular deps  : {len(state.circular_deps)}")
    print(f"  CRITICAL       : {risk_dist['CRITICAL']}")
    print(f"  HIGH           : {risk_dist['HIGH']}")
    print(f"  MEDIUM         : {risk_dist['MEDIUM']}")
    print(f"  LOW            : {risk_dist['LOW']}")
    print(f"  Explained      : {len(state.explanations)}")
    print(f"{'=' * 55}")
    if doc_path:
        print(f"\n  ★  Primary output: {doc_path}")
    print(f"\n  All outputs in: {args.output}/")
    print(f"    onboarding.md              ← read this first")
    print(f"    dependency_graph.html      ← open in browser")
    print(f"    complexity_report.json     ← triage tech debt")
    print(f"    explanations.json          ← raw LLM output")
    print(f"    graph_data.json            ← graph structure")
    print(f"    symbol_tables.json         ← parsed symbols")
    print(f"    file_manifest.json         ← file inventory")
    print()

    if args.test_rag:
        _run_rag_test(state)


def _run_rag_test(state) -> None:
    from src.utils.retriever import CodeRetriever, DEFAULT_CHROMA_DB_PATH
    if not state.chroma_collection_name:
        print("[RAG Test] No collection found.")
        return
    try:
        retriever = CodeRetriever(
            state.chroma_collection_name,
            chroma_db_path=DEFAULT_CHROMA_DB_PATH
        )
    except Exception as e:
        print(f"[RAG Test] Could not connect: {e}")
        return

    print(f"\n[RAG Test] {retriever.count()} chunks. Running 3 queries...\n")
    queries = [
        "entry point and main function",
        "error handling and exceptions",
        "imports and external dependencies"
    ]
    for query in queries:
        print(f"  Query: '{query}'")
        results = retriever.query(query, n_results=2)
        if results:
            for r in results:
                print(f"    → {r['symbol_name']} in {r['file_path']} "
                      f"(dist={r['distance']:.3f})")
        else:
            print("    → No results")
        print()


if __name__ == "__main__":
    main()