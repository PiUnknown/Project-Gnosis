"""
src/utils/explanation_cache.py

Disk-based cache for Agent 6 (Explainability) LLM output.

WHY THIS EXISTS:
Groq's free tier has a 100,000 token/day hard ceiling. A single run of
Agent 6 on a mid-sized repo costs ~50,000 tokens. Two runs in one day
hits the wall. The fix: persist each explanation to disk after the first
Groq call. Subsequent runs on the same repo load from cache and cost zero
tokens, unless a file's content has changed.

CACHE KEY DESIGN:
  "{owner}::{repo_name}::{file_path}::{file_sha}"

  - owner + repo_name: scopes the cache to a specific repo
  - file_path: scopes to one file within that repo
  - file_sha: the Git blob SHA from the GitHub API (a content hash)
    This means the cache entry is automatically invalidated when the
    file changes — no TTL needed, no manual cache-busting.

  The key string is SHA-256 hashed to produce a safe filename.

STORAGE:
  One JSON file per cached explanation.
  Location: ./explanation_cache/{first2chars}/{hash}.json
  Subdirectory by first 2 chars avoids putting 10,000 files in one dir.
  Each JSON file contains:
    {
      "owner": str,
      "repo_name": str,
      "file_path": str,
      "file_sha": str,
      "explanation": str,
      "cached_at": ISO timestamp
    }

WHY NOT SQLITE:
  JSON files are inspectable with any text editor. During development
  and demo debugging it is useful to open a cache file and read the
  stored explanation directly. SQLite requires a tool.

WHY NOT A SINGLE JSON FILE:
  A single cache.json with thousands of entries gets expensive to
  parse and write on every hit. Individual files mean O(1) reads.
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Default cache directory relative to project root
DEFAULT_CACHE_DIR = "./explanation_cache"


def make_cache_key(
    owner: str,
    repo_name: str,
    file_path: str,
    file_sha: str
) -> str:
    """
    Build a deterministic cache key string for one file version.

    The key encodes repo identity (owner + repo_name), file identity
    (file_path), and file content version (file_sha). Two files with
    the same path but different SHAs produce different keys — so a cache
    hit only occurs when the file content is byte-for-byte identical to
    the previously explained version.
    """
    raw = f"{owner}::{repo_name}::{file_path}::{file_sha}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached_explanation(
    cache_key: str,
    cache_dir: str = DEFAULT_CACHE_DIR
) -> Optional[str]:
    """
    Return the cached explanation string for this key, or None on miss.

    Never raises. A missing file, corrupted JSON, or unexpected key
    structure all return None — the caller falls through to Groq.
    """
    path = _key_to_path(cache_key, cache_dir)
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        explanation = data.get("explanation")
        if explanation and isinstance(explanation, str):
            return explanation
        return None
    except Exception:
        # Corrupted file: treat as miss, not error
        return None


def save_explanation(
    cache_key: str,
    explanation: str,
    owner: str,
    repo_name: str,
    file_path: str,
    file_sha: str,
    cache_dir: str = DEFAULT_CACHE_DIR
) -> bool:
    """
    Persist an explanation to disk.

    Returns True on success, False if the write failed.
    Failure is non-fatal — the pipeline continues without caching.
    """
    path = _key_to_path(cache_key, cache_dir)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "owner":       owner,
            "repo_name":   repo_name,
            "file_path":   file_path,
            "file_sha":    file_sha,
            "explanation": explanation,
            "cached_at":   datetime.now(timezone.utc).isoformat()
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def cache_stats(cache_dir: str = DEFAULT_CACHE_DIR) -> dict:
    """
    Return basic stats about the cache directory.
    Used by the agent to print a summary line at startup.
    """
    root = Path(cache_dir)
    if not root.exists():
        return {"entries": 0, "size_kb": 0}

    json_files = list(root.rglob("*.json"))
    total_bytes = sum(f.stat().st_size for f in json_files if f.is_file())
    return {
        "entries": len(json_files),
        "size_kb": round(total_bytes / 1024, 1)
    }


def _key_to_path(cache_key: str, cache_dir: str) -> Path:
    """
    Convert a cache key (SHA-256 hex) to a filesystem path.
    Uses the first 2 characters as a subdirectory to avoid
    putting all entries in one flat directory.
    """
    return Path(cache_dir) / cache_key[:2] / f"{cache_key}.json"