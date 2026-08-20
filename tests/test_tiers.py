import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.state import ArchaeonState, FileMetadata
from src.parsers.base import SymbolTable
from src.agents import ingestion, dependency_graph, complexity_scorer, code_rag, doc_generator
from src.api.main import app

# Create a FastAPI test client
client = TestClient(app)


class TestRepositoryTiers:

    @pytest.fixture(autouse=True)
    def setup_env(self):
        """Set up standard tier limits."""
        with patch("src.agents.ingestion.get_max_full_analysis_files", return_value=10), \
             patch("src.agents.ingestion.get_max_warning_analysis_files", return_value=20), \
             patch("src.agents.ingestion.get_max_sampled_analysis_files", return_value=30), \
             patch.dict(os.environ, {
                 "MAX_FULL_ANALYSIS_FILES": "10",
                 "MAX_WARNING_ANALYSIS_FILES": "20",
                 "MAX_SAMPLED_ANALYSIS_FILES": "30"
             }):
            yield

    @patch("src.agents.ingestion.fetch_file_tree")
    @patch("src.agents.ingestion.fetch_file_contents_batch")
    def test_tier_full_analysis(self, mock_fetch_batch, mock_fetch_tree):
        """Tier 1: <= MAX_FULL_ANALYSIS_FILES should result in 'Full' mode."""
        # 5 files (<= 10 limit)
        mock_fetch_tree.return_value = [
            {"path": f"src/file_{i}.py", "size": 100, "sha": f"sha_{i}", "type": "blob"}
            for i in range(5)
        ]
        mock_fetch_batch.return_value = {
            f"src/file_{i}.py": "def hello(): pass" for i in range(5)
        }

        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        state.owner = "owner"
        state.repo_name = "repo"
        state.default_branch = "main"

        state = ingestion.run(state)
        assert state.analysis_mode == "Full"
        assert state.files_discovered == 5
        assert len(state.file_manifest) == 5

    @patch("src.agents.ingestion.fetch_file_tree")
    @patch("src.agents.ingestion.fetch_file_contents_batch")
    def test_tier_warning_analysis(self, mock_fetch_batch, mock_fetch_tree):
        """Tier 2: > MAX_FULL_ANALYSIS_FILES and <= MAX_WARNING_ANALYSIS_FILES should result in 'Full (Warning)' mode."""
        # 15 files (10 < 15 <= 20)
        mock_fetch_tree.return_value = [
            {"path": f"src/file_{i}.py", "size": 100, "sha": f"sha_{i}", "type": "blob"}
            for i in range(15)
        ]
        mock_fetch_batch.return_value = {
            f"src/file_{i}.py": "def hello(): pass" for i in range(15)
        }

        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        state.owner = "owner"
        state.repo_name = "repo"
        state.default_branch = "main"

        state = ingestion.run(state)
        assert state.analysis_mode == "Full (Warning)"
        assert state.files_discovered == 15
        assert len(state.file_manifest) == 15

    @patch("src.agents.ingestion.fetch_file_tree")
    @patch("src.agents.ingestion.fetch_file_contents_batch")
    def test_tier_sampled_analysis_ingestion(self, mock_fetch_batch, mock_fetch_tree):
        """Tier 3: > MAX_WARNING_ANALYSIS_FILES and <= MAX_SAMPLED_ANALYSIS_FILES should result in 'Sampled' mode (Ingestion)."""
        # 25 files (20 < 25 <= 30)
        mock_fetch_tree.return_value = [
            {"path": f"src/file_{i}.py", "size": 100, "sha": f"sha_{i}", "type": "blob"}
            for i in range(25)
        ]
        mock_fetch_batch.return_value = {
            f"src/file_{i}.py": "def hello(): pass" for i in range(25)
        }

        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        state.owner = "owner"
        state.repo_name = "repo"
        state.default_branch = "main"

        state = ingestion.run(state)
        assert state.analysis_mode == "Sampled"
        assert state.files_discovered == 25
        assert len(state.file_manifest) == 25

    def test_dependency_graph_sampling(self):
        """Verify that Phase 3 selects the correct subset in Sampled Mode."""
        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        state.owner = "owner"
        state.repo_name = "repo"
        state.analysis_mode = "Sampled"

        # Mock 25 files in manifest
        state.file_manifest = [
            FileMetadata(path=f"src/file_{i}.py", language="Python", line_count=10, size_bytes=100, sha=f"sha_{i}")
            for i in range(25)
        ]
        
        # Mock symbol tables (some with more functions/classes to test importance sorting)
        for i in range(25):
            st = SymbolTable(file_path=f"src/file_{i}.py", language="Python", module_docstring=None)
            if i < 5:
                st.functions = [f"fn_{j}" for j in range(5 - i)]
            state.symbol_tables[f"src/file_{i}.py"] = st

        # Run Phase 3
        # Since we use patched env dict with MAX_FULL_ANALYSIS_FILES=10, it should select top 10 files.
        state = dependency_graph.run(state)

        assert state.analyzed_paths is not None
        assert len(state.analyzed_paths) == 10
        assert state.files_analyzed == 10
        # Check that src/file_0.py is in the subset (since it has most functions and thus high ranking)
        assert "src/file_0.py" in state.analyzed_paths

    @patch("src.agents.complexity_scorer.compute_python_complexity")
    def test_complexity_scorer_filters_subset(self, mock_python_comp):
        """Verify that Phase 4 (Complexity Scorer) only scores the selected subset."""
        mock_python_comp.return_value = {"hello": 1}

        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        state.file_manifest = [
            FileMetadata(path=f"src/file_{i}.py", language="Python", line_count=10, size_bytes=100, sha=f"sha_{i}")
            for i in range(5)
        ]
        state.symbol_tables = {
            f"src/file_{i}.py": SymbolTable(file_path=f"src/file_{i}.py", language="Python", module_docstring=None)
            for i in range(5)
        }
        state.raw_contents = {
            f"src/file_{i}.py": "def hello(): pass" for i in range(5)
        }
        
        # Subset has only file_0 and file_1
        state.analyzed_paths = {"src/file_0.py", "src/file_1.py"}
        state.analysis_mode = "Sampled"

        state = complexity_scorer.run(state)

        assert len(state.complexity_scores) == 2
        assert "src/file_0.py" in state.complexity_scores
        assert "src/file_1.py" in state.complexity_scores
        assert "src/file_2.py" not in state.complexity_scores

    def test_sampled_warning_alert_in_header(self):
        """Verify doc_generator outputs warning blocks appropriately."""
        state = ArchaeonState(repo_url="https://github.com/owner/repo")
        state.owner = "owner"
        state.repo_name = "repo"
        state.analysis_mode = "Sampled"
        state.files_discovered = 1500
        state.files_analyzed = 300
        state.file_manifest = []

        footer = doc_generator._build_footer(state)
        assert "Sampled" in footer

        summary = doc_generator._build_project_summary(state)
        assert "1500" in summary
        assert "300" in summary

    @patch("src.api.main.fetch_file_tree")
    @patch("src.api.main.fetch_repo_metadata")
    def test_api_rejection_over_limit(self, mock_metadata, mock_tree):
        """Verify that API rejects repos exceeding MAX_SAMPLED_ANALYSIS_FILES limit with 400 Bad Request."""
        mock_metadata.return_value = {"default_branch": "main"}
        # 35 files (> 30 limit)
        mock_tree.return_value = [
            {"path": f"src/file_{i}.py", "size": 100, "sha": f"sha_{i}", "type": "blob"}
            for i in range(35)
        ]

        response = client.post(
            "/api/analyze",
            json={"repo_url": "https://github.com/owner/large-repo"}
        )

        assert response.status_code == 400
        assert "exceeds the maximum file limit" in response.json()["detail"]
