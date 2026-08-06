"""
Tests for Phase 8: FastAPI Backend.

All pipeline execution is mocked — tests verify HTTP contract,
not pipeline logic (those are covered in earlier test phases).

Mocking strategy:
  pipeline_runner.run is replaced with controlled fake implementations:
    - instant_success_runner: immediately marks job complete with fake result
    - instant_failure_runner: immediately marks job failed
    - slow_runner: marks job running only (simulates in-progress)

Tests cover:
  TestHealthAndRoot         - /health and / endpoints
  TestAnalyzeEndpoint       - POST /analyze validation and job creation
  TestJobStatusEndpoint     - GET /jobs/{job_id} status polling
  TestJobResultEndpoint     - GET /jobs/{job_id}/result gating
  TestJobListEndpoint       - GET /jobs listing
  TestJobDeletion           - DELETE /jobs/{job_id}
  TestErrorHandling         - 404, 409, 422 error cases
  TestJobStore              - JobStore unit tests (no HTTP)
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.api import pipeline_runner
from src.api.main import app
from src.api.job_store import JobStore
from src.api.models import PHASE_PROGRESS
from src.api.pipeline_runner import run as pipeline_runner_run


# -----------------------------------------------------------------------
# TestClient setup
# -----------------------------------------------------------------------

@pytest.fixture
def client():
    """
    FastAPI TestClient.
    Runs requests synchronously in the test process.
    BackgroundTasks and thread pool calls are patched per-test.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clear_store():
    """Clear job store to isolate tests."""
    from src.api.job_store import store
    store.clear()


# -----------------------------------------------------------------------
# Fake pipeline runners
# -----------------------------------------------------------------------

FAKE_RESULT = {
    "job_id": "PLACEHOLDER",        # overwritten by the runner
    "repo": "testowner/testrepo",
    "branch": "main",
    "onboarding_doc": "# testrepo — Architecture Overview\n\nThis is the onboarding document.",
    "summary": {
        "total_files": 42,
        "language_breakdown": {"Python": 35, "JavaScript": 7},
        "total_functions": 150,
        "total_classes": 12,
        "total_import_edges": 87,
        "circular_dep_count": 0,
        "risk_distribution": {"CRITICAL": 0, "HIGH": 3, "MEDIUM": 10, "LOW": 29},
        "files_explained": 15,
        "top_complex_functions": []
    },
    "complexity_report": {"critical_and_high": [], "circular_deps": []},
    "graph_summary": {
        "top_files_by_indegree": [],
        "topological_order_available": True,
        "reading_order_top_10": []
    },
    "explanations": {"src/state.py": "This file defines shared state."}
}


def make_success_runner(job_store_instance=None):
    """Return a runner function that immediately completes the job."""
    def instant_success(job_id: str, repo_url: str, options: dict):
        from src.api.job_store import store
        target = job_store_instance or store
        target.start(job_id)
        target.update_phase(job_id, "ingestion", PHASE_PROGRESS["ingestion"])
        target.complete_phase(job_id, "ingestion")
        result = {**FAKE_RESULT, "job_id": job_id}
        target.finish(job_id, result)
    return instant_success


def instant_failure(job_id: str, repo_url: str, options: dict):
    """Runner that immediately fails the job."""
    from src.api.job_store import store
    store.start(job_id)
    store.fail(job_id, "GitHub repository not found: ConnectionError")


def slow_runner(job_id: str, repo_url: str, options: dict):
    """Runner that marks job as running but never completes it."""
    from src.api.job_store import store
    store.start(job_id)
    store.update_phase(job_id, "ast_parser", PHASE_PROGRESS["ast_parser"])
    # Deliberately does not call store.finish() — simulates in-progress job


# -----------------------------------------------------------------------
# TestHealthAndRoot
# -----------------------------------------------------------------------

class TestHealthAndRoot:

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_body_has_required_fields(self, client):
        response = client.get("/health")
        body = response.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "active_jobs" in body

    def test_root_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_contains_endpoint_list(self, client):
        response = client.get("/")
        body = response.json()
        assert "endpoints" in body

    def test_health_active_jobs_is_integer(self, client):
        response = client.get("/health")
        assert isinstance(response.json()["active_jobs"], int)


# -----------------------------------------------------------------------
# TestAnalyzeEndpoint
# -----------------------------------------------------------------------

