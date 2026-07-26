import os
import argparse
from dotenv import load_dotenv
from src.orchestrator import (
    run_pipeline,
    save_manifest,
    save_symbol_tables,
    save_graph_data,
    save_graph_html
)

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Project Gnosis — Code Archaeology Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --url https://github.com/psf/black
  python run.py --url https://github.com/tiangolo/fastapi --output ./my_outputs
        """
    )
    parser.add_argument("--url", required=True, help="GitHub repository URL")
    parser.add_argument("--output", default="./outputs", help="Output directory")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip pyvis HTML generation (faster)")
    args = parser.parse_args()

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("[INFO] No GITHUB_TOKEN in .env. Using unauthenticated mode.\n")

    state = run_pipeline(args.url, github_token)

    print(f"\n[Orchestrator] Saving outputs...")
    save_manifest(state, args.output)
    save_symbol_tables(state, args.output)
    save_graph_data(state, args.output)

    if not args.no_html:
        save_graph_html(state, args.output)

    G = state.dependency_graph
    print(f"\n{'=' * 55}")
    print(f"  Phase 3 Complete")
    print(f"  Files analyzed   : {G.number_of_nodes() if G else 0}")
    print(f"  Import edges     : {G.number_of_edges() if G else 0}")
    print(f"  Circular deps    : {len(state.circular_deps)}")
    print(f"  Outputs at       : {args.output}/")
    print(f"    file_manifest.json")
    print(f"    symbol_tables.json")
    print(f"    graph_data.json")
    print(f"    dependency_graph.html")
    print(f"  Next: open dependency_graph.html, then run Phase 4")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    main()