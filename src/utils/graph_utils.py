"""
Graph utilities: import resolution and dependency graph visualization.

Import resolution is the core challenge of Phase 3.
Phase 2 told us IS an import internal (boolean).
Phase 3 needs to know WHICH file it points to (path string).
These are different operations. Resolution lives here as pure functions
so they can be tested without touching state or the graph.

Two resolution strategies:

PYTHON:
  Absolute:  "src.utils.github_api"  →  "src/utils/github_api.py"
  Package:   "src.utils"             →  "src/utils/__init__.py"
  Relative:  ".utils" from "src/agents/x.py"  →  "src/agents/utils.py"
             Falls back to "src/utils/__init__.py" if not found in same dir.
  Bare rel:  "." + names=["utils"]  from "src/agents/x.py"  →  "src/agents/utils.py"

JAVASCRIPT / TYPESCRIPT:
  Relative:  "./utils" from "src/components/Button.tsx"
             → try src/components/utils.ts, .tsx, .js, .jsx
             → try src/components/utils/index.ts, .tsx, .js, .jsx
  Extension already present: "./utils.js" → direct match
  Parent dir: "../state" from "src/utils/helpers.ts" → "src/state.ts"
             NOTE: PurePosixPath does NOT normalize ".." — we do it manually.
"""

from pathlib import PurePosixPath
from typing import Optional

# JavaScript/TypeScript extensions to probe when no extension is given
_JS_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs']
_JS_INDEX_FILES = ['index.ts', 'index.tsx', 'index.js', 'index.jsx']


# -----------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------

def resolve_import_to_paths(
    importer_path: str,
    import_info,
    language: str,
    file_paths: set
) -> list:
    """
    Resolve an ImportInfo object to a list of actual file paths in the manifest.

    Returns a list because a bare relative Python import
    ("from . import utils, models") can resolve to multiple files.

    Returns empty list if resolution fails or if the import is external.
    The caller must check import_info.is_internal before calling this,
    or pass only internal imports.
    """
    if not import_info.is_internal:
        return []

    if language == 'Python':
        return _resolve_python(importer_path, import_info, file_paths)

    if language in ('JavaScript', 'TypeScript'):
        return _resolve_js(importer_path, import_info.module, file_paths)

    return []


# -----------------------------------------------------------------------
# Python resolution
# -----------------------------------------------------------------------

def _resolve_python(importer_path: str, import_info, file_paths: set) -> list:
    module = import_info.module
    names = import_info.names

    if not module.startswith('.'):
        return _resolve_python_absolute(module, file_paths)

    return _resolve_python_relative(importer_path, module, names, file_paths)


def _resolve_python_absolute(module: str, file_paths: set) -> list:
    """
    Resolve "src.utils.github_api" to "src/utils/github_api.py"
    or "src/utils/github_api/__init__.py".

    Handles comma-separated bare imports ("import os, sys") by trying
    each segment. These will almost always be external (os, sys are stdlib),
    but we try anyway since is_internal was already checked by Phase 2.
    """
    # Handle "import os, sys" which we stored as module="os, sys"
    segments = [s.strip() for s in module.split(',')]
    resolved = []
    for seg in segments:
        base = seg.replace('.', '/')
        result = _try_python_path_variants(base, file_paths)
        resolved.extend(result)
    return resolved


