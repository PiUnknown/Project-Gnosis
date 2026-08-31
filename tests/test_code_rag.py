"""
Tests for Phase 5: Code RAG Agent.

Tests are grouped:
  TestChunker          - pure chunking logic, no ChromaDB, no embedder
  TestCollectionNaming - make_collection_name edge cases
  TestMetadataConversion - ChromaDB sentinel value handling
  TestBuildWhereFilter - ChromaDB filter construction
  TestParseResults     - result parsing from ChromaDB format
  TestCodeRetriever    - full retrieval with ephemeral ChromaDB
  TestCodeRAGAgent     - full agent with mocked embedder + ephemeral ChromaDB

All tests are offline. The embedder is mocked to avoid loading 80MB model.
ChromaDB uses EphemeralClient (in-memory, no disk I/O).
"""
import re
import pytest
from unittest.mock import patch

from src.utils.chunker import make_chunks, _extract_lines, _make_chunk_id, CodeChunk
from src.utils.retriever import (
    make_collection_name,
    CodeRetriever,
    _build_where_filter,
    _parse_results
)
from src.agents.code_rag import _to_metadata
from src.parsers.base import SymbolTable, FunctionInfo, ClassInfo, ImportInfo
from src.state import ArchaeonState, FileMetadata


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def make_function(name, line_start=1, line_end=10, docstring=None, is_method=False):
    return FunctionInfo(
        name=name, params=["self"] if is_method else ["x"],
        line_start=line_start, line_end=line_end,
        docstring=docstring, is_async=False, is_method=is_method
    )


def make_class(name, line_start=1, line_end=30, method_names=None):
    return ClassInfo(
        name=name, bases=["Base"],
        method_names=method_names or ["__init__", "process"],
        line_start=line_start, line_end=line_end, docstring="A test class."
    )


def make_import(module, names=None, is_from=True, is_internal=False):
    return ImportInfo(
        module=module, names=names or [],
        is_from_import=is_from, is_internal=is_internal
    )


def make_symbol_table(file_path, language="Python", functions=None,
                       classes=None, imports=None, docstring=None,
                       parse_error=False):
    return SymbolTable(
        file_path=file_path, language=language,
        module_docstring=docstring,
        functions=functions or [],
        classes=classes or [],
        imports=imports or [],
        parse_error=parse_error
    )


SAMPLE_PYTHON = """\
\"\"\"Module for payment processing.\"\"\"
import os
from pathlib import Path

def validate_user(user_id):
    \"\"\"Check if user exists.\"\"\"
    if not user_id:
        return False
    return True

def process_payment(user_id, amount):
    for item in range(amount):
        if item > 0:
            pass
    return True

class PaymentHandler:
    \"\"\"Handles payment operations.\"\"\"

    def __init__(self, config):
        self.config = config

    def execute(self, payment):
        return True
"""

_INVALID_CHARS_PATTERN = re.compile(r'[^a-zA-Z0-9_-]')


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def mock_embed():
    """Mock embed_texts and embed_query to avoid loading the 80MB ML model."""
    def fake_embed_texts(texts):
        return [[0.1] * 384 for _ in texts]

    def fake_embed_query(text):
        return [0.1] * 384

    with patch("src.utils.embedder.embed_texts", side_effect=fake_embed_texts):
        with patch("src.utils.embedder.embed_query", side_effect=fake_embed_query):
            with patch("src.agents.code_rag.embed_texts", side_effect=fake_embed_texts):
                yield


@pytest.fixture
def ephemeral_chroma():
    """Return an in-memory ChromaDB client for testing."""
    chromadb = pytest.importorskip("chromadb")
    return chromadb.EphemeralClient()


