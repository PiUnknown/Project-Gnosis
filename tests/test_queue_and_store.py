"""
Tests for Redis JobStore and RQ Task Queue architecture.

Covers:
  - In-Memory JobStore operations (fallback mode)
  - Redis-backed JobStore operations (using FakeRedis)
  - RQ Queue enqueuing and statistics
  - Fallback execution when Redis is unavailable
"""
import json
import pytest
import fakeredis
from unittest.mock import patch, MagicMock

from src.api.job_store import (
    DEFAULT_JOB_TTL_SECONDS,
    BackendUnavailableError,
    Job,
    JobStore,
)
from src.api.queue import (
    QueueDispatchError,
    enqueue_analysis_job,
    get_queue_stats,
    get_rq_queue,
)
from src.api.models import PHASE_PROGRESS


class TestJobModel:

    def test_job_serialization_roundtrip(self):
        job = Job(
            job_id="test-job-123",
            repo_url="https://github.com/psf/black",
            options={"max_explanations": 10, "skip_llm": True},
            status="running",
            current_phase="ingestion",
            phases_completed=["metadata"],
            progress_pct=20
        )
        data = job.to_dict()
        assert data["job_id"] == "test-job-123"
        assert data["repo_url"] == "https://github.com/psf/black"
        assert data["status"] == "running"
        assert data["current_phase"] == "ingestion"
        assert data["phases_completed"] == ["metadata"]
        assert data["progress_pct"] == 20

        restored = Job.from_dict(data)
        assert restored.job_id == job.job_id
        assert restored.repo_url == job.repo_url
        assert restored.status == job.status
        assert restored.current_phase == job.current_phase
        assert restored.phases_completed == job.phases_completed
        assert restored.progress_pct == job.progress_pct


class TestInMemoryJobStore:

    def setup_method(self):
        self.store = JobStore()

    def test_create_and_get(self):
        job_id = self.store.create("https://github.com/test/repo", {"skip_llm": True})
        job = self.store.get(job_id)
        assert job is not None
        assert job.job_id == job_id
        assert job.status == "queued"
        assert job.repo_url == "https://github.com/test/repo"

    def test_lifecycle_transitions(self):
        job_id = self.store.create("https://github.com/test/repo", {})
        
        self.store.start(job_id)
        assert self.store.get(job_id).status == "running"

        self.store.update_phase(job_id, "ast_parser", 35)
        job = self.store.get(job_id)
        assert job.current_phase == "ast_parser"
        assert job.progress_pct == 35

        self.store.complete_phase(job_id, "ast_parser")
        assert "ast_parser" in self.store.get(job_id).phases_completed

        self.store.finish(job_id, {"summary": "done"})
        job = self.store.get(job_id)
        assert job.status == "complete"
        assert job.progress_pct == 100
        assert job.completed_at is not None
        assert job.result == {"summary": "done"}

    def test_fail_transition(self):
        job_id = self.store.create("https://github.com/test/repo", {})
        self.store.fail(job_id, "Network timeout")
        job = self.store.get(job_id)
        assert job.status == "failed"
        assert job.error == "Network timeout"
        assert job.completed_at is not None

    def test_delete_and_clear(self):
        job_id1 = self.store.create("https://github.com/test/1", {})
        job_id2 = self.store.create("https://github.com/test/2", {})
        assert len(self.store.list_all()) == 2

        assert self.store.delete(job_id1) is True
        assert self.store.get(job_id1) is None
        assert len(self.store.list_all()) == 1

        self.store.clear()
        assert len(self.store.list_all()) == 0


class TestRedisJobStore:

    def setup_method(self):
        self.fake_redis = fakeredis.FakeRedis(decode_responses=True)
        self.store = JobStore()
        self.store.connect_redis(self.fake_redis)

    def test_redis_create_and_get(self):
        assert self.store.is_redis is True
        job_id = self.store.create("https://github.com/test/redis-repo", {"skip_llm": False})
        
        job = self.store.get(job_id)
        assert job is not None
        assert job.job_id == job_id
        assert job.repo_url == "https://github.com/test/redis-repo"
        assert job.status == "queued"

    def test_redis_lifecycle_transitions(self):
        job_id = self.store.create("https://github.com/test/redis-repo", {})
        
        self.store.start(job_id)
        assert self.store.get(job_id).status == "running"

        self.store.update_phase(job_id, "dependency_graph", 50)
        job = self.store.get(job_id)
        assert job.current_phase == "dependency_graph"
        assert job.progress_pct == 50

        self.store.complete_phase(job_id, "dependency_graph")
        job = self.store.get(job_id)
        assert "dependency_graph" in job.phases_completed

        self.store.finish(job_id, {"onboarding_doc": "# Doc"})
        job = self.store.get(job_id)
        assert job.status == "complete"
        assert job.progress_pct == 100
        assert job.result == {"onboarding_doc": "# Doc"}

    def test_redis_fail_transition(self):
        job_id = self.store.create("https://github.com/test/redis-repo", {})
        self.store.fail(job_id, "AST Parse Error")
        job = self.store.get(job_id)
        assert job.status == "failed"
        assert job.error == "AST Parse Error"

    def test_redis_list_and_active_count(self):
        job1 = self.store.create("https://github.com/test/1", {})
        job2 = self.store.create("https://github.com/test/2", {})
        self.store.finish(job2, {"done": True})

        all_jobs = self.store.list_all()
        assert len(all_jobs) == 2
        assert self.store.active_count() == 1  # only job1 is queued

    def test_redis_delete_and_clear(self):
        job1 = self.store.create("https://github.com/test/1", {})
        job2 = self.store.create("https://github.com/test/2", {})

        assert self.store.delete(job1) is True
        assert self.store.get(job1) is None
        assert len(self.store.list_all()) == 1

        self.store.clear()
        assert len(self.store.list_all()) == 0

    def test_redis_create_failure_raises_backend_unavailable(self):
        class _BrokenPipeline:
            def pipeline(self, *args, **kwargs):
                raise RuntimeError("redis down")

        broken = JobStore()
        broken.connect_redis(_BrokenPipeline())

        with pytest.raises(BackendUnavailableError):
            broken.create("https://github.com/test/repo", {})

        # No silent in-memory record: the backend must stay empty.
        assert broken.backend == "redis"
        assert broken._memory_jobs == {}

    def test_finish_applies_default_ttl(self, monkeypatch):
        monkeypatch.delenv("JOB_TTL_SECONDS", raising=False)
        job_id = self.store.create("https://github.com/test/repo", {})
        self.store.start(job_id)

        self.store.finish(job_id, {"done": True})

        ttl = self.fake_redis.ttl(f"gnosis:job:{job_id}")
        assert 0 < ttl <= DEFAULT_JOB_TTL_SECONDS

    def test_fail_applies_default_ttl(self, monkeypatch):
        monkeypatch.delenv("JOB_TTL_SECONDS", raising=False)
        job_id = self.store.create("https://github.com/test/repo", {})

        self.store.fail(job_id, "boom")

        ttl = self.fake_redis.ttl(f"gnosis:job:{job_id}")
        assert 0 < ttl <= DEFAULT_JOB_TTL_SECONDS

    def test_expired_records_are_pruned_from_indexes(self):
        job_id = self.store.create("https://github.com/test/repo", {})
        self.fake_redis.delete(f"gnosis:job:{job_id}")  # simulate TTL expiry

        assert self.store.list_all() == []

        assert not self.fake_redis.sismember("gnosis:jobs", job_id)
        assert not self.fake_redis.sismember("gnosis:jobs:active", job_id)


