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
        raise ValueError(
            f"Repository not found: {owner}/{repo}. "
            "Check the URL. If this is a private repository, please provide a valid "
            "GitHub Personal Access Token (PAT) with 'repo' scope."
        )
    if response.status_code in (401, 403):
        raise PermissionError(
            f"Access denied or rate limit exceeded for {owner}/{repo}. "
            "If accessing a private repository, ensure your GitHub Personal Access Token (PAT) "
            "has 'repo' scope enabled."
        )

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

    if response.status_code == 404:
        raise ValueError(
            f"Repository or branch not found: {owner}/{repo}@{branch}. "
            "If this is a private repository, provide a valid GitHub PAT with 'repo' scope."
        )
    if response.status_code in (401, 403):
        raise PermissionError(
            f"Access denied fetching file tree for {owner}/{repo}. "
            "Ensure your GitHub Personal Access Token has 'repo' scope."
        )
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
    token: Optional[str] = None,
    session: Optional[requests.Session] = None,
    timeout: float = 15.0
) -> Optional[str]:
    """
    Fetch a single file's content.
    First attempts raw.githubusercontent.com (fast, with optional auth token).
    If that returns 404/403 and a token is provided (common for private repositories),
    falls back to GitHub API /contents with 'application/vnd.github.raw+json'.

    Returns decoded string content, or None if the file is binary, not found, or fails.
    """
    url = f"{GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
    sess = session or _RAW_SESSION
    headers = _get_headers(token) if token else {}
    try:
        response = sess.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            text = response.text
            response.close()
            return text
        response.close()

        # Fallback to GitHub REST API /contents for private repositories
        if token and response.status_code in (404, 403):
            api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
            api_headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.raw+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            api_resp = sess.get(api_url, headers=api_headers, timeout=timeout)
            if api_resp.status_code == 200:
                text = api_resp.text
                api_resp.close()
                return text
            api_resp.close()

        return None
    except Exception as exc:
        logger.warning("Transient failure fetching file '%s': %s", path, exc)
        return None


def fetch_file_contents_batch(
    owner: str,
    repo: str,
    branch: str,
    paths: list[str],
    token: Optional[str] = None,
    delay: float = 0.05
) -> dict[str, str]:
    """
    Fetch content for multiple files concurrently using a ThreadPoolExecutor.
    Uses raw.githubusercontent.com with persistent pooled sessions and API fallback.

    Returns dict: { path -> content_string }
    Binary files, 404s, and failed downloads are excluded from the result.
    """
    import concurrent.futures

    results = {}
    total = len(paths)
    if total == 0:
        return results

    max_workers = min(16, total)

    def fetch_one(p):
        try:
            return p, fetch_file_content_raw(owner, repo, branch, p, token=token, session=_RAW_SESSION)
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