@pytest.fixture
def populated_retriever(ephemeral_chroma, mock_embed):
    """
    Create a CodeRetriever backed by an ephemeral ChromaDB collection
    pre-populated with test chunks.

    WHY delete_collection BEFORE create_collection:
    chromadb.EphemeralClient() creates a new Python-level client per call,
    but the underlying Rust bindings use a shared in-process singleton
    backend. A collection created in test N is still visible in test N+1
    even though ephemeral_chroma is a new fixture instance each time.
    Deleting before creating guarantees a clean slate regardless of
    execution order or backend sharing.

    WHY yield INSTEAD OF return:
    yield lets pytest run teardown after the test body completes — even
    if the test fails. Without teardown a failed test leaves the collection
    behind and every subsequent test errors with "already exists" before
    it even runs its own logic.
    """
    # Clean up any collection left by a previous test
    try:
        ephemeral_chroma.delete_collection("test_collection")
    except Exception:
        pass

    col = ephemeral_chroma.create_collection(
        name="test_collection",
        metadata={"hnsw:space": "cosine"}
    )

    test_chunks = [
        {
            "id": "src_auth_py::validate_user::function",
            "doc": "# validate_user (src/auth.py)\ndef validate_user(user_id):\n    return bool(user_id)",
            "meta": {
                "file_path": "src/auth.py",
                "symbol_name": "validate_user",
                "symbol_type": "function",
                "language": "Python",
                "line_start": 5,
                "line_end": 12,
                "complexity": 2.0,
                "risk_level": "LOW"
            }
        },
        {
            "id": "src_auth_py::module::module",
            "doc": "# MODULE: src/auth.py\nfrom pathlib import Path\nimport os",
            "meta": {
                "file_path": "src/auth.py",
                "symbol_name": "module",
                "symbol_type": "module",
                "language": "Python",
                "line_start": 1,
                "line_end": 5,
                "complexity": -1.0,
                "risk_level": "UNKNOWN"
            }
        },
        {
            "id": "src_payments_py::process_payment::function",
            "doc": "# process_payment (src/payments.py)\ndef process_payment(amount):\n    for i in range(amount):\n        if i > 0: pass",
            "meta": {
                "file_path": "src/payments.py",
                "symbol_name": "process_payment",
                "symbol_type": "function",
                "language": "Python",
                "line_start": 15,
                "line_end": 25,
                "complexity": 4.0,
                "risk_level": "HIGH"
            }
        }
    ]

    from src.utils.embedder import embed_texts
    embeddings = embed_texts([c["doc"] for c in test_chunks])

    col.add(
        ids=[c["id"] for c in test_chunks],
        embeddings=embeddings,
        documents=[c["doc"] for c in test_chunks],
        metadatas=[c["meta"] for c in test_chunks]
    )

    yield CodeRetriever(
        collection_name="test_collection",
        _client=ephemeral_chroma
    )

    # Teardown: always delete so the next test starts clean
    try:
        ephemeral_chroma.delete_collection("test_collection")
    except Exception:
        pass


# -----------------------------------------------------------------------
# TestChunker
# -----------------------------------------------------------------------

