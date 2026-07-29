"""
Tests for Phase 6: Explainability Agent.

All tests are offline — no Groq API calls, no ChromaDB on disk.

Strategy:
  - call_llm is patched to return a canned string
  - sleep_between_calls is patched to be a no-op (no real delays)
  - CodeRetriever is replaced with MockRetriever (no ChromaDB needed)
  - state is constructed with minimal required fields

Tests cover:
  TestFileSelection         - _select_files_to_explain priority logic
  TestCodeContextAssembly   - _assemble_code_context budget and ordering
  TestPromptBuilding        - _build_user_prompt content and format
  TestExplainabilityAgent   - full agent.run() with all dependencies mocked
"""
import pytest
from unittest.mock import patch, MagicMock

from src.agents.explainability import (
    run,
    _select_files_to_explain,
    _assemble_code_context,
    _build_user_prompt,
    TIER_HIGH_INDEGREE,
    TIER_MEDIUM_INDEGREE,
    MAX_CODE_CHARS
)
from src.parsers.base import ComplexityScore
from src.state import ArchaeonState, FileMetadata


# -----------------------------------------------------------------------
# Fixtures and helpers
# -----------------------------------------------------------------------

def make_score(
    file_path: str,
    risk_level: str = "LOW",
    language: str = "Python",
    avg_complexity: float = 1.0,
    max_complexity: float = 1.0,
    max_complexity_function: str = "",
    coupling_score: int = 0,
    function_count: int = 2,
    parse_error: bool = False,
    is_in_circular_dep: bool = False,
    risk_reasons: list = None
) -> ComplexityScore:
    return ComplexityScore(
        file_path=file_path,
        language=language,
        function_scores={},
        avg_complexity=avg_complexity,
        max_complexity=max_complexity,
        max_complexity_function=max_complexity_function,
        function_count=function_count,
        avg_function_lines=10.0,
        coupling_score=coupling_score,
        undocumented_count=0,
        undocumented_ratio=0.0,
        parse_error=parse_error,
        is_in_circular_dep=is_in_circular_dep,
        line_count=100,
        risk_level=risk_level,
        risk_reasons=risk_reasons or []
    )


def make_graph_stats(in_degree: int = 0, out_degree: int = 0,
                     dependencies: list = None, dependents: list = None) -> dict:
    return {
        "in_degree": in_degree,
        "out_degree": out_degree,
        "pagerank": 0.01,
        "is_in_circular_dep": False,
        "dependencies": dependencies or [],
        "dependents": dependents or []
    }


def make_state(scores: dict = None, graph_stats: dict = None) -> ArchaeonState:
    state = ArchaeonState(
        repo_url="https://github.com/test/repo",
        owner="testowner",
        repo_name="testrepo",
        default_branch="main"
    )
    state.complexity_scores = scores or {}
    state.graph_stats = graph_stats or {}
    state.symbol_tables = {}
    state.chroma_collection_name = "gnosis_testowner_testrepo"
    state.file_manifest = []
    return state


class MockRetriever:
    """
    Drop-in replacement for CodeRetriever in tests.
    Returns configurable chunks per file path.
    """
    def __init__(self, chunks_by_file: dict = None, count: int = 10):
        self._chunks = chunks_by_file or {}
        self._count = count

    def get_file_chunks(self, file_path: str) -> list:
        return self._chunks.get(file_path, [])

    def count(self) -> int:
        return self._count


def make_chunk(
    file_path: str,
    symbol_name: str = "foo",
    symbol_type: str = "function",
    content: str = "def foo(): pass",
    complexity: float = None,
    line_start: int = 1,
    line_end: int = 5
) -> dict:
    return {
        "file_path": file_path,
        "symbol_name": symbol_name,
        "symbol_type": symbol_type,
        "content": content,
        "complexity": complexity,
        "risk_level": "LOW",
        "language": "Python",
        "line_start": line_start,
        "line_end": line_end,
        "distance": 0.0
    }


# -----------------------------------------------------------------------
# TestFileSelection
# -----------------------------------------------------------------------

