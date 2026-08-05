"""
Agent 4: Complexity Scorer

Reads from state:  symbol_tables, raw_contents, graph_stats,
                   circular_nodes, file_manifest
Writes to state:   complexity_scores

For each parseable file:
1. Coupling score from graph_stats['out_degree'] (unique internal deps)
2. Per-function cyclomatic complexity (radon for Python, custom for JS/TS)
3. Aggregate metrics: avg, max, undocumented ratio, avg function lines
4. Risk level: CRITICAL / HIGH / MEDIUM / LOW via OR logic on signals
5. Store ComplexityScore in state.complexity_scores[file_path]
"""
from pathlib import PurePosixPath

from src.state import ArchaeonState
from src.parsers.base import ComplexityScore
from src.parsers.complexity import compute_python_complexity, compute_js_complexity

# Languages for which we compute complexity.
# YAML, Markdown, TOML are skipped — no meaningful complexity metrics apply.
SCORED_LANGUAGES = frozenset({'Python', 'JavaScript', 'TypeScript'})

# -----------------------------------------------------------------------
# Risk thresholds — all constants in one dict for easy tuning and testing
# -----------------------------------------------------------------------
RISK_THRESHOLDS = {
    # Any single function at or above this complexity → CRITICAL
    'max_complexity_critical': 21,

    # Any single function at or above this → HIGH
    'max_complexity_high': 11,

    # File-level average
    'avg_complexity_high':   10.0,
    'avg_complexity_medium':  6.0,

    # Unique internal modules imported (out_degree)
    'coupling_high':   8,
    'coupling_medium': 4,

    # Documentation: ratio of functions with no docstring
    # Only checked when function_count >= min threshold (avoids false positives
    # on small utility files with 1-2 trivial functions)
    'undocumented_ratio_high':   0.8,
    'undocumented_ratio_medium': 0.6,
    'min_functions_for_undoc_check': 3,

    # Line count: supporting signal, not a primary driver
    'line_count_high':   600,
    'line_count_medium': 300,
}


def run(state: ArchaeonState) -> ArchaeonState:
    print(f"\n[Agent 4: Complexity Scorer]")

    # Build a line_count lookup from the manifest
    # (symbol_tables do not store line_count — that lives on FileMetadata)
    line_counts = {f.path: f.line_count for f in state.file_manifest}

    total = len(state.symbol_tables)
    scored = 0
    skipped = 0

    for idx, (file_path, symbol_table) in enumerate(state.symbol_tables.items()):
        print(f"\r  Scoring files: {idx + 1}/{total}", end="", flush=True)

        lang = symbol_table.language

        if lang not in SCORED_LANGUAGES:
            skipped += 1
            continue

        source = state.raw_contents.get(file_path, "")

        # Coupling: use graph out_degree (unique files this file imports).
        # WHY NOT COUNT ImportInfo OBJECTS:
        # A file might have `from X import A` and `from X import B` as two
        # separate ImportInfo objects both pointing to the same module X.
        # Counting ImportInfo objects = 2. Graph out_degree = 1 (one edge to X).
        # Graph out_degree is the correct coupling metric.
        if file_path in state.graph_stats:
            coupling_score = state.graph_stats[file_path]['out_degree']
        else:
            # Fallback if graph didn't include this file (should not happen,
            # but defensive programming is correct here)
            coupling_score = len(symbol_table.internal_imports)

        is_in_circular = file_path in state.circular_nodes
        line_count = line_counts.get(file_path, 0)

        score = _score_file(
            file_path=file_path,
            language=lang,
            symbol_table=symbol_table,
            source=source,
            line_count=line_count,
            coupling_score=coupling_score,
            is_in_circular_dep=is_in_circular
        )

        state.complexity_scores[file_path] = score
        scored += 1

        del source
        del score

    print()
    _print_summary(state, scored, skipped)
    
    del line_counts
    import gc
    gc.collect()
    
    return state