class TestChunker:

    def test_function_chunk_produced(self):
        st = make_symbol_table("src/a.py", functions=[make_function("foo", 5, 10)])
        chunks = make_chunks("src/a.py", "Python", SAMPLE_PYTHON, st)
        fn_chunks = [c for c in chunks if c.symbol_type == "function"]
        assert any(c.symbol_name == "foo" for c in fn_chunks)

    def test_class_chunk_produced(self):
        st = make_symbol_table(
            "src/a.py",
            classes=[make_class("PaymentHandler", 17, 30)]
        )
        chunks = make_chunks("src/a.py", "Python", SAMPLE_PYTHON, st)
        class_chunks = [c for c in chunks if c.symbol_type == "class"]
        assert any(c.symbol_name == "PaymentHandler" for c in class_chunks)

    def test_module_chunk_with_imports(self):
        st = make_symbol_table(
            "src/a.py",
            imports=[make_import("os"), make_import("pathlib", names=["Path"])]
        )
        chunks = make_chunks("src/a.py", "Python", SAMPLE_PYTHON, st)
        module_chunks = [c for c in chunks if c.symbol_type == "module"]
        assert len(module_chunks) == 1
        assert "os" in module_chunks[0].content

    def test_module_chunk_with_docstring(self):
        st = make_symbol_table("src/a.py", docstring="Payment module.")
        chunks = make_chunks("src/a.py", "Python", SAMPLE_PYTHON, st)
        module_chunks = [c for c in chunks if c.symbol_type == "module"]
        assert any("Payment module" in c.content for c in module_chunks)

    def test_no_module_chunk_when_no_imports_no_docstring(self):
        st = make_symbol_table("src/a.py")
        chunks = make_chunks("src/a.py", "Python", "def foo(): pass\n", st)
        module_chunks = [c for c in chunks if c.symbol_type == "module"]
        assert len(module_chunks) == 0

    def test_empty_raw_content_returns_empty(self):
        st = make_symbol_table("src/a.py", functions=[make_function("foo")])
        chunks = make_chunks("src/a.py", "Python", "", st)
        assert chunks == []

    def test_function_content_contains_header(self):
        st = make_symbol_table("src/auth.py", functions=[make_function("validate_user", 5, 8)])
        chunks = make_chunks("src/auth.py", "Python", SAMPLE_PYTHON, st)
        fn_chunk = next(c for c in chunks if c.symbol_name == "validate_user")
        assert "validate_user" in fn_chunk.content
        assert "src/auth.py" in fn_chunk.content

    def test_duplicate_symbol_names_on_same_line_disambiguated(self):
        # Simulated minified or single-line declarations sharing same name and line_start
        st = make_symbol_table(
            "src/bundle.js",
            language="JavaScript",
            functions=[
                make_function("render", line_start=1, line_end=1),
                make_function("render", line_start=1, line_end=1),
                make_function("render", line_start=1, line_end=1),
            ]
        )
        chunks = make_chunks("src/bundle.js", "JavaScript", "function render(){} function render(){} function render(){}", st)
        ids = [c.chunk_id for c in chunks if c.symbol_type == "function"]
        assert len(ids) == 3
        # All IDs must be unique
        assert len(set(ids)) == 3
        assert ids[0].endswith("::render::1::function")
        assert ids[1].endswith("::render::1::function_1")
        assert ids[2].endswith("::render::1::function_2")

    def test_function_line_numbers_on_chunk(self):
        func = make_function("validate_user", line_start=5, line_end=8)
        st = make_symbol_table("src/a.py", functions=[func])
        chunks = make_chunks("src/a.py", "Python", SAMPLE_PYTHON, st)
        fn_chunk = next(c for c in chunks if c.symbol_name == "validate_user")
        assert fn_chunk.line_start == 5
        assert fn_chunk.line_end == 8

    def test_complexity_attached_when_score_present(self):
        from src.parsers.base import ComplexityScore
        func = make_function("foo", 1, 5)
        cs = ComplexityScore(
            file_path="src/a.py", language="Python",
            function_scores={"foo": 7},
            avg_complexity=7.0, max_complexity=7.0,
            max_complexity_function="foo",
            function_count=1, avg_function_lines=5.0,
            coupling_score=0, undocumented_count=0,
            undocumented_ratio=0.0, parse_error=False,
            is_in_circular_dep=False, line_count=10,
            risk_level="MEDIUM", risk_reasons=[]
        )
        st = make_symbol_table("src/a.py", functions=[func])
        chunks = make_chunks("src/a.py", "Python", "def foo(x):\n    return x\n", st, cs)
        fn_chunk = next(c for c in chunks if c.symbol_name == "foo")
        assert fn_chunk.complexity == 7.0

    def test_complexity_none_when_no_score(self):
        func = make_function("foo", 1, 5)
        st = make_symbol_table("src/a.py", functions=[func])
        chunks = make_chunks("src/a.py", "Python", "def foo(x):\n    return x\n", st, None)
        fn_chunk = next(c for c in chunks if c.symbol_name == "foo")
        assert fn_chunk.complexity is None

    def test_class_chunk_content_has_header(self):
        cls = make_class("PaymentHandler", line_start=17, line_end=30)
        st = make_symbol_table("src/pay.py", classes=[cls])
        chunks = make_chunks("src/pay.py", "Python", SAMPLE_PYTHON, st)
        cls_chunk = next((c for c in chunks if c.symbol_type == "class"), None)
        assert cls_chunk is not None
        assert "PaymentHandler" in cls_chunk.content

    def test_chunk_id_is_unique_per_symbol(self):
        st = make_symbol_table(
            "src/a.py",
            functions=[make_function("foo", 1, 5), make_function("bar", 6, 10)]
        )
        chunks = make_chunks("src/a.py", "Python", SAMPLE_PYTHON, st)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))


# -----------------------------------------------------------------------
# TestCollectionNaming
# -----------------------------------------------------------------------

