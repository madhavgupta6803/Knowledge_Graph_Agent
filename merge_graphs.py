"""
Merge Graphs: Combines multiple circular JSON outputs into a single
unified knowledge graph.
"""

import json
import argparse
import sys
from pathlib import Path

# Make sure agent/ is importable when run from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.reference_extractor import DocumentReference, deduplicate_references
from agent.pdf_parser import DocumentMetadata
from agent.knowledge_graph import build_graph, export_json, export_graphml, export_mermaid


def load_references_from_json(json_path: str) -> tuple:
    """
    Load source metadata and references from an agent output JSON file.
    Returns (DocumentMetadata, list of raw ref dicts).
    """
    with open(json_path) as f:
        data = json.load(f)

    src = data.get("source_document", {})
    metadata = DocumentMetadata(
        title=src.get("title", ""),
        circular_number=src.get("circular_number", ""),
        date=src.get("date", ""),
        issuing_authority=src.get("issuing_authority", "Securities and Exchange Board of India (SEBI)"),
        addressees=src.get("addressees", []),
        total_pages=src.get("total_pages", 0),
        file_path=src.get("file_path", json_path),
    )

    # Convert stored dicts back to raw ref format expected by deduplicate_references
    raw_refs = []
    for ref in data.get("references", []):
        for page in ref.get("found_on_pages", [0]):
            raw_refs.append({
                "document_type": ref.get("document_type", "other"),
                "title":         ref.get("title", ""),
                "circular_number": ref.get("circular_number", ""),
                "date":          ref.get("date", ""),
                "clause":        ref.get("clause", ""),
                "context":       ref.get("context", ""),
                "page_number":   page,
            })

    return metadata, raw_refs


def merge_multiple_jsons(json_paths: list) -> tuple:
    """
    Merge all source circulars and their references into one combined graph.

    Strategy:
      - Each source circular becomes its own node (blue)
      - All referenced documents are shared nodes — if two circulars
        reference the same regulation, it appears once with edges from both
      - References are deduplicated across ALL circulars combined
    """
    import networkx as nx

    G = nx.DiGraph()
    all_sources = []
    all_combined_refs = []

    for json_path in json_paths:
        metadata, raw_refs = load_references_from_json(json_path)
        references = deduplicate_references(raw_refs)

        all_sources.append(metadata)
        all_combined_refs.append((metadata, references))

        # Add source node
        src_id = metadata.circular_number or metadata.title or Path(metadata.file_path).stem
        G.add_node(
            src_id,
            title=metadata.title or src_id,
            circular_number=metadata.circular_number,
            date=metadata.date,
            document_type="circular",
            is_source=True,
            file_path=metadata.file_path,
        )

        # Add referenced document nodes and edges
        for ref in references:
            ref_id = ref.circular_number or ref.title
            if not ref_id:
                continue

            # Add node — if it already exists from another circular, update attributes
            if ref_id not in G.nodes:
                G.add_node(
                    ref_id,
                    title=ref.title,
                    circular_number=ref.circular_number,
                    date=ref.date,
                    document_type=ref.document_type,
                    is_source=False,
                )
            else:
                # Fill any empty fields from this new sighting
                node = G.nodes[ref_id]
                if not node.get("date") and ref.date:
                    node["date"] = ref.date
                if not node.get("circular_number") and ref.circular_number:
                    node["circular_number"] = ref.circular_number
                if len(ref.title) > len(node.get("title", "")):
                    node["title"] = ref.title

            # Add edge — multiple circulars can reference the same doc
            # Use a unique edge key per (source, target, clause)
            G.add_edge(
                src_id,
                ref_id,
                clause=ref.clause,
                context=ref.context,
                found_on_pages=str(ref.found_on_pages),
                source_circular=src_id,
            )

    return G, all_sources, all_combined_refs


