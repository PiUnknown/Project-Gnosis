"""Regression coverage for API abuse, credential handling, and retained data."""
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.agents.dependency_graph import _detect_cycles, _sample_cycles
from src.api import main
from src.api.job_store import JobStore
from src.api.rate_limit import reset_local_rate_limits
from src.utils.chroma_retention import cleanup_expired_collections
from src.utils.token_crypto import TokenEncryptionError, encrypt_github_token


@pytest.fixture(autouse=True)
def clean_local_state():
    reset_local_rate_limits()


def test_submission_rate_limit_returns_429(monkeypatch):
    job_store = JobStore()
    monkeypatch.setattr(main, "store", job_store)
    monkeypatch.setattr(main, "enqueue_analysis_job", lambda *args, **kwargs: (False, "test"))
    monkeypatch.setenv("ANALYZE_RATE_LIMIT", "1")
    monkeypatch.setenv("ANALYZE_RATE_WINDOW_SECONDS", "60")

    with TestClient(main.app) as client:
        first = client.post("/analyze", json={"repo_url": "https://github.com/acme/first"})
        second = client.post("/analyze", json={"repo_url": "https://github.com/acme/second"})

    assert first.status_code == 202
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0
    assert len(job_store.list_all()) == 1


def test_per_request_token_is_encrypted_in_store_and_omitted_from_queue(monkeypatch):
    job_store = JobStore()
    queued = []
    monkeypatch.setattr(main, "store", job_store)
    monkeypatch.setattr(main, "encrypt_github_token", lambda value: f"ciphertext:{value[::-1]}")
    monkeypatch.setattr(
        main,
        "enqueue_analysis_job",
        lambda *args, **kwargs: queued.append(args[2]) or (False, "test"),
    )
    token = "ghp_user_private_token"

    with TestClient(main.app) as client:
        response = client.post(
            "/analyze",
            json={"repo_url": "https://github.com/acme/private", "github_token": token},
        )

    assert response.status_code == 202
    job = job_store.get(response.json()["job_id"])
    assert job.options["github_token_encrypted"] == f"ciphertext:{token[::-1]}"
    assert "github_token" not in job.options
    assert token not in repr(job.to_dict())
    assert len(queued) == 1
    assert "github_token" not in queued[0]
    assert token not in repr(queued[0])


def test_token_encryption_fails_closed_without_a_key(monkeypatch):
    monkeypatch.delenv("GNOSIS_TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(TokenEncryptionError, match="GNOSIS_TOKEN_ENCRYPTION_KEY"):
        encrypt_github_token("ghp_private")


def test_cors_configuration_does_not_allow_credentials_or_unrestricted_origins():
    cors = next(middleware for middleware in main.app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_credentials"] is False
    assert cors.kwargs["allow_origins"] != ["*"]


def test_queued_local_job_can_be_cancelled_before_execution(monkeypatch):
    job_store = JobStore()

    class PendingExecutor:
        def __init__(self):
            self.future = Future()

        def submit(self, *args):
            return self.future

    executor = PendingExecutor()
    monkeypatch.setattr(main, "store", job_store)
    monkeypatch.setattr(main, "_executor", executor)

    with TestClient(main.app) as client:
        submitted = client.post("/analyze", json={"repo_url": "https://github.com/acme/queued"})
        job_id = submitted.json()["job_id"]
        deleted = client.delete(f"/jobs/{job_id}")

    assert submitted.status_code == 202
    assert deleted.status_code == 204
    assert executor.future.cancelled()
    assert job_store.get(job_id) is None


def test_running_job_is_not_deleted_as_if_it_were_cancelled(monkeypatch):
    job_store = JobStore()
    job_id = job_store.create("https://github.com/acme/running", {})
    job_store.start(job_id)
    monkeypatch.setattr(main, "store", job_store)

    with TestClient(main.app) as client:
        response = client.delete(f"/jobs/{job_id}")

    assert response.status_code == 409
    assert job_store.get(job_id).status == "running"


def test_chroma_cleanup_removes_only_old_tagged_gnosis_collections():
    class FakeClient:
        def __init__(self):
            self.collections = {
                "gnosis_old": SimpleNamespace(metadata={"gnosis_managed": "project-gnosis", "gnosis_created_at": 100}),
                "gnosis_recent": SimpleNamespace(metadata={"gnosis_managed": "project-gnosis", "gnosis_created_at": 950}),
                "gnosis_legacy": SimpleNamespace(metadata={"hnsw:space": "cosine"}),
                "other_app": SimpleNamespace(metadata={"gnosis_managed": "project-gnosis", "gnosis_created_at": 1}),
            }
            self.deleted = []

        def list_collections(self):
            return [SimpleNamespace(name=name) for name in self.collections]

        def get_collection(self, name):
            return self.collections[name]

        def delete_collection(self, name):
            self.deleted.append(name)
            self.collections.pop(name)

    client = FakeClient()
    removed = cleanup_expired_collections(client, now=1000, ttl_seconds=500)

    assert removed == 1
    assert client.deleted == ["gnosis_old"]
    assert "gnosis_legacy" in client.collections
    assert "other_app" in client.collections


def test_cycle_examples_are_capped_but_all_cycle_nodes_are_identified(monkeypatch):
    import networkx as nx

    graph = nx.complete_graph(6, create_using=nx.DiGraph)
    graph.remove_edges_from(nx.selfloop_edges(graph))
    monkeypatch.setenv("MAX_CIRCULAR_CYCLES", "2")
    cyclic_nodes, examples, truncated = _detect_cycles(graph)

    assert len(examples) == 2
    assert truncated is True
    assert cyclic_nodes == set(graph.nodes())


def test_cycle_sample_handles_acyclic_graph():
    import networkx as nx

    graph = nx.DiGraph([(1, 2), (2, 3)])
    examples, truncated = _sample_cycles(graph, set())
    assert examples == []
    assert truncated is False