class TestCollectionNaming:

    def test_basic_name(self):
        name = make_collection_name("tiangolo", "fastapi")
        assert name == "gnosis_tiangolo_fastapi"

    def test_contains_only_valid_chars(self):
        name = make_collection_name("my-org", "my.repo.v2")
        assert _INVALID_CHARS_PATTERN.match(name) is None

    def test_max_length_enforced(self):
        name = make_collection_name("a" * 40, "b" * 40)
        assert len(name) <= 63

    def test_minimum_length(self):
        name = make_collection_name("a", "b")
        assert len(name) >= 3

    def test_deterministic(self):
        assert make_collection_name("owner", "repo") == make_collection_name("owner", "repo")

    def test_different_repos_give_different_names(self):
        assert make_collection_name("owner", "repo1") != make_collection_name("owner", "repo2")

    def test_job_id_suffix(self):
        name = make_collection_name("owner", "repo", "job-1234")
        assert name == "gnosis_owner_repo_job-1234"

    def test_job_id_truncation(self):
        job_id = "job-1234-5678-9012-3456-7890-1234-5678"
        name = make_collection_name(
            "verylongownernamethatwillbetruncated",
            "verylongreponamethatwillbetruncated",
            job_id
        )
        assert len(name) <= 63
        assert name.endswith("job-1234-5678-9012-3456-7890-1234-5678")


# -----------------------------------------------------------------------
# TestMetadataConversion
# -----------------------------------------------------------------------

class TestMetadataConversion:

    def _make_chunk(self, complexity=None, risk_level=None):
        return CodeChunk(
            chunk_id="test::foo::function",
            content="def foo(): pass",
            file_path="src/foo.py",
            symbol_name="foo",
            symbol_type="function",
            language="Python",
            line_start=1, line_end=3,
            complexity=complexity,
            risk_level=risk_level
        )

    def test_none_complexity_becomes_sentinel(self):
        meta = _to_metadata(self._make_chunk(complexity=None))
        assert meta["complexity"] == -1.0

    def test_real_complexity_stored_as_float(self):
        meta = _to_metadata(self._make_chunk(complexity=5))
        assert meta["complexity"] == 5.0
        assert isinstance(meta["complexity"], float)

    def test_none_risk_becomes_unknown(self):
        meta = _to_metadata(self._make_chunk(risk_level=None))
        assert meta["risk_level"] == "UNKNOWN"

    def test_real_risk_stored_as_is(self):
        meta = _to_metadata(self._make_chunk(risk_level="HIGH"))
        assert meta["risk_level"] == "HIGH"

    def test_no_none_values_in_output(self):
        meta = _to_metadata(self._make_chunk(complexity=None, risk_level=None))
        for val in meta.values():
            assert val is not None, f"None found in metadata: {meta}"


# -----------------------------------------------------------------------
# TestBuildWhereFilter
# -----------------------------------------------------------------------

class TestBuildWhereFilter:

    def test_no_filters_returns_none(self):
        assert _build_where_filter() is None

    def test_single_filter_no_and_wrapper(self):
        result = _build_where_filter(language="Python")
        assert result == {"language": "Python"}

    def test_two_filters_use_and(self):
        result = _build_where_filter(language="Python", symbol_type="function")
        assert "$and" in result
        assert len(result["$and"]) == 2

    def test_three_filters_all_in_and(self):
        result = _build_where_filter(
            language="Python", symbol_type="function", risk_level="HIGH"
        )
        assert "$and" in result
        assert len(result["$and"]) == 3

    def test_file_path_filter(self):
        result = _build_where_filter(file_path="src/auth.py")
        assert result == {"file_path": "src/auth.py"}


# -----------------------------------------------------------------------
# TestParseResults
# -----------------------------------------------------------------------