class TestFileSelection:

    def test_empty_scores_returns_empty(self):
        state = make_state(scores={})
        result = _select_files_to_explain(state, max_count=10)
        assert result == []

    def test_critical_selected_before_low(self):
        scores = {
            "src/low.py":      make_score("src/low.py",      risk_level="LOW"),
            "src/critical.py": make_score("src/critical.py", risk_level="CRITICAL"),
        }
        state = make_state(scores=scores)
        result = _select_files_to_explain(state, max_count=2)
        assert result[0] == "src/critical.py"

    def test_high_indegree_beats_high_risk(self):
        scores = {
            "src/hub.py":  make_score("src/hub.py",  risk_level="LOW"),
            "src/risky.py": make_score("src/risky.py", risk_level="HIGH"),
        }
        graph_stats = {
            "src/hub.py":   make_graph_stats(in_degree=TIER_HIGH_INDEGREE),
            "src/risky.py": make_graph_stats(in_degree=0),
        }
        state = make_state(scores=scores, graph_stats=graph_stats)
        result = _select_files_to_explain(state, max_count=2)
        assert result[0] == "src/hub.py"

    def test_cap_is_respected(self):
        scores = {f"src/file_{i}.py": make_score(f"src/file_{i}.py") for i in range(20)}
        state = make_state(scores=scores)
        result = _select_files_to_explain(state, max_count=5)
        assert len(result) == 5

    def test_within_tier_higher_indegree_first(self):
        scores = {
            "src/a.py": make_score("src/a.py", risk_level="HIGH"),
            "src/b.py": make_score("src/b.py", risk_level="HIGH"),
        }
        graph_stats = {
            "src/a.py": make_graph_stats(in_degree=3),
            "src/b.py": make_graph_stats(in_degree=10),
        }
        state = make_state(scores=scores, graph_stats=graph_stats)
        result = _select_files_to_explain(state, max_count=2)
        assert result[0] == "src/b.py"

    def test_critical_beats_high_indegree(self):
        scores = {
            "src/critical.py": make_score("src/critical.py", risk_level="CRITICAL"),
            "src/hub.py":      make_score("src/hub.py",      risk_level="LOW"),
        }
        graph_stats = {
            "src/critical.py": make_graph_stats(in_degree=0),
            "src/hub.py":      make_graph_stats(in_degree=100),
        }
        state = make_state(scores=scores, graph_stats=graph_stats)
        result = _select_files_to_explain(state, max_count=2)
        assert result[0] == "src/critical.py"

    def test_medium_selected_before_low(self):
        scores = {
            "src/low.py":    make_score("src/low.py",    risk_level="LOW"),
            "src/medium.py": make_score("src/medium.py", risk_level="MEDIUM"),
        }
        state = make_state(scores=scores)
        result = _select_files_to_explain(state, max_count=2)
        assert result[0] == "src/medium.py"

    def test_all_four_risk_levels_ordered(self):
        scores = {
            "src/low.py":      make_score("src/low.py",      risk_level="LOW"),
            "src/medium.py":   make_score("src/medium.py",   risk_level="MEDIUM"),
            "src/high.py":     make_score("src/high.py",     risk_level="HIGH"),
            "src/critical.py": make_score("src/critical.py", risk_level="CRITICAL"),
        }
        state = make_state(scores=scores)
        result = _select_files_to_explain(state, max_count=4)
        assert result[0] == "src/critical.py"
        assert result[-1] == "src/low.py"

    def test_result_is_list_of_strings(self):
        scores = {"src/a.py": make_score("src/a.py")}
        state = make_state(scores=scores)
        result = _select_files_to_explain(state, max_count=5)
        assert isinstance(result, list)
        assert all(isinstance(p, str) for p in result)

    def test_no_duplicates_in_result(self):
        scores = {f"src/f{i}.py": make_score(f"src/f{i}.py") for i in range(10)}
        state = make_state(scores=scores)
        result = _select_files_to_explain(state, max_count=10)
        assert len(result) == len(set(result))


# -----------------------------------------------------------------------
# TestCodeContextAssembly
# -----------------------------------------------------------------------

