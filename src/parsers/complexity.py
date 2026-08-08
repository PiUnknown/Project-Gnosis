"""
src/parsers/complexity.py

Cyclomatic complexity computation for Python, JavaScript, and TypeScript.

Python:       radon library  (cc_visit)
JS / TS:      custom tree-sitter branch counter

WHY NOT WRITE A CUSTOM PYTHON BRANCH COUNTER:
radon is the industry standard for Python complexity metrics. It correctly
handles generators, comprehensions, walrus operators (:=), match/case
(Python 3.10+), nested functions, and decorators. Writing a correct
branch counter for Python from scratch would duplicate years of radon
development and introduce subtle bugs in edge cases. Use the best tool
that exists. Writing your own is not cleverness, it is maintenance debt.

CYCLOMATIC COMPLEXITY DEFINITION (McCabe 1976):
  M = 1 + (number of decision points in the function)

  Decision points in Python (radon handles):
    if, elif, for, while, try, except, with, and, or, :=

  Decision points in JS/TS (we count):
    if, for, for-in, for-of, while, do-while, catch,
    ternary (?:), switch_case, &&, ||, ??

  Interpretation:
    1-5    Simple. Easy to test. Low risk.
    6-10   Moderate. Requires careful testing.
    11-20  Complex. Refactoring recommended.
    21+    Very high risk. Refactor before touching.
"""

# -----------------------------------------------------------------------
# JS / TS branch node type definitions
# -----------------------------------------------------------------------

# tree-sitter node types that create a new execution path in JS/TS.
# Each adds 1 to cyclomatic complexity.
_JS_BRANCH_TYPES = frozenset({
    'if_statement',
    'for_statement',
    'for_in_statement',
    'for_of_statement',
    'while_statement',
    'do_statement',
    'catch_clause',
    'ternary_expression',
    'switch_case',        # each `case X:` adds a path; `switch` itself does not
})

# Short-circuit logical operators. Each creates an alternative execution path.
# They appear as anonymous token children inside binary_expression or
# logical_expression nodes — not as named nodes themselves.
_JS_LOGICAL_OPS = frozenset({'&&', '||', '??'})


# -----------------------------------------------------------------------
# Python: radon
# -----------------------------------------------------------------------

def compute_python_complexity(source: str) -> dict:
    """
    Compute cyclomatic complexity per function and method using radon.

    Returns: {name: complexity_int}

    Naming:
      Top-level def foo()       → key "foo"
      Class Bar, method foo()   → key "Bar.foo"

    Dot-notation for methods prevents two classes with identically named
    methods (e.g., both have .process()) from overwriting each other in
    the result dict.

    Returns empty dict on any failure (missing radon, syntax error, etc.).
    Callers must handle empty dict: treat as zero functions scored.

    WHY WE SKIP BLOCKS WHERE block.letter == 'C':
    radon's cc_visit returns three block types:
      'F' — top-level function
      'M' — class method
      'C' — class itself

    A class block's complexity score counts the class body as a whole
    (including its methods), which double-counts complexity already
    captured in the 'M' blocks. Including 'C' blocks inflates
    max_complexity and produces incorrect results. We keep only
    function ('F') and method ('M') blocks.
    """
    try:
        from radon.complexity import cc_visit
        blocks = cc_visit(source)
    except ImportError:
        return {}
    except Exception:
        # SyntaxError or other parse failure.
        # Phase 2 already flagged this as parse_error=True.
        # We return empty here instead of crashing the whole pipeline.
        return {}

    result = {}
    for block in blocks:
        # FIX: skip class-level blocks (letter == 'C').
        # radon returns 'F' (function), 'M' (method), and 'C' (class).
        # Class blocks aggregate their methods' complexity and must be
        # excluded — only score individual functions and methods.
        if block.letter == 'C':
            continue

        classname = getattr(block, 'classname', None)
        key = f"{classname}.{block.name}" if classname else block.name
        # If same name appears twice (overloads or nested), keep the highest
        result[key] = max(result.get(key, 0), block.complexity)

    return result


