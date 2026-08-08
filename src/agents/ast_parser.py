"""
Agent 2: AST Parser Agent

Reads from state:  file_manifest, raw_contents
Writes to state:   symbol_tables

Pipeline:
1. For each file with raw content, get the appropriate tree-sitter parser
2. Parse source → AST
3. Check for parse errors (has_error on root node)
4. Extract symbols using language-specific parser module
5. Build SymbolTable and store in state.symbol_tables[file_path]
6. SECOND PASS: resolve which imports are internal

GRAMMAR SELECTION:
  .ts  files → "TypeScript" → language_typescript()
  .tsx files → "TSX"        → language_tsx()     ← JSX-aware superset
  .js  files → "JavaScript" → language_javascript() (includes JSX natively)
  .jsx files → "JavaScript" → language_javascript() (includes JSX natively)
  .py  files → "Python"     → language_python()

WHY TSX IS SEPARATE:
  tree-sitter-typescript ships two grammars: language_typescript() and
  language_tsx(). The TypeScript grammar does not parse JSX — any
  <Component /> expression triggers a has_error on the root node, causing
  every function/class in the file to still be extracted but the file to
  be flagged as CRITICAL (parse error signal). The TSX grammar is a
  strict superset of TypeScript that adds JSX node types. All TypeScript
  node types (function_declaration, class_declaration, import_statement)
  are identical in both grammars, so extract_js() works unchanged for
  both. Only the grammar binary selected at parse time differs.
"""
from src.state import ArchaeonState
from src.parsers.base import SymbolTable
from src.utils.tree_sitter_utils import get_parser
from src.parsers.python_parser import extract_symbols as extract_python
from src.parsers.js_parser import extract_symbols as extract_js
from src.parsers.generic_parser import extract_symbols as extract_generic

# Languages we attempt to parse in Phase 2
PARSEABLE = {
    "Python", "JavaScript", "TypeScript",
    "Go", "Rust", "Java", "C", "C++",
    "C/C++ Header", "C++ Header"
}


def run(state: ArchaeonState) -> ArchaeonState:
    print(f"\n[Agent 2: AST Parser]")

    file_paths = {f.path for f in state.file_manifest}
    total = len(state.file_manifest)
    parsed_count = 0
    skipped_count = 0
    error_count = 0

    for i, file_meta in enumerate(state.file_manifest):
        print(f"\r  Parsing files: {i + 1}/{total}", end="", flush=True)

        path = file_meta.path
        lang = file_meta.language

        if path not in state.raw_contents:
            skipped_count += 1
            continue

        if lang not in PARSEABLE:
            skipped_count += 1
            continue

        parser = None
        source = None
        source_bytes = None
        tree = None
        try:
            # FIX: .tsx files need the TSX grammar (language_tsx), not the
            # TypeScript grammar (language_typescript). The TypeScript grammar
            # has no JSX support — any <Component /> triggers a parse error.
            # tree_sitter_utils already has a "TSX" case; we just need to
            # route .tsx files to it. Language label stays "TypeScript" for
            # all downstream agents (complexity scorer, doc generator, stats).
            grammar_key = "TSX" if path.endswith(".tsx") else lang

            parser = get_parser(grammar_key)
            if not parser:
                skipped_count += 1
                continue

            source = state.raw_contents[path]
            source_bytes = bytes(source, 'utf-8')

            tree = parser.parse(source_bytes)
            has_error = tree.root_node.has_error

            try:
                if lang == 'Python':
                    docstring, functions, classes, imports = extract_python(tree, source_bytes)
                elif lang in ('JavaScript', 'TypeScript'):
                    docstring, functions, classes, imports = extract_js(tree, source_bytes, lang)
                elif lang in ("Go", "Rust", "Java", "C", "C++", "C/C++ Header", "C++ Header"):
                    docstring, functions, classes, imports = extract_generic(tree, source_bytes, lang)
                else:
                    skipped_count += 1
                    continue
            except Exception as exc:
                state.symbol_tables[path] = SymbolTable(
                    file_path=path,
                    language=lang,
                    module_docstring=None,
                    parse_error=True,
                    parse_error_detail=f"Extraction error: {exc}"
                )
                error_count += 1
                continue

            state.symbol_tables[path] = SymbolTable(
                file_path=path,
                language=lang,
                module_docstring=docstring,
                functions=functions,
                classes=classes,
                imports=imports,
                parse_error=has_error,
                parse_error_detail="tree-sitter detected syntax errors" if has_error else None
            )
            parsed_count += 1
        finally:
            if parser is not None:
                del parser
            if source is not None:
                del source
            if source_bytes is not None:
                del source_bytes
            if tree is not None:
                del tree

    print()

    _resolve_internal_imports(state, file_paths)
    _print_summary(state, parsed_count, skipped_count, error_count)

    del file_paths
    import gc
    gc.collect()

    return state


