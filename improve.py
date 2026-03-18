"""
Prompt Improvement Script
=========================
Runs the agent with TWO different prompt strategies on the same PDF,
evaluates both against ground truth, and prints a side-by-side comparison.

This demonstrates how evaluations drive prompt engineering improvements.

Usage:
    python -m evals.improve --pdf path/to/circular.pdf \
                            --ground-truth evals/ground_truth/circular.json \
                            --provider anthropic
"""

import os
import sys
import json
import argparse
import importlib
from pathlib import Path

# We monkey-patch the prompt inside reference_extractor for the "before" run
PROMPT_V1_SYSTEM = """You are a document analyst. Extract references to other documents from this page of a SEBI circular.
Return a JSON array with fields: document_type, title, circular_number, date, clause, context, page_number.
If no references, return []."""

PROMPT_V1_USER = """Page {page_number}:
{text}"""

PROMPT_V2_SYSTEM = """You are an expert regulatory analyst specialising in Indian securities law.
Your job is to extract every reference to an external document from a page of a SEBI circular.

External documents include, but are not limited to:
  • Other SEBI circulars (e.g. SEBI/HO/…/CIR/P/2019/62)
  • SEBI Regulations (e.g. SEBI (LODR) Regulations, 2015)
  • Acts of Parliament (e.g. SCRA 1956, Companies Act 2013)
  • Master Circulars, Guidelines, Directions, Notifications
  • RBI/IRDAI/other-regulator documents referenced in the text

Rules:
1. Return ONLY a valid JSON array — no prose, no markdown fences.
2. Each element must have these exact keys:
     document_type, title, circular_number, date, clause, context
3. If a field is unknown, use an empty string "".
4. document_type must be one of:
     circular | regulation | act | notification | master_circular | other
5. Include the page_number field set to the integer provided.
6. Do NOT invent references not present in the text.
7. If the page has no external references, return [].
"""

PROMPT_V2_USER = """Page number: {page_number}

--- BEGIN PAGE TEXT ---
{text}
--- END PAGE TEXT ---

Extract all references to external documents from this page."""


def run_agent_with_prompt(pdf_path, provider, system_prompt, user_prompt_template, output_suffix):
    """Run the agent with a custom prompt, return list of reference dicts."""
    import agent.reference_extractor as re_mod

    # Temporarily override prompts
    original_system = re_mod.SYSTEM_PROMPT
    original_user   = re_mod.PAGE_USER_PROMPT
    re_mod.SYSTEM_PROMPT    = system_prompt
    re_mod.PAGE_USER_PROMPT = user_prompt_template

    try:
        from agent.pdf_parser import extract_pages
        from agent.reference_extractor import extract_references_from_page, deduplicate_references

        pages, metadata = extract_pages(pdf_path)

        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        else:
            import google.generativeai as genai
            genai.configure(api_key=os.environ["GEMINI_API_KEY"])
            client = genai.GenerativeModel("gemini-2.0-flash")

        all_raw = []
        for page in pages:
            refs = extract_references_from_page(page, client, provider=provider)
            all_raw.extend(refs)

        references = deduplicate_references(all_raw)
        return [r.to_dict() for r in references]

    finally:
        re_mod.SYSTEM_PROMPT    = original_system
        re_mod.PAGE_USER_PROMPT = original_user


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf",          required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--provider",     default="anthropic", choices=["anthropic", "gemini"])
    args = parser.parse_args()

    from evals.evaluator import evaluate, print_report, compare_runs

    print("\n[Run 1] Basic prompt (v1) …")
    refs_v1 = run_agent_with_prompt(
        args.pdf, args.provider,
        PROMPT_V1_SYSTEM, PROMPT_V1_USER, "v1"
    )

    print("\n[Run 2] Improved prompt (v2) …")
    refs_v2 = run_agent_with_prompt(
        args.pdf, args.provider,
        PROMPT_V2_SYSTEM, PROMPT_V2_USER, "v2"
    )

    with open(args.ground_truth) as f:
        gt_data = json.load(f)
    gt_refs = gt_data.get("references", [])

    result_v1 = evaluate(refs_v1, gt_refs)
    result_v2 = evaluate(refs_v2, gt_refs)

    print_report(result_v1, label="V1 — Basic Prompt")
    print_report(result_v2, label="V2 — Improved Prompt")
    compare_runs(result_v1, result_v2)


if __name__ == "__main__":
    main()