class TestCodeContextAssembly:

    def test_empty_retriever_returns_empty_string(self):
        retriever = MockRetriever()
        result = _assemble_code_context("src/a.py", retriever)
        assert result == ""

    def test_module_chunk_appears_in_output(self):
        chunks = {
            "src/a.py": [
                make_chunk("src/a.py", "module", "module", "import os\nimport sys")
            ]
        }
        retriever = MockRetriever(chunks)
        result = _assemble_code_context("src/a.py", retriever)
        assert "import os" in result

    def test_function_chunk_appears_in_output(self):
        chunks = {
            "src/a.py": [
                make_chunk("src/a.py", "validate", "function", "def validate(x): return x")
            ]
        }
        retriever = MockRetriever(chunks)
        result = _assemble_code_context("src/a.py", retriever)
        assert "validate" in result

    def test_high_complexity_function_appears_before_low(self):
        chunks = {
            "src/a.py": [
                make_chunk("src/a.py", "simple",  "function", "def simple(): pass",  complexity=1.0),
                make_chunk("src/a.py", "complex", "function", "def complex(): pass", complexity=15.0),
            ]
        }
        retriever = MockRetriever(chunks)
        result = _assemble_code_context("src/a.py", retriever)
        assert result.index("complex") < result.index("simple")

    def test_module_chunk_appears_before_function_chunks(self):
        chunks = {
            "src/a.py": [
                make_chunk("src/a.py", "foo",    "function", "def foo(): pass"),
                make_chunk("src/a.py", "module", "module",   "import os"),
            ]
        }
        retriever = MockRetriever(chunks)
        result = _assemble_code_context("src/a.py", retriever)
        assert result.index("import os") < result.index("def foo")

    def test_budget_respected(self):
        large_content = "x" * (MAX_CODE_CHARS + 1000)
        chunks = {
            "src/a.py": [
                make_chunk("src/a.py", "huge", "function", large_content)
            ]
        }
        retriever = MockRetriever(chunks)
        result = _assemble_code_context("src/a.py", retriever)
        assert len(result) <= MAX_CODE_CHARS + 200  # small buffer for truncation notice

    def test_truncation_notice_added_when_over_budget(self):
        large_content = "x" * (MAX_CODE_CHARS + 1000)
        chunks = {
            "src/a.py": [
                make_chunk("src/a.py", "big", "function", large_content)
            ]
        }
        retriever = MockRetriever(chunks)
        result = _assemble_code_context("src/a.py", retriever)
        assert "truncated" in result.lower() or "budget" in result.lower()

    def test_chunks_separated_by_divider(self):
        chunks = {
            "src/a.py": [
                make_chunk("src/a.py", "foo", "function", "def foo(): pass"),
                make_chunk("src/a.py", "bar", "function", "def bar(): pass"),
            ]
        }
        retriever = MockRetriever(chunks)
        result = _assemble_code_context("src/a.py", retriever)
        assert "---" in result

    def test_file_with_no_chunks_returns_empty(self):
        retriever = MockRetriever(chunks_by_file={"src/other.py": []})
        result = _assemble_code_context("src/unknown.py", retriever)
        assert result == ""


# -----------------------------------------------------------------------
# TestPromptBuilding
# -----------------------------------------------------------------------