class TestQueueManagement:

    def test_memory_store_dispatches_to_threadpool(self):
        memory_store = JobStore()
        mock_executor = MagicMock()
        is_dist, mode = enqueue_analysis_job(
            "job-1",
            "https://github.com/test/repo",
            {},
            executor=mock_executor,
            store=memory_store,
        )
        assert is_dist is False
        assert mode == "local_threadpool"
        assert mock_executor.submit.called

    def test_degraded_store_dispatches_in_process(self):
        degraded_store = JobStore()
        degraded_store.connect_redis(fakeredis.FakeRedis())  # pretend Redis worked
        degraded_store.connect_redis(None)                   # then the link dropped
        assert degraded_store.degraded is True
        mock_executor = MagicMock()

        is_dist, mode = enqueue_analysis_job(
            "job-degraded",
            "https://github.com/test/repo",
            {},
            executor=mock_executor,
            store=degraded_store,
        )

        assert is_dist is False
        assert mode == "local_threadpool"
        assert mock_executor.submit.called

    def test_redis_dispatch_failure_raises_instead_of_threadpool(self):
        redis_store = JobStore()
        redis_store.connect_redis(fakeredis.FakeRedis())
        mock_executor = MagicMock()
        broken_queue = MagicMock()
        broken_queue.enqueue.side_effect = RuntimeError("quota exceeded")

        with patch("src.api.queue.get_rq_queue", return_value=broken_queue):
            with pytest.raises(QueueDispatchError):
                enqueue_analysis_job(
                    "job-fail",
                    "https://github.com/test/repo",
                    {},
                    executor=mock_executor,
                    store=redis_store,
                )

        assert not mock_executor.submit.called

    def test_rq_distributed_enqueue(self):
        fake_conn = fakeredis.FakeRedis()
        redis_store = JobStore()
        redis_store.connect_redis(fake_conn)
        is_dist, mode = enqueue_analysis_job(
            "job-rq-1",
            "https://github.com/test/repo",
            {},
            store=redis_store,
        )
        assert is_dist is True
        assert mode == "rq_distributed"

        q = get_rq_queue(fake_conn)
        assert len(q) == 1
        enqueued_job = q.jobs[0]
        assert enqueued_job.id == "job-rq-1"

    def test_queue_stats_fallback(self):
        memory_store = JobStore()
        stats = get_queue_stats(store=memory_store)
        assert stats["redis_connected"] is False
        assert stats["redis_configured"] is False
        assert stats["store_degraded"] is False
        assert stats["mode"] == "local_threadpool"
        assert stats["queue_depth"] == 0

    def test_queue_stats_reports_degraded_store(self):
        degraded_store = JobStore()
        degraded_store.connect_redis(fakeredis.FakeRedis())
        degraded_store.connect_redis(None)

        stats = get_queue_stats(store=degraded_store)
        assert stats["redis_configured"] is True
        assert stats["redis_connected"] is False
        assert stats["store_degraded"] is True
        assert stats["mode"] == "local_threadpool"

    def test_queue_stats_redis(self):
        fake_conn = fakeredis.FakeRedis()
        redis_store = JobStore()
        redis_store.connect_redis(fake_conn)
        stats = get_queue_stats(store=redis_store)
        assert stats["redis_connected"] is True
        assert stats["mode"] == "rq_distributed"
        assert stats["queue_depth"] == 0


class TestWorkerHealthHandler:

    def test_worker_health_handler_root_and_health(self):
        from src.api.worker import WorkerHealthHandler
        from http.server import HTTPServer
        import socket
        import threading
        import urllib.request

        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        server = HTTPServer(("127.0.0.1", port), WorkerHealthHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            # Test GET /
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as resp:
                assert resp.status == 200
                assert resp.read() == b"ok"

            # Test GET /health
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health") as resp:
                assert resp.status == 200
                assert resp.read() == b"ok"
        finally:
            server.shutdown()

