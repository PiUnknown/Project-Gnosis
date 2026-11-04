import logging
import os
import requests
import time
import tarfile
import base64
from urllib.parse import quote, unquote, urlencode, urlsplit
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
    url = url.strip()
    if "://" not in url:
        url = f"https://{url.lstrip('/')}"

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or host not in {"github.com", "www.github.com"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            f"Cannot parse GitHub URL: {url}. Expected https://github.com/owner/repo"
        )

    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Cannot parse GitHub URL: {url}. Expected https://github.com/owner/repo"
        )

    owner, repo = parts[:2]
    if repo.endswith(".git"):
        repo = repo[:-4]
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
    url = (
        f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}"
    )
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
    url = (
        f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/git/trees/{quote(branch, safe='')}?recursive=1"
    )
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
        raise ValueError(
            f"GitHub returned a truncated file tree for {owner}/{repo} "
            "(over 100,000 entries). Analysis stopped to avoid producing "
            "a report from an incomplete repository listing."
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
    url = (
        f"{GITHUB_RAW_BASE}/{quote(owner, safe='')}/{quote(repo, safe='')}/"
        f"{quote(branch, safe='')}/{quote(path, safe='/')}"
    )
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
            api_url = (
                f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/"
                f"{quote(repo, safe='')}/contents/{quote(path, safe='/')}?"
                f"{urlencode({'ref': branch})}"
            )
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


def fetch_file_content_by_sha(
    owner: str,
    repo: str,
    blob_sha: str,
    token: Optional[str] = None,
    timeout: float = 15.0,
) -> Optional[str]:
    """Fetch the exact text version identified by a Git blob SHA.

    This supports on-demand explanations when vector indexing was deferred,
    while keeping source tied to the snapshot that was analyzed.
    """
    if not isinstance(blob_sha, str) or len(blob_sha) not in (40, 64):
        return None
    if any(char not in "0123456789abcdefABCDEF" for char in blob_sha):
        return None

    url = (
        f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/git/blobs/{quote(blob_sha, safe='')}"
    )
    response = None
    try:
        response = _RAW_SESSION.get(url, headers=_get_headers(token), timeout=timeout)
        if response.status_code != 200:
            return None
        body = response.json()
        content = body.get("content")
        if body.get("encoding") != "base64" or not isinstance(content, str):
            return None
        return base64.b64decode(content, validate=False).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Could not fetch Git blob %s for %s/%s: %s", blob_sha, owner, repo, exc)
        return None
    finally:
        if response is not None:
            response.close()


def _fetch_archive_contents(
    owner: str,
    repo: str,
    branch: str,
    paths: list[str],
    timeout: tuple[float, float] = (10.0, 60.0),
) -> dict[str, str]:
    """Read selected files from one public GitHub tarball response.

    This avoids hundreds of separate raw-content requests for medium-sized
    public repositories. The tar stream is never extracted to disk; only paths
    from the already-filtered GitHub tree are retained. Callers fall back to
    the pooled per-file fetch path for missing files or any archive error.
    """
    wanted = set(paths)
    if not wanted:
        return {}

    url = (
        f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/tarball/{quote(branch, safe='')}"
    )
    response = None
    contents: dict[str, str] = {}
    try:
        response = _RAW_SESSION.get(
            url,
            headers=_get_headers(),
            timeout=timeout,
            stream=True,
        )
        response.raise_for_status()
        response.raw.decode_content = True

        with tarfile.open(fileobj=response.raw, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                _, separator, relative_path = member.name.partition("/")
                if not separator or relative_path not in wanted:
                    continue
                file_stream = archive.extractfile(member)
                if file_stream is None:
                    continue
                with file_stream:
                    contents[relative_path] = file_stream.read().decode(
                        "utf-8", errors="replace"
                    )
                if len(contents) == len(wanted):
                    break
    except Exception as exc:
        logger.info(
            "GitHub archive fetch unavailable for %s/%s (%s); "
            "falling back to per-file requests.",
            owner,
            repo,
            exc,
        )
        return {}
    finally:
        if response is not None:
            response.close()

    return contents


def fetch_file_contents_batch(
    owner: str,
    repo: str,
    branch: str,
    paths: list[str],
    token: Optional[str] = None,
    delay: float = 0.05,
    repo_size_kb: Optional[int] = None,
) -> dict[str, str]:
    """
    Fetch content for multiple files concurrently using a ThreadPoolExecutor.
    Uses raw.githubusercontent.com with persistent pooled sessions and API fallback.

    Returns dict: { path -> content_string }
    Binary files, 404s, and failed downloads are excluded from the result.
    """
    import concurrent.futures

    results: dict[str, str] = {}
    total = len(paths)
    if total == 0:
        return results

    # A bounded archive avoids hundreds of individual requests for medium
    # public repositories. Private repos and larger trees retain the pooled
    # raw-content path. Missing archive entries fall back individually.
    try:
        archive_min_files = max(1, int(os.getenv("GITHUB_ARCHIVE_MIN_FILES", "80")))
    except ValueError:
        archive_min_files = 80
    try:
        archive_max_repo_kb = max(
            0, int(os.getenv("GITHUB_ARCHIVE_MAX_REPO_KB", str(80 * 1024)))
        )
    except ValueError:
        archive_max_repo_kb = 80 * 1024
    if (
        token is None
        and repo_size_kb is not None
        and 0 < repo_size_kb <= archive_max_repo_kb
        and total >= archive_min_files
    ):
        print(f"  Fetching {total} files from one public GitHub archive...")
        results = _fetch_archive_contents(owner, repo, branch, paths)
        paths = [path for path in paths if path not in results]
        total = len(paths)
        if not paths:
            print(f"  Fetched {len(results)} files from archive.")
            return results
        if results:
            print(
                f"  Archive supplied {len(results)} files; fetching "
                f"{total} missing files individually..."
            )

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
