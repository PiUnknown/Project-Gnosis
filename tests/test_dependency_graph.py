"""
Tests for the Dependency Graph Agent (Phase 3).

All tests are offline — no GitHub API, no file I/O.
We build mock SymbolTables and ArchaeonStates to test:
  - Import resolution (Python absolute, relative, bare relative)
  - Import resolution (JavaScript relative)
  - Graph construction (correct nodes, edges, no self-loops)
  - Circular dependency detection
  - Topological sort order
  - PageRank computation (no crash on edge cases)
  - Graph stats structure and values
"""
import pytest
import networkx as nx

from src.utils.graph_utils import resolve_import_to_paths, _try_python_path_variants
from src.parsers.base import ImportInfo, SymbolTable
from src.agents.dependency_graph import run, _compute_pagerank
from src.state import ArchaeonState, FileMetadata


# -----------------------------------------------------------------------
# Helpers for building test fixtures
# -----------------------------------------------------------------------

def make_import(module: str, names: list = None, is_from: bool = True, is_internal: bool = True) -> ImportInfo:
    return ImportInfo(
        module=module,
        names=names or [],
        is_from_import=is_from,
        is_internal=is_internal
    )


def make_symbol_table(file_path: str, language: str, imports: list = None) -> SymbolTable:
    return SymbolTable(
        file_path=file_path,
        language=language,
        module_docstring=None,
        imports=imports or []
    )


def make_file_meta(path: str, language: str = "Python") -> FileMetadata:
    return FileMetadata(
        path=path,
        language=language,
        line_count=10,
        size_bytes=500,
        sha="abc123"
    )


def make_state(files: list, symbol_tables: dict) -> ArchaeonState:
    state = ArchaeonState(
        repo_url="https://github.com/test/repo",
        owner="test",
        repo_name="repo",
        default_branch="main"
    )
    state.file_manifest = [make_file_meta(f) for f in files]
    state.symbol_tables = symbol_tables
    return state


# -----------------------------------------------------------------------
# Import resolution: Python absolute
# -----------------------------------------------------------------------

class TestPythonAbsoluteResolution:

    def test_resolves_to_file(self):
        file_paths = {"src/utils/github_api.py", "src/state.py"}
        imp = make_import("src.utils.github_api")
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert "src/utils/github_api.py" in result

    def test_resolves_to_init(self):
        file_paths = {"src/utils/__init__.py"}
        imp = make_import("src.utils")
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert "src/utils/__init__.py" in result

    def test_external_import_returns_empty(self):
        file_paths = {"src/state.py"}
        imp = make_import("requests", is_internal=False)
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert result == []

    def test_missing_file_returns_empty(self):
        file_paths = {"src/state.py"}
        imp = make_import("src.utils.missing_module", is_internal=True)
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert result == []


# -----------------------------------------------------------------------
# Import resolution: Python relative
# -----------------------------------------------------------------------

class TestPythonRelativeResolution:

    def test_single_dot_resolves_sibling(self):
        # from .state import ArchaeonState (in src/agents/ingestion.py)
        file_paths = {"src/state.py", "src/agents/ingestion.py"}
        imp = make_import(".state", names=["ArchaeonState"])
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert "src/state.py" in result

    def test_double_dot_resolves_parent(self):
        # from ..state import X (in src/agents/ingestion.py)
        file_paths = {"src/state.py"}
        imp = make_import("..state", names=["X"])
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert "src/state.py" in result

    def test_bare_relative_resolves_names_as_submodules(self):
        # from . import state, utils (in src/agents/ingestion.py)
        file_paths = {"src/agents/state.py", "src/agents/utils.py"}
        imp = make_import(".", names=["state", "utils"])
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert "src/agents/state.py" in result
        assert "src/agents/utils.py" in result

    def test_bare_relative_skips_missing_names(self):
        # from . import missing (in src/agents/ingestion.py)
        file_paths = {"src/agents/other.py"}
        imp = make_import(".", names=["missing"])
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert result == []

    def test_wildcard_in_names_is_ignored(self):
        # from . import * — wildcard, no specific submodules to resolve
        file_paths = {"src/agents/utils.py"}
        imp = make_import(".", names=["*"])
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert result == []

    def test_relative_to_package_init(self):
        file_paths = {"src/utils/__init__.py"}
        imp = make_import(".utils")
        result = resolve_import_to_paths("src/agents/ingestion.py", imp, "Python", file_paths)
        assert "src/utils/__init__.py" in result


# -----------------------------------------------------------------------
# Import resolution: JavaScript / TypeScript
# -----------------------------------------------------------------------

