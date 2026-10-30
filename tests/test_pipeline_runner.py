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
        # The runner records the real outcome from state afterwards, so the
        # fake must populate the same fields the agent would.
        state.explanations_requested = 5
        state.explanations = {
            "src/a.py": "first explanation",
            "src/b.py": "second explanation",
        }
        return state

    _patch_agents(monkeypatch, fake_explainability)

    pipeline_runner.run(job_id, "https://github.com/owner/repo", {"skip_llm": False})

    job = job_store.get(job_id)
    assert job.status == "complete", job.error
    assert job.error is None
    assert job.explanations_completed == 2
    assert job.explanations_total == 5
    assert job.explanations_failed == 0


def test_failed_explanations_are_recorded_on_the_job(monkeypatch):
    """A total LLM outage must not look like a successful 20/20 run."""
    job_store = JobStore()
    job_id = job_store.create("https://github.com/owner/repo", {"skip_llm": False})
    monkeypatch.setattr(pipeline_runner, "store", job_store)

    def fake_explainability(state, max_count=20, progress_callback=None):
        state.explanations_requested = 5
        state.explanations_failed = 5
        state.explanation_error = "poolside/laguna-xs-2.1: NotFoundError: 404"
        # Progress stays at zero because nothing succeeded.
        progress_callback(0, 5)
        return state

    _patch_agents(monkeypatch, fake_explainability)

    pipeline_runner.run(job_id, "https://github.com/owner/repo", {"skip_llm": False})

    job = job_store.get(job_id)
    assert job.status == "complete", job.error
    assert job.explanations_completed == 0
    assert job.explanations_total == 5
    assert job.explanations_failed == 5
    assert "404" in job.explanation_error


def test_skip_llm_records_skip_reason(monkeypatch):
    job_store = JobStore()
    job_id = job_store.create("https://github.com/owner/repo", {"skip_llm": True})
    monkeypatch.setattr(pipeline_runner, "store", job_store)

    captured = {}

    def fake_doc_generator(state):
        captured["reason"] = state.explanations_skipped_reason
        return state

    def fake_explainability(state, max_count=20, progress_callback=None):
        return state

    _patch_agents(monkeypatch, fake_explainability)
    monkeypatch.setattr(pipeline_runner.doc_generator, "run", fake_doc_generator)

    pipeline_runner.run(job_id, "https://github.com/owner/repo", {"skip_llm": True})

    assert "skip_llm" in (captured["reason"] or "")


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

def test_graph_then_complexity_then_rag_order(monkeypatch):
    """
    Phases 3-5 must run in data-dependency order.

    dependency_graph decides which files are in scope (analyzed_paths), and
    both complexity_scorer and code_rag filter on it. Running them
    concurrently let complexity score every code file instead of the sampled
    subset, which is how a report ended up claiming "300 files selected" next
    to 871 complexity rows.
    """
    job_store = JobStore()
    job_id = job_store.create("https://github.com/owner/repo", {"skip_llm": True})
    monkeypatch.setattr(pipeline_runner, "store", job_store)

    order = []

    def record(name):
        def _run(state, **kwargs):
            order.append(name)
            if name == "graph":
                # Emulate Sampled mode: the graph decides the analysed subset.
                state.analyzed_paths = {"src/a.py"}
                state.files_analyzed = 1
            return state
        return _run

    _patch_agents(monkeypatch, lambda state, **kwargs: state)
    monkeypatch.setattr(pipeline_runner.dependency_graph, "run", record("graph"))
    monkeypatch.setattr(pipeline_runner.complexity_scorer, "run", record("complexity"))
    monkeypatch.setattr(
        pipeline_runner.complexity_scorer,
        "apply_graph_coupling",
        lambda state: order.append("coupling"),
    )
    monkeypatch.setattr(pipeline_runner.code_rag, "run", record("rag"))

    pipeline_runner.run(job_id, "https://github.com/owner/repo", {"skip_llm": True})

    assert order == ["graph", "complexity", "coupling", "rag"], order