def _score_file(
    file_path: str,
    language: str,
    symbol_table,
    source: str,
    line_count: int,
    coupling_score: int,
    is_in_circular_dep: bool
) -> ComplexityScore:
    """
    Compute all metrics for one file and return a ComplexityScore.
    Pure function: no state reads or writes.
    """
    functions = symbol_table.functions

    # ---- Per-function complexity ----------------------------------------
    if language == 'Python' and source:
        function_scores = compute_python_complexity(source)
    elif language in ('JavaScript', 'TypeScript') and source:
        function_scores = compute_js_complexity(source, language, symbol_table)
    else:
        function_scores = {}

    # ---- Aggregate complexity metrics -----------------------------------
    if function_scores:
        complexities = list(function_scores.values())
        avg_complexity = round(sum(complexities) / len(complexities), 2)
        max_complexity = float(max(complexities))
        max_complexity_function = max(function_scores, key=function_scores.get)
    else:
        avg_complexity = 0.0
        max_complexity = 0.0
        max_complexity_function = ""

    # ---- Function size metrics ------------------------------------------
    function_count = len(functions)
    if functions:
        lengths = [f.line_end - f.line_start + 1 for f in functions]
        avg_function_lines = round(sum(lengths) / len(lengths), 1)
    else:
        avg_function_lines = 0.0

    # ---- Documentation health -------------------------------------------
    undocumented_count = len(symbol_table.undocumented_functions)
    undocumented_ratio = (
        round(undocumented_count / function_count, 3)
        if function_count > 0 else 0.0
    )

    # ---- Risk assessment ------------------------------------------------
    risk_level, risk_reasons = _compute_risk(
        avg_complexity=avg_complexity,
        max_complexity=max_complexity,
        coupling_score=coupling_score,
        undocumented_ratio=undocumented_ratio,
        function_count=function_count,
        parse_error=symbol_table.parse_error,
        is_in_circular_dep=is_in_circular_dep,
        line_count=line_count
    )

    return ComplexityScore(
        file_path=file_path,
        language=language,
        function_scores=function_scores,
        avg_complexity=avg_complexity,
        max_complexity=max_complexity,
        max_complexity_function=max_complexity_function,
        function_count=function_count,
        avg_function_lines=avg_function_lines,
        coupling_score=coupling_score,
        undocumented_count=undocumented_count,
        undocumented_ratio=undocumented_ratio,
        parse_error=symbol_table.parse_error,
        is_in_circular_dep=is_in_circular_dep,
        line_count=line_count,
        risk_level=risk_level,
        risk_reasons=risk_reasons
    )


