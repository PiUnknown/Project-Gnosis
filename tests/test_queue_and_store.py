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

from src.api.job_store import Job, JobStore
from src.api.queue import enqueue_analysis_job, get_queue_stats, get_rq_queue
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


class TestQueueManagement:

    def test_fallback_enqueue_when_redis_unset(self):
        mock_executor = MagicMock()
        with patch("src.api.queue.get_redis_connection", return_value=None):
            is_dist, mode = enqueue_analysis_job("job-1", "https://github.com/test/repo", {}, executor=mock_executor)
            assert is_dist is False
            assert mode == "local_threadpool"
            assert mock_executor.submit.called

    def test_rq_distributed_enqueue(self):
        fake_conn = fakeredis.FakeRedis()
        with patch("src.api.queue.get_redis_connection", return_value=fake_conn):
            is_dist, mode = enqueue_analysis_job("job-rq-1", "https://github.com/test/repo", {})
            assert is_dist is True
            assert mode == "rq_distributed"
            
            q = get_rq_queue(fake_conn)
            assert len(q) == 1
            enqueued_job = q.jobs[0]
            assert enqueued_job.id == "job-rq-1"

    def test_queue_stats_fallback(self):
        with patch("src.api.queue.get_redis_connection", return_value=None):
            stats = get_queue_stats()
            assert stats["redis_connected"] is False
            assert stats["mode"] == "local_threadpool"
            assert stats["queue_depth"] == 0

    def test_queue_stats_redis(self):
        fake_conn = fakeredis.FakeRedis()
        with patch("src.api.queue.get_redis_connection", return_value=fake_conn):
            stats = get_queue_stats()
            assert stats["redis_connected"] is True
            assert stats["mode"] == "rq_distributed"
            assert stats["queue_depth"] == 0
