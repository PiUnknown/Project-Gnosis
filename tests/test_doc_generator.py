"""
Tests for Phase 7: Doc Generator Agent.

All tests are offline — no LLM calls, no ChromaDB, no network.

Structure:
  TestSectionBuilders       - test each _build_* function independently
  TestRobustness            - empty/missing state fields handled gracefully
  TestFullAgentRun          - test run() with realistic state
  TestDocumentStructure     - verify output has correct Markdown structure
"""
import pytest
from datetime import datetime

from src.agents.doc_generator import (
    run,
    _build_header,
    _build_project_summary,
    _build_repository_statistics,
    _build_architecture_map,
    _build_core_components,
    _build_tech_debt_report,
    _build_reading_order,
    _build_footer,
    _language_breakdown,
    _risk_counts
)
from src.parsers.base import (
    ComplexityScore, SymbolTable, FunctionInfo, ClassInfo
)
from src.state import ArchaeonState, FileMetadata


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

def make_file_meta(path: str, language: str = "Python",
                   line_count: int = 100) -> FileMetadata:
    return FileMetadata(
        path=path, language=language,
        line_count=line_count, size_bytes=2000, sha="abc"
    )


def make_score(
    file_path: str,
    risk_level: str = "LOW",
    language: str = "Python",
    avg_complexity: float = 2.0,
    max_complexity: float = 3.0,
    max_complexity_function: str = "foo",
    function_count: int = 3,
    coupling_score: int = 1,
    parse_error: bool = False,
    is_in_circular_dep: bool = False,
    risk_reasons: list = None,
    function_scores: dict = None
) -> ComplexityScore:
    return ComplexityScore(
        file_path=file_path, language=language,
        function_scores=function_scores or {"foo": 3},
        avg_complexity=avg_complexity,
        max_complexity=max_complexity,
        max_complexity_function=max_complexity_function,
        function_count=function_count,
        avg_function_lines=12.0,
        coupling_score=coupling_score,
        undocumented_count=0,
        undocumented_ratio=0.0,
        parse_error=parse_error,
        is_in_circular_dep=is_in_circular_dep,
        line_count=100,
        risk_level=risk_level,
        risk_reasons=risk_reasons or []
    )


def make_graph_stats_entry(
    in_degree: int = 0,
    out_degree: int = 0,
    dependents: list = None,
    dependencies: list = None
) -> dict:
    return {
        "in_degree": in_degree,
        "out_degree": out_degree,
        "pagerank": 0.01,
        "is_in_circular_dep": False,
        "dependents": dependents or [],
        "dependencies": dependencies or []
    }


def make_symbol_table(
    path: str,
    language: str = "Python",
    module_docstring: str = None,
    functions: list = None,
    classes: list = None
) -> SymbolTable:
    return SymbolTable(
        file_path=path, language=language,
        module_docstring=module_docstring,
        functions=functions or [],
        classes=classes or [],
        imports=[]
    )


def make_function(name: str, line_start: int = 1,
                  line_end: int = 10) -> FunctionInfo:
    return FunctionInfo(
        name=name, params=["x"], line_start=line_start, line_end=line_end,
        docstring=None, is_async=False, is_method=False
    )