# -----------------------------------------------------------------------
# JS / TS: custom tree-sitter branch counter
# -----------------------------------------------------------------------

def compute_js_complexity(source: str, language: str, symbol_table, grammar_key: str = None) -> dict:
    """
    Compute cyclomatic complexity per function in a JS/TS file.

    Strategy:
    1. Re-parse source with tree-sitter (fast — C parser, ~1M lines/sec)
    2. Build a {line_number: function_name} map from the Phase 2 symbol table
    3. Walk the AST: when a function node is found at a known line, count
       all branch nodes in its subtree
    4. Store complexity = 1 + branch_count

    WHY RE-PARSE INSTEAD OF SAVING TREES IN STATE:
    Storing 300 tree-sitter trees in state costs significant RAM: each tree
    holds parsed node structures and references to source bytes. Re-parsing
    is fast enough that the memory saving outweighs the re-parsing cost.
    At 300 files × 100KB each = 30MB of source. Re-parsing all of it takes
    ~1 second. Storing parsed trees would cost 5-10x that in memory.
    The tradeoff is clear at this scale.

    Returns: {function_name: complexity_int}
    Empty dict on any failure.
    """
    try:
        from src.utils.tree_sitter_utils import get_parser
    except ImportError:
        return {}

    if not source:
        return {}

    parser = get_parser(grammar_key or language)
    if parser is None:
        return {}

    try:
        source_bytes = bytes(source, 'utf-8')
        tree = parser.parse(source_bytes)
    except Exception:
        return {}

    # Build line → name lookup from Phase 2 symbol table.
    # FunctionInfo.line_start is 1-indexed (set by all Phase 2 parsers).
    # tree-sitter node.start_point[0] is 0-indexed; we add 1 when comparing.
    line_to_name: dict = {}
    for func in symbol_table.functions:
        line_to_name[func.line_start] = func.name

    result: dict = {}
    _walk_and_score(tree.root_node, line_to_name, result)
    return result


def _walk_and_score(node, line_to_name: dict, result: dict) -> None:
    """
    Walk the AST recursively. When a function node is encountered:
    1. Compute its 1-indexed start line
    2. Look up its name in line_to_name (from symbol table)
    3. Count all branch nodes in its entire subtree
    4. Store complexity = 1 + branch_count in result

    Continues walking into nested functions — they get scored separately
    when their own node is encountered during the walk.
    """
    ntype = node.type

    # Case 1: named function or method
    is_named_func = ntype in ('function_declaration', 'method_definition')

    # Case 2: arrow function assigned to a variable
    # AST: variable_declarator { name: identifier, value: arrow_function }
    value_node = None
    is_arrow = False
    if ntype == 'variable_declarator':
        value_node = node.child_by_field_name('value')
        is_arrow = (value_node is not None and value_node.type == 'arrow_function')

    if is_named_func or is_arrow:
        line = node.start_point[0] + 1
        func_name = line_to_name.get(line)

        if func_name:
            # Count branches in the whole function subtree (including nested functions)
            target_node = value_node if is_arrow else node
            branch_count = _count_branches(target_node)
            complexity = 1 + branch_count
            result[func_name] = max(result.get(func_name, 0), complexity)

    # Always walk children — handles nested functions, export-wrapped functions,
    # class bodies, and any other containers
    for child in node.children:
        _walk_and_score(child, line_to_name, result)


def _count_branches(node) -> int:
    """
    Recursively count branch-inducing nodes in a subtree.

    Two types:
    1. Named node types: if, for, while, catch, ternary, switch_case
    2. Logical operators (&&, ||, ??) — anonymous tokens inside
       binary_expression or logical_expression nodes

    Counts inside nested functions too.
    This matches radon's behavior: a nested function's branches count
    toward the outer function's complexity. Both functions get scored
    separately when the outer function's walk reaches the inner one.
    """
    count = 0

    if node.type in _JS_BRANCH_TYPES:
        count += 1

    # Logical operators appear as anonymous token children of
    # binary_expression or logical_expression nodes
    if node.type in ('binary_expression', 'logical_expression'):
        for child in node.children:
            if child.type in _JS_LOGICAL_OPS:
                count += 1

    for child in node.children:
        count += _count_branches(child)

    return count


