"""
dependency_graph.py
Builds a dependency graph using NetworkX and returns D3-compatible JSON.
"""

import networkx as nx
from pathlib import Path


def get_complexity_color(complexity: int) -> str:
    """Return color based on complexity score."""
    if complexity <= 10:
        return "#3b82f6"   # blue - low
    elif complexity <= 25:
        return "#eab308"   # yellow - medium
    elif complexity <= 50:
        return "#f97316"   # orange - high
    else:
        return "#ef4444"   # red - critical


def build_graph(deps: list[dict], files: list[dict]) -> dict:
    """
    Build a NetworkX directed graph from dependency edges.
    Returns D3-compatible JSON: { nodes: [...], links: [...], metrics: {...} }
    """
    G = nx.DiGraph()

    # Build file metadata lookup
    file_meta = {f["name"]: f for f in files}

    # Add all nodes (files)
    for f in files:
        G.add_node(f["name"], **{
            "path": f.get("path", f["name"]),
            "lang": f.get("lang", ""),
            "lines": f.get("lines", 0),
            "complexity": f.get("complexity", 1),
            "functions": f.get("functions", 0),
        })

    # Add edges
    for dep in deps:
        src = dep.get("source", "")
        tgt = dep.get("target", "")
        if src in G and tgt in G:
            G.add_edge(src, tgt)

    # Compute graph metrics
    in_degree = dict(G.in_degree())
    out_degree = dict(G.out_degree())

    # PageRank for node importance
    try:
        pagerank = nx.pagerank(G, max_iter=100)
    except:
        pagerank = {n: 1.0 for n in G.nodes()}

    # Find cycles
    try:
        cycles = list(nx.simple_cycles(G))
        cycle_nodes = set(n for cycle in cycles for n in cycle)
    except:
        cycles = []
        cycle_nodes = set()

    # Build D3 nodes
    nodes = []
    for node in G.nodes():
        meta = file_meta.get(node, {})
        complexity = meta.get("complexity", 1)
        pr = pagerank.get(node, 0)

        nodes.append({
            "id": node,
            "path": meta.get("path", node),
            "lang": meta.get("lang", ""),
            "lines": meta.get("lines", 0),
            "complexity": complexity,
            "functions": meta.get("functions", 0),
            "color": get_complexity_color(complexity),
            "in_degree": in_degree.get(node, 0),
            "out_degree": out_degree.get(node, 0),
            "pagerank": round(pr * 100, 2),
            "is_hub": in_degree.get(node, 0) >= 3,
            "in_cycle": node in cycle_nodes,
            # Node size proportional to importance
            "size": max(8, min(24, 8 + pr * 300 + in_degree.get(node, 0) * 2)),
        })

    # Build D3 links
    links = []
    for src, tgt in G.edges():
        links.append({
            "source": src,
            "target": tgt,
        })

    # Graph-level metrics
    metrics = {
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "cycles_detected": len(cycles),
        "cycle_nodes": list(cycle_nodes),
        "hub_files": [n for n in G.nodes() if in_degree.get(n, 0) >= 3],
        "isolated_files": [n for n in G.nodes() if G.degree(n) == 0],
        "most_imported": sorted(
            [(n, in_degree.get(n, 0)) for n in G.nodes()],
            key=lambda x: x[1], reverse=True
        )[:5],
    }

    return {
        "nodes": nodes,
        "links": links,
        "metrics": metrics,
    }