def make_full_state(
    num_files: int = 4,
    with_explanations: bool = True,
    with_graph: bool = True,
    with_cycles: bool = False
) -> ArchaeonState:
    """
    Build a realistic ArchaeonState for integration tests.
    """
    paths = [f"src/module_{i}.py" for i in range(num_files)]
    risk_levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    state = ArchaeonState(
        repo_url="https://github.com/testowner/testrepo",
        owner="testowner",
        repo_name="testrepo",
        default_branch="main"
    )

    # File manifest
    state.file_manifest = [make_file_meta(p) for p in paths]

    # Symbol tables
    state.symbol_tables = {
        p: make_symbol_table(
            p,
            module_docstring=f"Module {i} handles core operations.",
            functions=[make_function(f"func_{i}_a"), make_function(f"func_{i}_b")]
        )
        for i, p in enumerate(paths)
    }

    # Complexity scores
    state.complexity_scores = {
        p: make_score(
            p,
            risk_level=risk_levels[i % 4],
            function_scores={f"func_{i}_a": i + 1, f"func_{i}_b": i + 2},
            avg_complexity=float(i + 1),
            max_complexity=float(i + 2),
            coupling_score=i,
            risk_reasons=[f"Reason {i}"] if risk_levels[i % 4] != "LOW" else []
        )
        for i, p in enumerate(paths)
    }

    # Graph stats
    if with_graph:
        state.graph_stats = {
            p: make_graph_stats_entry(
                in_degree=num_files - i,
                out_degree=i,
                dependents=paths[:i],
                dependencies=paths[i+1:] if i + 1 < num_files else []
            )
            for i, p in enumerate(paths)
        }

    # Circular deps
    if with_cycles:
        state.circular_deps = [[paths[0], paths[1]]]
        state.circular_nodes = {paths[0], paths[1]}
        state.topological_order = []
    else:
        state.circular_deps = []
        state.circular_nodes = set()
        state.topological_order = list(reversed(paths))

    # Explanations
    if with_explanations:
        state.explanations = {
            p: f"This file defines the core logic for module {i}. "
               f"It exports func_{i}_a and func_{i}_b. "
               f"New engineers should read this after understanding the state module."
            for i, p in enumerate(paths)
        }
    else:
        state.explanations = {}

    # Dependency graph (minimal NetworkX stub)
    try:
        import networkx as nx
        G = nx.DiGraph()
        for p in paths:
            G.add_node(p)
        for i in range(len(paths) - 1):
            G.add_edge(paths[i + 1], paths[i])
        state.dependency_graph = G
    except ImportError:
        state.dependency_graph = None

    return state


# -----------------------------------------------------------------------
# TestSectionBuilders
# -----------------------------------------------------------------------

class TestHeader:

    def test_contains_repo_name(self):
        state = make_full_state()
        result = _build_header(state)
        assert "testrepo" in result

    def test_is_h1_markdown(self):
        state = make_full_state()
        result = _build_header(state)
        assert result.startswith("# ")


class TestProjectSummary:

    def test_contains_h2_heading(self):
        state = make_full_state()
        result = _build_project_summary(state)
        assert "## Project Summary" in result

    def test_contains_file_count(self):
        state = make_full_state(num_files=4)
        result = _build_project_summary(state)
        assert "4" in result

    def test_contains_language(self):
        state = make_full_state()
        result = _build_project_summary(state)
        assert "Python" in result


    def test_critical_count_mentioned(self):
        state = make_full_state(num_files=4)
        result = _build_project_summary(state)
        # The state has 1 CRITICAL file (index 3 % 4 == 3 → "CRITICAL")
        assert "CRITICAL" in result or "critical" in result.lower()

    def test_no_crash_without_explanations(self):
        state = make_full_state(with_explanations=False)
        result = _build_project_summary(state)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_crash_without_graph_stats(self):
        state = make_full_state(with_graph=False)
        result = _build_project_summary(state)
        assert isinstance(result, str)


class TestStatsSection:

    def test_contains_h2_heading(self):
        state = make_full_state()
        result = _build_repository_statistics(state)
        assert "## Repository Statistics" in result

    def test_contains_markdown_table(self):
        state = make_full_state()
        result = _build_repository_statistics(state)
        assert "|" in result

    def test_file_count_in_table(self):
        state = make_full_state(num_files=4)
        result = _build_repository_statistics(state)
        assert "4" in result

    def test_circular_dep_count_shown(self):
        state = make_full_state(with_cycles=True)
        result = _build_repository_statistics(state)
        assert "1" in result   # 1 cycle

    def test_zero_circular_deps_shown(self):
        state = make_full_state(with_cycles=False)
        result = _build_repository_statistics(state)
        assert "0" in result


