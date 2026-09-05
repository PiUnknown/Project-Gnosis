"""
Graph utilities: import resolution and dependency graph visualization.

Import resolution is the core challenge of Phase 3.
Phase 2 told us IS an import internal (boolean).
Phase 3 needs to know WHICH file it points to (path string).
These are different operations. Resolution lives here as pure functions
so they can be tested without touching state or the graph.

Two resolution strategies:

PYTHON:
  Absolute:  "src.utils.github_api"  ->  "src/utils/github_api.py"
  Package:   "src.utils"             ->  "src/utils/__init__.py"
  Relative:  ".utils" from "src/agents/x.py"  ->  "src/agents/utils.py"
  Bare rel:  "." + names=["utils"]  from "src/agents/x.py"  ->  "src/agents/utils.py"

JAVASCRIPT / TYPESCRIPT:
  Relative:  "./utils" from "src/components/Button.tsx"
             -> try src/components/utils.ts, .tsx, .js, .jsx
             -> try src/components/utils/index.ts, .tsx, .js, .jsx
  Extension already present: "./utils.js" -> direct match

TOOLTIP NOTE:
  pyvis passes node `title` to vis.js, which in newer versions (9.x+)
  sets it as textContent, not innerHTML. HTML tags like <b> and <br>
  render as raw text. We use plain-text tooltips with newline separators,
  then post-process the generated HTML to inject CSS that styles the
  .vis-tooltip div into a clean dark-theme card.
"""

from pathlib import PurePosixPath
from typing import Optional

_JS_EXTENSIONS = ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs']
_JS_INDEX_FILES = ['index.ts', 'index.tsx', 'index.js', 'index.jsx']


# -----------------------------------------------------------------------
# -----------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------

def resolve_import_to_paths(
    importer_path: str,
    import_info,
    language: str,
    file_paths: set
) -> list:
    if not import_info.is_internal:
        return []
    if language == 'Python':
        return _resolve_python(importer_path, import_info, file_paths)
    if language in ('JavaScript', 'TypeScript'):
        return _resolve_js(importer_path, import_info.module, file_paths)
    if language == 'Rust':
        return _resolve_rust(importer_path, import_info, file_paths)
    if language in ('C', 'C/C++ Header', 'C++'):
        return _resolve_c(importer_path, import_info, file_paths)
    if language == 'Go':
        return _resolve_go(importer_path, import_info, file_paths)
    if language == 'Java':
        return _resolve_java(importer_path, import_info, file_paths)
    return []


# -----------------------------------------------------------------------
# Python resolution
# -----------------------------------------------------------------------

def _resolve_python(importer_path: str, import_info, file_paths: set) -> list:
    module = import_info.module
    names  = import_info.names
    if not module.startswith('.'):
        return _resolve_python_absolute(module, file_paths)
    return _resolve_python_relative(importer_path, module, names, file_paths)


def _resolve_python_absolute(module: str, file_paths: set) -> list:
    segments = [s.strip() for s in module.split(',')]
    resolved = []
    for seg in segments:
        base = seg.replace('.', '/')
        # Check direct, src/, and app/ layouts
        for prefix in ('', 'src/', 'app/'):
            result = _try_python_path_variants(prefix + base, file_paths)
            if result:
                resolved.extend(result)
                break
    return resolved


def _resolve_python_relative(
    importer_path: str,
    module: str,
    names: list,
    file_paths: set
) -> list:
    dots      = len(module) - len(module.lstrip('.'))
    remainder = module[dots:]

    base = PurePosixPath(importer_path).parent
    for _ in range(dots - 1):
        base = base.parent

    if remainder:
        target = str(base / remainder.replace('.', '/'))
        result = _try_python_path_variants(target, file_paths)
        if result:
            return result
        parent_target = str(base.parent / remainder.replace('.', '/'))
        return _try_python_path_variants(parent_target, file_paths)
    else:
        resolved = []
        for name in names:
            if name == '*':
                continue
            target     = str(base / name)
            candidates = _try_python_path_variants(target, file_paths)
            resolved.extend(candidates)
        return resolved


def _try_python_path_variants(base_path: str, file_paths: set) -> list:
    base_path  = base_path.replace('\\', '/')
    candidates = [base_path + '.py', base_path + '/__init__.py']
    for candidate in candidates:
        if candidate in file_paths:
            return [candidate]
    return []


# -----------------------------------------------------------------------
# JavaScript / TypeScript resolution
# -----------------------------------------------------------------------

