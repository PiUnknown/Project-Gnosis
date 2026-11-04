"""Regression coverage for the opt-in deferred vector-index path."""
import base64
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.agents import explainability
from src.api import main, pipeline_runner
from src.api.job_store import JobStore
from src.api.models import AnalysisResult
from src.state import FileMetadata
from src.utils.github_api import fetch_file_content_by_sha


def test_deferred_pipeline_keeps_initial_result_features(monkeypatch):
    job_store = JobStore()
    job_id = job_store.create(
        "https://github.com/owner/repo", {"defer_code_index": True}
    )
    monkeypatch.setattr(pipeline_runner, "store", job_store)
    monkeypatch.setattr(
        pipeline_runner,
        "fetch_repo_metadata",
        lambda *args, **kwargs: {"default_branch": "main", "size": 1},
    )

    def ingest(state, **kwargs):
        state.file_manifest = [
            FileMetadata("src/app.py", "Python", 3, 36, "a" * 40)
        ]
        state.files_discovered = 1
        state.files_analyzed = 1
        state.files_with_content = 1
        state.analysis_mode = "Full"
        return state

    def passthrough(state, **kwargs):
        return state

    monkeypatch.setattr(pipeline_runner.ingestion, "run", ingest)
    monkeypatch.setattr(pipeline_runner.ast_parser, "run", passthrough)
    monkeypatch.setattr(pipeline_runner.dependency_graph, "run", passthrough)
    monkeypatch.setattr(pipeline_runner.complexity_scorer, "run", passthrough)
    monkeypatch.setattr(
        pipeline_runner.complexity_scorer, "apply_graph_coupling", lambda state: None
    )
    monkeypatch.setattr(
        pipeline_runner.code_rag,
        "run",
        lambda state: (_ for _ in ()).throw(AssertionError("index should be deferred")),
    )

    def make_doc(state):
        state.final_doc = "Onboarding document"
        state.agent_context_md = "Agent context"
        return state

    monkeypatch.setattr(pipeline_runner.doc_generator, "run", make_doc)

    pipeline_runner.run(
        job_id,
        "https://github.com/owner/repo",
        {"defer_code_index": True},
    )

    job = job_store.get(job_id)
    assert job.status == "complete", job.error
    assert job.result["code_index_status"] == "deferred"
    assert job.result["onboarding_doc"] == "Onboarding document"
    assert job.result["agent_context"] == "Agent context"
    assert "graph_data" in job.result
    assert "dependency_rows" in job.result
    assert "complexity_rows" in job.result
    assert job.result["analyzed_files"][0]["path"] == "src/app.py"
    assert AnalysisResult.model_validate(job.result).code_index_status == "deferred"


def test_analyze_endpoint_passes_defer_option_to_worker(monkeypatch):
    job_store = JobStore()
    submitted = {}
    monkeypatch.setattr(main, "store", job_store)

    def enqueue(job_id, repo_url, options, **kwargs):
        submitted.update(options)

    monkeypatch.setattr(main, "enqueue_analysis_job", enqueue)

    response = TestClient(main.app).post(
        "/api/analyze",
        json={
            "repo_url": "https://github.com/owner/repo",
            "options": {"defer_code_index": True},
        },
    )

    assert response.status_code == 202
    assert submitted["defer_code_index"] is True
    assert job_store.get(response.json()["job_id"]).options["defer_code_index"] is True


def test_file_explanation_uses_analyzed_blob_without_chroma():
    code = "def answer():\n    return 42\n"
    prompt = {}

    def fake_llm(**kwargs):
        prompt["text"] = kwargs["user_prompt"]
        return "This file returns the answer."

    with patch.dict("os.environ", {"NVIDIA_API_KEY": "test-key"}):
        with patch.object(explainability, "get_cached_explanation", return_value=None):
            with patch.object(
                explainability, "CodeRetriever", side_effect=ValueError("collection missing")
            ):
                with patch.object(explainability, "fetch_file_content_by_sha", return_value=code):
                    with patch.object(explainability, "fetch_file_content_raw") as branch_fetch:
                        with patch.object(explainability, "call_llm", side_effect=fake_llm):
                            with patch.object(explainability, "save_explanation"):
                                result, cached = explainability.explain_file_on_demand(
                                    owner="owner",
                                    repo_name="repo",
                                    branch="main",
                                    file_path="src/app.py",
                                    file_sha="a" * 40,
                                    language="Python",
                                    collection_name="gnosis_owner_repo_job",
                                    file_metadata={"risk": "LOW"},
                                )

    assert result == "This file returns the answer."
    assert cached is False
    assert "def answer()" in prompt["text"]
    branch_fetch.assert_not_called()


def test_fetch_file_content_by_sha_decodes_github_blob():
    source = "print('snapshot')\n"
    response = type(
        "Response",
        (),
        {
            "status_code": 200,
            "json": lambda self: {
                "encoding": "base64",
                "content": base64.b64encode(source.encode()).decode(),
            },
            "close": lambda self: None,
        },
    )()

    with patch("src.utils.github_api._RAW_SESSION.get", return_value=response) as get:
        content = fetch_file_content_by_sha("owner", "repo", "a" * 40)

    assert content == source
    assert "/git/blobs/" + "a" * 40 in get.call_args.args[0]


def test_fetch_file_content_by_sha_rejects_invalid_sha_without_request():
    with patch("src.utils.github_api._RAW_SESSION.get") as get:
        assert fetch_file_content_by_sha("owner", "repo", "not-a-sha") is None
    get.assert_not_called()
