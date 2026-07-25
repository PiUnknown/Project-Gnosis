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
"""
from src.state import ArchaeonState
from src.parsers.base import SymbolTable
from src.utils.tree_sitter_utils import get_parser
from src.parsers.python_parser import extract_symbols as extract_python
from src.parsers.js_parser import extract_symbols as extract_js

# Languages we attempt to parse in Phase 2
PARSEABLE = {"Python", "JavaScript", "TypeScript"}


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

        # Skip if we have no content (fetch may have failed or been binary)
        if path not in state.raw_contents:
            skipped_count += 1
            continue

        # Skip unsupported languages (YAML, Markdown, etc.)
        if lang not in PARSEABLE:
            skipped_count += 1
            continue

        parser = get_parser(lang)
        if not parser:
            skipped_count += 1
            continue

        source = state.raw_contents[path]
        source_bytes = bytes(source, 'utf-8')

        # Parse the source into an AST
        tree = parser.parse(source_bytes)
        has_error = tree.root_node.has_error

        # Extract symbols using the language-appropriate extractor
        try:
            if lang == 'Python':
                docstring, functions, classes, imports = extract_python(tree, source_bytes)
            elif lang in ('JavaScript', 'TypeScript'):
                docstring, functions, classes, imports = extract_js(tree, source_bytes, lang)
            else:
                skipped_count += 1
                continue

        except Exception as exc:
            # Extraction itself failed (not a parse error, but our code failing)
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

    print()

    # Second pass: resolve is_internal on all imports
    # WHY SECOND PASS: during parsing we only have the current file's imports.
    # We need the complete file_paths set (all files in the manifest) to
    # check if an import like "src.utils.github_api" resolves to a real file.
    # That set is only complete after all files are in the symbol table.
    _resolve_internal_imports(state, file_paths)

    _print_summary(state, parsed_count, skipped_count, error_count)
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


def _is_internal_python(module: str, file_paths: set) -> bool:
    """
    Check if a Python import module string resolves to a file in our manifest.

    Relative imports (starting with '.') are always internal.
    For absolute imports, we try two path patterns:
      "src.utils.github_api"  →  "src/utils/github_api.py"
      "src.utils"             →  "src/utils/__init__.py"
    """
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
    """
    JS/TS imports starting with './' or '../' are relative = internal.
    Bare specifiers like 'react', 'lodash' are external packages.
    """
    return module.startswith('./') or module.startswith('../')


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------

def _print_summary(state: ArchaeonState, parsed: int, skipped: int, errors: int) -> None:
    total_functions = sum(len(st.functions) for st in state.symbol_tables.values())
    total_classes = sum(len(st.classes) for st in state.symbol_tables.values())
    total_internal = sum(len(st.internal_imports) for st in state.symbol_tables.values())
    total_undocumented = sum(len(st.undocumented_functions) for st in state.symbol_tables.values())
    error_files = [p for p, st in state.symbol_tables.items() if st.parse_error]

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