def _resolve_python_relative(
    importer_path: str,
    module: str,
    names: list,
    file_paths: set
) -> list:
    """
    Resolve a relative Python import.

    Dot counting:
      '.'   → dots=1 → same package (importer's directory)
      '..'  → dots=2 → parent package
      '...' → dots=3 → grandparent package

    Algorithm:
      Start at importer's directory.
      Go up (dots - 1) levels.
      Append remainder (module after the dots).
      If remainder is empty, try each name from import_info.names
      as a potential submodule.

    Fallback for remainder imports:
      If "from .state import X" doesn't resolve in the computed directory
      (e.g. src/agents/state.py doesn't exist), try one level higher
      (e.g. src/state.py). This handles namespace packages and projects
      where the top-level package boundary doesn't match the file structure.
    """
    dots = len(module) - len(module.lstrip('.'))
    remainder = module[dots:]

    # Navigate up the package hierarchy
    base = PurePosixPath(importer_path).parent
    for _ in range(dots - 1):
        base = base.parent

    if remainder:
        # "from .utils import X" → resolve .utils, not X
        # X is a symbol inside utils, not a file
        target = str(base / remainder.replace('.', '/'))
        result = _try_python_path_variants(target, file_paths)
        if result:
            return result

        # FIX: fallback — if the module isn't found in the computed
        # directory, try one level up. This handles cases where
        # namespace packages or non-standard layouts mean the file
        # lives in the parent directory rather than the sibling dir.
        # Example: ".state" from "src/agents/ingestion.py" may resolve
        # to "src/state.py" when "src/agents/state.py" doesn't exist.
        parent_target = str(base.parent / remainder.replace('.', '/'))
        return _try_python_path_variants(parent_target, file_paths)

    else:
        # "from . import utils, models"
        # Here each name in names might be a submodule (a file)
        resolved = []
        for name in names:
            if name == '*':
                continue
            target = str(base / name)
            candidates = _try_python_path_variants(target, file_paths)
            resolved.extend(candidates)
        return resolved


def _try_python_path_variants(base_path: str, file_paths: set) -> list:
    """
    Given a base path like "src/utils/github_api", try:
      1. src/utils/github_api.py
      2. src/utils/github_api/__init__.py

    Returns a list with at most one match (the first one found).
    """
    # Normalize separators
    base_path = base_path.replace('\\', '/')

    candidates = [
        base_path + '.py',
        base_path + '/__init__.py',
    ]
    for candidate in candidates:
        if candidate in file_paths:
            return [candidate]
    return []


# -----------------------------------------------------------------------
# JavaScript / TypeScript resolution
# -----------------------------------------------------------------------

def _normalize_posix_path(path: str) -> str:
    """
    Resolve '..' and '.' components in a POSIX path string without
    accessing the filesystem.

    WHY THIS EXISTS:
    PurePosixPath does NOT normalize '..' components.
    str(PurePosixPath('src/utils') / '../state') returns
    'src/utils/../state' — the '..' is kept verbatim. That string
    never matches 'src/state.ts' in a file_paths set lookup.
    This function manually collapses the path segments so that
    '../state' from 'src/utils/' correctly becomes 'src/state'.
    """
    parts = []
    for part in path.replace('\\', '/').split('/'):
        if part == '..':
            if parts:
                parts.pop()
        elif part and part != '.':
            parts.append(part)
    return '/'.join(parts)


def _resolve_js(importer_path: str, module: str, file_paths: set) -> list:
    """
    Resolve a JS/TS relative import module string to a file path.

    Only handles relative imports (./  or  ../).
    Bare specifiers (react, lodash) are external and should not reach here
    because import_info.is_internal would be False for them.

    JS imports often have no extension:
      "./utils"  →  could be  utils.ts, utils.tsx, utils.js, utils/index.ts, ...
    We probe each candidate in order and return the first match.
    """
    if not (module.startswith('./') or module.startswith('../')):
        return []

    importer_dir = PurePosixPath(importer_path).parent
    raw_target = str(importer_dir / module).replace('\\', '/')

    # FIX: PurePosixPath does NOT normalize '..' components — normalize manually.
    # e.g. 'src/utils/../state' → 'src/state'
    # Without this, file_paths lookups against normalized paths always fail.
    raw_target = _normalize_posix_path(raw_target)

    # Case 1: Import already has an extension ("./utils.js")
    if raw_target in file_paths:
        return [raw_target]

    # Case 2: No extension → probe all JS/TS extensions
    for ext in _JS_EXTENSIONS:
        candidate = raw_target + ext
        if candidate in file_paths:
            return [candidate]

    # Case 3: Directory import → probe index files
    for index_file in _JS_INDEX_FILES:
        candidate = raw_target + '/' + index_file
        if candidate in file_paths:
            return [candidate]

    return []


