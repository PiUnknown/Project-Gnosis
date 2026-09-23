"""
Diff Engine for Incremental Repository Updates.

Computes changes (added, modified, deleted, unchanged files) between consecutive
archaeology runs and restores cached symbol tables, complexity scores, and
explanations so downstream agents only process deltas.
"""

import json
import os
import logging
from dataclasses import dataclass, field
from typing import Optional

from src.state import ArchaeonState, FileMetadata
from src.parsers.base import (
    SymbolTable,
    FunctionInfo,
    ClassInfo,
    ImportInfo,
    ComplexityScore,
)

logger = logging.getLogger(__name__)


@dataclass
class ManifestDiff:
    """Represents the file-level delta between a previous run and the current run."""
    added: list[FileMetadata] = field(default_factory=list)
    modified: list[tuple[FileMetadata, FileMetadata]] = field(default_factory=list)  # (old, new)
    deleted: list[FileMetadata] = field(default_factory=list)
    unchanged: list[FileMetadata] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    @property
    def changed_paths(self) -> set[str]:
        """Set of all file paths added or modified in this run."""
        paths = {f.path for f in self.added}
        paths.update(new_f.path for _, new_f in self.modified)
        return paths

    @property
    def deleted_paths(self) -> set[str]:
        return {f.path for f in self.deleted}

    @property
    def unchanged_paths(self) -> set[str]:
        return {f.path for f in self.unchanged}

    def to_dict(self) -> dict:
        return {
            "added_count": len(self.added),
            "modified_count": len(self.modified),
            "deleted_count": len(self.deleted),
            "unchanged_count": len(self.unchanged),
            "added_files": [f.path for f in self.added],
            "modified_files": [new_f.path for _, new_f in self.modified],
            "deleted_files": [f.path for f in self.deleted],
            "unchanged_files": [f.path for f in self.unchanged],
        }


def compute_manifest_diff(
    previous_manifest: list[FileMetadata],
    current_manifest: list[FileMetadata]
) -> ManifestDiff:
    """
    Compare previous FileMetadata list with current FileMetadata list.
    Uses Git blob SHA (`sha`), file size, and file path to determine deltas.
    """
    prev_by_path: dict[str, FileMetadata] = {f.path: f for f in previous_manifest}
    curr_by_path: dict[str, FileMetadata] = {f.path: f for f in current_manifest}

    diff = ManifestDiff()

    # Detect added, modified, unchanged
    for path, curr_file in curr_by_path.items():
        if path not in prev_by_path:
            diff.added.append(curr_file)
        else:
            prev_file = prev_by_path[path]
            # If SHA is present and differs, or if SHA is missing but size/lines differ
            sha_changed = (
                prev_file.sha and curr_file.sha and prev_file.sha != curr_file.sha
            )
            size_changed = (
                not (prev_file.sha and curr_file.sha)
                and prev_file.size_bytes != curr_file.size_bytes
            )
            if sha_changed or size_changed:
                diff.modified.append((prev_file, curr_file))
            else:
                diff.unchanged.append(curr_file)

    # Detect deleted
    for path, prev_file in prev_by_path.items():
        if path not in curr_by_path:
            diff.deleted.append(prev_file)

    return diff


def rehydrate_symbol_tables(raw_symbol_data: dict) -> dict[str, SymbolTable]:
    """Convert a raw JSON symbol_tables dictionary back into native SymbolTable objects."""
    result: dict[str, SymbolTable] = {}
    for file_path, data in raw_symbol_data.items():
        functions = [
            FunctionInfo(
                name=f.get("name", ""),
                params=f.get("params", []),
                line_start=f.get("line_start", 0),
                line_end=f.get("line_end", 0),
                docstring=f.get("docstring"),
                is_async=f.get("is_async", False),
                is_method=f.get("is_method", False)
            )
            for f in data.get("functions", [])
        ]
        classes = [
            ClassInfo(
                name=c.get("name", ""),
                bases=c.get("bases", []),
                method_names=c.get("method_names", []),
                line_start=c.get("line_start", 0),
                line_end=c.get("line_end", 0),
                docstring=c.get("docstring")
            )
            for c in data.get("classes", [])
        ]
        imports = [
            ImportInfo(
                module=i.get("module", ""),
                names=i.get("names", []),
                is_from_import=i.get("is_from_import", False),
                is_internal=i.get("is_internal", False)
            )
            for i in data.get("imports", [])
        ]
        st = SymbolTable(
            file_path=file_path,
            language=data.get("language", "Unknown"),
            module_docstring=data.get("module_docstring"),
            functions=functions,
            classes=classes,
            imports=imports,
            parse_error=data.get("parse_error", False),
            parse_error_detail=data.get("parse_error_detail")
        )
        result[file_path] = st
    return result


