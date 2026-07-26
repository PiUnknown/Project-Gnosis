"""
Tests for Phase 4: Complexity Scorer Agent.

All tests are offline — no network calls, no file I/O.
Tests cover:
  - Python complexity via radon
  - JS/TS branch counting and per-function scoring
  - Risk level assignment for all four levels
  - Full agent run with mock state
"""
import pytest
from src.parsers.complexity import (
    compute_python_complexity,
    compute_js_complexity,
    _count_branches,
)
from src.agents.complexity_scorer import _compute_risk, RISK_THRESHOLDS, run
from src.parsers.base import SymbolTable, FunctionInfo, ComplexityScore
from src.state import ArchaeonState, FileMetadata


# -----------------------------------------------------------------------
# Test fixtures
# -----------------------------------------------------------------------

def make_function(name: str, line_start: int = 1, line_end: int = 10,
                  docstring: str = None) -> FunctionInfo:
    return FunctionInfo(
        name=name, params=[], line_start=line_start, line_end=line_end,
        docstring=docstring, is_async=False, is_method=False
    )


def make_symbol_table(file_path: str, language: str,
                      functions=None, parse_error: bool = False) -> SymbolTable:
    return SymbolTable(
        file_path=file_path, language=language, module_docstring=None,
        functions=functions or [], classes=[], imports=[],
        parse_error=parse_error
    )


def make_minimal_state(files_and_tables: dict) -> ArchaeonState:
    """Build the minimum viable state to run the complexity agent."""
    state = ArchaeonState(
        repo_url="https://github.com/test/repo",
        owner="test", repo_name="repo", default_branch="main"
    )
    state.file_manifest = [
        FileMetadata(path=p, language=st.language,
                     line_count=100, size_bytes=2000, sha="abc")
        for p, st in files_and_tables.items()
    ]
    state.symbol_tables = files_and_tables
    state.raw_contents = {}
    state.graph_stats = {}
    state.circular_nodes = set()
    return state


# -----------------------------------------------------------------------
# Python complexity: radon
# -----------------------------------------------------------------------

class TestPythonComplexity:

    def test_no_branch_function_has_complexity_1(self):
        source = "def foo(x):\n    return x + 1\n"
        result = compute_python_complexity(source)
        assert result.get("foo") == 1

    def test_single_if_gives_complexity_2(self):
        source = (
            "def foo(x):\n"
            "    if x:\n"
            "        return 1\n"
            "    return 0\n"
        )
        result = compute_python_complexity(source)
        assert result.get("foo") == 2

    def test_for_loop_gives_complexity_2(self):
        source = (
            "def foo(items):\n"
            "    for item in items:\n"
            "        print(item)\n"
        )
        result = compute_python_complexity(source)
        assert result.get("foo") == 2

    def test_nested_branches_accumulate(self):
        source = (
            "def foo(x, items):\n"
            "    if x:\n"
            "        for item in items:\n"
            "            if item > 0:\n"
            "                pass\n"
            "    return x\n"
        )
        result = compute_python_complexity(source)
        # base(1) + if(1) + for(1) + inner if(1) = 4
        assert result.get("foo", 0) >= 4

    def test_multiple_functions_scored_independently(self):
        source = (
            "def simple():\n    return 1\n\n"
            "def branchy(x):\n"
            "    if x > 0:\n        return x\n"
            "    elif x < 0:\n        return -x\n"
            "    return 0\n"
        )
        result = compute_python_complexity(source)
        assert result.get("simple") == 1
        assert result.get("branchy", 0) >= 3   # 1 + if + elif

    def test_empty_source_returns_empty_dict(self):
        assert compute_python_complexity("") == {}

    def test_syntax_error_returns_empty_dict(self):
        result = compute_python_complexity("def broken(\n")
        assert isinstance(result, dict)   # must not raise

    def test_class_method_is_scored(self):
        source = (
            "class Processor:\n"
            "    def process(self, x):\n"
            "        if x > 0:\n"
            "            return x\n"
            "        return -x\n"
        )
        result = compute_python_complexity(source)
        # radon may return "process" or "Processor.process"
        assert len(result) >= 1
        assert max(result.values()) == 2