class TestJSResolution:

    def test_resolves_with_extension(self):
        file_paths = {"src/utils/helpers.ts"}
        imp = make_import("./helpers.ts")
        result = resolve_import_to_paths("src/utils/index.ts", imp, "TypeScript", file_paths)
        assert "src/utils/helpers.ts" in result

    def test_resolves_without_extension(self):
        file_paths = {"src/utils/helpers.ts"}
        imp = make_import("./helpers")
        result = resolve_import_to_paths("src/utils/index.ts", imp, "TypeScript", file_paths)
        assert "src/utils/helpers.ts" in result

    def test_resolves_index_file(self):
        file_paths = {"src/components/Button/index.tsx"}
        imp = make_import("./Button")
        result = resolve_import_to_paths("src/components/App.tsx", imp, "TypeScript", file_paths)
        assert "src/components/Button/index.tsx" in result

    def test_parent_dir_import(self):
        file_paths = {"src/state.ts"}
        imp = make_import("../state")
        result = resolve_import_to_paths("src/utils/helpers.ts", imp, "TypeScript", file_paths)
        assert "src/state.ts" in result

    def test_external_bare_specifier_returns_empty(self):
        file_paths = {"src/state.ts"}
        imp = make_import("react", is_internal=False)
        result = resolve_import_to_paths("src/App.tsx", imp, "TypeScript", file_paths)
        assert result == []

    def test_unresolvable_relative_returns_empty(self):
        file_paths = {"src/state.ts"}
        imp = make_import("./nonexistent")
        result = resolve_import_to_paths("src/App.tsx", imp, "TypeScript", file_paths)
        assert result == []


# -----------------------------------------------------------------------
# Graph construction
# -----------------------------------------------------------------------