def test_complexity_sees_analyzed_paths_before_scoring(monkeypatch):
    """The graph's sampled subset must exist before complexity scoring starts."""
    job_store = JobStore()
    job_id = job_store.create("https://github.com/owner/repo", {"skip_llm": True})
    monkeypatch.setattr(pipeline_runner, "store", job_store)

    observed = {}

    def graph(state, **kwargs):
        state.analyzed_paths = {"src/a.py"}
        state.files_analyzed = 1
        return state

    def complexity(state, **kwargs):
        observed["analyzed_paths"] = state.analyzed_paths
        observed["files_analyzed"] = state.files_analyzed
        return state

    _patch_agents(monkeypatch, lambda state, **kwargs: state)
    monkeypatch.setattr(pipeline_runner.dependency_graph, "run", graph)
    monkeypatch.setattr(pipeline_runner.complexity_scorer, "run", complexity)

    pipeline_runner.run(job_id, "https://github.com/owner/repo", {"skip_llm": True})

    assert observed["analyzed_paths"] == {"src/a.py"}
    assert observed["files_analyzed"] == 1

# -----------------------------------------------------------------------
# Result serialisation: the explanation outcome must be explicit
# -----------------------------------------------------------------------

def _result_state(**kwargs):
    from src.state import ArchaeonState

    state = ArchaeonState(repo_url="https://github.com/o/r", owner="o", repo_name="r")
    state.default_branch = "main"
    state.files_discovered = 10
    state.files_analyzed = 5
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


def test_result_language_breakdown_counts_only_scored_files():
    """The production regression: 871 language files beside total_files 300."""
    from types import SimpleNamespace

    def score(path, language):
        return SimpleNamespace(
            file_path=path,
            language=language,
            function_scores={},
            avg_complexity=0.0,
            max_complexity=0.0,
            max_complexity_function="",
            function_count=0,
            avg_function_lines=0.0,
            risk_level="LOW",
            risk_reasons=[],
            coupling_score=0.0,
        )

    state = _result_state()
    state.files_analyzed = 2
    state.complexity_scores = {
        "src/a.rs": score("src/a.rs", "Rust"),
        "src/b.py": score("src/b.py", "Python"),
    }
    # Unscored manifest entries must not inflate the breakdown.
    state.file_manifest = [
        SimpleNamespace(path="src/a.rs", language="Rust"),
        SimpleNamespace(path="src/b.py", language="Python"),
        SimpleNamespace(path="src/c.rs", language="Rust"),
        SimpleNamespace(path="README.md", language="Markdown"),
    ]

    result = pipeline_runner._serialize_result("job", state)
    breakdown = result["summary"]["language_breakdown"]

    assert breakdown == {"Python": 1, "Rust": 1}
    assert sum(breakdown.values()) == result["summary"]["total_files"]


def test_result_reports_complete_explanations():
    state = _result_state(
        explanations_requested=5,
        explanations={"a.py": "x", "b.py": "y"},
    )
    result = pipeline_runner._serialize_result("job", state)
    assert result["explanation_status"] == "complete"
    assert result["explanations_requested"] == 5
    assert result["explanations_failed"] == 0


def test_result_reports_partial_explanations():
    state = _result_state(
        explanations_requested=5,
        explanations={"a.py": "x"},
        explanations_failed=4,
        explanation_error="rate limit",
    )
    result = pipeline_runner._serialize_result("job", state)
    assert result["explanation_status"] == "partial"
    assert result["explanations_failed"] == 4
    assert result["explanation_error"] == "rate limit"


def test_result_reports_failed_explanations():
    """The production regression: 20/20 progress but zero explanations."""
    state = _result_state(
        explanations_requested=20,
        explanations_failed=20,
        explanation_error="poolside/laguna-xs-2.1: NotFoundError: 404",
    )
    result = pipeline_runner._serialize_result("job", state)
    assert result["explanation_status"] == "failed"
    assert result["explanations_failed"] == 20
    assert "404" in result["explanation_error"]


def test_result_reports_skipped_explanations():
    state = _result_state()
    result = pipeline_runner._serialize_result("job", state, skip_llm=True)
    assert result["explanation_status"] == "skipped"
