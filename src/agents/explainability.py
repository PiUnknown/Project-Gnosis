"""
Agent 6: Explainability Agent

Reads from state:  complexity_scores, graph_stats, circular_nodes,
                   chroma_collection_name, symbol_tables, owner, repo_name
Writes to state:   explanations

Pipeline per file:
1. Get all code chunks for the file from ChromaDB
2. Assemble context: code + dependency info + risk metadata
3. Build system + user prompt
4. Call Groq LLM (llama-3.3-70b-versatile, temp=0.1)
5. Store explanation string in state.explanations[file_path]

File selection: priority tiers, capped at max_count.

Tier 0: CRITICAL risk files (parse errors, circular deps, complexity >= 21)
Tier 1: High structural importance (in_degree >= 5)
Tier 2: HIGH risk files
Tier 3: Moderate importance (in_degree >= 2)
Tier 4: MEDIUM risk files
Within each tier: sorted by in_degree descending (most imported first)
"""

import os
from pathlib import PurePosixPath

from src.state import ArchaeonState
from src.utils.groq_client import call_llm, sleep_between_calls
from src.utils.retriever import CodeRetriever, DEFAULT_CHROMA_DB_PATH

# Default cap for free tier (30 req/min, ~20 files in one run)
DEFAULT_MAX_EXPLANATIONS = 20

# Code context budget in characters (~4 chars per token, targeting ~2000 tokens)
MAX_CODE_CHARS = 8000

# Tier boundaries for file selection
TIER_HIGH_INDEGREE = 5
TIER_MEDIUM_INDEGREE = 2

# -----------------------------------------------------------------------
# System prompt (static, sent with every call)
# -----------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior software engineer writing onboarding documentation \
for a new team member joining a project they have never seen before.

Your task: given source code from one file and metadata about its role in the \
codebase, write a precise technical explanation (200-300 words) that a new \
engineer can read in under 2 minutes and immediately understand how this file \
fits into the system.

Rules:
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

def run(state: ArchaeonState, max_count: int = DEFAULT_MAX_EXPLANATIONS) -> ArchaeonState:
    print(f"\n[Agent 6: Explainability]")

    # Guard: Phase 5 must have run
    if not state.chroma_collection_name:
        print("  [WARNING] No ChromaDB collection in state.")
        print("  Run Phase 5 (code_rag) before Phase 6 (explainability).")
        return state

    # Guard: API key must be present
    if not os.getenv("GROQ_API_KEY"):
        print("  [WARNING] GROQ_API_KEY not set in .env.")
        print("  Get a free key at https://console.groq.com")
        return state

    # Connect to ChromaDB
    try:
        retriever = CodeRetriever(
            collection_name=state.chroma_collection_name,
            chroma_db_path=DEFAULT_CHROMA_DB_PATH
        )
        print(f"  ChromaDB chunks : {retriever.count()}")
    except Exception as exc:
        print(f"  [ERROR] Could not connect to ChromaDB: {exc}")
        return state

    # Select files
    selected = _select_files_to_explain(state, max_count)
    print(f"  Files selected  : {len(selected)} (cap: {max_count})")
    print(f"  Files skipped   : "
          f"{len(state.complexity_scores) - len(selected)} (below priority or over cap)")

    if not selected:
        print("  No files to explain.")
        return state

    print()
    explained = 0
    failed = 0

    for idx, file_path in enumerate(selected):
        short_name = PurePosixPath(file_path).name
        score = state.complexity_scores.get(file_path)
        risk = score.risk_level if score else "UNKNOWN"
        in_deg = state.graph_stats.get(file_path, {}).get('in_degree', 0)

        print(f"  [{idx + 1:>2}/{len(selected)}] {short_name:<35} "
              f"risk={risk:<8} in_degree={in_deg}")

        # Assemble context
        code_context = _assemble_code_context(file_path, retriever)
        graph_entry  = state.graph_stats.get(file_path, {})
        language     = score.language if score else "Unknown"

        # Build prompts
        user_prompt = _build_user_prompt(
            file_path=file_path,
            language=language,
            complexity_score=score,
            graph_stats_entry=graph_entry,
            code_context=code_context
        )

        # Call Groq
        explanation = call_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=800
        )

        if explanation:
            state.explanations[file_path] = explanation.strip()
            explained += 1
        else:
            failed += 1

        # Rate limit: sleep after every call except the last
        if idx < len(selected) - 1:
            sleep_between_calls()

    _print_summary(state, selected, explained, failed)
    return state


# -----------------------------------------------------------------------
# File selection
# -----------------------------------------------------------------------

def _select_files_to_explain(state: ArchaeonState, max_count: int) -> list:
    """
    Select and prioritize files for LLM explanation.

    Returns list[str] of file paths, ordered by priority, capped at max_count.

    Priority (lower number = explain first):
      Tier 0: CRITICAL risk
      Tier 1: in_degree >= TIER_HIGH_INDEGREE (structurally critical)
      Tier 2: HIGH risk
      Tier 3: in_degree >= TIER_MEDIUM_INDEGREE
      Tier 4: MEDIUM risk
      Tier 5: everything else (LOW, files with no complexity score entry)

    Within each tier: higher in_degree comes first.
    Negative in_degree used as secondary sort key to get descending order.
    """
    if not state.complexity_scores:
        return []

    candidates = []

    for file_path, score in state.complexity_scores.items():
        in_degree = state.graph_stats.get(file_path, {}).get('in_degree', 0)
        risk = score.risk_level

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

        # Secondary sort: higher in_degree first within same tier
        candidates.append((tier, -in_degree, file_path))

    candidates.sort(key=lambda x: (x[0], x[1]))
    return [path for _, _, path in candidates[:max_count]]