# -----------------------------------------------------------------------
# JS branch counting: _count_branches
# -----------------------------------------------------------------------

def _parse_js_root(source: str, language: str = "JavaScript"):
    from src.utils.tree_sitter_utils import get_parser
    parser = get_parser(language)
    if parser is None:
        pytest.skip(f"{language} grammar not installed")
    return parser.parse(bytes(source, 'utf-8')).root_node


class TestJSBranchCounting:

    def test_no_branches_returns_zero(self):
        root = _parse_js_root("function foo() { return 1; }\n")
        assert _count_branches(root) == 0

    def test_if_statement_counts_one(self):
        root = _parse_js_root("function foo(x) { if (x) { return 1; } }\n")
        assert _count_branches(root) >= 1

    def test_for_loop_counts_one(self):
        root = _parse_js_root("for (let i = 0; i < 10; i++) {}\n")
        assert _count_branches(root) >= 1

    def test_for_of_counts_one(self):
        root = _parse_js_root("for (const x of arr) {}\n")
        assert _count_branches(root) >= 1

    def test_while_loop_counts_one(self):
        root = _parse_js_root("while (true) { break; }\n")
        assert _count_branches(root) >= 1

    def test_catch_clause_counts_one(self):
        root = _parse_js_root("try { foo(); } catch (e) { bar(); }\n")
        assert _count_branches(root) >= 1

    def test_ternary_counts_one(self):
        root = _parse_js_root("const x = a ? b : c;\n")
        assert _count_branches(root) >= 1

    def test_logical_and_counts_one(self):
        root = _parse_js_root("const x = a && b;\n")
        assert _count_branches(root) >= 1

    def test_logical_or_counts_one(self):
        root = _parse_js_root("const x = a || b;\n")
        assert _count_branches(root) >= 1

    def test_switch_cases_count_separately(self):
        source = (
            "switch(x) {\n"
            "  case 1: break;\n"
            "  case 2: break;\n"
            "  default: break;\n"
            "}\n"
        )
        root = _parse_js_root(source)
        # 2 switch_case nodes (default does not count)
        assert _count_branches(root) >= 2


# -----------------------------------------------------------------------
# JS per-function complexity: compute_js_complexity
# -----------------------------------------------------------------------

class TestJSPerFunctionComplexity:

    def _run(self, source: str, language: str = "JavaScript") -> dict:
        from src.utils.tree_sitter_utils import get_parser
        from src.parsers.js_parser import extract_symbols
        parser = get_parser(language)
        if parser is None:
            pytest.skip(f"{language} grammar not installed")
        src_bytes = bytes(source, 'utf-8')
        tree = parser.parse(src_bytes)
        _, functions, _, _ = extract_symbols(tree, src_bytes, language)
        st = SymbolTable(file_path="test.js", language=language,
                         module_docstring=None, functions=functions)
        return compute_js_complexity(source, language, st)

    def test_simple_function_has_complexity_1(self):
        result = self._run("function foo() { return 1; }\n")
        assert result.get("foo") == 1

    def test_if_gives_complexity_2(self):
        result = self._run("function foo(x) { if (x) { return 1; } return 0; }\n")
        assert result.get("foo") == 2

    def test_arrow_function_is_scored(self):
        source = "const add = (a, b) => { if (a > b) { return a; } return b; };\n"
        result = self._run(source)
        assert result.get("add") == 2

    def test_empty_source_returns_empty_dict(self):
        result = self._run("")
        assert result == {}

    def test_two_functions_scored_independently(self):
        source = (
            "function simple() { return 1; }\n"
            "function branchy(x) { if (x) { return 1; } return 0; }\n"
        )
        result = self._run(source)
        assert result.get("simple") == 1
        assert result.get("branchy") == 2


# -----------------------------------------------------------------------
# Risk level assignment
# -----------------------------------------------------------------------

