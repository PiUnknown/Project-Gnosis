"""
Agent 6: Explainability Agent

Reads from state:  complexity_scores, graph_stats, circular_nodes,
                   chroma_collection_name, symbol_tables, owner, repo_name,
                   file_manifest
Writes to state:   explanations

LLM PROVIDER: NVIDIA NIM via src/utils/nvidia_client.py
CACHING: ./explanation_cache/ keyed by owner::repo::file_path::sha
"""

import os
import time
import concurrent.futures
from pathlib import PurePosixPath
from typing import Callable, Optional

from src.state import ArchaeonState
from src.utils.nvidia_client import call_llm, get_client, sleep_between_calls
from src.utils.retriever import CodeRetriever, DEFAULT_CHROMA_DB_PATH
from src.utils.explanation_cache import (
    make_cache_key,
    get_cached_explanation,
    save_explanation,
    cache_stats
)

DEFAULT_MAX_EXPLANATIONS = 20
MAX_CODE_CHARS           = 8000
TIER_HIGH_INDEGREE       = 5
TIER_MEDIUM_INDEGREE     = 2

SYSTEM_PROMPT = """You are a senior software engineer writing onboarding documentation \
for a new team member joining a project they have never seen before.

Your task: given source code from one file and metadata about its role in the \
codebase, write a precise technical explanation (200-300 words) that a new \
engineer can read in under 2 minutes and immediately understand how this file \
fits into the system.

Strict Formatting Constraints:
- Output ONLY the final 2-3 paragraph technical explanation.
- DO NOT include any thinking process, reasoning steps, analysis preambles, or scratchpad commentary.
- DO NOT wrap the output in <thought>, <think>, or markdown code fences.
- Reference actual function names, class names, and method names from the code.
- Do not speculate about behavior that is not visible in the provided code.
- Do not use filler phrases like "this file plays a crucial role" or \
"it is important to note".
- Write plain technical prose. No bullet points. No markdown headers.
- If there are risks (circular dependency, high complexity, no docstrings, \
parse errors), name them explicitly and specifically.
- End with one concrete sentence about what a new engineer should read first."""


# -----------------------------------------------------------------------
# Agent entry point
# -----------------------------------------------------------------------

