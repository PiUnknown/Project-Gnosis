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
    save_explanations
)

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Project Gnosis — Code Archaeology Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --url https://github.com/psf/black
  python run.py --url https://github.com/realpython/codetiming --skip-llm
  python run.py --url https://github.com/tiangolo/fastapi --max-explain 10
  python run.py --url https://github.com/tiangolo/fastapi --test-rag
        """
    )
    parser.add_argument("--url",         required=True, help="GitHub repository URL")
    parser.add_argument("--output",      default="./outputs", help="Output directory")
    parser.add_argument("--no-html",     action="store_true",
                        help="Skip pyvis HTML generation")
    parser.add_argument("--skip-llm",    action="store_true",
                        help="Skip Phase 6 (no Groq calls). Useful if no API key.")
    parser.add_argument("--max-explain", type=int, default=20,
                        help="Max files to explain via LLM (default 20, free tier limit)")
    parser.add_argument("--test-rag",    action="store_true",
                        help="Run 3 test queries against ChromaDB after pipeline")
    args = parser.parse_args()

    github_token = os.getenv("GITHUB_TOKEN")
    groq_key     = os.getenv("GROQ_API_KEY")

    if not github_token:
        print("[INFO] No GITHUB_TOKEN in .env. Using unauthenticated mode.\n")

    if not groq_key and not args.skip_llm:
        print("[INFO] No GROQ_API_KEY in .env.")
        print("       Phase 6 (Explainability) will be skipped.")
        print("       Get a free key at https://console.groq.com\n")
        args.skip_llm = True

    state = run_pipeline(
        repo_url=args.url,
        github_token=github_token,
        max_explanations=args.max_explain,
        skip_llm=args.skip_llm
    )

    print(f"\n[Orchestrator] Saving outputs...")
    save_manifest(state, args.output)
    save_symbol_tables(state, args.output)
    save_graph_data(state, args.output)
    save_complexity_report(state, args.output)
    save_rag_info(state, args.output)
    save_explanations(state, args.output)

    if not args.no_html:
        save_graph_html(state, args.output)

    G = state.dependency_graph
    scores = list(state.complexity_scores.values())
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in scores:
        risk_dist[s.risk_level] = risk_dist.get(s.risk_level, 0) + 1

    print(f"\n{'=' * 55}")
    print(f"  Phase 6 Complete")
    print(f"  Files analyzed   : {len(state.file_manifest)}")
    print(f"  Files explained  : {len(state.explanations)}")
    print(f"  CRITICAL         : {risk_dist['CRITICAL']}")
    print(f"  HIGH             : {risk_dist['HIGH']}")
    print(f"  Outputs at       : {args.output}/")
    print(f"    explanations.json")
    print(f"    complexity_report.json")
    print(f"    dependency_graph.html")
    print(f"  Next: review explanations.json, then run Phase 7")
    print(f"{'=' * 55}\n")

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
    for query in ["entry point and main function",
                  "error handling and exceptions",
                  "imports and external dependencies"]:
        print(f"  Query: '{query}'")
        results = retriever.query(query, n_results=2)
        for r in results:
            print(f"    → {r['symbol_name']} in {r['file_path']} "
                  f"(dist={r['distance']:.3f})")
        print()


if __name__ == "__main__":
    main()