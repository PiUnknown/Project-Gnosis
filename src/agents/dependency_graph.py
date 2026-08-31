"""
Agent 3: Dependency Graph Agent

Reads from state:  symbol_tables, file_manifest
Writes to state:   dependency_graph, circular_deps, circular_nodes,
                   graph_stats, topological_order

Steps:
1. Add every file in the manifest as a node (including isolated files
   with no imports — we want them in the graph so Phase 4 can find them)
2. For each file's internal imports, resolve to actual file paths
   and add directed edges (importer → importee)
3. Detect all circular dependencies with nx.simple_cycles()
4. Compute per-node metrics: in-degree, out-degree, PageRank
5. Compute topological order (suggested reading order) if no cycles
6. Store everything in state for downstream agents
"""
import sys
import networkx as nx
from pathlib import PurePosixPath

from src.state import ArchaeonState
from src.utils.graph_utils import resolve_import_to_paths

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run(state: ArchaeonState) -> ArchaeonState:
    print(f"\n[Agent 3: Dependency Graph]")

    file_paths = {f.path for f in state.file_manifest}

    # ----------------------------------------------------------------
    # Step 1: Build the directed graph
    # ----------------------------------------------------------------
    G = nx.DiGraph()

    # Add every file as a node, even those with no imports.
    # If we only added files that appear in edges, isolated files
    # would be invisible to Phase 4 and Phase 6.
    for file_meta in state.file_manifest:
        G.add_node(
            file_meta.path,
            language=file_meta.language,
            line_count=file_meta.line_count
        )

    # ----------------------------------------------------------------
    # Step 2: Add edges from resolved internal imports
    # ----------------------------------------------------------------
    total_files = len(state.symbol_tables)
    edge_count = 0
    unresolved_count = 0

    for idx, (file_path, symbol_table) in enumerate(state.symbol_tables.items()):
        print(f"\r  Building edges: {idx + 1}/{total_files}", end="", flush=True)

        lang = symbol_table.language

        for import_info in symbol_table.imports:
            if not import_info.is_internal:
                continue

            resolved = resolve_import_to_paths(
                file_path,
                import_info,
                lang,
                file_paths
            )

            if not resolved:
                # is_internal was True but resolution still failed.
                # Most common cause: the import references a file our
                # manifest doesn't have (filtered out as too large,
                # wrong extension, or in an excluded directory).
                unresolved_count += 1
                continue

            for target_path in resolved:
                # Skip self-loops (shouldn't happen, but guard anyway)
                if target_path == file_path:
                    continue
                # Skip if target isn't in our manifest
                if target_path not in file_paths:
                    continue

                if not G.has_edge(file_path, target_path):
                    G.add_edge(file_path, target_path)
                    edge_count += 1

    print()

    state.dependency_graph = G
    print(f"  Nodes (files)    : {G.number_of_nodes()}")
    print(f"  Edges (imports)  : {G.number_of_edges()}")
    if unresolved_count > 0:
        print(f"  Unresolved       : {unresolved_count} internal imports "
              f"(files filtered out or not in manifest)")

    # ----------------------------------------------------------------
    # Step 3: Detect circular dependencies
    # ----------------------------------------------------------------
    print(f"\n  Detecting circular dependencies...")
    cycles = list(nx.simple_cycles(G))
    state.circular_deps = cycles

    circular_nodes: set = set()
    for cycle in cycles:
        for node in cycle:
            circular_nodes.add(node)
    state.circular_nodes = circular_nodes

    if cycles:
        print(f"  [WARN] {len(cycles)} circular dependency cycle(s) found:")
        for cycle in cycles[:5]:
            names = [PurePosixPath(p).name for p in cycle]
            cycle_str = " -> ".join(names) + f" -> {names[0]}"
            print(f"    {cycle_str}")
        if len(cycles) > 5:
            print(f"    ...and {len(cycles) - 5} more cycles")
    else:
        print(f"  [OK] No circular dependencies detected")

    # ----------------------------------------------------------------
    # Step 4: Compute PageRank
    # ----------------------------------------------------------------
    pagerank = _compute_pagerank(G)

    # ----------------------------------------------------------------
    # Step 5: Build per-file graph stats
    # ----------------------------------------------------------------
    graph_stats = {}
    for node in G.nodes():
        in_deg = G.in_degree(node)
        out_deg = G.out_degree(node)

        # predecessors = files that import this file (in-edges)
        # successors   = files this file imports (out-edges)
        dependents = list(G.predecessors(node))
        dependencies = list(G.successors(node))

        graph_stats[node] = {
            "in_degree": in_deg,
            "out_degree": out_deg,
            "pagerank": round(pagerank.get(node, 0.0), 6),
            "is_in_circular_dep": node in circular_nodes,
            "dependents": dependents,
            "dependencies": dependencies,
        }

    state.graph_stats = graph_stats

    # ----------------------------------------------------------------
    # Step 6: Topological sort (suggested reading order)
    # ----------------------------------------------------------------
    if not cycles:
        # nx.topological_sort returns a generator where for each edge
        # A → B, A appears before B. In our graph A → B means A imports B.
        # So A (the importer) comes before B (the imported) in topo order.
        # For reading order we want B before A: understand dependencies first.
        # Hence we reverse the topological sort.
        topo_list = list(nx.topological_sort(G))
        state.topological_order = list(reversed(topo_list))
        print(f"\n  Reading order computed ({len(state.topological_order)} files)")
    else:
        state.topological_order = []
        print(f"\n  Reading order skipped — resolve circular dependencies first")

    # ----------------------------------------------------------------
    # Step 7: Sampled subset selection (if in Sampled mode)
    # ----------------------------------------------------------------
    if state.analysis_mode == "Sampled":
        import os
        MAX_FULL_ANALYSIS_FILES = int(os.getenv("MAX_FULL_ANALYSIS_FILES", 300))
        
        candidates = []
        for file_meta in state.file_manifest:
            path = file_meta.path
            g_s = graph_stats.get(path, {})
            pr = g_s.get("pagerank", 0.0)
            in_deg = g_s.get("in_degree", 0)
            out_deg = g_s.get("out_degree", 0)
            
            symbol_table = state.symbol_tables.get(path)
            symbol_count = 0
            if symbol_table:
                symbol_count = len(symbol_table.functions) + len(symbol_table.classes)
                
            depth = path.count("/")
            candidates.append({
                "path": path,
                "pagerank": pr,
                "in_degree": in_deg,
                "out_degree": out_deg,
                "symbol_count": symbol_count,
                "depth": depth
            })
            
        candidates.sort(key=lambda x: (
            -x["pagerank"],
            -x["in_degree"],
            -x["symbol_count"],
            x["depth"],
            x["path"]
        ))
        
        selected_paths = {c["path"] for c in candidates[:MAX_FULL_ANALYSIS_FILES]}
        state.analyzed_paths = selected_paths
        state.files_analyzed = len(selected_paths)
        print(f"  [Sampled Mode] Selected {state.files_analyzed} of {len(state.file_manifest)} files for detailed analysis.")
    else:
        state.analyzed_paths = None
        state.files_analyzed = len(state.file_manifest)

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    _print_summary(state, graph_stats, circular_nodes)
    return state