def run(
    state: ArchaeonState,
    max_count: int = DEFAULT_MAX_EXPLANATIONS,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> ArchaeonState:
    import os
    key = os.getenv("NVIDIA_API_KEY", "NOT_FOUND")
    print(f"  [Agent 6 DEBUG] NVIDIA_API_KEY = {'SET (' + key[:8] + '...)' if key != 'NOT_FOUND' else 'NOT FOUND'}")

    t_agent_start = time.time()
    print(f"\n[Agent 6: Explainability]")
    print(f"  [Agent 6] Started at {time.strftime('%H:%M:%S')}")

    if not state.chroma_collection_name:
        print("  [WARNING] No ChromaDB collection in state. Run Phase 5 first.")
        return state

    if not os.getenv("NVIDIA_API_KEY"):
        print("  [WARNING] NVIDIA_API_KEY not set. Get a key at https://build.nvidia.com")
        return state

    # ---- ChromaDB connection -------------------------------------------
    print(f"  [Agent 6] Connecting to ChromaDB...")
    try:
        retriever = CodeRetriever(
            collection_name=state.chroma_collection_name,
            chroma_db_path=DEFAULT_CHROMA_DB_PATH
        )
        print(f"  ChromaDB chunks : {retriever.count()}")
    except Exception as exc:
        print(f"  [ERROR] Could not connect to ChromaDB: {exc}")
        return state

    # ---- SHA lookup from manifest --------------------------------------
    sha_lookup: dict = {}
    for file_meta in state.file_manifest:
        if hasattr(file_meta, 'sha') and file_meta.sha:
            sha_lookup[file_meta.path] = file_meta.sha

    stats = cache_stats()
    print(f"  Cache           : {stats['entries']} entries ({stats['size_kb']} KB)")

    # ---- Incremental state reuse ---------------------------------------
    if state.is_incremental and state.previous_state and state.previous_state.explanations:
        unchanged_paths = state.manifest_diff.unchanged_paths if state.manifest_diff else set()
        for p, exp in state.previous_state.explanations.items():
            if p in unchanged_paths:
                state.explanations[p] = exp
        print(f"  [Incremental] Reused {len(state.explanations)} explanations for unchanged files.")

    # ---- File selection ------------------------------------------------
    selected = _select_files_to_explain(state, max_count)
    print(f"  Files selected  : {len(selected)} (cap: {max_count})")
    print(f"  Files skipped   : "
          f"{len(state.complexity_scores) - len(selected)} "
          f"(below priority or over cap)")

    if not selected:
        print("  No files to explain.")
        return state

    print()
    total_selected = len(selected)
    explained = sum(1 for path in selected if path in state.explanations)
    cache_hits = 0
    failed = 0
    work = []

    def report_progress() -> None:
        if progress_callback:
            progress_callback(explained, total_selected)

    report_progress()

    # Prepare contexts and prompts once, in stable priority order. Only the
    # independent remote inference calls run concurrently.
    for idx, file_path in enumerate(selected):
        if file_path in state.explanations:
            cache_hits += 1
            continue

        short_name = PurePosixPath(file_path).name
        score = state.complexity_scores.get(file_path)
        risk = score.risk_level if score else "UNKNOWN"
        in_deg = state.graph_stats.get(file_path, {}).get("in_degree", 0)
        file_sha = sha_lookup.get(file_path, "")
        cache_key = make_cache_key(
            owner=state.owner,
            repo_name=state.repo_name,
            file_path=file_path,
            file_sha=file_sha,
        )

        cached = get_cached_explanation(cache_key)
        if cached:
            state.explanations[file_path] = cached
            explained += 1
            cache_hits += 1
            report_progress()
            print(f"  [{idx + 1:>2}/{total_selected}] {short_name}: cache hit")
            continue

        print(
            f"\n  [{idx + 1:>2}/{total_selected}] {short_name:<35} "
            f"risk={risk:<8} in_degree={in_deg}  "
            f"[{time.strftime('%H:%M:%S')}]"
        )
        print("  [Agent 6] Assembling code context from ChromaDB...")
        context_started = time.perf_counter()
        raw_code = state.raw_contents.get(file_path, "")
        code_context = _assemble_code_context(
            file_path, retriever, raw_content=raw_code
        )
        print(
            f"  [Agent 6] Context assembled in "
            f"{time.perf_counter() - context_started:.2f}s "
            f"({len(code_context)} chars)"
        )

        user_prompt = _build_user_prompt(
            file_path=file_path,
            language=score.language if score else "Unknown",
            complexity_score=score,
            graph_stats_entry=state.graph_stats.get(file_path, {}),
            code_context=code_context,
        )
        print(
            f"  [Agent 6] Prompt ready: system={len(SYSTEM_PROMPT)}chars  "
            f"user={len(user_prompt)}chars"
        )
        work.append({
            "file_path": file_path,
            "file_sha": file_sha,
            "cache_key": cache_key,
            "user_prompt": user_prompt,
            "short_name": short_name,
        })

    try:
        max_workers = int(os.getenv("NVIDIA_LLM_MAX_CONCURRENCY", "2"))
    except ValueError:
        max_workers = 2
    max_workers = max(1, min(4, max_workers, len(work) or 1))
    try:
        start_interval = max(
            0.0,
            float(os.getenv("NVIDIA_LLM_START_INTERVAL_SECONDS", "0.5")),
        )
    except ValueError:
        start_interval = 0.5

    if work:
        # Initialize the shared SDK client before worker threads start.
        get_client()
        print(
            f"  [Agent 6] Sending {len(work)} uncached prompts "
            f"(max concurrency={max_workers})"
        )
        futures = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:
            for index, item in enumerate(work):
                future = executor.submit(
                    call_llm,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=item["user_prompt"],
                    temperature=0.1,
                    max_tokens=800,
                )
                futures[future] = item
                if index + 1 < len(work) and start_interval:
                    sleep_between_calls(start_interval)

            for future in concurrent.futures.as_completed(futures):
                item = futures[future]
                try:
                    explanation = future.result()
                except Exception as exc:
                    explanation = None
                    print(
                        f"  [Agent 6] {item['short_name']} failed: {exc}"
                    )

                if explanation:
                    explanation = explanation.strip()
                    state.explanations[item["file_path"]] = explanation
                    if item["file_sha"]:
                        cached = save_explanation(
                            cache_key=item["cache_key"],
                            explanation=explanation,
                            owner=state.owner,
                            repo_name=state.repo_name,
                            file_path=item["file_path"],
                            file_sha=item["file_sha"],
                        )
                        print(
                            f"  [Agent 6] {item['short_name']} cached={cached}"
                        )
                else:
                    failed += 1
                    print(
                        f"  [Agent 6] No explanation returned for "
                        f"{item['short_name']}"
                    )

                explained += 1
                report_progress()

    agent_elapsed = time.time() - t_agent_start
    _print_summary(
        state,
        selected,
        len(state.explanations),
        cache_hits,
        len(work),
        failed,
        agent_elapsed,
    )
    return state


# -----------------------------------------------------------------------
# File selection
# -----------------------------------------------------------------------

def _select_files_to_explain(state: ArchaeonState, max_count: int) -> list:
    if not state.complexity_scores:
        return []

    candidates = []
    for file_path, score in state.complexity_scores.items():
        in_degree = state.graph_stats.get(file_path, {}).get('in_degree', 0)
        risk      = score.risk_level

        if risk == "CRITICAL":
            tier = 0
        elif in_degree >= TIER_HIGH_INDEGREE:
            tier = 1
        elif risk == "HIGH":
            tier = 2
        elif in_degree >= TIER_MEDIUM_INDEGREE:
            tier = 3
        elif risk == "MEDIUM":
            tier = 4
        else:
            tier = 5

        candidates.append((tier, -in_degree, file_path))

    candidates.sort(key=lambda x: (x[0], x[1]))
    return [path for _, _, path in candidates[:max_count]]


# -----------------------------------------------------------------------
# Context assembly
# -----------------------------------------------------------------------

def _assemble_code_context(file_path: str, retriever: CodeRetriever, raw_content: str = "") -> str:
    chunks = retriever.get_file_chunks(file_path)
    if not chunks:
        if raw_content:
            if len(raw_content) > MAX_CODE_CHARS:
                return raw_content[:MAX_CODE_CHARS] + "\n... [truncated]"
            return raw_content
        return ""

    module_chunks = [c for c in chunks if c['symbol_type'] == 'module']
    fn_chunks     = sorted(
        [c for c in chunks if c['symbol_type'] == 'function'],
        key=lambda c: -(c.get('complexity') or 0)
    )
    class_chunks  = [c for c in chunks if c['symbol_type'] == 'class']

    ordered    = module_chunks + fn_chunks + class_chunks
    parts      = []
    char_count = 0
    truncated  = False

    for chunk in ordered:
        content = chunk['content']
        if char_count + len(content) > MAX_CODE_CHARS:
            remaining = MAX_CODE_CHARS - char_count
            if remaining > 300:
                parts.append(content[:remaining] + "\n... [truncated]")
            else:
                parts.append(f"# ... {len(ordered) - len(parts)} more chunks not shown")
            truncated = True
            break
        parts.append(content)
        char_count += len(content)

    if not truncated and len(ordered) > len(parts):
        parts.append(f"# ... {len(ordered) - len(parts)} additional chunks omitted")

    return '\n\n---\n\n'.join(parts)


# -----------------------------------------------------------------------
# Prompt construction
# -----------------------------------------------------------------------

def _build_user_prompt(
    file_path: str,
    language: str,
    complexity_score,
    graph_stats_entry: dict,
    code_context: str
) -> str:
    if complexity_score:
        risk_level  = complexity_score.risk_level
        reasons_str = ""
        if complexity_score.risk_reasons:
            reasons_str = " | ".join(complexity_score.risk_reasons[:2])
            reasons_str = f"\nRisk reasons: {reasons_str}"
        max_fn_str = (
            f" in `{complexity_score.max_complexity_function}`"
            if complexity_score.max_complexity_function else ""
        )
        complexity_str = (
            f"Avg cyclomatic complexity: {complexity_score.avg_complexity:.1f} | "
            f"Max: {int(complexity_score.max_complexity)}{max_fn_str}"
        )
        coupling_str = (
            f"Coupling: imports from {complexity_score.coupling_score} internal file(s)"
        )
        fn_count_str = f"Functions: {complexity_score.function_count}"
    else:
        risk_level     = "UNKNOWN"
        reasons_str    = ""
        complexity_str = "Complexity: not analyzed"
        coupling_str   = ""
        fn_count_str   = ""

    header = (
        f"File: {file_path}\n"
        f"Language: {language}\n"
        f"Risk level: {risk_level}{reasons_str}\n"
        f"{complexity_str}\n"
        f"{coupling_str}\n"
        f"{fn_count_str}"
    ).strip()

    in_degree    = graph_stats_entry.get('in_degree', 0)
    dependencies = graph_stats_entry.get('dependencies', [])
    dependents   = graph_stats_entry.get('dependents', [])

    dep_lines = []
    if dependencies:
        dep_names = [PurePosixPath(d).name for d in dependencies[:8]]
        dep_lines.append(f"This file imports: {', '.join(dep_names)}")
        if len(dependencies) > 8:
            dep_lines.append(f"  ...and {len(dependencies) - 8} more")
    if dependents:
        dep_names = [PurePosixPath(d).name for d in dependents[:8]]
        dep_lines.append(f"Imported by {in_degree} file(s): {', '.join(dep_names)}")
        if len(dependents) > 8:
            dep_lines.append(f"  ...and {len(dependents) - 8} more")

    dep_context = '\n'.join(dep_lines) if dep_lines else "No internal dependency relationships detected."

    code_section = (
        f"Source Code:\n{code_context}" if code_context.strip()
        else (
            "Source Code:\n[No code chunks available — file may have parse errors "
            "or was not included in the RAG collection.]"
        )
    )

    task = (
        "Explain this file in 200-300 words for a new engineer. Cover:\n"
        "1. Primary responsibility — what does this file do?\n"
        "2. Architecture role — where does it sit in the dependency chain?\n"
        "3. Key entry points — which functions or classes should they read first?\n"
        "4. Risks or cautions — what must they know before modifying this file?\n"
        "\nBe specific. Use actual function and class names. Do not speculate."
    )

    return (
        f"{header}\n\n"
        f"Dependencies:\n{dep_context}\n\n"
        f"{code_section}\n\n"
        f"Task:\n{task}"
    )


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------

def _print_summary(
    state: ArchaeonState,
    selected: list,
    explained: int,
    cache_hits: int,
    api_calls: int,
    failed: int,
    agent_elapsed: float
) -> None:
    api_explained = explained - cache_hits
    print(f"\n[Agent 6: Explainability] Done in {agent_elapsed:.1f}s")
    print(f"  Files attempted  : {len(selected)}")
    print(f"  Cache hits       : {cache_hits}  (0 tokens spent)")
    print(f"  NVIDIA API calls : {api_calls}")
    print(f"  Explained        : {explained} ({cache_hits} from cache, "
          f"{api_explained} from NVIDIA NIM)")
    print(f"  Failed           : {failed}")
    print(f"  Total in state   : {len(state.explanations)}")

    if failed > 0:
        print(
            f"\n  [INFO] {failed} file(s) failed. Check [NVIDIA] log lines above "
            f"for timeout or rate limit details."
        )
    if cache_hits == len(selected):
        print(f"\n  [INFO] All explanations from cache. Zero API tokens used.")
    elif cache_hits > 0:
        print(f"\n  [INFO] Cache saved ~{cache_hits * 3000:,} tokens this run.")

    if state.explanations:
        print(f"\n  Sample explanation ({len(state.explanations)} total):")
        sample_path = next(iter(state.explanations))
        sample_text = state.explanations[sample_path]
        preview = sample_text[:300].replace('\n', ' ')
        if len(sample_text) > 300:
            preview += "..."
        print(f"  [{PurePosixPath(sample_path).name}]")
        print(f"  {preview}")