# -----------------------------------------------------------------------
# Generic Cyclomatic Complexity Walker
# -----------------------------------------------------------------------

_GENERIC_BRANCH_TYPES = {
    'Go': frozenset({'if_statement', 'for_statement', 'expression_case', 'select_statement'}),
    'Rust': frozenset({'if_expression', 'if_let_expression', 'while_expression', 'while_let_expression', 'for_expression', 'loop_expression', 'match_arm'}),
    'Java': frozenset({'if_statement', 'for_statement', 'enhanced_for_statement', 'while_statement', 'do_statement', 'catch_clause', 'ternary_expression', 'switch_label'}),
    'C': frozenset({'if_statement', 'for_statement', 'while_statement', 'do_statement', 'case_statement', 'conditional_expression'}),
    'C++': frozenset({'if_statement', 'for_statement', 'while_statement', 'do_statement', 'case_statement', 'conditional_expression', 'catch_clause'}),
}

# Header mapping to base language branch rules
_GENERIC_BRANCH_TYPES['C/C++ Header'] = _GENERIC_BRANCH_TYPES['C']
_GENERIC_BRANCH_TYPES['C++ Header'] = _GENERIC_BRANCH_TYPES['C++']

_GENERIC_FUNC_TYPES = {
    'Go': frozenset({'function_declaration', 'method_declaration'}),
    'Rust': frozenset({'function_item'}),
    'Java': frozenset({'method_declaration', 'constructor_declaration'}),
    'C': frozenset({'function_definition'}),
    'C++': frozenset({'function_definition'}),
}
_GENERIC_FUNC_TYPES['C/C++ Header'] = _GENERIC_FUNC_TYPES['C']
_GENERIC_FUNC_TYPES['C++ Header'] = _GENERIC_FUNC_TYPES['C++']

_GENERIC_LOGICAL_OPS = frozenset({'&&', '||'})


def compute_generic_complexity(source: str, language: str, symbol_table) -> dict:
    """
    Compute cyclomatic complexity per function in Go, Rust, Java, C, and C++ files.
    """
    try:
        from src.utils.tree_sitter_utils import get_parser
    except ImportError:
        return {}

    if not source:
        return {}

    # Grammar key routing (Headers map to C or C++)
    grammar_key = language
    if language == 'C/C++ Header':
        grammar_key = 'C'
    elif language == 'C++ Header':
        grammar_key = 'C++'

    parser = get_parser(grammar_key)
    if parser is None:
        return {}

    try:
        source_bytes = bytes(source, 'utf-8')
        tree = parser.parse(source_bytes)
    except Exception:
        return {}

    # Build line → name lookup from symbol table
    line_to_name: dict = {}
    for func in symbol_table.functions:
        line_to_name[func.line_start] = func.name

    result: dict = {}
    branch_types = _GENERIC_BRANCH_TYPES.get(language, frozenset())
    func_types = _GENERIC_FUNC_TYPES.get(language, frozenset())

    def _walk(node):
        if node.type in func_types:
            line = node.start_point[0] + 1
            func_name = line_to_name.get(line)
            if func_name:
                branch_count = _count_generic_branches(node, branch_types)
                complexity = 1 + branch_count
                result[func_name] = max(result.get(func_name, 0), complexity)

        for child in node.children:
            _walk(child)

    _walk(tree.root_node)
    return result


def _count_generic_branches(node, branch_types) -> int:
    count = 0
    if node.type in branch_types:
        count += 1

    if node.type == 'binary_expression':
        for child in node.children:
            if child.type in _GENERIC_LOGICAL_OPS:
                count += 1

    for child in node.children:
        count += _count_generic_branches(child, branch_types)

    return count