class TestGraphConstruction:

    def test_all_files_added_as_nodes(self):
        files = ["src/a.py", "src/b.py", "src/c.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python"),
            "src/b.py": make_symbol_table("src/b.py", "Python"),
            "src/c.py": make_symbol_table("src/c.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        for f in files:
            assert f in result.dependency_graph.nodes()

    def test_import_creates_edge(self):
        files = ["src/a.py", "src/b.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table(
                "src/a.py", "Python",
                imports=[make_import("src.b")]
            ),
            "src/b.py": make_symbol_table("src/b.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert result.dependency_graph.has_edge("src/a.py", "src/b.py")

    def test_no_self_loops(self):
        files = ["src/a.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table(
                "src/a.py", "Python",
                imports=[make_import("src.a")]
            ),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert not result.dependency_graph.has_edge("src/a.py", "src/a.py")

    def test_external_imports_create_no_edges(self):
        files = ["src/a.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table(
                "src/a.py", "Python",
                imports=[make_import("requests", is_internal=False)]
            ),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert result.dependency_graph.number_of_edges() == 0

    def test_in_degree_correct(self):
        # a.py and c.py both import b.py → b has in_degree 2
        files = ["src/a.py", "src/b.py", "src/c.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python"),
            "src/c.py": make_symbol_table("src/c.py", "Python",
                imports=[make_import("src.b")]),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert result.dependency_graph.in_degree("src/b.py") == 2
        assert result.dependency_graph.out_degree("src/b.py") == 0


# -----------------------------------------------------------------------
# Circular dependency detection
# -----------------------------------------------------------------------

class TestCircularDependencies:

    def test_no_cycles_detected_in_clean_graph(self):
        files = ["src/a.py", "src/b.py", "src/c.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python",
                imports=[make_import("src.c")]),
            "src/c.py": make_symbol_table("src/c.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert result.circular_deps == []
        assert result.circular_nodes == set()

    def test_direct_cycle_detected(self):
        # a imports b, b imports a
        files = ["src/a.py", "src/b.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python",
                imports=[make_import("src.a")]),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert len(result.circular_deps) >= 1
        assert "src/a.py" in result.circular_nodes
        assert "src/b.py" in result.circular_nodes

    def test_three_way_cycle_detected(self):
        # a → b → c → a
        files = ["src/a.py", "src/b.py", "src/c.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python",
                imports=[make_import("src.c")]),
            "src/c.py": make_symbol_table("src/c.py", "Python",
                imports=[make_import("src.a")]),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert len(result.circular_deps) >= 1
        assert result.circular_nodes == {"src/a.py", "src/b.py", "src/c.py"}


# -----------------------------------------------------------------------
# Topological order
# -----------------------------------------------------------------------

class TestTopologicalOrder:

    def test_topological_order_computed_when_no_cycles(self):
        files = ["src/a.py", "src/b.py", "src/c.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python",
                imports=[make_import("src.c")]),
            "src/c.py": make_symbol_table("src/c.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert len(result.topological_order) == 3

    def test_dependencies_come_before_importers(self):
        # a imports b imports c → reading order: c, b, a
        files = ["src/a.py", "src/b.py", "src/c.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python",
                imports=[make_import("src.c")]),
            "src/c.py": make_symbol_table("src/c.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        order = result.topological_order
        assert order.index("src/c.py") < order.index("src/b.py")
        assert order.index("src/b.py") < order.index("src/a.py")

    def test_topological_order_empty_when_cycles_exist(self):
        files = ["src/a.py", "src/b.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python",
                imports=[make_import("src.a")]),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert result.topological_order == []


# -----------------------------------------------------------------------
# Graph stats
# -----------------------------------------------------------------------

class TestGraphStats:

    def test_graph_stats_populated_for_all_files(self):
        files = ["src/a.py", "src/b.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python"),
            "src/b.py": make_symbol_table("src/b.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert "src/a.py" in result.graph_stats
        assert "src/b.py" in result.graph_stats

    def test_graph_stats_contains_expected_keys(self):
        files = ["src/a.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        stats = result.graph_stats["src/a.py"]
        assert "in_degree" in stats
        assert "out_degree" in stats
        assert "pagerank" in stats
        assert "is_in_circular_dep" in stats
        assert "dependents" in stats
        assert "dependencies" in stats

    def test_dependents_and_dependencies_correct(self):
        # a imports b → b.dependents=[a], a.dependencies=[b]
        files = ["src/a.py", "src/b.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert "src/a.py" in result.graph_stats["src/b.py"]["dependents"]
        assert "src/b.py" in result.graph_stats["src/a.py"]["dependencies"]

    def test_circular_dep_flag_set_correctly(self):
        files = ["src/a.py", "src/b.py", "src/c.py"]
        symbol_tables = {
            "src/a.py": make_symbol_table("src/a.py", "Python",
                imports=[make_import("src.b")]),
            "src/b.py": make_symbol_table("src/b.py", "Python",
                imports=[make_import("src.a")]),
            "src/c.py": make_symbol_table("src/c.py", "Python"),
        }
        state = make_state(files, symbol_tables)
        result = run(state)
        assert result.graph_stats["src/a.py"]["is_in_circular_dep"] is True
        assert result.graph_stats["src/b.py"]["is_in_circular_dep"] is True
        assert result.graph_stats["src/c.py"]["is_in_circular_dep"] is False


# -----------------------------------------------------------------------
# PageRank edge cases
# -----------------------------------------------------------------------

class TestPageRank:

    def test_no_crash_on_empty_graph(self):
        G = nx.DiGraph()
        G.add_node("a.py")
        result = _compute_pagerank(G)
        assert "a.py" in result
        assert isinstance(result["a.py"], float)

    def test_no_crash_on_single_edge(self):
        G = nx.DiGraph()
        G.add_edge("a.py", "b.py")
        result = _compute_pagerank(G)
        assert "a.py" in result
        assert "b.py" in result

    def test_higher_indegree_gets_higher_pagerank(self):
        # b and c both import a → a should have higher pagerank than b or c
        G = nx.DiGraph()
        G.add_edge("b.py", "a.py")
        G.add_edge("c.py", "a.py")
        result = _compute_pagerank(G)
        assert result["a.py"] > result["b.py"]


# -----------------------------------------------------------------------
# Rust, C/C++, and Go Import Resolution
# -----------------------------------------------------------------------

class TestMultiLanguageResolution:

    def test_rust_crate_resolution(self):
        file_paths = {
            "duck-control/src/bus.rs",
            "duck-control/src/imu.rs",
            "duck-control/src/io.rs",
            "btd/src/bluez.rs",
            "btd/src/gatt.rs"
        }
        imp = make_import("crate::imu", names=["ImuData"])
        res = resolve_import_to_paths("duck-control/src/bus.rs", imp, "Rust", file_paths)
        assert res == ["duck-control/src/imu.rs"]

        imp_btd = make_import("crate::gatt", names=["RPC_UUID"])
        res_btd = resolve_import_to_paths("btd/src/bluez.rs", imp_btd, "Rust", file_paths)
        assert res_btd == ["btd/src/gatt.rs"]

    def test_rust_super_relative_resolution(self):
        file_paths = {
            "src/models/user.rs",
            "src/utils.rs"
        }
        imp = make_import("super::utils", names=["helper"])
        res = resolve_import_to_paths("src/models/user.rs", imp, "Rust", file_paths)
        assert res == ["src/utils.rs"]

    def test_c_include_resolution(self):
        file_paths = {
            "deploy/audio/tlv320aic3x.c",
            "deploy/audio/tlv320aic3x.h"
        }
        imp = make_import('"tlv320aic3x.h"', names=[])
        res = resolve_import_to_paths("deploy/audio/tlv320aic3x.c", imp, "C", file_paths)
        assert res == ["deploy/audio/tlv320aic3x.h"]

    def test_go_package_resolution(self):
        file_paths = {
            "pkg/auth/auth.go",
            "cmd/server/main.go"
        }
        imp = make_import("github.com/org/repo/pkg/auth", names=[])
        res = resolve_import_to_paths("cmd/server/main.go", imp, "Go", file_paths)
        assert res == ["pkg/auth/auth.go"]