class TestParseResults:

    def _make_chroma_result(self, doc, meta, dist):
        return {
            "documents": [[doc]],
            "metadatas": [[meta]],
            "distances": [[dist]]
        }

    def test_basic_result_parsed(self):
        raw = self._make_chroma_result(
            "def foo(): pass",
            {"file_path": "src/a.py", "symbol_name": "foo",
             "symbol_type": "function", "language": "Python",
             "line_start": 1, "line_end": 3,
             "complexity": 2.0, "risk_level": "LOW"},
            0.12
        )
        chunks = _parse_results(raw)
        assert len(chunks) == 1
        assert chunks[0]["symbol_name"] == "foo"
        assert chunks[0]["distance"] == 0.12

    def test_sentinel_complexity_converted_to_none(self):
        raw = self._make_chroma_result(
            "import os",
            {"file_path": "src/a.py", "symbol_name": "module",
             "symbol_type": "module", "language": "Python",
             "line_start": 1, "line_end": 3,
             "complexity": -1.0, "risk_level": "UNKNOWN"},
            0.05
        )
        chunks = _parse_results(raw)
        assert chunks[0]["complexity"] is None

    def test_sentinel_risk_level_converted_to_none(self):
        raw = self._make_chroma_result(
            "import os",
            {"file_path": "src/a.py", "symbol_name": "module",
             "symbol_type": "module", "language": "Python",
             "line_start": 1, "line_end": 3,
             "complexity": -1.0, "risk_level": "UNKNOWN"},
            0.05
        )
        chunks = _parse_results(raw)
        assert chunks[0]["risk_level"] is None

    def test_empty_results_returns_empty_list(self):
        raw = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        assert _parse_results(raw) == []

    def test_multiple_results_all_parsed(self):
        raw = {
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[
                {"file_path": "a.py", "symbol_name": "f1", "symbol_type": "function",
                 "language": "Python", "line_start": 1, "line_end": 5,
                 "complexity": 1.0, "risk_level": "LOW"},
                {"file_path": "b.py", "symbol_name": "f2", "symbol_type": "function",
                 "language": "Python", "line_start": 1, "line_end": 5,
                 "complexity": 2.0, "risk_level": "MEDIUM"},
                {"file_path": "c.py", "symbol_name": "module", "symbol_type": "module",
                 "language": "Python", "line_start": 1, "line_end": 3,
                 "complexity": -1.0, "risk_level": "UNKNOWN"},
            ]],
            "distances": [[0.1, 0.2, 0.3]]
        }
        chunks = _parse_results(raw)
        assert len(chunks) == 3


# -----------------------------------------------------------------------
# TestCodeRetriever
# -----------------------------------------------------------------------

class TestCodeRetriever:

    def test_count_returns_correct_number(self, populated_retriever):
        assert populated_retriever.count() == 3

    def test_query_returns_results(self, populated_retriever):
        results = populated_retriever.query("validate user authentication", n_results=2)
        assert isinstance(results, list)
        assert len(results) > 0

    def test_query_results_have_required_fields(self, populated_retriever):
        results = populated_retriever.query("payment processing", n_results=1)
        if results:
            chunk = results[0]
            for field in ("content", "file_path", "symbol_name", "symbol_type",
                          "language", "line_start", "line_end", "distance"):
                assert field in chunk, f"Missing field: {field}"

    def test_empty_query_returns_empty(self, populated_retriever):
        results = populated_retriever.query("")
        assert results == []

    def test_query_with_language_filter(self, populated_retriever):
        results = populated_retriever.query(
            "process payment", n_results=3, language="Python"
        )
        for chunk in results:
            assert chunk["language"] == "Python"

    def test_query_with_symbol_type_filter(self, populated_retriever):
        results = populated_retriever.query(
            "function code", n_results=3, symbol_type="function"
        )
        for chunk in results:
            assert chunk["symbol_type"] == "function"

    def test_get_file_chunks_returns_correct_file(self, populated_retriever):
        chunks = populated_retriever.get_file_chunks("src/auth.py")
        assert len(chunks) == 2
        for chunk in chunks:
            assert chunk["file_path"] == "src/auth.py"

    def test_get_file_chunks_unknown_file_returns_empty(self, populated_retriever):
        chunks = populated_retriever.get_file_chunks("src/does_not_exist.py")
        assert chunks == []

    def test_get_file_chunks_sentinel_converted(self, populated_retriever):
        chunks = populated_retriever.get_file_chunks("src/auth.py")
        module_chunk = next(
            (c for c in chunks if c["symbol_name"] == "module"), None
        )
        if module_chunk:
            assert module_chunk["complexity"] is None
            assert module_chunk["risk_level"] is None

    def test_missing_collection_raises_value_error(self, ephemeral_chroma):
        with pytest.raises(ValueError, match="not found"):
            CodeRetriever("nonexistent_collection", _client=ephemeral_chroma)


# -----------------------------------------------------------------------
# TestCodeRAGAgent
# -----------------------------------------------------------------------

