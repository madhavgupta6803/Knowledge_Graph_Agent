# #!/usr/bin/env python3
# """
# SEBI Knowledge Graph Agent — Main Entry Point

# Usage:
#     python main.py <path_to_pdf> [options]

# Options:
#     --provider      anthropic | gemini  (default: anthropic)
#     --output-dir    Directory for output files (default: ./output)
#     --verbose       Print progress per page
#     --no-graphml    Skip GraphML export
#     --no-mermaid    Skip Mermaid export
# """

# import argparse
# import os
# import sys
# import json
# import time
# from pathlib import Path

# from pdf_parser import extract_pages
# from reference_extractor import extract_references_from_page, deduplicate_references
# from knowledge_graph import build_graph, export_json, export_graphml, export_mermaid


# def get_client(provider: str):
#     if provider == "anthropic":
#         try:
#             import anthropic
#         except ImportError:
#             sys.exit("anthropic package not installed. Run: pip install anthropic")
#         api_key = os.environ.get("ANTHROPIC_API_KEY")
#         if not api_key:
#             sys.exit("Set ANTHROPIC_API_KEY environment variable.")
#         return anthropic.Anthropic(api_key=api_key)

#     elif provider == "gemini":
#         try:
#             import google.generativeai as genai
#         except ImportError:
#             sys.exit("google-generativeai not installed. Run: pip install google-generativeai")
#         api_key = os.environ.get("GEMINI_API_KEY")
#         if not api_key:
#             sys.exit("Set GEMINI_API_KEY environment variable.")
#         genai.configure(api_key=api_key)
#         return genai.GenerativeModel("gemini-2-flash")

#     else:
#         sys.exit(f"Unknown provider: {provider}. Use 'anthropic' or 'gemini'.")


# def run(pdf_path: str, provider: str, output_dir: str, verbose: bool, skip_graphml: bool, skip_mermaid: bool):
#     pdf_path = Path(pdf_path)
#     if not pdf_path.exists():
#         sys.exit(f"File not found: {pdf_path}")

#     output_dir = Path(output_dir)
#     output_dir.mkdir(parents=True, exist_ok=True)

#     stem = pdf_path.stem

#     print(f"\n{'='*60}")
#     print(f"  SEBI Knowledge Graph Agent")
#     print(f"  Provider : {provider}")
#     print(f"  File     : {pdf_path.name}")
#     print(f"{'='*60}\n")

#     # ── Step 1: Parse PDF ──────────────────────────────────────
#     print("[ 1/4 ] Parsing PDF …")
#     pages, metadata = extract_pages(str(pdf_path))
#     print(f"        {len(pages)} pages extracted.")
#     if metadata.circular_number:
#         print(f"        Detected circular: {metadata.circular_number}")

#     # ── Step 2: Extract references page by page ─────────────────
#     print(f"\n[ 2/4 ] Extracting references ({len(pages)} pages) …")
#     client = get_client(provider)
#     all_raw_refs = []

#     for page in pages:
#         if verbose:
#             print(f"        Page {page.page_number:>3} / {len(pages)} …", end=" ", flush=True)

#         refs = extract_references_from_page(page, client, provider=provider)
#         all_raw_refs.extend(refs)
#         if provider == "gemini":
#             time.sleep(4) # Wait 4 seconds between pages
#         if verbose:
#             print(f"{len(refs)} ref(s) found.")

#     print(f"        Raw references extracted: {len(all_raw_refs)}")

#     # ── Step 3: Deduplicate ─────────────────────────────────────
#     print("\n[ 3/4 ] Deduplicating and structuring …")
#     references = deduplicate_references(all_raw_refs)
#     print(f"        Unique references: {len(references)}")

#     # ── Step 4: Build graph & export ────────────────────────────
#     print("\n[ 4/4 ] Building knowledge graph and exporting …")
#     G = build_graph(metadata, references)

#     json_path   = output_dir / f"{stem}_references.json"
#     export_json(G, metadata, references, str(json_path))
#     print(f"        ✓ JSON  → {json_path}")

