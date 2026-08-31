import logging
import requests
import time
from typing import Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com"


def _create_raw_session() -> requests.Session:
    """Create a persistent HTTP session with connection pooling and exponential retries."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=25, pool_maxsize=25)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_RAW_SESSION = _create_raw_session()


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
    try:
        response = _RAW_SESSION.get(url, headers=_get_headers(token), timeout=15.0)
    except Exception as exc:
        raise ConnectionError(f"Failed to connect to GitHub API: {exc}")

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
    try:
        response = _RAW_SESSION.get(url, headers=_get_headers(token), timeout=25.0)
    except Exception as exc:
        raise ConnectionError(f"Failed to fetch file tree from GitHub: {exc}")

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
    path: str,
    session: Optional[requests.Session] = None,
    timeout: float = 15.0
) -> Optional[str]:
    """
    Fetch a single file's content via raw.githubusercontent.com.

    WHY RAW INSTEAD OF API:
    The GitHub API /contents endpoint counts against your 60/hr unauthenticated
    rate limit. raw.githubusercontent.com serves static files with a much more
    generous limit and requires no authentication for public repos.
    This means we can fetch 300 files without needing a token.

    Returns decoded string content, or None if the file is binary, not found, or fails.
    """
    url = f"{GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
    sess = session or _RAW_SESSION
    try:
        response = sess.get(url, timeout=timeout)
        if response.status_code != 200:
            response.close()
            return None
        text = response.text
        response.close()
        return text
    except Exception as exc:
        logger.warning("Transient failure fetching raw file '%s': %s", path, exc)
        return None


def fetch_file_contents_batch(
    owner: str,
    repo: str,
    branch: str,
    paths: list[str],
    delay: float = 0.05
) -> dict[str, str]:
    """
    Fetch content for multiple files concurrently using a ThreadPoolExecutor.
    Uses raw.githubusercontent.com for all fetches with pooled retries.

    Returns dict: { path -> content_string }
    Binary files, 404s, and failed downloads are excluded from the result.
    """
    import concurrent.futures

    results = {}
    total = len(paths)
    if total == 0:
        return results

    max_workers = min(12, total)

    def fetch_one(p):
        try:
            return p, fetch_file_content_raw(owner, repo, branch, p, session=_RAW_SESSION)
        except Exception as exc:
            logger.warning("Error fetching %s in worker thread: %s", p, exc)
            return p, None

    print(f"  Fetching {total} file contents concurrently (max {max_workers} threads)...")
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, path): path for path in paths}
        for future in concurrent.futures.as_completed(futures):
            try:
                path, content = future.result()
                if content is not None:
                    results[path] = content
            except Exception as exc:
                logger.warning("Worker future result failed: %s", exc)
            completed += 1
            if completed % 10 == 0 or completed == total:
                print(f"\r  Fetched {completed}/{total} files...", end="", flush=True)

    print()  # newline after progress
    return results