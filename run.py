import os
import argparse
from dotenv import load_dotenv
from src.orchestrator import run_pipeline, save_manifest


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
    parser.add_argument(
        "--url",
        required=True,
        help="GitHub repository URL (public repos only in Phase 1)"
    )
    parser.add_argument(
        "--output",
        default="./outputs",
        help="Directory to save output files (default: ./outputs)"
    )
    args = parser.parse_args()

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("[INFO] No GITHUB_TOKEN in .env. Using unauthenticated mode.")
        print("       File tree fetch uses API (60 req/hr limit).")
        print("       File content uses raw URLs (no limit).")
        print("       For large repos, add GITHUB_TOKEN to .env\n")

    state = run_pipeline(args.url, github_token)
    manifest_path = save_manifest(state, args.output)

    print(f"\n{'=' * 55}")
    print(f"  Phase 1 Complete")
    print(f"  Files analyzed : {len(state.file_manifest)}")
    print(f"  Manifest at    : {manifest_path}")
    print(f"  Next: inspect the manifest, then run Phase 2")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    main()