#     if not skip_graphml:
#         gml_path = output_dir / f"{stem}_graph.graphml"
#         export_graphml(G, str(gml_path))
#         print(f"        ✓ GraphML → {gml_path}")

#     if not skip_mermaid:
#         mmd_path = output_dir / f"{stem}_diagram.mmd"
#         export_mermaid(G, str(mmd_path))
#         print(f"        ✓ Mermaid → {mmd_path}")

#     # ── Summary ─────────────────────────────────────────────────
#     print(f"\n{'='*60}")
#     print("  SUMMARY")
#     print(f"{'='*60}")
#     print(f"  Total unique references: {len(references)}")

#     from collections import Counter
#     type_counts = Counter(r.document_type for r in references)
#     for dtype, count in type_counts.most_common():
#         print(f"    {dtype:<20} {count}")

#     print(f"\n  Top references:")
#     for ref in sorted(references, key=lambda r: len(r.found_on_pages), reverse=True)[:5]:
#         pages_str = ", ".join(str(p) for p in ref.found_on_pages)
#         print(f"    • [{ref.document_type}] {ref.title[:60]}")
#         print(f"      Pages: {pages_str}")
#         if ref.circular_number:
#             print(f"      Ref#: {ref.circular_number}")

#     print(f"\n  Output directory: {output_dir.resolve()}")
#     print(f"{'='*60}\n")

#     return references


# def main():
#     parser = argparse.ArgumentParser(
#         description="SEBI Circular Knowledge Graph Agent"
#     )
#     parser.add_argument("pdf", help="Path to the SEBI circular PDF")
#     parser.add_argument("--provider", default="anthropic", choices=["anthropic", "gemini"])
#     parser.add_argument("--output-dir", default="output")
#     parser.add_argument("--verbose", action="store_true")
#     parser.add_argument("--no-graphml", action="store_true")
#     parser.add_argument("--no-mermaid", action="store_true")

#     args = parser.parse_args()
#     run(
#         pdf_path=args.pdf,
#         provider=args.provider,
#         output_dir=args.output_dir,
#         verbose=args.verbose,
#         skip_graphml=args.no_graphml,
#         skip_mermaid=args.no_mermaid,
#     )


# if __name__ == "__main__":
#     main()


#!/usr/bin/env python3
"""
SEBI Knowledge Graph Agent — Main Entry Point
Supports: Anthropic, Gemini, and Hugging Face (Qwen)
"""

import argparse
import os
import sys
import json
import time
from pathlib import Path

# Note: Ensure these local modules exist in your directory
try:
    from agent.pdf_parser import extract_pages
    from agent.reference_extractor import extract_references_from_page, deduplicate_references
    from agent.knowledge_graph import build_graph, export_json, export_graphml, export_mermaid
except ImportError as e:
    sys.exit(f"Missing local module: {e}")

def get_client(provider: str):
    if provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            sys.exit("anthropic package not installed. Run: pip install anthropic")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.exit("Set ANTHROPIC_API_KEY environment variable.")
        return anthropic.Anthropic(api_key=api_key)

    elif provider == "gemini":
        try:
            import google.generativeai as genai
        except ImportError:
            sys.exit("google-generativeai not installed. Run: pip install google-generativeai")
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            sys.exit("Set GEMINI_API_KEY environment variable.")
        genai.configure(api_key=api_key)
        # Using 1.5-flash as it is more stable for free tier than 2.0
        return genai.GenerativeModel("gemini-1.5-flash")

    elif provider == "huggingface":
        try:
            from huggingface_hub import InferenceClient
        except ImportError:
            sys.exit("huggingface_hub not installed. Run: pip install huggingface_hub")
        
        api_key = os.environ.get("HUGGINGFACE_TOKEN")
        if not api_key:
            sys.exit("Set HUGGINGFACE_TOKEN environment variable.")
        
        # We target the Qwen 2.5 72B model on Hugging Face
        # return InferenceClient(model="Qwen/Qwen2.5-72B-Instruct", token=api_key)
        return InferenceClient(model="Qwen/Qwen2.5-72B-Instruct", token=api_key)

    else:
        sys.exit(f"Unknown provider: {provider}. Use 'anthropic', 'gemini', or 'huggingface'.")