# -----------------------------------------------------------------------
# PageRank computation
# -----------------------------------------------------------------------

def _compute_pagerank(G: nx.DiGraph) -> dict:
    """
    Compute PageRank for all nodes.

    WHY PAGERANK OVER RAW IN-DEGREE:
    In-degree counts direct importers. PageRank accounts for the
    importance of those importers. If "state.py" is imported by 5 files
    and "utils.py" is also imported by 5 files, in-degree treats them equally.
    But if state.py's importers are themselves imported by many files,
    state.py scores higher in PageRank. It surfaces the true core
    of a codebase: files that are central to the whole dependency chain.

    Edge case: graphs with no edges or all-zero in-degree cause
    PageRank to behave oddly. We fall back to normalized in-degree.
    """
    if G.number_of_edges() == 0:
        # No edges: every node is equally "unimportant" by PageRank standards
        n = max(G.number_of_nodes(), 1)
        return {node: 1.0 / n for node in G.nodes()}

    try:
        return nx.pagerank(G, alpha=0.85, max_iter=200)
    except nx.PowerIterationFailedConvergence:
        # Fallback: normalized in-degree
        n = max(G.number_of_nodes(), 1)
        return {node: G.in_degree(node) / n for node in G.nodes()}
    except Exception:
        return {node: 0.0 for node in G.nodes()}


# -----------------------------------------------------------------------
# Summary printer
# -----------------------------------------------------------------------

def _print_summary(state: ArchaeonState, graph_stats: dict, circular_nodes: set) -> None:
    G = state.dependency_graph

    # Isolated files: no imports, nobody imports them
    isolated = [
        n for n in G.nodes()
        if G.in_degree(n) == 0 and G.out_degree(n) == 0
    ]

    # Top files by in-degree
    top = sorted(
        [(p, s['in_degree']) for p, s in graph_stats.items()],
        key=lambda x: -x[1]
    )

    print(f"\n[Agent 3: Dependency Graph] Done")
    print(f"  Total nodes      : {G.number_of_nodes()}")
    print(f"  Total edges      : {G.number_of_edges()}")
    print(f"  Isolated files   : {len(isolated)}")
    print(f"  Files in cycles  : {len(circular_nodes)}")

    print(f"\n  Most imported files (highest in-degree):")
    shown = 0
    for path, in_deg in top:
        if in_deg == 0:
            break
        name = PurePosixPath(path).name
        bar = "#" * min(in_deg, 20)
        print(f"    {name:<40} {bar} {in_deg}")
        shown += 1
        if shown >= 8:
            break

    if not shown:
        print("    (no import relationships detected)")