# -----------------------------------------------------------------------
# Context assembly
# -----------------------------------------------------------------------

def _assemble_code_context(file_path: str, retriever: CodeRetriever) -> str:
    """
    Assemble the code section of the prompt for one file.

    Ordering:
      1. Module chunk (imports + docstring) — orientation context
      2. Function chunks sorted by complexity descending — most complex first
         so if we hit the budget limit, high-complexity functions are preserved
      3. Class chunks — structural overview

    Budget: MAX_CODE_CHARS characters across all chunks combined.
    When the budget is hit, a truncation notice is appended instead of
    silently cutting mid-chunk.
    """
    chunks = retriever.get_file_chunks(file_path)

    if not chunks:
        return ""

    # Separate by type and sort functions by complexity (highest first)
    module_chunks = [c for c in chunks if c['symbol_type'] == 'module']
    fn_chunks     = sorted(
        [c for c in chunks if c['symbol_type'] == 'function'],
        key=lambda c: -(c.get('complexity') or 0)
    )
    class_chunks  = [c for c in chunks if c['symbol_type'] == 'class']

    ordered = module_chunks + fn_chunks + class_chunks
    parts   = []
    char_count = 0
    truncated  = False

    for chunk in ordered:
        content = chunk['content']

        if char_count + len(content) > MAX_CODE_CHARS:
            remaining = MAX_CODE_CHARS - char_count
            if remaining > 300:
                # Include partial content rather than nothing
                parts.append(content[:remaining] + "\n... [truncated — budget reached]")
            else:
                # Not enough space to show anything useful
                parts.append(
                    f"# ... {len(ordered) - len(parts)} more chunks "
                    f"not shown (budget limit)"
                )
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
    """
    Build the user turn of the LLM prompt for one file.

    The prompt contains four sections:
    1. File header: path, language, risk level with reasons, coupling
    2. Dependencies: what this file imports and what imports it
    3. Source code: from ChromaDB (may be empty for parse-error files)
    4. Task: explicit instruction to the model
    """

    # ---- Section 1: File header ----------------------------------------
    if complexity_score:
        risk_level = complexity_score.risk_level
        reasons_str = ""
        if complexity_score.risk_reasons:
            reasons_str = " | ".join(complexity_score.risk_reasons[:2])
            reasons_str = f"\nRisk reasons: {reasons_str}"

        max_fn_str = ""
        if complexity_score.max_complexity_function:
            max_fn_str = f" in `{complexity_score.max_complexity_function}`"

        complexity_str = (
            f"Avg cyclomatic complexity: {complexity_score.avg_complexity:.1f} | "
            f"Max: {int(complexity_score.max_complexity)}{max_fn_str}"
        )
        coupling_str = (
            f"Coupling: imports from "
            f"{complexity_score.coupling_score} internal file(s)"
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

    # ---- Section 2: Dependencies ----------------------------------------
    in_degree   = graph_stats_entry.get('in_degree', 0)
    out_degree  = graph_stats_entry.get('out_degree', 0)
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
        dep_lines.append(
            f"Imported by {in_degree} file(s): {', '.join(dep_names)}"
        )
        if len(dependents) > 8:
            dep_lines.append(f"  ...and {len(dependents) - 8} more")

    if not dep_lines:
        dep_context = "No internal dependency relationships detected."
    else:
        dep_context = '\n'.join(dep_lines)

    # ---- Section 3: Source code -----------------------------------------
    if code_context.strip():
        code_section = f"Source Code:\n{code_context}"
    else:
        code_section = (
            "Source Code:\n"
            "[No code chunks available. This file may have parse errors "
            "or was not included in the RAG collection. "
            "Explain based on the metadata above.]"
        )

    # ---- Section 4: Task ------------------------------------------------
    task = (
        "Explain this file in 200-300 words for a new engineer. Cover:\n"
        "1. Primary responsibility — what does this file do?\n"
        "2. Architecture role — where does it sit in the dependency chain?\n"
        "3. Key entry points — which functions or classes should they read first?\n"
        "4. Risks or cautions — what must they know before modifying this file?\n"
        "\n"
        "Be specific. Use actual function and class names. Do not speculate."
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
    failed: int
) -> None:
    print(f"\n[Agent 6: Explainability] Done")
    print(f"  Files attempted  : {len(selected)}")
    print(f"  Explained        : {explained}")
    print(f"  Failed (Groq)    : {failed}")
    print(f"  Total in state   : {len(state.explanations)}")

    if failed > 0:
        print(
            f"\n  [INFO] {failed} file(s) failed. Common causes: "
            f"rate limit exceeded, context too long, or API key issue."
        )

    if explained > 0:
        print(f"\n  Sample explanation ({explained} total):")
        sample_path = next(iter(state.explanations))
        sample_text = state.explanations[sample_path]
        preview = sample_text[:300].replace('\n', ' ')
        if len(sample_text) > 300:
            preview += "..."
        print(f"  [{PurePosixPath(sample_path).name}]")
        print(f"  {preview}")