class TestRiskLevelAssignment:

    def _risk(self, **overrides) -> tuple:
        defaults = dict(
            avg_complexity=1.0, max_complexity=1.0, coupling_score=0,
            undocumented_ratio=0.0, function_count=5, parse_error=False,
            is_in_circular_dep=False, line_count=50
        )
        defaults.update(overrides)
        return _compute_risk(**defaults)

    # CRITICAL
    def test_parse_error_is_critical(self):
        level, reasons = self._risk(parse_error=True)
        assert level == "CRITICAL"
        assert len(reasons) > 0

    def test_circular_dep_is_critical(self):
        level, reasons = self._risk(is_in_circular_dep=True)
        assert level == "CRITICAL"
        assert len(reasons) > 0

    def test_max_complexity_at_critical_threshold(self):
        level, _ = self._risk(max_complexity=float(RISK_THRESHOLDS['max_complexity_critical']))
        assert level == "CRITICAL"

    def test_max_complexity_one_below_critical_is_not_critical(self):
        level, _ = self._risk(max_complexity=float(RISK_THRESHOLDS['max_complexity_critical'] - 1))
        assert level != "CRITICAL"

    # HIGH
    def test_avg_complexity_at_high_threshold(self):
        level, _ = self._risk(avg_complexity=RISK_THRESHOLDS['avg_complexity_high'])
        assert level == "HIGH"

    def test_max_complexity_at_high_threshold(self):
        level, _ = self._risk(max_complexity=float(RISK_THRESHOLDS['max_complexity_high']))
        assert level == "HIGH"

    def test_coupling_at_high_threshold(self):
        level, _ = self._risk(coupling_score=RISK_THRESHOLDS['coupling_high'])
        assert level == "HIGH"

    def test_high_undocumented_with_enough_functions(self):
        min_f = RISK_THRESHOLDS['min_functions_for_undoc_check']
        level, _ = self._risk(
            undocumented_ratio=RISK_THRESHOLDS['undocumented_ratio_high'],
            function_count=min_f + 1
        )
        assert level == "HIGH"

    def test_undocumented_ignored_with_too_few_functions(self):
        min_f = RISK_THRESHOLDS['min_functions_for_undoc_check']
        level, _ = self._risk(undocumented_ratio=0.99, function_count=min_f - 1)
        assert level not in ("HIGH", "CRITICAL")

    def test_high_line_count_is_high(self):
        level, _ = self._risk(line_count=RISK_THRESHOLDS['line_count_high'])
        assert level == "HIGH"

    # MEDIUM
    def test_avg_complexity_at_medium_threshold(self):
        level, _ = self._risk(avg_complexity=RISK_THRESHOLDS['avg_complexity_medium'])
        assert level == "MEDIUM"

    def test_coupling_at_medium_threshold(self):
        level, _ = self._risk(coupling_score=RISK_THRESHOLDS['coupling_medium'])
        assert level == "MEDIUM"

    def test_medium_line_count(self):
        level, _ = self._risk(line_count=RISK_THRESHOLDS['line_count_medium'])
        assert level == "MEDIUM"

    # LOW
    def test_completely_clean_file_is_low(self):
        level, reasons = self._risk()
        assert level == "LOW"
        assert reasons == []

    # Priority
    def test_critical_overrides_all_other_signals(self):
        level, _ = self._risk(
            parse_error=True,
            avg_complexity=15.0,
            coupling_score=12,
            line_count=1000
        )
        assert level == "CRITICAL"

    def test_high_overrides_medium_signals(self):
        level, _ = self._risk(
            avg_complexity=RISK_THRESHOLDS['avg_complexity_high'],
            coupling_score=RISK_THRESHOLDS['coupling_medium']
        )
        assert level == "HIGH"

    def test_multiple_medium_signals_stay_medium(self):
        level, reasons = self._risk(
            avg_complexity=RISK_THRESHOLDS['avg_complexity_medium'],
            coupling_score=RISK_THRESHOLDS['coupling_medium']
        )
        assert level == "MEDIUM"
        assert len(reasons) >= 2


# -----------------------------------------------------------------------
# Full agent run with mock state
# -----------------------------------------------------------------------

