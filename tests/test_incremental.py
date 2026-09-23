"""
Tests for Diff Engine and Incremental Repository Analysis.
"""
import pytest
from src.state import ArchaeonState, FileMetadata
from src.utils.diff_engine import (
    ManifestDiff,
    compute_manifest_diff,
    rehydrate_symbol_tables,
    rehydrate_complexity_scores,
    load_cached_state,
)
from src.parsers.base import SymbolTable, FunctionInfo, ClassInfo, ImportInfo, ComplexityScore


def test_compute_manifest_diff_all_types():
    prev_manifest = [
        FileMetadata(path="src/unchanged.py", language="Python", line_count=10, size_bytes=200, sha="sha1"),
        FileMetadata(path="src/modified.py", language="Python", line_count=20, size_bytes=400, sha="sha2_old"),
        FileMetadata(path="src/deleted.py", language="Python", line_count=30, size_bytes=600, sha="sha3"),
    ]

    curr_manifest = [
        FileMetadata(path="src/unchanged.py", language="Python", line_count=10, size_bytes=200, sha="sha1"),
        FileMetadata(path="src/modified.py", language="Python", line_count=25, size_bytes=450, sha="sha2_new"),
        FileMetadata(path="src/added.py", language="Python", line_count=15, size_bytes=300, sha="sha4"),
    ]

    diff = compute_manifest_diff(prev_manifest, curr_manifest)

    assert diff.has_changes is True
    assert len(diff.added) == 1
    assert diff.added[0].path == "src/added.py"

    assert len(diff.modified) == 1
    assert diff.modified[0][0].path == "src/modified.py"
    assert diff.modified[0][1].sha == "sha2_new"

    assert len(diff.deleted) == 1
    assert diff.deleted[0].path == "src/deleted.py"

    assert len(diff.unchanged) == 1
    assert diff.unchanged[0].path == "src/unchanged.py"

    assert diff.changed_paths == {"src/added.py", "src/modified.py"}
    assert diff.deleted_paths == {"src/deleted.py"}
    assert diff.unchanged_paths == {"src/unchanged.py"}


def test_rehydrate_symbol_tables():
    raw_data = {
        "main.py": {
            "language": "Python",
            "module_docstring": "Main module",
            "parse_error": False,
            "parse_error_detail": None,
            "functions": [
                {
                    "name": "calc",
                    "params": ["x", "y"],
                    "line_start": 5,
                    "line_end": 10,
                    "docstring": "Do calculation",
                    "is_async": False,
                    "is_method": False
                }
            ],
            "classes": [
                {
                    "name": "Engine",
                    "bases": ["Base"],
                    "method_names": ["run"],
                    "line_start": 12,
                    "line_end": 20,
                    "docstring": "Core engine"
                }
            ],
            "imports": [
                {
                    "module": "utils",
                    "names": ["helper"],
                    "is_from_import": True,
                    "is_internal": True
                }
            ]
        }
    }

    rehydrated = rehydrate_symbol_tables(raw_data)
    assert "main.py" in rehydrated
    st = rehydrated["main.py"]
    assert isinstance(st, SymbolTable)
    assert st.language == "Python"
    assert st.module_docstring == "Main module"
    assert len(st.functions) == 1
    assert st.functions[0].name == "calc"
    assert st.functions[0].docstring == "Do calculation"
    assert len(st.classes) == 1
    assert st.classes[0].name == "Engine"
    assert len(st.imports) == 1
    assert st.imports[0].is_internal is True


def test_rehydrate_complexity_scores():
    raw_data = {
        "files_by_risk": {
            "CRITICAL": [],
            "HIGH": [
                {
                    "file_path": "core/heavy.py",
                    "language": "Python",
                    "risk_level": "HIGH",
                    "risk_reasons": ["High cyclomatic complexity"],
                    "avg_complexity": 14.5,
                    "max_complexity": 22.0,
                    "max_complexity_function": "solve",
                    "function_count": 4,
                    "avg_function_lines": 35.0,
                    "coupling_score": 10,
                    "undocumented_count": 1,
                    "undocumented_ratio": 0.25,
                    "line_count": 400,
                    "parse_error": False,
                    "is_in_circular_dep": False,
                    "function_scores": {"solve": 22, "init": 2}
                }
            ],
            "MEDIUM": [],
            "LOW": []
        }
    }

    rehydrated = rehydrate_complexity_scores(raw_data)
    assert "core/heavy.py" in rehydrated
    cs = rehydrated["core/heavy.py"]
    assert isinstance(cs, ComplexityScore)
    assert cs.risk_level == "HIGH"
    assert cs.max_complexity == 22.0
    assert cs.max_complexity_function == "solve"
    assert cs.coupling_score == 10
