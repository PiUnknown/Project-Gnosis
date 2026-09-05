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
# -----------------------------------------------------------------------
# Internal import resolution
# -----------------------------------------------------------------------

def _extract_go_modules(state: ArchaeonState) -> list:
    modules = []
    for path, content in state.raw_contents.items():
        if path == "go.mod" or path.endswith("/go.mod"):
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("module "):
                    mod_name = line[len("module "):].strip().strip('"\'')
                    if mod_name:
                        prefix = path[:-6] if path.endswith("/go.mod") else ""
                        modules.append((mod_name, prefix))
    return modules


def _extract_rust_crates(state: ArchaeonState) -> list:
    crates = []
    for path, content in state.raw_contents.items():
        if path == "Cargo.toml" or path.endswith("/Cargo.toml"):
            in_package = False
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("[package]"):
                    in_package = True
                    continue
                elif line.startswith("["):
                    in_package = False
                if in_package and line.startswith("name"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        crate_name = parts[1].strip().strip('"\'')
                        if crate_name:
                            crates.append(crate_name)
    return crates


def _resolve_internal_imports(state: ArchaeonState, file_paths: set) -> None:
    go_modules = _extract_go_modules(state)
    rust_crates = _extract_rust_crates(state)

    for file_path, symbol_table in state.symbol_tables.items():
        lang = symbol_table.language
        for imp in symbol_table.imports:
            if lang == 'Python':
                imp.is_internal = _is_internal_python(imp.module, file_paths)
            elif lang in ('JavaScript', 'TypeScript'):
                imp.is_internal = _is_internal_js(imp.module, file_paths)
            elif lang == 'Go':
                imp.is_internal = _is_internal_go(imp.module, file_paths, go_modules)
            elif lang == 'Rust':
                imp.is_internal = _is_internal_rust(imp.module, file_paths, rust_crates)
            elif lang == 'Java':
                imp.is_internal = _is_internal_java(imp.module, file_paths)
            elif lang in ('C', 'C++', 'C/C++ Header', 'C++ Header'):
                imp.is_internal = _is_internal_c(imp.module, file_paths)


def _is_internal_python(module: str, file_paths: set) -> bool:
    if not module:
        return False
    if module.startswith('.'):
        return True
    base = module.replace('.', '/')
    for prefix in ('', 'src/', 'app/'):
        if (prefix + base + '.py') in file_paths or (prefix + base + '/__init__.py') in file_paths:
            return True
    return False


def _is_internal_js(module: str, file_paths: set = None) -> bool:
    if not module:
        return False
    if module.startswith('./') or module.startswith('../'):
        return True
    
    if not file_paths:
        return False

    cleaned = module
    if module.startswith('@/') or module.startswith('~/') or module.startswith('#/'):
        cleaned = module[2:]
    elif module.startswith('@src/'):
        cleaned = module[5:]

    candidates = [
        cleaned,
        f"src/{cleaned}",
        f"app/{cleaned}",
        f"lib/{cleaned}",
        f"frontend/src/{cleaned}",
        f"frontend/{cleaned}"
    ]
    _exts = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '']
    _indices = ['/index.ts', '/index.tsx', '/index.js', '/index.jsx']

    for cand in candidates:
        for ext in _exts:
            if (cand + ext) in file_paths:
                return True
        for idx in _indices:
            if (cand + idx) in file_paths:
                return True
    return False


def _is_internal_go(module: str, file_paths: set, go_modules: list = None) -> bool:
    if not module:
        return False
    module = module.strip('"\' ')
    if module.startswith('./') or module.startswith('../'):
        return True

    # Standard library has no dots in the first path component
    first_part = module.split('/')[0]
    if '.' not in first_part:
        return False

    # 1. Match against detected go.mod module declaration
    if go_modules:
        for mod_name, mod_prefix in go_modules:
            if module == mod_name:
                return True
            if module.startswith(mod_name + '/'):
                rel_pkg = module[len(mod_name) + 1:]
                target_dir = f"{mod_prefix}{rel_pkg}" if mod_prefix else rel_pkg
                if any((f.startswith(target_dir + '/') or f'/{target_dir}/' in f) and f.endswith('.go') for f in file_paths):
                    return True

    # 2. Heuristic suffix match: check if subpath matches any directory containing .go files
    parts = module.split('/')
    for i in range(1, len(parts)):
        subpath = '/'.join(parts[i:])
        if any((f.startswith(subpath + '/') or f'/{subpath}/' in f) and f.endswith('.go') for f in file_paths):
            return True

    return False


def _is_internal_rust(module: str, file_paths: set, rust_crates: list = None) -> bool:
    if not module:
        return False
    if module.startswith("crate::") or module.startswith("super::") or module.startswith("self::"):
        return True
    first = module.split('::')[0]
    if rust_crates and first in rust_crates:
        return True
    return any(f.startswith(f"{first}/") or f.startswith(f"crates/{first}/") for f in file_paths)


def _is_internal_java(module: str, file_paths: set) -> bool:
    if not module:
        return False
    # Exclude common external frameworks
    if module.startswith(("java.", "javax.", "android.", "androidx.", "org.springframework.", "org.junit.", "org.slf4j.")):
        return False

    path_suffix = module.replace('.', '/')
    if path_suffix.endswith('/*'):
        path_suffix = path_suffix[:-2]

    for f in file_paths:
        if f.endswith('.java') or f.endswith('.kt') or f.endswith('.scala'):
            if f.startswith(path_suffix + '/') or f'/{path_suffix}/' in f or f.endswith(f"{path_suffix}.java") or f.endswith(f"{path_suffix}.kt") or f'/{path_suffix}.' in f or f == f"{path_suffix}.java":
                return True
    return False


def _is_internal_c(module: str, file_paths: set) -> bool:
    if not module:
        return False
    clean = module.strip('"<> ')
    header_name = clean.split('/')[-1]
    return any(f.endswith('/' + header_name) or f == header_name for f in file_paths)


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
                print(f"      -> {detail}")
        if len(error_files) > 5:
            print(f"    ...and {len(error_files) - 5} more")