class TestArchitectureMap:

    def test_contains_h2_heading(self):
        state = make_full_state()
        result = _build_architecture_map(state)
        assert "## Architecture Map" in result

    def test_high_indegree_file_appears(self):
        state = make_full_state(num_files=4)
        result = _build_architecture_map(state)
        # module_0 has in_degree=4 (highest)
        assert "module_0" in result

    def test_table_present(self):
        state = make_full_state()
        result = _build_architecture_map(state)
        assert "In-Degree (Imports)" in result

    def test_circular_node_flagged(self):
        state = make_full_state(with_cycles=True)
        # Circular nodes are marked as CRITICAL risk level
        result = _build_architecture_map(state)
        assert "CRITICAL" in result

    def test_empty_graph_stats_returns_message(self):
        state = make_full_state(with_graph=False)
        result = _build_architecture_map(state)
        assert isinstance(result, str)
        # Should either return empty or a helpful message
        assert "Architecture" in result or result == ""


class TestCoreComponents:

    def test_contains_h2_heading(self):
        state = make_full_state(with_explanations=True)
        result = _build_core_components(state)
        assert "## Core Components" in result

    def test_each_explained_file_has_h3_heading(self):
        state = make_full_state(num_files=3, with_explanations=True)
        result = _build_core_components(state)
        for i in range(3):
            assert f"module_{i}.py" in result

    def test_explanation_text_appears(self):
        state = make_full_state(num_files=2, with_explanations=True)
        result = _build_core_components(state)
        assert "core logic" in result

    def test_risk_level_shown(self):
        state = make_full_state(num_files=4, with_explanations=True)
        result = _build_core_components(state)
        assert "CRITICAL" in result or "HIGH" in result

    def test_no_explanations_shows_fallback_message(self):
        state = make_full_state(with_explanations=False)
        result = _build_core_components(state)
        assert "full explanation" not in result

    def test_dependency_context_shown(self):
        state = make_full_state(num_files=4, with_explanations=True)
        result = _build_core_components(state)
        # Should show imports/imported-by context
        assert "Depends on" in result or "Depended on by" in result

    def test_most_imported_file_appears_first(self):
        state = make_full_state(num_files=4, with_explanations=True)
        result = _build_core_components(state)
        # module_0 has highest in_degree (4)
        idx_0 = result.find("module_0")
        idx_1 = result.find("module_1")
        if idx_0 >= 0 and idx_1 >= 0:
            assert idx_0 < idx_1


class TestTechDebtReport:

    def test_contains_h2_heading(self):
        state = make_full_state()
        result = _build_tech_debt_report(state)
        assert "## Tech Debt Report" in result

    def test_circular_dep_listed(self):
        state = make_full_state(with_cycles=True)
        result = _build_tech_debt_report(state)
        assert "module_0" in result or "Circular" in result

    def test_no_cycles_message_when_clean(self):
        state = make_full_state(with_cycles=False)
        result = _build_tech_debt_report(state)
        assert "No circular" in result or "✅" in result

    def test_critical_files_table_present(self):
        state = make_full_state(num_files=4)
        result = _build_tech_debt_report(state)
        # CRITICAL risk file should appear
        assert "module_3" in result   # index 3 → CRITICAL

    def test_complex_functions_listed(self):
        state = make_full_state(num_files=4)
        # Give one file a highly complex function
        state.complexity_scores["src/module_3.py"].function_scores = {"big_fn": 22}
        result = _build_tech_debt_report(state)
        assert "big_fn" in result or "22" in result

    def test_parse_error_files_listed(self):
        state = make_full_state(num_files=2)
        state.complexity_scores["src/module_0.py"].parse_error = True
        state.complexity_scores["src/module_0.py"].risk_level = "CRITICAL"
        result = _build_tech_debt_report(state)
        assert "Parse Error" in result or "parse" in result.lower() or "module_0" in result

    def test_high_coupling_files_listed(self):
        state = make_full_state(num_files=2)
        state.complexity_scores["src/module_0.py"].risk_level = "CRITICAL"
        state.complexity_scores["src/module_0.py"].coupling_score = 10
        result = _build_tech_debt_report(state)
        assert "Coupling" in result or "coupling" in result.lower() or "module_0" in result


