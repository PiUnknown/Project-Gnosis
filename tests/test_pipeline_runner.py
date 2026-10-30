"""Regression tests for the API pipeline runner wiring.

These tests run the real ``pipeline_runner.run`` orchestration with the agent
implementations stubbed out, so callback/signature mismatches between the
runner and the job store are caught without touching the network.
"""
from src.api import pipeline_runner
from src.api.job_store import JobStore


def _patch_agents(monkeypatch, explainability_run):
    monkeypatch.setattr(pipeline_runner, "parse_github_url", lambda url: ("owner", "repo"))
    monkeypatch.setattr(
        pipeline_runner,
        "fetch_repo_metadata",
        lambda owner, repo, token=None: {"default_branch": "main", "size": 1},
    )

    def _passthrough(state, **kwargs):
        return state

    monkeypatch.setattr(pipeline_runner.ingestion, "run", _passthrough)
    monkeypatch.setattr(pipeline_runner.ast_parser, "run", _passthrough)
    monkeypatch.setattr(pipeline_runner.dependency_graph, "run", _passthrough)
    monkeypatch.setattr(pipeline_runner.complexity_scorer, "run", _passthrough)
    monkeypatch.setattr(
        pipeline_runner.complexity_scorer, "apply_graph_coupling", lambda state: None
    )
    monkeypatch.setattr(pipeline_runner.code_rag, "run", _passthrough)
    monkeypatch.setattr(pipeline_runner.explainability, "run", explainability_run)
    monkeypatch.setattr(pipeline_runner.doc_generator, "run", _passthrough)
    monkeypatch.setattr(
        pipeline_runner,
        "_serialize_result",
        lambda job_id, state, skip_llm=False: {"ok": True},
    )
    monkeypatch.setattr(
        pipeline_runner,
        "decrypt_github_token",
        lambda token: None,
    )


def test_explainability_progress_callback_receives_bound_job_id(monkeypatch):
    job_store = JobStore()
    job_id = job_store.create("https://github.com/owner/repo", {"skip_llm": False})
    monkeypatch.setattr(pipeline_runner, "store", job_store)

    seen_states = []

    def fake_explainability(state, max_count=20, progress_callback=None):
        seen_states.append(state)
        assert progress_callback is not None
        # The agent contract is (completed, total); the runner must bind job_id.
        progress_callback(2, 5)
        return state

    _patch_agents(monkeypatch, fake_explainability)

    pipeline_runner.run(job_id, "https://github.com/owner/repo", {"skip_llm": False})

    job = job_store.get(job_id)
    assert job.status == "complete", job.error
    assert job.error is None
    assert job.explanations_completed == 2
    assert job.explanations_total == 5


def test_skip_llm_does_not_wire_explainability_callback(monkeypatch):
    job_store = JobStore()
    job_id = job_store.create("https://github.com/owner/repo", {"skip_llm": True})
    monkeypatch.setattr(pipeline_runner, "store", job_store)

    calls = []

    def fake_explainability(state, max_count=20, progress_callback=None):
        calls.append(progress_callback)
        return state

    _patch_agents(monkeypatch, fake_explainability)

    pipeline_runner.run(job_id, "https://github.com/owner/repo", {"skip_llm": True})

    job = job_store.get(job_id)
    assert job.status == "complete", job.error
    assert calls == []