def _normalize_posix_path(path: str) -> str:
    """
    Resolve '..' and '.' components without filesystem access.
    PurePosixPath does NOT normalize '..' — str(PurePosixPath('a/b/../c'))
    returns 'a/b/../c' unchanged.
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
    importer_dir = PurePosixPath(importer_path).parent
    targets = []

    if module.startswith('./') or module.startswith('../'):
        raw_target = str(importer_dir / module).replace('\\', '/')
        targets.append(_normalize_posix_path(raw_target))
    else:
        # Handle path aliases (@/, ~/, #/, src/, etc.)
        cleaned = module
        if module.startswith('@/') or module.startswith('~/') or module.startswith('#/'):
            cleaned = module[2:]
        elif module.startswith('@src/'):
            cleaned = module[5:]

        targets.extend([
            cleaned,
            f"src/{cleaned}",
            f"app/{cleaned}",
            f"lib/{cleaned}",
            f"frontend/src/{cleaned}",
            f"frontend/{cleaned}"
        ])

    for raw_target in targets:
        raw_target = _normalize_posix_path(raw_target)
        if raw_target in file_paths:
            return [raw_target]
        for ext in _JS_EXTENSIONS:
            candidate = raw_target + ext
            if candidate in file_paths:
                return [candidate]
        for index_file in _JS_INDEX_FILES:
            candidate = raw_target + '/' + index_file
            if candidate in file_paths:
                return [candidate]
    return []


# -----------------------------------------------------------------------
# Rust resolution
# -----------------------------------------------------------------------

def _resolve_rust(importer_path: str, import_info, file_paths: set) -> list:
    module = import_info.module
    names = import_info.names
    importer = PurePosixPath(importer_path)

    # Determine crate source root (e.g. "crate_name/src" or directory containing Cargo.toml)
    parts = list(importer.parts)
    if 'src' in parts:
        src_idx = parts.index('src')
        crate_src = PurePosixPath(*parts[:src_idx + 1])
    else:
        crate_src = importer.parent

    # Parse Rust module path syntax (crate::, super::, self::, foo::bar)
    mod_path = module.replace('crate::', '').replace('super::', '../').replace('self::', './').replace('::', '/')

    candidates = []
    if module.startswith('crate::'):
        base = crate_src / mod_path
    elif module.startswith('super::') or module.startswith('self::'):
        base = importer.parent / mod_path
    else:
        base = crate_src / mod_path

    raw = _normalize_posix_path(str(base).replace('\\', '/'))
    candidates.extend([raw + '.rs', raw + '/mod.rs'])

    # Also check if imported symbol names correspond to submodule files
    for name in names:
        if name and name not in ('self', '*', '{', '}'):
            sub = raw + '/' + name
            candidates.extend([sub + '.rs', sub + '/mod.rs'])

    return [c for c in candidates if c in file_paths and c != importer_path]


# -----------------------------------------------------------------------
# C / C++ resolution
# -----------------------------------------------------------------------

def _resolve_c(importer_path: str, import_info, file_paths: set) -> list:
    module = import_info.module.strip('"<>\' ')
    importer_dir = PurePosixPath(importer_path).parent

    candidates = [
        _normalize_posix_path(str(importer_dir / module).replace('\\', '/')),
        module.replace('\\', '/')
    ]

    # Search for header in manifest if not directly relative
    if not any(c in file_paths for c in candidates):
        header_name = PurePosixPath(module).name
        for p in file_paths:
            if p.endswith('/' + header_name) or p == header_name:
                candidates.append(p)

    return [c for c in candidates if c in file_paths and c != importer_path]


# -----------------------------------------------------------------------
# Go resolution
# -----------------------------------------------------------------------

def _resolve_go(importer_path: str, import_info, file_paths: set) -> list:
    module = import_info.module.strip('"\' ')
    importer_dir = PurePosixPath(importer_path).parent

    # 1. Relative imports
    if module.startswith('./') or module.startswith('../'):
        raw = _normalize_posix_path(str(importer_dir / module).replace('\\', '/'))
        return [p for p in file_paths if (p.startswith(raw + '/') or p == raw + '.go') and p.endswith('.go')]

    # 2. Heuristic package subpath match
    # E.g. "github.com/levitateos/soda-os/internal/daemon" -> match files in "internal/daemon/"
    parts = module.split('/')
    for i in range(1, len(parts)):
        subpath = '/'.join(parts[i:])
        matched = [p for p in file_paths if (p.startswith(subpath + '/') or f'/{subpath}/' in p) and p.endswith('.go')]
        if matched:
            return matched

    # 3. Last segment package name fallback
    pkg_suffix = parts[-1]
    return [p for p in file_paths if f'/{pkg_suffix}/' in p and p.endswith('.go')]


# -----------------------------------------------------------------------
# Java resolution
# -----------------------------------------------------------------------

def _resolve_java(importer_path: str, import_info, file_paths: set) -> list:
    module = import_info.module.strip('; ')
    path_suffix = module.replace('.', '/')
    if path_suffix.endswith('/*'):
        pkg_dir = path_suffix[:-2]
        return [p for p in file_paths if (p.endswith('.java') or p.endswith('.kt')) and f'/{pkg_dir}/' in p]

    # Direct class file match
    target_java = f"{path_suffix}.java"
    target_kt = f"{path_suffix}.kt"
    return [p for p in file_paths if p.endswith(target_java) or p.endswith(target_kt) or f'/{path_suffix}.' in p]


# -----------------------------------------------------------------------
# Visualization
# -----------------------------------------------------------------------

# Injected into the pyvis HTML after generation to style .vis-tooltip.
# vis.js 9.x renders node `title` as textContent (not innerHTML), so
# HTML tags in title show as raw text. We use newline-delimited plain
# text and style the container div to look like a proper dark-theme card.
_TOOLTIP_CSS = """<style>
div.vis-tooltip {
    background-color : #13131f !important;
    border           : 1px solid #3d3d5c !important;
    border-radius    : 10px !important;
    padding          : 10px 15px !important;
    font-family      : 'Consolas', 'Cascadia Code', 'Monaco', monospace !important;
    font-size        : 12px !important;
    color            : #cdd6f4 !important;
    white-space      : pre !important;
    line-height      : 1.75 !important;
    box-shadow       : 0 6px 28px rgba(0, 0, 0, 0.75) !important;
    pointer-events   : none !important;
    max-width        : 360px !important;
    letter-spacing   : 0.01em !important;
}
</style>
"""


def generate_graph_html(
    graph,
    graph_stats: dict,
    circular_nodes: set,
    output_path: str
) -> bool:
    """
    Render the dependency graph as a standalone interactive HTML file.

    Node color tiers:
      red    #e74c3c — circular dependency
      orange #e67e22 — in_degree >= 6  (critical hub)
      yellow #f1c40f — in_degree 3-5
      green  #27ae60 — in_degree 1-2
      blue   #2980b9 — in_degree 0  (isolated)

    Returns True on success, False if pyvis is not installed.
    """
    try:
        from pyvis.network import Network
    except ImportError:
        print("  [WARNING] pyvis not installed. Run: pip install pyvis")
        return False

    net = Network(
        height="820px",
        width="100%",
        directed=True,
        notebook=False,
        bgcolor="#0f0f1a",
        font_color="#ecf0f1"
    )

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
        "tooltipDelay": 100,
        "navigationButtons": true,
        "keyboard": true
      }
    }
    """)

    for node, stats in graph_stats.items():
        in_deg  = stats['in_degree']
        out_deg = stats['out_degree']
        label   = PurePosixPath(node).name

        if node in circular_nodes:
            color, border = "#e74c3c", "#c0392b"
        elif in_deg >= 6:
            color, border = "#e67e22", "#ca6f1e"
        elif in_deg >= 3:
            color, border = "#f1c40f", "#d4ac0d"
        elif in_deg >= 1:
            color, border = "#27ae60", "#1e8449"
        else:
            color, border = "#2980b9", "#1f618d"

        size = min(45, 12 + in_deg * 4)

        # Plain-text tooltip — vis.js 9.x sets title as textContent so
        # HTML tags show as raw text. Use spaces for alignment and \n
        # for line breaks; CSS (injected below) handles the box styling.
        circ_str = "YES  ⚠" if stats['is_in_circular_dep'] else "No"
        divider  = "─" * 34
        tooltip  = (
            f"{node}\n"
            f"{divider}\n"
            f"Imported by   {in_deg:>4}  file{'s' if in_deg  != 1 else ' '}\n"
            f"Imports       {out_deg:>4}  file{'s' if out_deg != 1 else ' '}\n"
            f"PageRank      {stats['pagerank']:.4f}\n"
            f"Circular dep  {circ_str}"
        )

        net.add_node(
            node,
            label=label,
            title=tooltip,
            color={"background": color, "border": border,
                   "highlight": {"background": "#ffffff"}},
            size=size
        )

    for src, dst in graph.edges():
        net.add_edge(src, dst, arrows="to")

    try:
        net.write_html(output_path)
    except AttributeError:
        net.save_graph(output_path)

    # Post-process: inject tooltip CSS before </head>.
    # This is the only reliable way to style .vis-tooltip because
    # pyvis exposes no configuration option for that div.
    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            html = f.read()

        if '</head>' in html:
            html = html.replace('</head>', _TOOLTIP_CSS + '</head>', 1)
        else:
            html = _TOOLTIP_CSS + html

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

    except Exception as e:
        # Non-fatal: graph still works, just without custom tooltip styling
        print(f"  [WARNING] Could not inject tooltip CSS: {e}")

    return True