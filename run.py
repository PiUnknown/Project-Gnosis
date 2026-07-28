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
    save_rag_info
)

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Project Gnosis — Code Archaeology Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --url https://github.com/psf/black
  python run.py --url https://github.com/realpython/codetiming --no-html
  python run.py --url https://github.com/tiangolo/fastapi --test-rag
        """
    )
    parser.add_argument("--url", required=True, help="GitHub repository URL")
    parser.add_argument("--output", default="./outputs", help="Output directory")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip pyvis HTML generation")
    parser.add_argument("--test-rag", action="store_true",
                        help="Run 3 test queries against the RAG collection after pipeline")
    args = parser.parse_args()

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("[INFO] No GITHUB_TOKEN in .env. Using unauthenticated mode.\n")

    state = run_pipeline(args.url, github_token)

    print(f"\n[Orchestrator] Saving outputs...")
    save_manifest(state, args.output)
    save_symbol_tables(state, args.output)
    save_graph_data(state, args.output)
    save_complexity_report(state, args.output)
    save_rag_info(state, args.output)

    if not args.no_html:
        save_graph_html(state, args.output)

    scores = list(state.complexity_scores.values())
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in scores:
        risk_dist[s.risk_level] = risk_dist.get(s.risk_level, 0) + 1

    print(f"\n{'=' * 55}")
    print(f"  Phase 5 Complete")
    print(f"  Files analyzed   : {len(state.file_manifest)}")
    print(f"  Collection       : {state.chroma_collection_name}")
    print(f"  ChromaDB at      : ./chroma_db/")
    print(f"  CRITICAL         : {risk_dist['CRITICAL']}")
    print(f"  HIGH             : {risk_dist['HIGH']}")
    print(f"  Outputs at       : {args.output}/")
    print(f"    rag_info.json")
    print(f"    complexity_report.json")
    print(f"    dependency_graph.html")
    print(f"{'=' * 55}\n")

    if args.test_rag:
        _run_rag_test(state)


def _run_rag_test(state) -> None:
    """
    Run 3 test queries against the built collection to verify retrieval works.
    Use --test-rag flag to activate after Phase 5 completes.
    """
    from src.utils.retriever import CodeRetriever, DEFAULT_CHROMA_DB_PATH

    if not state.chroma_collection_name:
        print("[RAG Test] No collection found. Did Phase 5 complete?")
        return

    try:
        retriever = CodeRetriever(
            state.chroma_collection_name,
            chroma_db_path=DEFAULT_CHROMA_DB_PATH
        )
    except Exception as e:
        print(f"[RAG Test] Could not connect: {e}")
        return

    print(f"\n[RAG Test] Collection has {retriever.count()} chunks")
    print(f"[RAG Test] Running 3 test queries...\n")

    test_queries = [
        "entry point and main function",
        "error handling and exceptions",
        "imports and external dependencies",
    ]

    for query in test_queries:
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