# -----------------------------------------------------------------------
# Visualization
# -----------------------------------------------------------------------

def generate_graph_html(
    graph,
    graph_stats: dict,
    circular_nodes: set,
    output_path: str
) -> bool:
    """
    Render the dependency graph as a standalone interactive HTML file
    using pyvis with D3.js physics.

    Node size: proportional to in-degree (bigger = more imported = more critical)
    Node color:
      #e74c3c  red    — in a circular dependency
      #e67e22  orange — in_degree >= 6  (critical hub)
      #f1c40f  yellow — in_degree 3-5   (frequently used)
      #27ae60  green  — in_degree 1-2   (used but not critical)
      #2980b9  blue   — in_degree 0     (isolated file)

    Returns True on success, False if pyvis is not installed.
    """
    try:
        from pyvis.network import Network
    except ImportError:
        print("  [WARNING] pyvis not installed. Skipping graph HTML generation.")
        print("            Run: pip install pyvis")
        return False

    net = Network(
        height="820px",
        width="100%",
        directed=True,
        notebook=False,
        bgcolor="#0f0f1a",
        font_color="#ecf0f1"
    )

    # Physics: ForceAtlas2 gives good separation for code graphs
    net.set_options("""
    var options = {
      "physics": {
        "enabled": true,
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.005,
          "springLength": 120,
          "springConstant": 0.08,
          "damping": 0.6
        },
        "solver": "forceAtlas2Based",
        "stabilization": { "iterations": 200, "updateInterval": 25 }
      },
      "edges": {
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.6 } },
        "color": { "color": "rgba(255,255,255,0.2)", "highlight": "#ffffff" },
        "smooth": { "type": "continuous" },
        "width": 1
      },
      "nodes": {
        "font": { "size": 11, "face": "monospace" },
        "borderWidth": 1.5,
        "shadow": { "enabled": true }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 150,
        "navigationButtons": true,
        "keyboard": true
      }
    }
    """)

    # Add nodes
    for node, stats in graph_stats.items():
        in_deg = stats['in_degree']
        label = PurePosixPath(node).name   # filename only, not full path

        # Color by risk tier
        if node in circular_nodes:
            color = "#e74c3c"
            border = "#c0392b"
        elif in_deg >= 6:
            color = "#e67e22"
            border = "#ca6f1e"
        elif in_deg >= 3:
            color = "#f1c40f"
            border = "#d4ac0d"
        elif in_deg >= 1:
            color = "#27ae60"
            border = "#1e8449"
        else:
            color = "#2980b9"
            border = "#1f618d"

        # Size: 12 to 45, scaled by in_degree
        size = min(45, 12 + in_deg * 4)

        tooltip = (
            f"<b>{node}</b><br>"
            f"In-degree: {in_deg} (imported by {in_deg} files)<br>"
            f"Out-degree: {stats['out_degree']} (imports {stats['out_degree']} files)<br>"
            f"PageRank: {stats['pagerank']:.4f}<br>"
            f"Circular dep: {'YES ⚠️' if stats['is_in_circular_dep'] else 'No'}"
        )

        net.add_node(
            node,
            label=label,
            title=tooltip,
            color={"background": color, "border": border, "highlight": {"background": "#ffffff"}},
            size=size
        )

    # Add edges
    for src, dst in graph.edges():
        net.add_edge(src, dst, arrows="to")

    # Save
    try:
        net.write_html(output_path)
    except AttributeError:
        # Older pyvis uses save_graph
        net.save_graph(output_path)

    return True