class TestAnalyzeEndpoint:

    def test_valid_url_returns_202(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/testowner/testrepo"}
            )
        assert response.status_code == 202

    def test_response_contains_job_id(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/testowner/testrepo"}
            )
        body = response.json()
        assert "job_id" in body
        assert len(body["job_id"]) > 0

    def test_response_status_is_queued(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/testowner/testrepo"}
            )
        assert response.json()["status"] == "queued"

    def test_missing_repo_url_returns_422(self, client):
        response = client.post("/analyze", json={})
        assert response.status_code == 422

    def test_empty_repo_url_returns_422(self, client):
        response = client.post("/analyze", json={"repo_url": ""})
        assert response.status_code == 422

    def test_non_github_url_returns_422(self, client):
        response = client.post(
            "/analyze",
            json={"repo_url": "https://gitlab.com/owner/repo"}
        )
        assert response.status_code == 422

    def test_invalid_url_format_returns_422(self, client):
        response = client.post(
            "/analyze",
            json={"repo_url": "https://github.com/onlyone"}
        )
        assert response.status_code == 422

    def test_negative_max_explanations_returns_422(self, client):
        response = client.post("/analyze", json={
            "repo_url": "https://github.com/owner/repo",
            "options": {"max_explanations": -1}
        })
        assert response.status_code == 422

    def test_max_explanations_over_100_returns_422(self, client):
        response = client.post("/analyze", json={
            "repo_url": "https://github.com/owner/repo",
            "options": {"max_explanations": 101}
        })
        assert response.status_code == 422

    def test_options_defaults_applied(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        assert response.status_code == 202

    def test_skip_llm_option_accepted(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            response = client.post("/analyze", json={
                "repo_url": "https://github.com/owner/repo",
                "options": {"skip_llm": True, "max_explanations": 0}
            })
        assert response.status_code == 202

    def test_two_submissions_get_different_job_ids(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            r1 = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo1"}
            )
            r2 = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo2"}
            )
        assert r1.json()["job_id"] != r2.json()["job_id"]

    def test_executor_submit_called_with_pipeline_runner(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        mock_executor.submit.assert_called_once()
        args = mock_executor.submit.call_args[0]
        assert args[0] == pipeline_runner.run

    def test_duplicate_submission_returns_409(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            r1 = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
            assert r1.status_code == 202
            
            r2 = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
            assert r2.status_code == 409
            body = r2.json()
            assert body["job_id"] == r1.json()["job_id"]
            assert body["status"] == "queued"
            assert "already running" in body["message"]


# -----------------------------------------------------------------------
# TestJobStatusEndpoint
# -----------------------------------------------------------------------

class TestJobStatusEndpoint:

    def _submit_job(self, client, runner_fn=None) -> str:
        """Helper: submit a job and return the job_id."""
        with patch("src.api.main._executor") as mock_executor:
            if runner_fn:
                def submit_side_effect(fn, job_id, repo_url, options):
                    runner_fn(job_id, repo_url, options)
                mock_executor.submit.side_effect = submit_side_effect
            else:
                mock_executor.submit.return_value = None
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        return response.json()["job_id"]

    def test_get_status_returns_200(self, client):
        job_id = self._submit_job(client)
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200

    def test_status_body_has_required_fields(self, client):
        job_id = self._submit_job(client)
        body = client.get(f"/jobs/{job_id}").json()
        for field in ("job_id", "status", "progress_pct",
                      "phases_completed", "created_at", "repo_url"):
            assert field in body, f"Missing: {field}"

    def test_queued_job_has_correct_status(self, client):
        job_id = self._submit_job(client)
        body = client.get(f"/jobs/{job_id}").json()
        assert body["status"] in ("queued", "running")

    def test_completed_job_has_correct_status(self, client):
        job_id = self._submit_job(client, runner_fn=make_success_runner())
        body = client.get(f"/jobs/{job_id}").json()
        assert body["status"] == "complete"
        assert body["progress_pct"] == 100

    def test_failed_job_has_error_field(self, client):
        job_id = self._submit_job(client, runner_fn=instant_failure)
        body = client.get(f"/jobs/{job_id}").json()
        assert body["status"] == "failed"
        assert body["error"] is not None
        assert len(body["error"]) > 0

    def test_running_job_shows_current_phase(self, client):
        job_id = self._submit_job(client, runner_fn=slow_runner)
        body = client.get(f"/jobs/{job_id}").json()
        assert body["status"] == "running"
        assert body["current_phase"] is not None

    def test_unknown_job_id_returns_404(self, client):
        response = client.get("/jobs/nonexistent-job-id")
        assert response.status_code == 404

    def test_completed_job_has_completed_at_set(self, client):
        job_id = self._submit_job(client, runner_fn=make_success_runner())
        body = client.get(f"/jobs/{job_id}").json()
        assert body["completed_at"] is not None

    def test_phases_completed_is_list(self, client):
        job_id = self._submit_job(client, runner_fn=make_success_runner())
        body = client.get(f"/jobs/{job_id}").json()
        assert isinstance(body["phases_completed"], list)

    def test_completed_job_phases_completed_nonempty(self, client):
        job_id = self._submit_job(client, runner_fn=make_success_runner())
        body = client.get(f"/jobs/{job_id}").json()
        assert len(body["phases_completed"]) > 0

    def test_progress_pct_in_range(self, client):
        job_id = self._submit_job(client, runner_fn=slow_runner)
        body = client.get(f"/jobs/{job_id}").json()
        assert 0 <= body["progress_pct"] <= 100


# -----------------------------------------------------------------------
# TestJobResultEndpoint
# -----------------------------------------------------------------------

class TestJobResultEndpoint:

    def _submit_and_complete(self, client) -> str:
        with patch("src.api.main._executor") as mock_executor:
            def submit_side_effect(fn, job_id, repo_url, options):
                make_success_runner()(job_id, repo_url, options)
            mock_executor.submit.side_effect = submit_side_effect
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        return response.json()["job_id"]

    def _submit_only(self, client) -> str:
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        return response.json()["job_id"]

    def _submit_and_fail(self, client) -> str:
        with patch("src.api.main._executor") as mock_executor:
            def submit_side_effect(fn, job_id, repo_url, options):
                instant_failure(job_id, repo_url, options)
            mock_executor.submit.side_effect = submit_side_effect
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        return response.json()["job_id"]

    def test_completed_job_result_returns_200(self, client):
        job_id = self._submit_and_complete(client)
        response = client.get(f"/jobs/{job_id}/result")
        assert response.status_code == 200

    def test_result_contains_onboarding_doc(self, client):
        job_id = self._submit_and_complete(client)
        body = client.get(f"/jobs/{job_id}/result").json()
        assert "onboarding_doc" in body
        assert len(body["onboarding_doc"]) > 0

    def test_result_contains_summary(self, client):
        job_id = self._submit_and_complete(client)
        body = client.get(f"/jobs/{job_id}/result").json()
        assert "summary" in body
        assert "total_files" in body["summary"]

    def test_result_contains_explanations(self, client):
        job_id = self._submit_and_complete(client)
        body = client.get(f"/jobs/{job_id}/result").json()
        assert "explanations" in body

    def test_result_contains_graph_summary(self, client):
        job_id = self._submit_and_complete(client)
        body = client.get(f"/jobs/{job_id}/result").json()
        assert "graph_summary" in body

    def test_queued_job_result_returns_409(self, client):
        job_id = self._submit_only(client)
        response = client.get(f"/jobs/{job_id}/result")
        assert response.status_code == 409

    def test_failed_job_result_returns_500(self, client):
        job_id = self._submit_and_fail(client)
        response = client.get(f"/jobs/{job_id}/result")
        assert response.status_code == 500

    def test_unknown_job_result_returns_404(self, client):
        response = client.get("/jobs/does-not-exist/result")
        assert response.status_code == 404

    def test_running_job_result_returns_409(self, client):
        with patch("src.api.main._executor") as mock_executor:
            def submit_side_effect(fn, job_id, repo_url, options):
                slow_runner(job_id, repo_url, options)
            mock_executor.submit.side_effect = submit_side_effect
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        job_id = response.json()["job_id"]
        result_response = client.get(f"/jobs/{job_id}/result")
        assert result_response.status_code == 409

    def test_result_repo_field_matches_submission(self, client):
        job_id = self._submit_and_complete(client)
        body = client.get(f"/jobs/{job_id}/result").json()
        assert "testowner/testrepo" in body["repo"]


# -----------------------------------------------------------------------
# TestJobListEndpoint
# -----------------------------------------------------------------------

class TestJobListEndpoint:

    def test_list_returns_200(self, client):
        response = client.get("/jobs")
        assert response.status_code == 200

    def test_list_body_structure(self, client):
        response = client.get("/jobs")
        body = response.json()
        assert "total" in body
        assert "jobs" in body
        assert isinstance(body["jobs"], list)

    def test_list_includes_submitted_jobs(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        response = client.get("/jobs")
        body = response.json()
        assert body["total"] >= 1

    def test_list_job_summaries_have_required_fields(self, client):
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        response = client.get("/jobs")
        jobs = response.json()["jobs"]
        if jobs:
            for field in ("job_id", "status", "progress_pct",
                          "created_at", "repo_url"):
                assert field in jobs[0], f"Missing: {field}"

    def test_total_matches_jobs_length(self, client):
        response = client.get("/jobs")
        body = response.json()
        assert body["total"] == len(body["jobs"])


# -----------------------------------------------------------------------
# TestJobDeletion
# -----------------------------------------------------------------------

class TestJobDeletion:

    def _submit_job(self, client) -> str:
        with patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None
            response = client.post(
                "/analyze",
                json={"repo_url": "https://github.com/owner/repo"}
            )
        return response.json()["job_id"]

    def test_delete_existing_job_returns_204(self, client):
        job_id = self._submit_job(client)
        response = client.delete(f"/jobs/{job_id}")
        assert response.status_code == 204

    def test_delete_nonexistent_job_returns_404(self, client):
        response = client.delete("/jobs/nonexistent-job")
        assert response.status_code == 404

    def test_deleted_job_not_findable(self, client):
        job_id = self._submit_job(client)
        client.delete(f"/jobs/{job_id}")
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 404

    def test_delete_twice_returns_404_second_time(self, client):
        job_id = self._submit_job(client)
        client.delete(f"/jobs/{job_id}")
        response = client.delete(f"/jobs/{job_id}")
        assert response.status_code == 404


# -----------------------------------------------------------------------
# TestErrorHandling
# -----------------------------------------------------------------------

class TestErrorHandling:

    def test_404_for_unknown_job(self, client):
        response = client.get("/jobs/totally-fake-id-xyz")
        assert response.status_code == 404

    def test_422_for_invalid_json(self, client):
        response = client.post(
            "/analyze",
            json={"repo_url": "not-a-github-url-at-all"}
        )
        assert response.status_code == 422

    def test_422_response_has_detail_field(self, client):
        response = client.post("/analyze", json={"repo_url": ""})
        assert response.status_code == 422
        body = response.json()
        assert "detail" in body

    def test_405_for_wrong_method(self, client):
        response = client.get("/analyze")
        assert response.status_code == 405


# -----------------------------------------------------------------------
# TestJobStore (unit tests, no HTTP)
# -----------------------------------------------------------------------

class TestJobStore:

    def test_create_returns_string_id(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_two_creates_return_different_ids(self):
        s = JobStore()
        id1 = s.create("https://github.com/a/b", {})
        id2 = s.create("https://github.com/a/b", {})
        assert id1 != id2

    def test_get_returns_job_after_create(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        job = s.get(job_id)
        assert job is not None
        assert job.job_id == job_id

    def test_get_returns_none_for_unknown(self):
        s = JobStore()
        assert s.get("nonexistent") is None

    def test_start_sets_running_status(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        s.start(job_id)
        assert s.get(job_id).status == "running"

    def test_update_phase_sets_current_phase(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        s.start(job_id)
        s.update_phase(job_id, "ast_parser", 35)
        job = s.get(job_id)
        assert job.current_phase == "ast_parser"
        assert job.progress_pct == 35

    def test_complete_phase_appends_to_list(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        s.start(job_id)
        s.complete_phase(job_id, "ingestion")
        s.complete_phase(job_id, "ast_parser")
        assert "ingestion" in s.get(job_id).phases_completed
        assert "ast_parser" in s.get(job_id).phases_completed

    def test_complete_phase_no_duplicates(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        s.start(job_id)
        s.complete_phase(job_id, "ingestion")
        s.complete_phase(job_id, "ingestion")
        assert s.get(job_id).phases_completed.count("ingestion") == 1

    def test_finish_sets_complete_status(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        s.start(job_id)
        s.finish(job_id, {"data": "result"})
        job = s.get(job_id)
        assert job.status == "complete"
        assert job.result == {"data": "result"}
        assert job.progress_pct == 100
        assert job.completed_at is not None

    def test_fail_sets_failed_status(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        s.start(job_id)
        s.fail(job_id, "Something went wrong")
        job = s.get(job_id)
        assert job.status == "failed"
        assert job.error == "Something went wrong"
        assert job.completed_at is not None

    def test_delete_removes_job(self):
        s = JobStore()
        job_id = s.create("https://github.com/a/b", {})
        assert s.delete(job_id) is True
        assert s.get(job_id) is None

    def test_delete_nonexistent_returns_false(self):
        s = JobStore()
        assert s.delete("nonexistent") is False

    def test_list_all_returns_all_jobs(self):
        s = JobStore()
        id1 = s.create("https://github.com/a/b", {})
        id2 = s.create("https://github.com/c/d", {})
        all_jobs = s.list_all()
        ids = [j.job_id for j in all_jobs]
        assert id1 in ids
        assert id2 in ids

    def test_active_count_counts_queued_and_running(self):
        s = JobStore()
        id1 = s.create("https://github.com/a/b", {})
        id2 = s.create("https://github.com/c/d", {})
        id3 = s.create("https://github.com/e/f", {})
        s.start(id2)
        s.finish(id3, {})
        # id1 = queued, id2 = running, id3 = complete
        assert s.active_count() == 2