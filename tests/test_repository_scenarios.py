"""Offline, end-to-end-ish repository shape checks using GitHub response fixtures."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.agents import ast_parser, code_rag, complexity_scorer, dependency_graph, doc_generator, ingestion
from src.api.main import app
from src.state import ArchaeonState, FileMetadata
from src.utils.github_api import (
    fetch_file_content_raw,
    fetch_file_contents_batch,
    fetch_file_tree,
    parse_github_url,
)


def _state(branch="main"):
    return ArchaeonState(
        repo_url="https://github.com/acme/sample",
        owner="acme",
        repo_name="sample",
        default_branch=branch,
    )


def _tree_entry(path, size=100):
    return {"path": path, "size": size, "sha": f"sha-{path}", "type": "blob"}


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com.attacker.example/acme/sample",
        "https://attacker.example/github.com/acme/sample",
        "https://github.com@attacker.example/acme/sample",
        "ftp://github.com/acme/sample",
    ],
)
def test_repo_url_parser_rejects_host_spoofing_and_non_http_schemes(url):
    with pytest.raises(ValueError):
        parse_github_url(url)


def test_api_rejects_a_github_string_that_is_not_a_github_host():
    response = TestClient(app).post(
        "/api/analyze",
        json={"repo_url": "https://github.com.attacker.example/acme/sample"},
    )
    assert response.status_code == 422


def test_github_urls_encode_slash_branches_and_special_file_names():
    tree_response = MagicMock(status_code=200)
    tree_response.json.return_value = {
        "tree": [_tree_entry("src/name #1?.py")],
        "truncated": False,
    }
    content_response = MagicMock(status_code=200, text="print('ok')")

    with patch("src.utils.github_api._RAW_SESSION.get", side_effect=[tree_response, content_response]) as get:
        tree = fetch_file_tree("acme", "sample", "feature/review")
        content = fetch_file_content_raw(
            "acme", "sample", "feature/review", "src/name #1?.py"
        )

    assert len(tree) == 1
    assert content == "print('ok')"
    assert "/git/trees/feature%2Freview?recursive=1" in get.call_args_list[0].args[0]
    assert "/feature%2Freview/src/name%20%231%3F.py" in get.call_args_list[1].args[0]


def test_truncated_github_tree_fails_clearly_instead_of_reporting_partial_analysis():
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "tree": [_tree_entry("src/partial.py")],
        "truncated": True,
    }
    with patch("src.utils.github_api._RAW_SESSION.get", return_value=response):
        with pytest.raises(ValueError, match="truncated file tree"):
            fetch_file_tree("acme", "large-monorepo", "main")


def test_public_archive_partial_hit_falls_back_to_raw_file_fetches(monkeypatch):
    paths = [f"src/module_{index}.py" for index in range(80)]
    raw_calls = []

    def raw_fetch(owner, repo, branch, path, **kwargs):
        raw_calls.append(path)
        return f"raw:{path}"

    monkeypatch.setattr(
        "src.utils.github_api._fetch_archive_contents",
        lambda owner, repo, branch, requested: {requested[0]: "archive hit"},
    )
    monkeypatch.setattr("src.utils.github_api.fetch_file_content_raw", raw_fetch)

    result = fetch_file_contents_batch(
        "acme", "large-monorepo", "main", paths, repo_size_kb=5_000
    )

    assert result[paths[0]] == "archive hit"
    assert len(result) == 80
    assert len(raw_calls) == 79
    assert paths[0] not in raw_calls


def test_mixed_language_monorepo_ignores_generated_and_dependency_trees(monkeypatch):
    entries = [
        _tree_entry("README.md"),
        _tree_entry("services/api/app.py"),
        _tree_entry("apps/web/src/App.tsx"),
        _tree_entry("apps/cli/main.go"),
        _tree_entry("config/service.yaml"),
        _tree_entry("apps/web/node_modules/react/index.js"),
        _tree_entry("vendor/legacy/helper.py"),
        _tree_entry("static/app.min.js"),
        _tree_entry("services/api/generated.py", 150_001),
        _tree_entry("package-lock.json"),
    ]
    contents = {
        "README.md": "# Sample service",
        "services/api/app.py": "from .models import Item\n\ndef get_item():\n    return Item()\n",
        "apps/web/src/App.tsx": "export const App = () => <main>Hello</main>;\n",
        "apps/cli/main.go": "package main\nfunc main() {}\n",
        "config/service.yaml": "service:\n  name: sample\n",
    }
    monkeypatch.setattr(ingestion, "fetch_file_tree", lambda *args: entries)
    monkeypatch.setattr(
        ingestion,
        "fetch_file_contents_batch",
        lambda *args, **kwargs: contents.copy(),
    )

    state = ingestion.run(_state())
    parsed = ast_parser.run(state)

    paths = {meta.path for meta in parsed.file_manifest}
    assert paths == set(contents)
    assert "apps/web/node_modules/react/index.js" not in paths
    assert "vendor/legacy/helper.py" not in paths
    assert "static/app.min.js" not in paths
    assert "services/api/generated.py" not in paths
    assert parsed.symbol_tables["services/api/app.py"].parse_error is False
    assert parsed.symbol_tables["apps/web/src/App.tsx"].parse_error is False
    assert parsed.symbol_tables["apps/cli/main.go"].parse_error is False

    dependency_graph.run(parsed)
    complexity_scorer.run(parsed)
    complexity_scorer.apply_graph_coupling(parsed)

    chromadb = pytest.importorskip("chromadb")
    chroma_client = chromadb.EphemeralClient()

    def fake_embeddings(texts):
        return [[0.01] * code_rag.EMBEDDING_DIM for _ in texts]

    with patch("chromadb.PersistentClient", return_value=chroma_client), patch(
        "src.agents.code_rag.embed_texts", side_effect=fake_embeddings
    ):
        code_rag.run(parsed)
    doc_generator.run(parsed)

    assert parsed.complexity_scores
    assert chroma_client.get_collection(parsed.chroma_collection_name).count() > 0
    assert "sample" in parsed.final_doc


def test_empty_or_unsupported_repo_completes_analysis_stages(monkeypatch):
    entries = [
        _tree_entry("assets/logo.png", 2_000),
        _tree_entry("package.json", 500),
        _tree_entry("node_modules/pkg/index.js", 200),
    ]
    monkeypatch.setattr(ingestion, "fetch_file_tree", lambda *args: entries)
    content_fetch = MagicMock(return_value={})
    monkeypatch.setattr(ingestion, "fetch_file_contents_batch", content_fetch)

    state = ingestion.run(_state())
    ast_parser.run(state)
    dependency_graph.run(state)
    complexity_scorer.run(state)

    class EmptyCollection:
        def count(self):
            return 0

    class EmptyChroma:
        def delete_collection(self, **kwargs):
            raise ValueError("collection does not exist")

        def get_or_create_collection(self, **kwargs):
            return EmptyCollection()

    with patch("chromadb.PersistentClient", return_value=EmptyChroma()):
        code_rag.run(state)
    doc_generator.run(state)

    assert state.files_discovered == 0
    assert state.file_manifest == []
    assert state.raw_contents == {}
    assert state.chroma_collection_name
    assert state.final_doc
    content_fetch.assert_called_once()
    assert content_fetch.call_args.args[3] == []


def test_missing_content_in_partial_download_keeps_other_files_usable(monkeypatch):
    entries = [_tree_entry("src/available.py"), _tree_entry("src/missing.py")]
    monkeypatch.setattr(ingestion, "fetch_file_tree", lambda *args: entries)
    monkeypatch.setattr(
        ingestion,
        "fetch_file_contents_batch",
        lambda *args, **kwargs: {"src/available.py": "def good():\n    return 1\n"},
    )

    state = ingestion.run(_state())
    assert state.files_with_content == 1
    state = ast_parser.run(state)
    dependency_graph.run(state)
    doc_generator.run(state)

    assert len(state.file_manifest) == 2
    assert set(state.raw_contents) == {"src/available.py"}
    assert "src/available.py" in state.symbol_tables
    assert "src/missing.py" not in state.symbol_tables
    assert "1 of 2 selected files" in state.final_doc
    assert "Partial-input warning" in state.final_doc


def test_incremental_coverage_reuses_prior_content_paths_after_rag_cleanup(monkeypatch):
    previous = _state()
    previous.file_manifest = [
        FileMetadata(path="src/available.py", language="Python", line_count=2, size_bytes=10, sha="a"),
        FileMetadata(path="src/missing.py", language="Python", line_count=2, size_bytes=10, sha="b"),
    ]
    previous.content_paths = {"src/available.py"}
    previous.raw_contents = {}  # Code RAG clears these after building the prior index.

    state = _state()
    state.is_incremental = True
    state.previous_state = previous
    entries = [
        _tree_entry("src/available.py"),
        _tree_entry("src/missing.py"),
    ]
    entries[0]["sha"] = "a"
    entries[1]["sha"] = "b"
    monkeypatch.setattr(ingestion, "fetch_file_tree", lambda *args: entries)
    content_fetch = MagicMock(return_value={})
    monkeypatch.setattr(ingestion, "fetch_file_contents_batch", content_fetch)

    result = ingestion.run(state)

    assert result.content_paths == {"src/available.py"}
    assert result.files_with_content == 1
    content_fetch.assert_called_once()
    assert content_fetch.call_args.args[3] == []


def test_malformed_file_is_flagged_without_stopping_other_files(monkeypatch):
    entries = [_tree_entry("src/good.py"), _tree_entry("src/broken.py")]
    monkeypatch.setattr(ingestion, "fetch_file_tree", lambda *args: entries)
    monkeypatch.setattr(
        ingestion,
        "fetch_file_contents_batch",
        lambda *args, **kwargs: {
            "src/good.py": "def good():\n    return 1\n",
            "src/broken.py": "def broken(:\n    return 2\n",
        },
    )

    state = ast_parser.run(ingestion.run(_state()))

    assert state.symbol_tables["src/good.py"].parse_error is False
    assert state.symbol_tables["src/broken.py"].parse_error is True


def test_hard_file_limit_rejects_before_content_download(monkeypatch):
    monkeypatch.setenv("MAX_SAMPLED_ANALYSIS_FILES", "3")
    entries = [_tree_entry(f"src/f{i}.py") for i in range(4)]
    monkeypatch.setattr(ingestion, "fetch_file_tree", lambda *args: entries)
    content_fetch = MagicMock(return_value={})
    monkeypatch.setattr(ingestion, "fetch_file_contents_batch", content_fetch)

    with pytest.raises(ValueError, match="maximum file limit of 3"):
        ingestion.run(_state(), reject_over_max=True)
    content_fetch.assert_not_called()


def test_incremental_index_cleanup_error_does_not_crash_job():
    pytest.importorskip("chromadb")

    class Collection:
        def count(self):
            return 0

        def delete(self, **kwargs):
            raise RuntimeError("simulated stale-index failure")

    class ChromaClient:
        def get_or_create_collection(self, **kwargs):
            return Collection()

    state = _state()
    state.is_incremental = True
    state.manifest_diff = SimpleNamespace(deleted_paths={"src/deleted.py"}, modified=[])
    with patch("chromadb.PersistentClient", return_value=ChromaClient()):
        result = code_rag.run(state)

    assert result.chroma_collection_name