class TestPromptBuilding:

    def test_file_path_in_prompt(self):
        score = make_score("src/auth.py")
        prompt = _build_user_prompt("src/auth.py", "Python", score, {}, "def login(): pass")
        assert "src/auth.py" in prompt

    def test_language_in_prompt(self):
        score = make_score("src/auth.py")
        prompt = _build_user_prompt("src/auth.py", "TypeScript", score, {}, "")
        assert "TypeScript" in prompt

    def test_risk_level_in_prompt(self):
        score = make_score("src/auth.py", risk_level="CRITICAL")
        prompt = _build_user_prompt("src/auth.py", "Python", score, {}, "")
        assert "CRITICAL" in prompt

    def test_risk_reasons_in_prompt(self):
        score = make_score(
            "src/auth.py",
            risk_level="CRITICAL",
            risk_reasons=["Involved in a circular dependency"]
        )
        prompt = _build_user_prompt("src/auth.py", "Python", score, {}, "")
        assert "circular" in prompt.lower()

    def test_code_context_in_prompt(self):
        score = make_score("src/a.py")
        code = "def validate_token(token): return True"
        prompt = _build_user_prompt("src/a.py", "Python", score, {}, code)
        assert "validate_token" in prompt

    def test_dependencies_in_prompt(self):
        score = make_score("src/a.py")
        stats = make_graph_stats(
            dependencies=["src/b.py", "src/c.py"],
            dependents=["src/main.py"]
        )
        prompt = _build_user_prompt("src/a.py", "Python", score, stats, "")
        assert "b.py" in prompt or "src/b.py" in prompt

    def test_dependents_in_prompt(self):
        score = make_score("src/a.py")
        stats = make_graph_stats(dependents=["src/main.py", "src/app.py"], in_degree=2)
        prompt = _build_user_prompt("src/a.py", "Python", score, stats, "")
        assert "main.py" in prompt or "Imported by" in prompt

    def test_no_code_context_shows_fallback_message(self):
        score = make_score("src/a.py")
        prompt = _build_user_prompt("src/a.py", "Python", score, {}, "")
        assert "not available" in prompt.lower() or "parse error" in prompt.lower() or "not chunked" in prompt.lower() or "No code" in prompt

    def test_none_complexity_score_does_not_crash(self):
        prompt = _build_user_prompt("src/a.py", "Python", None, {}, "def foo(): pass")
        assert "src/a.py" in prompt
        assert isinstance(prompt, str)

    def test_empty_graph_stats_does_not_crash(self):
        score = make_score("src/a.py")
        prompt = _build_user_prompt("src/a.py", "Python", score, {}, "def foo(): pass")
        assert isinstance(prompt, str)

    def test_task_instruction_in_prompt(self):
        score = make_score("src/a.py")
        prompt = _build_user_prompt("src/a.py", "Python", score, {}, "")
        assert "200" in prompt or "300" in prompt or "Task" in prompt

    def test_max_complexity_function_in_prompt(self):
        score = make_score(
            "src/a.py",
            max_complexity=15.0,
            max_complexity_function="process_request"
        )
        prompt = _build_user_prompt("src/a.py", "Python", score, {}, "")
        assert "process_request" in prompt

    def test_coupling_score_in_prompt(self):
        score = make_score("src/a.py", coupling_score=7)
        prompt = _build_user_prompt("src/a.py", "Python", score, {}, "")
        assert "7" in prompt


# -----------------------------------------------------------------------
# TestExplainabilityAgent (full agent with all dependencies mocked)
# -----------------------------------------------------------------------

CANNED_EXPLANATION = (
    "This file defines the shared state object used by all agents. "
    "The ArchaeonState dataclass holds the outputs of every pipeline stage. "
    "New engineers should read state.py before any agent file."
)


def _make_full_state(num_files: int = 3) -> ArchaeonState:
    """Build a complete state object for full agent run tests."""
    scores = {}
    graph  = {}

    for i in range(num_files):
        path = f"src/module_{i}.py"
        risk = ["LOW", "MEDIUM", "HIGH", "CRITICAL"][i % 4]
        scores[path] = make_score(path, risk_level=risk)
        graph[path]  = make_graph_stats(in_degree=i)

    state = make_state(scores=scores, graph_stats=graph)
    return state


