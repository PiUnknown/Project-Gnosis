"""Measure public GitHub repositories with and without synchronous indexing.

Each repository snapshot is fetched once and reused for baseline and deferred
runs. This makes both runs use identical source and network inputs. NVIDIA
embedding inference is replaced with deterministic vectors and Chroma is
in-memory. GitHub snapshot time is reported separately.

Run: python scripts/benchmark_public_repos.py
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb
from src.agents import code_rag
from src.agents.ingestion import get_max_sampled_analysis_files
from src.api import pipeline_runner
from src.api.job_store import JobStore
from src.utils.filters import should_include_file
from src.utils.github_api import (
    fetch_file_contents_batch,
    fetch_file_tree,
    fetch_repo_metadata,
    parse_github_url,
)


REPOSITORIES = (
    ("small", "https://github.com/psf/requests"),
    ("medium", "https://github.com/psf/black"),
    ("large", "https://github.com/numpy/numpy"),
)


class PhaseCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.samples: dict[str, list[float]] = {}

    def emit(self, record):
        if record.msg != "pipeline_phase_elapsed phase=%s duration_ms=%.2f rss_mb=%.0f vms_mb=%.0f":
            return
        phase, duration_ms, *_ = record.args
        self.samples.setdefault(phase, []).append(float(duration_ms))


def fetch_snapshot(repo_url: str) -> dict:
    owner, repo = parse_github_url(repo_url)
    t0 = time.perf_counter()
    metadata = fetch_repo_metadata(owner, repo)
    metadata_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    tree = fetch_file_tree(owner, repo, metadata["default_branch"])
    tree_ms = (time.perf_counter() - t0) * 1000

    selected = [
        entry for entry in tree
        if should_include_file(entry["path"], entry.get("size", 0))
    ]
    selected.sort(key=lambda entry: (entry["path"].count("/"), entry["path"]))
    selected = selected[:get_max_sampled_analysis_files()]
    paths = [entry["path"] for entry in selected]

    t0 = time.perf_counter()
    contents = fetch_file_contents_batch(
        owner,
        repo,
        metadata["default_branch"],
        paths,
        repo_size_kb=int(metadata.get("size") or 0),
    )
    contents_ms = (time.perf_counter() - t0) * 1000
    return {
        "metadata": metadata,
        "tree": tree,
        "contents": contents,
        "fetch_ms": round(metadata_ms + tree_ms + contents_ms, 1),
        "metadata_fetch_ms": round(metadata_ms, 1),
        "tree_fetch_ms": round(tree_ms, 1),
        "contents_fetch_ms": round(contents_ms, 1),
        "files_in_tree": len(tree),
        "files_selected": len(selected),
        "files_fetched": len(contents),
    }


def run_one(repo_url: str, snapshot: dict, defer_code_index: bool) -> dict:
    store = JobStore()
    job_id = store.create(repo_url, {"defer_code_index": defer_code_index})
    capture = PhaseCapture()
    metrics_logger = logging.getLogger("src.utils.metrics")
    old_level = metrics_logger.level
    metrics_logger.setLevel(logging.INFO)
    metrics_logger.addHandler(capture)
    chroma_client = chromadb.EphemeralClient()

    def fake_embeddings(texts):
        vector = [0.125] * code_rag.EMBEDDING_DIM
        return [vector.copy() for _ in texts]

    start = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="gnosis-public-benchmark-") as chroma_dir:
            with patch.object(pipeline_runner, "store", store), \
                 patch.object(
                     pipeline_runner,
                     "fetch_repo_metadata",
                     return_value=snapshot["metadata"],
                 ), \
                 patch(
                     "src.agents.ingestion.fetch_file_tree",
                     return_value=snapshot["tree"],
                 ), \
                 patch(
                     "src.agents.ingestion.fetch_file_contents_batch",
                     side_effect=lambda owner, repo, branch, paths, **kwargs: {
                         path: snapshot["contents"][path]
                         for path in paths
                         if path in snapshot["contents"]
                     },
                 ), \
                 patch.object(code_rag, "DEFAULT_CHROMA_DB_PATH", chroma_dir), \
                 patch.object(chromadb, "PersistentClient", return_value=chroma_client), \
                 patch.object(code_rag, "embed_texts", side_effect=fake_embeddings), \
                 contextlib.redirect_stdout(io.StringIO()):
                pipeline_runner.run(
                    job_id,
                    repo_url,
                    {"defer_code_index": defer_code_index},
                )
    finally:
        try:
            job = store.get(job_id)
            if job:
                owner, repo = job.result["repo"].split("/", 1) if job.result else ("", "")
                if owner and repo:
                    chroma_client.delete_collection(
                        name=code_rag.make_collection_name(owner, repo, job_id)
                    )
        except Exception:
            pass
        metrics_logger.removeHandler(capture)
        metrics_logger.setLevel(old_level)

    elapsed_ms = (time.perf_counter() - start) * 1000
    job = store.get(job_id)
    if not job or job.status != "complete":
        raise RuntimeError(f"{repo_url} failed: {job.error if job else 'missing job'}")
    return {
        "analysis_ms_excluding_github_fetch": round(elapsed_ms, 1),
        "estimated_total_with_shared_github_snapshot_ms": round(
            elapsed_ms + snapshot["fetch_ms"], 1
        ),
        "phase_ms": {
            phase: round(values[-1], 1)
            for phase, values in capture.samples.items()
        },
        "files_discovered": job.result["files_discovered"],
        "files_analyzed": job.result["files_analyzed"],
        "analysis_mode": job.result["analysis_mode"],
        "code_index_status": job.result["code_index_status"],
    }


def main():
    results = {}
    for index, (tier, repo_url) in enumerate(REPOSITORIES):
        print(f"Fetching public snapshot for {tier}: {repo_url}", file=sys.stderr)
        snapshot = fetch_snapshot(repo_url)
        order = (False, True) if index % 2 == 0 else (True, False)
        variants = {}
        for deferred in order:
            key = "deferred" if deferred else "baseline"
            variants[key] = run_one(repo_url, snapshot, deferred)
        baseline = variants["baseline"]["analysis_ms_excluding_github_fetch"]
        deferred_ms = variants["deferred"]["analysis_ms_excluding_github_fetch"]
        variants["initial_result_reduction_pct"] = round(
            ((baseline - deferred_ms) / baseline * 100) if baseline else 0.0, 1
        )
        variants["repository"] = repo_url
        variants["snapshot"] = {
            key: snapshot[key]
            for key in (
                "fetch_ms",
                "metadata_fetch_ms",
                "tree_fetch_ms",
                "contents_fetch_ms",
                "files_in_tree",
                "files_selected",
                "files_fetched",
            )
        }
        results[tier] = variants

    print(json.dumps({
        "benchmark": "public GitHub snapshots reused for baseline and deferred runs",
        "github_fetches_measured": True,
        "nvidia_embedding_service_measured": False,
        "queue_and_production_host_measured": False,
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