# -----------------------------------------------------------------------
# Internal import resolution
# -----------------------------------------------------------------------

def _resolve_internal_imports(state: ArchaeonState, file_paths: set) -> None:
    for file_path, symbol_table in state.symbol_tables.items():
        lang = symbol_table.language
        for imp in symbol_table.imports:
            if lang == 'Python':
                imp.is_internal = _is_internal_python(imp.module, file_paths)
            elif lang in ('JavaScript', 'TypeScript'):
                imp.is_internal = _is_internal_js(imp.module)
            elif lang == 'Go':
                imp.is_internal = _is_internal_go(imp.module, file_paths)
            elif lang == 'Rust':
                imp.is_internal = _is_internal_rust(imp.module)
            elif lang == 'Java':
                imp.is_internal = _is_internal_java(imp.module, file_paths)
            elif lang in ('C', 'C++', 'C/C++ Header', 'C++ Header'):
                imp.is_internal = _is_internal_c(imp.module)


def _is_internal_python(module: str, file_paths: set) -> bool:
    if not module:
        return False
    if module.startswith('.'):
        return True
    as_file = module.replace('.', '/') + '.py'
    if as_file in file_paths:
        return True
    as_init = module.replace('.', '/') + '/__init__.py'
    return as_init in file_paths


def _is_internal_js(module: str) -> bool:
    return module.startswith('./') or module.startswith('../')


def _is_internal_go(module: str, file_paths: set) -> bool:
    if not module:
        return False
    # stdlib has no dots in first path component
    first_part = module.split('/')[0]
    if '.' not in first_part:
        return False
    # internal if path matches manifest files
    return any(module in f or f.startswith(module.split('/')[-1]) for f in file_paths)


def _is_internal_rust(module: str) -> bool:
    if not module:
        return False
    # internal if starts with "crate::", "super::", or "self::"
    return module.startswith("crate::") or module.startswith("super::") or module.startswith("self::")


def _is_internal_java(module: str, file_paths: set) -> bool:
    if not module:
        return False
    # internal if module path maps to a .java file in manifest
    path_prefix = module.replace('.', '/')
    return any(f.startswith(path_prefix) for f in file_paths)


def _is_internal_c(module: str) -> bool:
    if not module:
        return False
    # internal if module does NOT start with "<" (quoted includes are local)
    return not module.startswith("<")


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------

def _print_summary(state: ArchaeonState, parsed: int, skipped: int, errors: int) -> None:
    total_functions   = sum(len(st.functions)            for st in state.symbol_tables.values())
    total_classes     = sum(len(st.classes)              for st in state.symbol_tables.values())
    total_internal    = sum(len(st.internal_imports)     for st in state.symbol_tables.values())
    total_undocumented = sum(len(st.undocumented_functions) for st in state.symbol_tables.values())
    error_files       = [p for p, st in state.symbol_tables.items() if st.parse_error]

    print(f"\n[Agent 2: AST Parser] Done")
    print(f"  Files parsed       : {parsed}")
    print(f"  Files skipped      : {skipped}")
    print(f"  Parse errors       : {len(error_files)}")
    print(f"  Functions extracted: {total_functions}")
    print(f"  Classes extracted  : {total_classes}")
    print(f"  Internal imports   : {total_internal}")
    print(f"  Undocumented funcs : {total_undocumented}")

    if error_files:
        print(f"\n  [TECH DEBT] Files with parse errors (first 5):")
        for path in error_files[:5]:
            detail = state.symbol_tables[path].parse_error_detail
            print(f"    {path}")
            if detail:
                print(f"      → {detail}")
        if len(error_files) > 5:
            print(f"    ...and {len(error_files) - 5} more")