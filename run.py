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
  python run.py --url https://github.com/realpython/codetiming --no-html
        """
    )
    parser.add_argument("--url", required=True, help="GitHub repository URL")
    parser.add_argument("--output", default="./outputs", help="Output directory")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip pyvis HTML generation")
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

    if not args.no_html:
        save_graph_html(state, args.output)

    scores = list(state.complexity_scores.values())
    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in scores:
        risk_dist[s.risk_level] = risk_dist.get(s.risk_level, 0) + 1

    print(f"\n{'=' * 55}")
    print(f"  Phase 4 Complete")
    print(f"  Files analyzed   : {len(state.file_manifest)}")
    print(f"  Files scored     : {len(scores)}")
    print(f"  CRITICAL         : {risk_dist['CRITICAL']}")
    print(f"  HIGH             : {risk_dist['HIGH']}")
    print(f"  MEDIUM           : {risk_dist['MEDIUM']}")
    print(f"  LOW              : {risk_dist['LOW']}")
    print(f"  Outputs at       : {args.output}/")
    print(f"    complexity_report.json")
    print(f"    dependency_graph.html")
    print(f"  Next: run Phase 5 (Code RAG Agent)")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    main()