class TestCodeRAGAgent:

    def _make_state(self, files_and_tables: dict) -> ArchaeonState:
        state = ArchaeonState(
            repo_url="https://github.com/test/repo",
            owner="testowner", repo_name="testrepo",
            default_branch="main"
        )
        state.file_manifest = [
            FileMetadata(path=p, language=st.language,
                         line_count=20, size_bytes=500, sha="abc")
            for p, st in files_and_tables.items()
        ]
        state.symbol_tables = files_and_tables
        state.raw_contents = {p: SAMPLE_PYTHON for p in files_and_tables}
        state.complexity_scores = {}
        state.circular_nodes = set()
        return state

    def test_collection_name_written_to_state(self, mock_embed, ephemeral_chroma):
        st = make_symbol_table(
            "src/auth.py", "Python",
            functions=[make_function("foo", 5, 8)],
            imports=[make_import("os")]
        )
        state = self._make_state({"src/auth.py": st})

        from src.agents import code_rag
        import chromadb
        with patch.object(chromadb, "PersistentClient", return_value=ephemeral_chroma):
            result = code_rag.run(state)

        assert result.chroma_collection_name is not None
        assert "gnosis" in result.chroma_collection_name

    def test_unsupported_language_skipped(self, mock_embed, ephemeral_chroma):
        st_yaml = make_symbol_table("config.yaml", "YAML")
        st_py = make_symbol_table(
            "src/main.py", "Python",
            functions=[make_function("main", 1, 5)]
        )
        state = self._make_state({"config.yaml": st_yaml, "src/main.py": st_py})
        state.raw_contents["config.yaml"] = "key: value\n"

        from src.agents import code_rag
        import chromadb
        with patch.object(chromadb, "PersistentClient", return_value=ephemeral_chroma):
            result = code_rag.run(state)

        assert result.chroma_collection_name is not None

    def test_parse_error_files_produce_no_chunks(self, mock_embed, ephemeral_chroma):
        st_broken = make_symbol_table("src/broken.py", "Python", parse_error=True)
        st_ok = make_symbol_table(
            "src/ok.py", "Python",
            functions=[make_function("fine", 1, 5)],
            imports=[make_import("os")]
        )
        state = self._make_state({
            "src/broken.py": st_broken,
            "src/ok.py": st_ok
        })

        from src.agents import code_rag
        import chromadb
        with patch.object(chromadb, "PersistentClient", return_value=ephemeral_chroma):
            result = code_rag.run(state)

        retriever = CodeRetriever(
            result.chroma_collection_name,
            _client=ephemeral_chroma
        )
        chunks = retriever.get_file_chunks("src/broken.py")
        assert chunks == []

    def test_missing_content_file_skipped(self, mock_embed, ephemeral_chroma):
        st = make_symbol_table("src/a.py", "Python",
                               functions=[make_function("foo", 1, 5)])
        state = self._make_state({"src/a.py": st})
        state.raw_contents = {}   # No content for any file

        from src.agents import code_rag
        import chromadb
        with patch.object(chromadb, "PersistentClient", return_value=ephemeral_chroma):
            result = code_rag.run(state)

        # Should complete without error
        assert result.chroma_collection_name is not None

    def test_duplicate_ids_across_files_handled_in_code_rag(self, mock_embed, ephemeral_chroma):
        # Simulate two files producing overlapping chunk IDs or multiple functions on same line
        st1 = make_symbol_table("src/file1.js", "JavaScript", functions=[
            make_function("handler", 1, 1),
            make_function("handler", 1, 1),
            make_function("handler", 1, 1),
        ])
        st2 = make_symbol_table("src/file2.js", "JavaScript", functions=[
            make_function("handler", 1, 1),
            make_function("handler", 1, 1),
        ])
        state = self._make_state({"src/file1.js": st1, "src/file2.js": st2})
        state.raw_contents["src/file1.js"] = "function handler(){}"
        state.raw_contents["src/file2.js"] = "function handler(){}"

        from src.agents import code_rag
        import chromadb
        with patch.object(chromadb, "PersistentClient", return_value=ephemeral_chroma):
            result = code_rag.run(state)

        # Must successfully insert into ChromaDB without raising DuplicateIDError
        assert result.chroma_collection_name is not None
        retriever = CodeRetriever(result.chroma_collection_name, _client=ephemeral_chroma)
        chunks1 = retriever.get_file_chunks("src/file1.js")
        chunks2 = retriever.get_file_chunks("src/file2.js")
        assert len(chunks1) == 3
        assert len(chunks2) == 2