class TestExplainabilityAgent:

    def _patched_run(self, state, mock_retriever, max_count=5,
                     call_llm_return=CANNED_EXPLANATION):
        """Helper: run the agent with all external deps mocked."""
        with patch(
            "src.agents.explainability.CodeRetriever",
            return_value=mock_retriever
        ):
            with patch(
                "src.agents.explainability.call_llm",
                return_value=call_llm_return
            ):
                with patch("src.agents.explainability.sleep_between_calls"):
                    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
                        return run(state, max_count=max_count)

    def test_explanations_populated(self):
        state = _make_full_state(num_files=3)
        result = self._patched_run(state, MockRetriever())
        assert len(result.explanations) > 0

    def test_explanation_is_string(self):
        state = _make_full_state(num_files=2)
        result = self._patched_run(state, MockRetriever())
        for exp in result.explanations.values():
            assert isinstance(exp, str)
            assert len(exp) > 0

    def test_cap_respected_in_explanations(self):
        state = _make_full_state(num_files=10)
        result = self._patched_run(state, MockRetriever(), max_count=3)
        assert len(result.explanations) <= 3

    def test_groq_failure_does_not_crash(self):
        state = _make_full_state(num_files=3)
        result = self._patched_run(state, MockRetriever(), call_llm_return=None)
        # Pipeline should complete; explanations may be empty but no exception
        assert isinstance(result.explanations, dict)

    def test_missing_collection_name_returns_early(self):
        state = _make_full_state()
        state.chroma_collection_name = None
        with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
            result = run(state, max_count=5)
        assert len(result.explanations) == 0

    def test_missing_api_key_returns_early(self):
        state = _make_full_state()
        env = {k: v for k, v in __import__("os").environ.items() if k != "GROQ_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            result = run(state, max_count=5)
        assert len(result.explanations) == 0

    def test_code_context_used_from_retriever(self):
        state = _make_full_state(num_files=1)
        path  = list(state.complexity_scores.keys())[0]
        chunks = {
            path: [make_chunk(path, "authenticate", "function",
                              "def authenticate(token): return verify(token)")]
        }
        retriever = MockRetriever(chunks_by_file=chunks)
        captured_prompts = []

        def capture_call(system_prompt, user_prompt, **kwargs):
            captured_prompts.append(user_prompt)
            return CANNED_EXPLANATION

        with patch("src.agents.explainability.CodeRetriever", return_value=retriever):
            with patch("src.agents.explainability.call_llm", side_effect=capture_call):
                with patch("src.agents.explainability.sleep_between_calls"):
                    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
                        run(state, max_count=1)

        assert len(captured_prompts) > 0
        assert "authenticate" in captured_prompts[0]

    def test_graph_context_used_from_state(self):
        state = _make_full_state(num_files=1)
        path  = list(state.complexity_scores.keys())[0]
        state.graph_stats[path] = make_graph_stats(
            in_degree=7,
            dependents=["src/main.py", "src/app.py"],
            dependencies=["src/db.py"]
        )
        captured_prompts = []

        def capture_call(system_prompt, user_prompt, **kwargs):
            captured_prompts.append(user_prompt)
            return CANNED_EXPLANATION

        with patch("src.agents.explainability.CodeRetriever", return_value=MockRetriever()):
            with patch("src.agents.explainability.call_llm", side_effect=capture_call):
                with patch("src.agents.explainability.sleep_between_calls"):
                    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
                        run(state, max_count=1)

        assert len(captured_prompts) > 0
        assert "main.py" in captured_prompts[0] or "Imported by" in captured_prompts[0]

    def test_sleep_called_between_calls_not_after_last(self):
        state = _make_full_state(num_files=3)
        sleep_calls = []

        def mock_sleep(delay=None):
            sleep_calls.append(True)

        with patch("src.agents.explainability.CodeRetriever", return_value=MockRetriever()):
            with patch("src.agents.explainability.call_llm", return_value=CANNED_EXPLANATION):
                with patch("src.agents.explainability.sleep_between_calls", side_effect=mock_sleep):
                    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
                        result = run(state, max_count=3)

        explained = len(result.explanations)
        # sleep is called between calls: explained - 1 times (not after the last)
        assert len(sleep_calls) == max(0, explained - 1)

    def test_explanation_stripped_of_whitespace(self):
        state = _make_full_state(num_files=1)
        padded = "   \n\n" + CANNED_EXPLANATION + "\n\n   "

        with patch("src.agents.explainability.CodeRetriever", return_value=MockRetriever()):
            with patch("src.agents.explainability.call_llm", return_value=padded):
                with patch("src.agents.explainability.sleep_between_calls"):
                    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
                        result = run(state, max_count=1)

        for exp in result.explanations.values():
            assert not exp.startswith(" ")
            assert not exp.endswith(" ")
            assert not exp.startswith("\n")
            assert not exp.endswith("\n")

    def test_partial_success_when_some_calls_fail(self):
        state = _make_full_state(num_files=4)
        call_count = [0]

        def alternating_calls(system_prompt, user_prompt, **kwargs):
            call_count[0] += 1
            # Every other call fails
            return CANNED_EXPLANATION if call_count[0] % 2 == 1 else None

        with patch("src.agents.explainability.CodeRetriever", return_value=MockRetriever()):
            with patch("src.agents.explainability.call_llm", side_effect=alternating_calls):
                with patch("src.agents.explainability.sleep_between_calls"):
                    with patch.dict("os.environ", {"GROQ_API_KEY": "test_key"}):
                        result = run(state, max_count=4)

        # Some explanations stored, some not — but no crash
        assert 0 < len(result.explanations) <= 4