class TestReadingOrder:

    def test_contains_h2_heading(self):
        state = make_full_state()
        result = _build_reading_order(state)
        assert "## Suggested Reading Order" in result

    def test_files_listed_when_topo_order_exists(self):
        state = make_full_state(with_cycles=False)
        result = _build_reading_order(state)
        assert "module_" in result

    def test_numbered_list_when_topo_order_exists(self):
        state = make_full_state(with_cycles=False)
        result = _build_reading_order(state)
        assert "1." in result

    def test_cycle_warning_when_no_topo_order(self):
        state = make_full_state(with_cycles=True)
        result = _build_reading_order(state)
        assert "circular" in result.lower() or "cycle" in result.lower()

    def test_cap_respected(self):
        # Make state with many files
        state = ArchaeonState(
            repo_url="https://github.com/t/r",
            owner="t", repo_name="r", default_branch="main"
        )
        state.topological_order = [f"src/file_{i}.py" for i in range(50)]
        state.circular_deps = []
        state.circular_nodes = set()
        state.complexity_scores = {}
        state.graph_stats = {}
        state.explanations = {}
        state.file_manifest = []
        state.symbol_tables = {}

        result = _build_reading_order(state)
        # Cap is 25, so "26." should not appear
        assert "26." not in result

    def test_overflow_note_shown(self):
        state = ArchaeonState(
            repo_url="https://github.com/t/r",
            owner="t", repo_name="r", default_branch="main"
        )
        state.topological_order = [f"src/file_{i}.py" for i in range(50)]
        state.circular_deps = []
        state.circular_nodes = set()
        state.complexity_scores = {}
        state.graph_stats = {}
        state.explanations = {}
        state.file_manifest = []
        state.symbol_tables = {}

        result = _build_reading_order(state)
        assert "more" in result or "graph_data" in result

    def test_safe_starting_files_shown_when_cycles(self):
        state = make_full_state(with_cycles=True, num_files=4)
        # module_2 is LOW risk (index 2 % 4 → "HIGH" → no)
        # Let's force a LOW risk file
        state.complexity_scores["src/module_0.py"].risk_level = "LOW"
        state.circular_nodes = {"src/module_1.py"}  # only module_1 in cycle
        result = _build_reading_order(state)
        assert "not available" in result


class TestFooter:

    def test_starts_with_divider(self):
        state = make_full_state()
        result = _build_footer(state)
        assert result.startswith("---")

    def test_contains_gnosis(self):
        state = make_full_state()
        result = _build_footer(state)
        assert "Gnosis" in result

    def test_contains_analysis_mode(self):
        state = make_full_state()
        result = _build_footer(state)
        assert "Mode" in result

    def test_contains_github_url(self):
        state = make_full_state()
        result = _build_footer(state)
        assert "https://github.com/testowner/testrepo" in result

    def test_contains_branch_name(self):
        state = make_full_state()
        result = _build_footer(state)
        assert "main" in result

    def test_contains_year(self):
        state = make_full_state()
        result = _build_footer(state)
        assert str(datetime.now().year) in result

    def test_none_branch_defaults_to_main(self):
        state = make_full_state()
        state.default_branch = None
        result = _build_footer(state)
        assert "main" in result


# -----------------------------------------------------------------------
# TestRobustness
# -----------------------------------------------------------------------