class TestComplexityAgent:

    def test_python_file_is_scored(self):
        source = "def foo(x):\n    if x:\n        return 1\n    return 0\n"
        st = make_symbol_table("src/foo.py", "Python",
                               functions=[make_function("foo", 1, 4)])
        state = make_minimal_state({"src/foo.py": st})
        state.raw_contents["src/foo.py"] = source
        result = run(state)
        assert "src/foo.py" in result.complexity_scores

    def test_yaml_file_is_skipped(self):
        st = make_symbol_table("config.yaml", "YAML")
        state = make_minimal_state({"config.yaml": st})
        result = run(state)
        assert "config.yaml" not in result.complexity_scores

    def test_markdown_file_is_skipped(self):
        st = make_symbol_table("README.md", "Markdown")
        state = make_minimal_state({"README.md": st})
        result = run(state)
        assert "README.md" not in result.complexity_scores

    def test_missing_content_scores_gracefully(self):
        st = make_symbol_table("src/empty.py", "Python")
        state = make_minimal_state({"src/empty.py": st})
        # No entry in raw_contents
        result = run(state)
        assert "src/empty.py" in result.complexity_scores
        score = result.complexity_scores["src/empty.py"]
        assert score.function_scores == {}
        assert score.avg_complexity == 0.0
        assert score.risk_level == "LOW"

    def test_coupling_sourced_from_graph_stats(self):
        st = make_symbol_table("src/hub.py", "Python")
        state = make_minimal_state({"src/hub.py": st})
        state.graph_stats["src/hub.py"] = {
            "out_degree": 9, "in_degree": 3, "pagerank": 0.05,
            "is_in_circular_dep": False, "dependents": [], "dependencies": []
        }
        result = run(state)
        score = result.complexity_scores["src/hub.py"]
        assert score.coupling_score == 9
        assert score.risk_level == "HIGH"   # coupling >= 8 threshold

    def test_circular_dep_propagates_to_critical(self):
        st = make_symbol_table("src/cycle.py", "Python")
        state = make_minimal_state({"src/cycle.py": st})
        state.circular_nodes = {"src/cycle.py"}
        result = run(state)
        score = result.complexity_scores["src/cycle.py"]
        assert score.is_in_circular_dep is True
        assert score.risk_level == "CRITICAL"
        assert len(score.risk_reasons) > 0

    def test_parse_error_propagates_to_critical(self):
        st = make_symbol_table("src/broken.py", "Python", parse_error=True)
        state = make_minimal_state({"src/broken.py": st})
        result = run(state)
        assert result.complexity_scores["src/broken.py"].risk_level == "CRITICAL"

    def test_undocumented_ratio_computed_correctly(self):
        functions = [
            make_function("documented", docstring="Does something"),
            make_function("undoc_a", docstring=None),
            make_function("undoc_b", docstring=None),
            make_function("undoc_c", docstring=None),
        ]
        st = make_symbol_table("src/docs.py", "Python", functions=functions)
        state = make_minimal_state({"src/docs.py": st})
        result = run(state)
        score = result.complexity_scores["src/docs.py"]
        assert score.function_count == 4
        assert score.undocumented_count == 3
        assert abs(score.undocumented_ratio - 0.75) < 0.01

    def test_avg_function_lines_computed(self):
        functions = [
            make_function("foo", line_start=1,  line_end=20),   # 20 lines
            make_function("bar", line_start=22, line_end=41),   # 20 lines
        ]
        st = make_symbol_table("src/lines.py", "Python", functions=functions)
        state = make_minimal_state({"src/lines.py": st})
        result = run(state)
        assert result.complexity_scores["src/lines.py"].avg_function_lines == 20.0

    def test_all_scored_files_have_required_fields(self):
        st = make_symbol_table("src/a.py", "Python")
        state = make_minimal_state({"src/a.py": st})
        result = run(state)
        score = result.complexity_scores["src/a.py"]
        for field in ("risk_level", "risk_reasons", "function_scores",
                      "avg_complexity", "max_complexity", "coupling_score",
                      "undocumented_ratio", "parse_error", "is_in_circular_dep"):
            assert hasattr(score, field), f"Missing field: {field}"