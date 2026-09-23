"""
Tests for GitHub API Authentication (PAT) and Private Repository Access.
"""
from unittest.mock import MagicMock, patch
import pytest
from src.utils.github_api import (
    fetch_repo_metadata,
    fetch_file_tree,
    fetch_file_content_raw,
    fetch_file_contents_batch,
    _get_headers
)


def test_get_headers_with_and_without_token():
    headers_no_tok = _get_headers(None)
    assert "Authorization" not in headers_no_tok
    assert headers_no_tok["Accept"] == "application/vnd.github+json"

    headers_tok = _get_headers("ghp_test_secret_pat_123")
    assert headers_tok["Authorization"] == "Bearer ghp_test_secret_pat_123"


def test_fetch_repo_metadata_private_repo_404_error_message():
    with patch("src.utils.github_api._RAW_SESSION.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        with pytest.raises(ValueError) as exc_info:
            fetch_repo_metadata("private_org", "secret_repo", token=None)
        assert "private repository" in str(exc_info.value).lower()
        assert "personal access token" in str(exc_info.value).lower()


def test_fetch_file_content_raw_with_token_and_api_fallback():
    with patch("src.utils.github_api._RAW_SESSION.get") as mock_get:
        # First call to raw.githubusercontent.com returns 404
        mock_raw_resp = MagicMock()
        mock_raw_resp.status_code = 404
        
        # Second call to api.github.com/repos/.../contents/... returns 200 with raw text
        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 200
        mock_api_resp.text = "print('private repository content')"

        mock_get.side_effect = [mock_raw_resp, mock_api_resp]

        content = fetch_file_content_raw(
            owner="private_org",
            repo="secret_repo",
            branch="main",
            path="secret.py",
            token="ghp_mock_token"
        )

        assert content == "print('private repository content')"
        assert mock_get.call_count == 2
