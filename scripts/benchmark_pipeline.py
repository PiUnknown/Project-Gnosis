"""Offline size-tier benchmark for the synchronous and deferred index paths.

The generated repositories exercise Gnosis's real ingestion, parser, graph,
complexity, code-RAG, and report stages. GitHub and NVIDIA calls are replaced
with deterministic local fixtures, so these measurements isolate local work
and do not represent production network latency.

Run: python scripts/benchmark_pipeline.py --trials 3
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import io
import json
import logging
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb
from src.agents import code_rag, ingestion
from src.api import pipeline_runner
from src.api.job_store import JobStore


class PhaseCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.samples: dict[str, list[float]] = {}

    def emit(self, record):
        if record.msg != "pipeline_phase_elapsed phase=%s duration_ms=%.2f rss_mb=%.0f vms_mb=%.0f":
            return
        phase, duration_ms, *_ = record.args
        self.samples.setdefault(phase, []).append(float(duration_ms))


def make_repository(file_count: int):
    contents: dict[str, str] = {}
    tree = []
    for index in range(file_count):
        path = f"module_{index:05}.py"
        previous = (
            f"from module_{index - 1:05} import transform as previous_transform\n"
            if index else ""
        )
        source = (
            f'"""Synthetic dependency-chain module {index}."""\n'
            f"{previous}"
            "def transform(value):\n"
            "    if value < 0:\n"
            "        return 0\n"
            "    if value == 0:\n"
            f"        return {index}\n"
            f"    return value + {index}\n"
        )
        contents[path] = source
        tree.append({
            "path": path,
            "size": len(source.encode("utf-8")),
            "sha": f"{index:040x}",
            "type": "blob",
        })
    return tree, contents


def benchmark_one(file_count: int, deferred: bool):
    tree, contents = make_repository(file_count)
    store = JobStore()
    repo_url = f"https://github.com/benchmark/repository-{file_count}"
    job_id = store.create(repo_url, {"defer_code_index": deferred})
    capture = PhaseCapture()
    metrics_logger = logging.getLogger("src.utils.metrics")
    old_level = metrics_logger.level
    metrics_logger.setLevel(logging.INFO)
    metrics_logger.addHandler(capture)
    chroma_client = chromadb.EphemeralClient()

    def fetch_contents(owner, repo, branch, paths, **kwargs):
        return {path: contents[path] for path in paths if path in contents}

    def fake_embeddings(texts):
        vector = [0.125] * code_rag.EMBEDDING_DIM
        return [vector.copy() for _ in texts]

    start = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="gnosis-chroma-") as chroma_dir:
            with patch.object(pipeline_runner, "store", store), \
                 patch.object(
                     pipeline_runner,
                     "fetch_repo_metadata",
                     return_value={"default_branch": "main", "size": 0},
                 ), \
                 patch.object(ingestion, "fetch_file_tree", return_value=tree), \
                 patch.object(ingestion, "fetch_file_contents_batch", side_effect=fetch_contents), \
                 patch.object(code_rag, "DEFAULT_CHROMA_DB_PATH", chroma_dir), \
                 patch.object(chromadb, "PersistentClient", return_value=chroma_client), \
                 patch.object(code_rag, "embed_texts", side_effect=fake_embeddings), \
                 contextlib.redirect_stdout(io.StringIO()):
                pipeline_runner.run(
                    job_id,
                    repo_url,
                    {"defer_code_index": deferred},
                )
    finally:
        try:
            chroma_client.delete_collection(
                name=code_rag.make_collection_name(
                    "benchmark", f"repository-{file_count}", job_id
                )
            )
        except Exception:
            pass
        metrics_logger.removeHandler(capture)
        metrics_logger.setLevel(old_level)

    elapsed_ms = (time.perf_counter() - start) * 1000
    job = store.get(job_id)
    if not job or job.status != "complete":
        raise RuntimeError(f"{file_count} files (deferred={deferred}) failed: {job.error if job else 'missing job'}")

    return {
        "initial_result_ms": elapsed_ms,
        "phase_ms": {name: values[-1] for name, values in capture.samples.items()},
        "files_discovered": job.result["files_discovered"],
        "files_analyzed": job.result["files_analyzed"],
        "analysis_mode": job.result["analysis_mode"],
        "code_index_status": job.result["code_index_status"],
    }


def summarize(values: list[dict]) -> dict:
    phase_names = sorted({name for value in values for name in value["phase_ms"]})
    return {
        "initial_result_ms_median": round(statistics.median(v["initial_result_ms"] for v in values), 1),
        "phase_ms_median": {
            phase: round(statistics.median(v["phase_ms"].get(phase, 0.0) for v in values), 1)
            for phase in phase_names
        },
        "files_discovered": values[-1]["files_discovered"],
        "files_analyzed": values[-1]["files_analyzed"],
        "analysis_mode": values[-1]["analysis_mode"],
        "code_index_status": values[-1]["code_index_status"],
        "trials": values,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--small", type=int, default=20)
    parser.add_argument("--medium", type=int, default=200)
    parser.add_argument("--large", type=int, default=1100)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be at least 1")

    results = {}
    for size_name, file_count in (
        ("small", args.small),
        ("medium", args.medium),
        ("large", args.large),
    ):
        raw_trials = {"baseline": [], "deferred": []}
        for trial_index in range(args.trials):
            order = (False, True) if trial_index % 2 == 0 else (True, False)
            for deferred in order:
                key = "deferred" if deferred else "baseline"
                raw_trials[key].append(benchmark_one(file_count, deferred))
                gc.collect()
        variants = {
            key: summarize(trial_results)
            for key, trial_results in raw_trials.items()
        }
        baseline = variants["baseline"]["initial_result_ms_median"]
        deferred_ms = variants["deferred"]["initial_result_ms_median"]
        variants["deferred"]["initial_result_reduction_pct"] = round(
            ((baseline - deferred_ms) / baseline * 100) if baseline else 0.0, 1
        )
        results[size_name] = variants

    print(json.dumps({
        "benchmark": "offline synthetic repository size tiers",
        "external_network_latency_measured": False,
        "embedding_service_measured": False,
        "trials_per_variant": args.trials,
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    main()