def rehydrate_complexity_scores(raw_complexity_data: dict) -> dict[str, ComplexityScore]:
    """Convert raw complexity report JSON back into ComplexityScore objects."""
    result: dict[str, ComplexityScore] = {}
    files_by_risk = raw_complexity_data.get("files_by_risk", {})
    all_scores = []
    for risk_list in files_by_risk.values():
        if isinstance(risk_list, list):
            all_scores.extend(risk_list)

    for item in all_scores:
        file_path = item.get("file_path")
        if not file_path:
            continue
        score = ComplexityScore(
            file_path=file_path,
            language=item.get("language", "Unknown"),
            function_scores=item.get("function_scores", {}),
            avg_complexity=item.get("avg_complexity", 0.0),
            max_complexity=item.get("max_complexity", 0.0),
            max_complexity_function=item.get("max_complexity_function", ""),
            function_count=item.get("function_count", 0),
            avg_function_lines=item.get("avg_function_lines", 0.0),
            coupling_score=item.get("coupling_score", 0),
            undocumented_count=item.get("undocumented_count", 0),
            undocumented_ratio=item.get("undocumented_ratio", 0.0),
            parse_error=item.get("parse_error", False),
            is_in_circular_dep=item.get("is_in_circular_dep", False),
            line_count=item.get("line_count", 0),
            risk_level=item.get("risk_level", "LOW"),
            risk_reasons=item.get("risk_reasons", [])
        )
        result[file_path] = score
    return result


def load_cached_manifest(output_dir: str = "./outputs") -> Optional[list[FileMetadata]]:
    """Load previously saved file_manifest.json from the output directory."""
    manifest_path = os.path.join(output_dir, "file_manifest.json")
    if not os.path.exists(manifest_path):
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        files = []
        for item in data.get("files", []):
            files.append(
                FileMetadata(
                    path=item["path"],
                    language=item.get("language", "Unknown"),
                    line_count=item.get("line_count", 0),
                    size_bytes=item.get("size_bytes", 0),
                    sha=item.get("sha", "")
                )
            )
        return files
    except Exception as exc:
        logger.warning("Failed to load cached file_manifest.json: %s", exc)
        return None


def load_cached_state(output_dir: str = "./outputs") -> Optional[ArchaeonState]:
    """
    Restore an ArchaeonState containing previous symbol tables, complexity scores,
    explanations, and manifests from the output directory.
    """
    manifest = load_cached_manifest(output_dir)
    if not manifest:
        return None

    state = ArchaeonState(repo_url="")
    state.file_manifest = manifest

    # Load symbol tables
    st_path = os.path.join(output_dir, "symbol_tables.json")
    if os.path.exists(st_path):
        try:
            with open(st_path, "r", encoding="utf-8") as f:
                state.symbol_tables = rehydrate_symbol_tables(json.load(f))
        except Exception as exc:
            logger.warning("Failed to load cached symbol_tables.json: %s", exc)

    # Load complexity scores
    cr_path = os.path.join(output_dir, "complexity_report.json")
    if os.path.exists(cr_path):
        try:
            with open(cr_path, "r", encoding="utf-8") as f:
                state.complexity_scores = rehydrate_complexity_scores(json.load(f))
        except Exception as exc:
            logger.warning("Failed to load cached complexity_report.json: %s", exc)

    # Load explanations
    exp_path = os.path.join(output_dir, "explanations.json")
    if os.path.exists(exp_path):
        try:
            with open(exp_path, "r", encoding="utf-8") as f:
                exp_data = json.load(f)
                state.explanations = exp_data.get("explanations", {})
        except Exception as exc:
            logger.warning("Failed to load cached explanations.json: %s", exc)

    # Load final_doc
    onb_path = os.path.join(output_dir, "onboarding.md")
    if os.path.exists(onb_path):
        try:
            with open(onb_path, "r", encoding="utf-8") as f:
                state.final_doc = f.read()
        except Exception:
            pass

    # Load file_explanations.md
    fe_path = os.path.join(output_dir, "file_explanations.md")
    if os.path.exists(fe_path):
        try:
            with open(fe_path, "r", encoding="utf-8") as f:
                state.file_explanations_doc = f.read()
        except Exception:
            pass

    return state