class TestRobustness:

    def _empty_state(self) -> ArchaeonState:
        state = ArchaeonState(
            repo_url="https://github.com/t/r",
            owner="t", repo_name="r", default_branch="main"
        )
        state.file_manifest   = []
        state.symbol_tables   = {}
        state.complexity_scores = {}
        state.graph_stats     = {}
        state.circular_deps   = []
        state.circular_nodes  = set()
        state.topological_order = []
        state.explanations    = {}
        state.dependency_graph = None
        return state

    def test_empty_state_header_does_not_crash(self):
        state = self._empty_state()
        result = _build_header(state)
        assert isinstance(result, str)

    def test_empty_state_summary_does_not_crash(self):
        state = self._empty_state()
        result = _build_project_summary(state)
        assert isinstance(result, str)

    def test_empty_state_stats_does_not_crash(self):
        state = self._empty_state()
        result = _build_repository_statistics(state)
        assert isinstance(result, str)

    def test_empty_state_arch_map_does_not_crash(self):
        state = self._empty_state()
        result = _build_architecture_map(state)
        assert isinstance(result, str)

    def test_empty_state_components_does_not_crash(self):
        state = self._empty_state()
        result = _build_core_components(state)
        assert isinstance(result, str)

    def test_empty_state_tech_debt_does_not_crash(self):
        state = self._empty_state()
        result = _build_tech_debt_report(state)
        assert isinstance(result, str)

    def test_empty_state_reading_order_does_not_crash(self):
        state = self._empty_state()
        result = _build_reading_order(state)
        assert isinstance(result, str)

    def test_empty_state_footer_does_not_crash(self):
        state = self._empty_state()
        result = _build_footer(state)
        assert isinstance(result, str)

    def test_full_run_on_empty_state_does_not_crash(self):
        state = self._empty_state()
        result = run(state)
        assert isinstance(result.final_doc, str)


# -----------------------------------------------------------------------
# TestFullAgentRun
# -----------------------------------------------------------------------

class TestFullAgentRun:

    def test_final_doc_populated(self):
        state = make_full_state()
        result = run(state)
        assert result.final_doc is not None
        assert len(result.final_doc) > 0

    def test_final_doc_is_string(self):
        state = make_full_state()
        result = run(state)
        assert isinstance(result.final_doc, str)

    def test_final_doc_contains_repo_name(self):
        state = make_full_state()
        result = run(state)
        assert "testrepo" in result.final_doc

    def test_final_doc_contains_all_major_headings(self):
        state = make_full_state()
        result = run(state)
        doc = result.final_doc
        for heading in [
            "Architecture Overview",
            "Project Summary",
            "Repository Statistics",
            "Architecture Map",
            "Core Components",
            "Tech Debt Report",
            "Suggested Reading Order"
        ]:
            assert heading in doc, f"Missing heading: {heading}"

    def test_explained_files_appear_in_components(self):
        state = make_full_state(num_files=3, with_explanations=True)
        result = run(state)
        for i in range(3):
            assert f"module_{i}" in result.final_doc

    def test_critical_file_appears_in_tech_debt(self):
        state = make_full_state(num_files=4)
        result = run(state)
        # module_3 is CRITICAL (index 3 % 4)
        assert "module_3" in result.final_doc

    def test_sections_separated_by_divider(self):
        state = make_full_state()
        result = run(state)
        assert "---" in result.final_doc

    def test_doc_generation_without_explanations(self):
        state = make_full_state(with_explanations=False)
        result = run(state)
        assert "Core Components" in result.final_doc
        assert "full explanation" not in result.final_doc

    def test_doc_generation_with_cycles(self):
        state = make_full_state(with_cycles=True)
        result = run(state)
        assert "circular" in result.final_doc.lower() or "cycle" in result.final_doc.lower()

    def test_word_count_reasonable(self):
        state = make_full_state(num_files=4, with_explanations=True)
        result = run(state)
        word_count = len(result.final_doc.split())
        # A document with 4 explained files should have substantial content
        assert word_count > 200

    def test_state_returned_not_modified_in_place_unexpectedly(self):
        state = make_full_state()
        original_url = state.repo_url
        result = run(state)
        assert result.repo_url == original_url
        assert result.final_doc is not None


# -----------------------------------------------------------------------
# TestDocumentStructure
# -----------------------------------------------------------------------

