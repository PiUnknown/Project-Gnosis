from src.state import ArchaeonState, FileMetadata
from src.utils.github_api import fetch_file_tree, fetch_file_contents_batch
from src.utils.filters import should_include_file, detect_language


import os

# Limit thresholds for dynamic repository tiers. Configurable via env.
def get_max_full_analysis_files():
    return int(os.getenv("MAX_FULL_ANALYSIS_FILES", 300))

def get_max_warning_analysis_files():
    return int(os.getenv("MAX_WARNING_ANALYSIS_FILES", 1000))

def get_max_sampled_analysis_files():
    return int(os.getenv("MAX_SAMPLED_ANALYSIS_FILES", 3000))


def run(state: ArchaeonState) -> ArchaeonState:
    """
    Ingestion Agent entry point.

    Reads from state:  owner, repo_name, default_branch, github_token
    Writes to state:   file_manifest, raw_contents

    Steps:
    1. Fetch the full file tree from GitHub (1 API call)
    2. Filter to relevant code files
    3. Cap at MAX_FILES_TO_FETCH, prioritizing shallow files
    4. Build FileMetadata objects (manifest)
    5. Fetch raw content for each file (raw.githubusercontent.com, no API limit)
    6. Update line counts in manifest
    """
    print(f"\n[Agent 1: Ingestion] {state.owner}/{state.repo_name}")

    # Step 1: Fetch the full file tree
    print("  Fetching file tree...")
    tree_entries = fetch_file_tree(
        state.owner,
        state.repo_name,
        state.default_branch,
        state.github_token
    )
    print(f"  Total entries found: {len(tree_entries)}")

    # Step 2: Filter
    filtered = []
    for entry in tree_entries:
        if should_include_file(entry["path"], entry.get("size", 0)):
            filtered.append(entry)

    print(f"  Files after filtering: {len(filtered)}")

    # Step 3: Cap & Determine analysis mode
    # Sort by path depth first (fewer slashes = closer to root = more likely core)
    # then alphabetically for determinism
    filtered.sort(key=lambda e: (e["path"].count("/"), e["path"]))

    file_count = len(filtered)
    state.files_discovered = file_count

    if file_count <= get_max_full_analysis_files():
        state.analysis_mode = "Full"
    elif file_count <= get_max_warning_analysis_files():
        state.analysis_mode = "Full (Warning)"
        print(f"  [WARNING] High file count detected ({file_count} files). Running full analysis with warning.")
    else:
        state.analysis_mode = "Sampled"
        print(f"  [INFO] Sampled analysis mode enabled ({file_count} files discovered).")

    if len(filtered) > get_max_sampled_analysis_files():
        print(f"  [WARNING] Capping at {get_max_sampled_analysis_files()} files for ingestion.")
        filtered = filtered[:get_max_sampled_analysis_files()]

    # Step 4: Build manifest (no content yet, line_count is 0 for now)
    file_manifest = []
    for entry in filtered:
        metadata = FileMetadata(
            path=entry["path"],
            language=detect_language(entry["path"]),
            line_count=0,
            size_bytes=entry.get("size", 0),
            sha=entry.get("sha", "")
        )
        file_manifest.append(metadata)

    state.file_manifest = file_manifest

    # Step 5: Check incremental mode and fetch contents
    if state.is_incremental and state.previous_state and state.previous_state.file_manifest:
        from src.utils.diff_engine import compute_manifest_diff
        state.manifest_diff = compute_manifest_diff(
            state.previous_state.file_manifest,
            state.file_manifest
        )
        paths_to_fetch = list(state.manifest_diff.changed_paths)
        print(f"  [Incremental] Delta detected: {len(state.manifest_diff.added)} added, "
              f"{len(state.manifest_diff.modified)} modified, {len(state.manifest_diff.deleted)} deleted, "
              f"{len(state.manifest_diff.unchanged)} unchanged.")
        print(f"  Fetching content for {len(paths_to_fetch)} changed files...")
    else:
        paths_to_fetch = [f.path for f in file_manifest]
        print(f"  Fetching content for {len(paths_to_fetch)} files (via raw/API)...")

    raw_contents = fetch_file_contents_batch(
        state.owner,
        state.repo_name,
        state.default_branch,
        paths_to_fetch,
        token=state.github_token,
        delay=0.05
    )

    # In incremental mode, preserve previous raw contents for unchanged files if available
    if state.is_incremental and state.previous_state and state.previous_state.raw_contents:
        for f in (state.manifest_diff.unchanged if state.manifest_diff else []):
            if f.path in state.previous_state.raw_contents and f.path not in raw_contents:
                raw_contents[f.path] = state.previous_state.raw_contents[f.path]

    state.raw_contents = raw_contents
    del paths_to_fetch

    # Step 6: Update line counts now that content is available
    for metadata in state.file_manifest:
        if metadata.path in state.raw_contents:
            content = state.raw_contents[metadata.path]
            metadata.line_count = content.count("\n") + 1
            del content
        elif state.is_incremental and state.previous_state:
            # Fallback for unchanged file line counts from previous manifest
            prev_meta = next(
                (pm for pm in state.previous_state.file_manifest if pm.path == metadata.path),
                None
            )
            if prev_meta and prev_meta.line_count:
                metadata.line_count = prev_meta.line_count

    # Summary
    _print_summary(state)
    
    # Aggressively release ingestion references
    del tree_entries
    del filtered
    del file_manifest
    del raw_contents
    import gc
    gc.collect()

    return state


def _print_summary(state: ArchaeonState) -> None:
    """Print a human-readable breakdown of what was ingested."""
    lang_counts: dict[str, int] = {}
    for f in state.file_manifest:
        lang_counts[f.language] = lang_counts.get(f.language, 0) + 1

    print(f"\n[Agent 1: Ingestion] Done")
    print(f"  Files in manifest : {len(state.file_manifest)}")
    print(f"  Files with content: {len(state.raw_contents)}")
    print(f"  Language breakdown:")
    for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
        print(f"    {lang:<20} {count} files")