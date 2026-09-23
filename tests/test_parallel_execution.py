"""
Tests for Parallel Agent and Multi-threaded File Execution.
"""
import pytest
from unittest.mock import MagicMock, patch
from src.state import ArchaeonState, FileMetadata
from src.agents import ast_parser, complexity_scorer, dependency_graph
from src.parsers.base import SymbolTable, FunctionInfo, ComplexityScore


def test_ast_parser_concurrent_parsing():
    state = ArchaeonState(repo_url="https://github.com/example/repo")
    
    # Create 10 files with valid python code
    files = []
    for i in range(10):
        path = f"file_{i}.py"
        files.append(FileMetadata(path=path, language="Python", line_count=10, size_bytes=100, sha=f"sha_{i}"))
        state.raw_contents[path] = f"def fn_{i}(x):\n    return x + {i}\n"
    
    state.file_manifest = files
    
    result_state = ast_parser.run(state)
    
    assert len(result_state.symbol_tables) == 10
    for i in range(10):
        st = result_state.symbol_tables[f"file_{i}.py"]
        assert len(st.functions) == 1
        assert st.functions[0].name == f"fn_{i}"


def test_complexity_scorer_concurrent_scoring_and_coupling():
    state = ArchaeonState(repo_url="https://github.com/example/repo")
    
    files = []
    for i in range(8):
        path = f"score_file_{i}.py"
        files.append(FileMetadata(path=path, language="Python", line_count=20, size_bytes=200, sha=f"sha_{i}"))
        code = f"""
def complex_{i}(x):
    if x > 0:
        return {i}
    elif x < -5:
        return -{i}
    return 0
"""
        state.raw_contents[path] = code
        fn = FunctionInfo(name=f"complex_{i}", params=["x"], line_start=2, line_end=7, docstring=None, is_async=False, is_method=False)
        st = SymbolTable(file_path=path, language="Python", module_docstring=None, functions=[fn])
        state.symbol_tables[path] = st

    state.file_manifest = files
    
    # Run complexity scoring
    result_state = complexity_scorer.run(state)
    assert len(result_state.complexity_scores) == 8
    
    # Now simulate graph completion with coupling data
    state.graph_stats["score_file_0.py"] = {"out_degree": 12, "in_degree": 5}
    state.circular_nodes.add("score_file_0.py")
    
    complexity_scorer.apply_graph_coupling(state)
    
    score_0 = state.complexity_scores["score_file_0.py"]
    assert score_0.coupling_score == 12
    assert score_0.is_in_circular_dep is True
    assert score_0.risk_level in ("CRITICAL", "HIGH")