def run(pdf_path: str, provider: str, output_dir: str, verbose: bool, skip_graphml: bool, skip_mermaid: bool):
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        sys.exit(f"File not found: {pdf_path}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = pdf_path.stem

    print(f"\n{'='*60}")
    print(f"  SEBI Knowledge Graph Agent")
    print(f"  Provider : {provider}")
    print(f"  File     : {pdf_path.name}")
    print(f"{'='*60}\n")

    # ── Step 1: Parse PDF ──────────────────────────────────────
    print("[ 1/4 ] Parsing PDF …")
    pages, metadata = extract_pages(str(pdf_path))
    print(f"        {len(pages)} pages extracted.")

    # ── Step 2: Extract references page by page ─────────────────
    print(f"\n[ 2/4 ] Extracting references ({len(pages)} pages) …")
    client = get_client(provider)
    all_raw_refs = []

    for page in pages:
        if verbose:
            print(f"        Page {page.page_number:>3} / {len(pages)} …", end=" ", flush=True)

        # The extraction function needs to be updated in reference_extractor.py 
        # to handle the client.chat.completions.create() syntax for HF.
        try:
            refs = extract_references_from_page(page, client, provider=provider)
            all_raw_refs.extend(refs)
        except Exception as e:
            print(f"\n[ERROR] Failed on page {page.page_number}: {e}")
            continue

        # Rate limiting for free tiers
        if provider in ["gemini", "huggingface"]:
            time.sleep(2) 

        if verbose:
            print(f"{len(refs)} ref(s) found.")

    print(f"        Raw references extracted: {len(all_raw_refs)}")
    print("        Running verification pass for Master Circular clauses ...")
    from agent.reference_extractor import verify_master_circular_clauses
    extra = verify_master_circular_clauses(pages, client, provider=provider)
    if extra:
        print(f"        Verification pass found {len(extra)} additional clause ref(s).")
        all_raw_refs.extend(extra)

    # ── Step 3: Deduplicate ─────────────────────────────────────
    print("\n[ 3/4 ] Deduplicating and structuring …")
    references = deduplicate_references(all_raw_refs)
    print(f"        Unique references: {len(references)}")

    # ── Step 4: Build graph & export ────────────────────────────
    print("\n[ 4/4 ] Building knowledge graph and exporting …")
    G = build_graph(metadata, references)

    json_path = output_dir / f"{stem}_references_v2.json"
    export_json(G, metadata, references, str(json_path))
    print(f"        ✓ JSON    → {json_path}")

    if not skip_graphml:
        gml_path = output_dir / f"{stem}_graph_v2.graphml"
        export_graphml(G, str(gml_path))
        print(f"        ✓ GraphML → {gml_path}")

    if not skip_mermaid:
        mmd_path = output_dir / f"{stem}_diagram_v2.mmd"
        export_mermaid(G, str(mmd_path) if hasattr(G, 'nodes') else None)
        print(f"        ✓ Mermaid → {mmd_path}")

    print(f"\n{'='*60}")
    print(f"  Process Complete. Output in: {output_dir.resolve()}")
    print(f"{'='*60}\n")

    return references

def main():
    parser = argparse.ArgumentParser(description="SEBI Circular Knowledge Graph Agent")
    parser.add_argument("pdf", help="Path to the SEBI circular PDF")
    parser.add_argument("--provider", default="huggingface", choices=["anthropic", "gemini", "huggingface"])
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--no-graphml", action="store_true")
    parser.add_argument("--no-mermaid", action="store_true")

    args = parser.parse_args()
    run(
        pdf_path=args.pdf,
        provider=args.provider,
        output_dir=args.output_dir,
        verbose=args.verbose,
        skip_graphml=args.no_graphml,
        skip_mermaid=args.no_mermaid,
    )

if __name__ == "__main__":
    main()