def _compute_risk(
    avg_complexity: float,
    max_complexity: float,
    coupling_score: int,
    undocumented_ratio: float,
    function_count: int,
    parse_error: bool,
    is_in_circular_dep: bool,
    line_count: int
) -> tuple:
    """
    Assign a risk level and human-readable reasons list.

    Priority: CRITICAL > HIGH > MEDIUM > LOW.
    A file sits at the highest level that ANY of its signals reach.

    WHY OR LOGIC NOT AND LOGIC:
    Risk signals are independent dangers. A single function with complexity
    25 is dangerous regardless of everything else in the file. A circular
    dependency is dangerous regardless of internal complexity. Requiring
    multiple signals to co-occur (AND logic) would hide real dangers.
    The cost of a false positive is low: a developer reviews it and finds
    it is fine. The cost of a false negative is high: a real risk that
    nobody knows to look for.
    """
    T = RISK_THRESHOLDS
    reasons: list = []
    level = "LOW"

    # ---- CRITICAL -------------------------------------------------------
    if parse_error:
        reasons.append("File contains syntax errors (tree-sitter parse failure)")
        level = "CRITICAL"

    if is_in_circular_dep:
        reasons.append("Involved in a circular dependency")
        level = "CRITICAL"

    if max_complexity >= T['max_complexity_critical']:
        reasons.append(
            f"Function '{_trunc(str(max_complexity))}' has cyclomatic complexity "
            f"{int(max_complexity)} (threshold: {T['max_complexity_critical']})"
        )
        level = "CRITICAL"

    if level == "CRITICAL":
        return level, reasons

    # ---- HIGH -----------------------------------------------------------
    if max_complexity >= T['max_complexity_high']:
        reasons.append(
            f"A function has cyclomatic complexity {int(max_complexity)} "
            f"(threshold: {T['max_complexity_high']})"
        )
        level = "HIGH"

    if avg_complexity >= T['avg_complexity_high']:
        reasons.append(
            f"Average complexity across file is {avg_complexity:.1f} "
            f"(threshold: {T['avg_complexity_high']:.1f})"
        )
        level = "HIGH"

    if coupling_score >= T['coupling_high']:
        reasons.append(
            f"Imports from {coupling_score} unique internal modules "
            f"(threshold: {T['coupling_high']})"
        )
        level = "HIGH"

    if (function_count >= T['min_functions_for_undoc_check']
            and undocumented_ratio >= T['undocumented_ratio_high']):
        reasons.append(
            f"{undocumented_ratio:.0%} of {function_count} functions have no docstring"
        )
        level = "HIGH"

    if line_count >= T['line_count_high']:
        reasons.append(f"File is {line_count} lines (threshold: {T['line_count_high']})")
        level = "HIGH"

    if level == "HIGH":
        return level, reasons

    # ---- MEDIUM ---------------------------------------------------------
    if avg_complexity >= T['avg_complexity_medium']:
        reasons.append(
            f"Average complexity across file is {avg_complexity:.1f} "
            f"(threshold: {T['avg_complexity_medium']:.1f})"
        )
        level = "MEDIUM"

    if coupling_score >= T['coupling_medium']:
        reasons.append(
            f"Imports from {coupling_score} unique internal modules "
            f"(threshold: {T['coupling_medium']})"
        )
        level = "MEDIUM"

    if (function_count >= T['min_functions_for_undoc_check']
            and undocumented_ratio >= T['undocumented_ratio_medium']):
        reasons.append(
            f"{undocumented_ratio:.0%} of {function_count} functions have no docstring"
        )
        level = "MEDIUM"

    if line_count >= T['line_count_medium']:
        reasons.append(f"File is {line_count} lines (threshold: {T['line_count_medium']})")
        level = "MEDIUM"

    return level, reasons


def _trunc(s: str, n: int = 40) -> str:
    """Truncate long string for display in reason messages."""
    return s if len(s) <= n else s[:n] + "..."


def _print_summary(state: ArchaeonState, scored: int, skipped: int) -> None:
    scores = list(state.complexity_scores.values())

    risk_dist = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for s in scores:
        risk_dist[s.risk_level] = risk_dist.get(s.risk_level, 0) + 1

    complexities = [s.avg_complexity for s in scores if s.avg_complexity > 0]
    repo_avg = round(sum(complexities) / len(complexities), 2) if complexities else 0.0

    print(f"\n[Agent 4: Complexity Scorer] Done")
    print(f"  Files scored       : {scored}")
    print(f"  Files skipped      : {skipped}")
    print(f"  Repo avg complexity: {repo_avg}")
    print(f"\n  Risk distribution:")
    for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        bar = "█" * min(risk_dist[level], 30)
        print(f"    {level:<8} {bar} {risk_dist[level]}")

    critical = [s for s in scores if s.risk_level == "CRITICAL"]
    if critical:
        print(f"\n  CRITICAL files:")
        for s in critical[:6]:
            name = PurePosixPath(s.file_path).name
            print(f"    {name}")
            for reason in s.risk_reasons[:2]:
                print(f"      → {reason}")

    # Top 5 most complex functions across the whole repo
    all_fn: list = []
    for s in scores:
        for fn_name, complexity in s.function_scores.items():
            all_fn.append((s.file_path, fn_name, complexity))

    if all_fn:
        top = sorted(all_fn, key=lambda x: -x[2])[:5]
        print(f"\n  Most complex functions:")
        for file_path, fn_name, complexity in top:
            fname = PurePosixPath(file_path).name
            print(f"    {complexity:>3}  {fn_name:<35} ({fname})")