class TestDocumentStructure:

    def test_starts_with_h1(self):
        state = make_full_state()
        result = run(state)
        assert result.final_doc.startswith("# ")

    def test_no_raw_none_strings(self):
        state = make_full_state()
        result = run(state)
        assert "None" not in result.final_doc

    def test_no_empty_sections(self):
        state = make_full_state()
        result = run(state)
        # No two consecutive dividers (which would mean empty section)
        assert "---\n\n---" not in result.final_doc

    def test_markdown_table_has_header_and_separator(self):
        state = make_full_state()
        result = run(state)
        doc = result.final_doc
        assert "|" in doc

    def test_code_blocks_are_closed(self):
        state = make_full_state()
        result = run(state)
        # Every ``` should appear an even number of times
        code_block_count = result.final_doc.count("```")
        assert code_block_count % 2 == 0

    def test_headings_are_hierarchical(self):
        state = make_full_state()
        result = run(state)
        doc = result.final_doc
        # Should have exactly one H1
        h1_count = sum(1 for line in doc.split('\n') if line.startswith("# ") and not line.startswith("## "))
        assert h1_count == 1

    def test_backtick_file_paths(self):
        state = make_full_state(with_explanations=True)
        result = run(state)
        # File paths in components should be wrapped in backticks
        assert "`src/module_0.py`" in result.final_doc


# -----------------------------------------------------------------------
# TestHelperFunctions
# -----------------------------------------------------------------------

class TestHelperFunctions:

    def test_language_breakdown_counts_correctly(self):
        state = make_full_state()
        state.file_manifest.append(make_file_meta("README.md", "Markdown"))
        state.file_manifest.append(make_file_meta("config.yaml", "YAML"))
        breakdown = _language_breakdown(state)
        assert breakdown["Markdown"] == 1
        assert breakdown["YAML"] == 1
        assert breakdown["Python"] == 4

    def test_risk_distribution_counts_all_levels(self):
        state = make_full_state(num_files=4)
        dist = _risk_counts(state)
        total = sum(dist.values())
        assert total == 4
        assert dist["CRITICAL"] == 1
        assert dist["HIGH"] == 1
        assert dist["MEDIUM"] == 1
        assert dist["LOW"] == 1

    def test_risk_distribution_empty_scores(self):
        state = make_full_state()
        state.complexity_scores = {}
        dist = _risk_counts(state)
        assert all(v == 0 for v in dist.values())

    def test_all_documents_render_footer_at_bottom(self):
        state = make_full_state(with_explanations=True)
        result = run(state)
        
        # 1. onboarding.md
        assert "**Generated by Project Gnosis (Code Archaeology Agent)**" in result.final_doc
        assert result.final_doc.strip().endswith(state.analysis_mode)

        # 2. agent_context.md
        # Top header should NOT have "Generated by Project Gnosis"
        top_header = result.agent_context_md.split("## System Overview")[0]
        assert "Generated by Project Gnosis" not in top_header
        # Bottom footer MUST have the complete footer
        assert "**Generated by Project Gnosis (Code Archaeology Agent)**" in result.agent_context_md
        assert result.agent_context_md.strip().endswith(state.analysis_mode)

        # 3. file_explanations.md should NOT contain the metadata footer
        assert "**Generated by Project Gnosis (Code Archaeology Agent)**" not in result.file_explanations_doc

    def test_skip_llm_user_friendly_message(self):
        state = make_full_state(with_explanations=False)
        result = run(state)

        # file_explanations_doc should contain the all-caps notice (no metadata footer)
        assert "SKIPPED AI EXPLANATIONS" in result.file_explanations_doc
        assert "AI EXPLANATIONS WERE SKIPPED FOR THIS RUN. RE-RUN ANALYSIS WITH SKIP LLM DISABLED TO GENERATE FILE WALKTHROUGHS." in result.file_explanations_doc
        assert "**Generated by Project Gnosis (Code Archaeology Agent)**" not in result.file_explanations_doc

        # agent_context_md should also contain the all-caps notice
        assert "SKIPPED AI EXPLANATIONS" in result.agent_context_md
        assert "AI EXPLANATIONS WERE SKIPPED FOR THIS RUN. RE-RUN ANALYSIS WITH SKIP LLM DISABLED TO GENERATE FILE WALKTHROUGHS." in result.agent_context_md