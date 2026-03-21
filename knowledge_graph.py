"""
Knowledge Graph Builder: Constructs and exports a graph where nodes are
documents and edges represent "references" relationships.

Uses networkx for in-memory graph operations and supports export to:
  • JSON  (for downstream processing / API responses)
  • GraphML (for Gephi / Cytoscape visualisation)
  • Mermaid diagram (for README / markdown embedding)
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Dict, Optional

import networkx as nx

from pdf_parser import DocumentMetadata
from reference_extractor import DocumentReference


# ─────────────────────────────────────────────
# Graph construction
# ─────────────────────────────────────────────

def build_graph(
    source_metadata: DocumentMetadata,
    references: List[DocumentReference],
) -> nx.DiGraph:
    """
    Build a directed graph:
      source document  ──references──►  each referenced document

    Node attributes:  title, circular_number, date, document_type
    Edge attributes:  clause, context, found_on_pages
    """
    G = nx.DiGraph()

    # Source node
    src_id = source_metadata.circular_number or source_metadata.title or Path(source_metadata.file_path).stem
    G.add_node(
        src_id,
        title=source_metadata.title or src_id,
        circular_number=source_metadata.circular_number,
        date=source_metadata.date,
        document_type="circular",
        is_source=True,
    )

    for ref in references:
        ref_id = ref.circular_number or ref.title
        if not ref_id:
            continue

        G.add_node(
            ref_id,
            title=ref.title,
            circular_number=ref.circular_number,
            date=ref.date,
            document_type=ref.document_type,
            is_source=False,
        )

        G.add_edge(
            src_id,
            ref_id,
            clause=ref.clause,
            context=ref.context,
            found_on_pages=ref.found_on_pages,
        )

    return G


# ─────────────────────────────────────────────
# Export helpers
# ─────────────────────────────────────────────

def export_json(
    G: nx.DiGraph,
    source_metadata: DocumentMetadata,
    references: List[DocumentReference],
    output_path: str,
) -> Dict:
    """Export full results as a structured JSON file."""
    payload = {
        "source_document": {
            "title": source_metadata.title,
            "circular_number": source_metadata.circular_number,
            "date": source_metadata.date,
            "issuing_authority": source_metadata.issuing_authority,
            "total_pages": source_metadata.total_pages,
            "file_path": source_metadata.file_path,
        },
        "total_references": len(references),
        "references_by_type": _group_by_type(references),
        "references": [r.to_dict() for r in references],
        "graph": {
            "nodes": len(G.nodes),
            "edges": len(G.edges),
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return payload


def export_graphml(G: nx.DiGraph, output_path: str) -> None:
    """Export graph in GraphML format (opens in Gephi/yEd/Cytoscape)."""
    # networkx requires string attributes for GraphML
    H = nx.DiGraph()
    for node, data in G.nodes(data=True):
        H.add_node(str(node), **{k: str(v) for k, v in data.items()})
    for u, v, data in G.edges(data=True):
        edge_data = {k: str(v) for k, v in data.items()}
        H.add_edge(str(u), str(v), **edge_data)
    nx.write_graphml(H, output_path)


def export_mermaid(G: nx.DiGraph, output_path: str) -> str:
    """
    Export a Mermaid flowchart diagram.
    Nodes are labelled with short IDs for readability.
    """
    lines = ["graph LR"]
    node_ids: Dict[str, str] = {}

    for i, (node, data) in enumerate(G.nodes(data=True)):
        short = f"N{i}"
        node_ids[node] = short
        label = data.get("title", str(node))[:50].replace('"', "'")
        dtype = data.get("document_type", "other")
        style = _mermaid_style(dtype, data.get("is_source", False))
        lines.append(f'    {short}["{label}"]')
        if style:
            lines.append(f"    style {short} {style}")

    for u, v, data in G.edges(data=True):
        uid = node_ids.get(u, u)
        vid = node_ids.get(v, v)
        label = (data.get("clause") or "references")[:30]
        lines.append(f"    {uid} -->|{label}| {vid}")

    mermaid_str = "\n".join(lines)
    with open(output_path, "w") as f:
        f.write(mermaid_str)
    return mermaid_str


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _group_by_type(references: List[DocumentReference]) -> Dict[str, List[Dict]]:
    groups: Dict[str, List[Dict]] = {}
    for ref in references:
        dtype = ref.document_type or "other"
        groups.setdefault(dtype, []).append(ref.to_dict())
    return groups


def _mermaid_style(doc_type: str, is_source: bool) -> str:
    if is_source:
        return "fill:#1a56db,color:#fff,stroke:#1a56db"
    styles = {
        "circular":       "fill:#0e9f6e,color:#fff",
        "regulation":     "fill:#7e3af2,color:#fff",
        "act":            "fill:#e3a008,color:#fff",
        "master_circular":"fill:#ff5a1f,color:#fff",
        "notification":   "fill:#3f83f8,color:#fff",
    }
    return styles.get(doc_type, "fill:#9ca3af,color:#fff")