def build_combined_payload(G, all_sources, all_combined_refs) -> dict:
    """Build the combined JSON payload."""
    import networkx as nx

    sources_summary = []
    for meta in all_sources:
        sources_summary.append({
            "title": meta.title,
            "circular_number": meta.circular_number,
            "date": meta.date,
            "addressees": meta.addressees,
            "total_pages": meta.total_pages,
            "file_path": meta.file_path,
        })

    # Collect all unique referenced documents across all circulars
    all_refs_flat = []
    for _, refs in all_combined_refs:
        for ref in refs:
            all_refs_flat.append(ref.to_dict())

    # Group shared references (appear in multiple circulars)
    shared = {}
    for _, refs in all_combined_refs:
        for ref in refs:
            key = ref.circular_number or ref.title
            if key not in shared:
                shared[key] = {"ref": ref.to_dict(), "cited_by": []}
            src_meta = next(
                (m for m, r in all_combined_refs if ref in r), None
            )

    return {
        "type": "combined_knowledge_graph",
        "source_circulars": sources_summary,
        "total_source_circulars": len(all_sources),
        "total_unique_referenced_documents": len(G.nodes) - len(all_sources),
        "total_edges": len(G.edges),
        "graph": {
            "nodes": len(G.nodes),
            "edges": len(G.edges),
        },
        "all_references": all_refs_flat,
    }


def export_combined_mermaid(G, output_path: str) -> str:
    """Export Mermaid diagram for the combined graph."""
    STYLES = {
        "circular":        "fill:#1a56db,color:#fff",   # source circulars — blue
        "regulation":      "fill:#7e3af2,color:#fff",
        "act":             "fill:#e3a008,color:#fff",
        "master_circular": "fill:#ff5a1f,color:#fff",
        "notification":    "fill:#3f83f8,color:#fff",
    }

    lines = ["graph LR"]
    node_ids = {}

    for i, (node, data) in enumerate(G.nodes(data=True)):
        short = f"N{i}"
        node_ids[node] = short
        label = data.get("title", str(node))[:50].replace('"', "'")
        dtype = data.get("document_type", "other")
        is_src = data.get("is_source", False)

        # Source circulars get a distinct style
        if is_src:
            style = "fill:#1a56db,color:#fff,stroke:#fff,stroke-width:2px"
        else:
            style = STYLES.get(dtype, "fill:#9ca3af,color:#fff")

        lines.append(f'    {short}["{label}"]')
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


def main():
    parser = argparse.ArgumentParser(
        description="Merge multiple circular JSON outputs into a single knowledge graph"
    )
    parser.add_argument(
        "json_files", nargs="+",
        help="Two or more agent output JSON files to merge"
    )
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--name", default="combined_graph",
                        help="Base name for output files")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Merging {len(args.json_files)} circular(s) into combined graph")
    print(f"{'='*60}\n")

    for f in args.json_files:
        print(f"  + {f}")

    print("\nBuilding combined graph...")
    G, all_sources, all_combined_refs = merge_multiple_jsons(args.json_files)

    print(f"  Nodes : {len(G.nodes)} ({len(all_sources)} source circulars + {len(G.nodes)-len(all_sources)} referenced docs)")
    print(f"  Edges : {len(G.edges)}")

    # Export JSON
    json_path = output_dir / f"{args.name}.json"
    payload = build_combined_payload(G, all_sources, all_combined_refs)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\n  ✓ JSON    → {json_path}")

    # Export GraphML
    import networkx as nx
    H = nx.DiGraph()
    for node, data in G.nodes(data=True):
        H.add_node(str(node), **{k: str(v) for k, v in data.items()})
    for u, v, data in G.edges(data=True):
        H.add_edge(str(u), str(v), **{k: str(v2) for k, v2 in data.items()})
    gml_path = output_dir / f"{args.name}.graphml"
    nx.write_graphml(H, str(gml_path))
    print(f"  ✓ GraphML → {gml_path}")

    # Export Mermaid
    mmd_path = output_dir / f"{args.name}.mmd"
    export_combined_mermaid(G, str(mmd_path))
    print(f"  ✓ Mermaid → {mmd_path}")

    # Print shared references (appear in multiple circulars)
    print(f"\n{'='*60}")
    print("  Shared references (cited by multiple circulars):")
    print(f"{'='*60}")
    for node, data in G.nodes(data=True):
        if data.get("is_source"):
            continue
        in_edges = list(G.in_edges(node))
        if len(in_edges) > 1:
            print(f"\n  [{data.get('document_type','?')}] {data.get('title','?')[:60]}")
            for src, _ in in_edges:
                src_data = G.nodes.get(src, {})
                print(f"    ← {src_data.get('title', src)[:60]}")

    print(f"\n  Output: {output_dir.resolve()}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()