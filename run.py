import os
import argparse
from dotenv import load_dotenv
from src.orchestrator import run_pipeline, save_manifest, save_symbol_tables

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
    args = parser.parse_args()

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("[INFO] No GITHUB_TOKEN in .env. Using unauthenticated mode.\n")

    state = run_pipeline(args.url, github_token)

    save_manifest(state, args.output)
    save_symbol_tables(state, args.output)

    print(f"\n{'=' * 55}")
    print(f"  Phase 2 Complete")
    print(f"  Files parsed     : {len(state.symbol_tables)}")
    print(f"  Outputs at       : {args.output}/")
    print(f"    file_manifest.json")
    print(f"    symbol_tables.json")
    print(f"  Next: inspect symbol_tables.json, then run Phase 3")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    main()