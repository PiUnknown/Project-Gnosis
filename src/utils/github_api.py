import requests
import time
from typing import Optional


GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"


def parse_github_url(url: str) -> tuple[str, str]:
    """
    Extract owner and repo name from a GitHub URL.

    Handles:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      https://github.com/owner/repo/
    """
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    parts = url.replace("https://", "").replace("http://", "").split("/")
    # Expected: ["github.com", "owner", "repo"]
    if len(parts) < 3:
        raise ValueError(f"Cannot parse GitHub URL: {url}. Expected format: https://github.com/owner/repo")

    owner = parts[1]
    repo = parts[2]
    return owner, repo


def _get_headers(token: Optional[str] = None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_repo_metadata(owner: str, repo: str, token: Optional[str] = None) -> dict:
    """
    Fetch basic repo metadata: default branch, description, size.
    This is 1 API call. Uses the authenticated token if provided.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    response = requests.get(url, headers=_get_headers(token))

    if response.status_code == 404:
        raise ValueError(f"Repository not found: {owner}/{repo}. Check the URL and make sure the repo is public.")
    if response.status_code == 403:
        raise PermissionError(
            "GitHub API rate limit exceeded or access denied. "
            "Add a GITHUB_TOKEN to your .env file to increase rate limits."
        )
    if response.status_code == 401:
        raise PermissionError("Invalid GITHUB_TOKEN. Check your token in .env.")

    response.raise_for_status()
    return response.json()


def fetch_file_tree(
    owner: str,
    repo: str,
    branch: str,
    token: Optional[str] = None
) -> list[dict]:
    """
    Fetch the complete recursive file tree for a repository.
    This is 1 API call regardless of repo size.

    Returns list of file entries:
    [{"path": str, "type": "blob"|"tree", "size": int, "sha": str}, ...]
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    response = requests.get(url, headers=_get_headers(token))

    if response.status_code == 409:
        raise ValueError(f"Repository {owner}/{repo} is empty.")

    response.raise_for_status()
    data = response.json()

    if data.get("truncated"):
        print(
            "[WARNING] Repository tree is truncated by GitHub (>100k entries). "
            "Only partial results will be analyzed."
        )

    # Return only file blobs, not directory entries
    return [entry for entry in data.get("tree", []) if entry["type"] == "blob"]


def fetch_file_content_raw(
    owner: str,
    repo: str,
    branch: str,
    path: str
) -> Optional[str]:
    """
    Fetch a single file's content via raw.githubusercontent.com.

    WHY RAW INSTEAD OF API:
    The GitHub API /contents endpoint counts against your 60/hr unauthenticated
    rate limit. raw.githubusercontent.com serves static files with a much more
    generous limit and requires no authentication for public repos.
    This means we can fetch 300 files without needing a token.

    Returns decoded string content, or None if the file is binary or not found.
    """
    url = f"{GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
    response = requests.get(url)

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        return None

    # If the response is binary (images, compiled files), decoding will fail
    try:
        return response.text
    except Exception:
        return None


def fetch_file_contents_batch(
    owner: str,
    repo: str,
    branch: str,
    paths: list[str],
    delay: float = 0.05
) -> dict[str, str]:
    """
    Fetch content for multiple files with a small delay between requests.
    Uses raw.githubusercontent.com for all fetches (no API rate limit impact).

    Returns dict: { path -> content_string }
    Binary files and 404s are excluded from the result.
    """
    results = {}
    total = len(paths)

    for i, path in enumerate(paths):
        print(f"\r  Fetching file contents: {i + 1}/{total}", end="", flush=True)
        content = fetch_file_content_raw(owner, repo, branch, path)
        if content is not None:
            results[path] = content
        time.sleep(delay)

    print()  # newline after progress
    return results