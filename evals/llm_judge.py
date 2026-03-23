# """
# LLM-as-Judge Evaluator
# ======================
# Automatically scores agent output WITHOUT needing a ground truth file.
# For each extracted reference, asks the LLM:
#   1. Is this reference actually present in the source text? (hallucination check)
#   2. Are the fields (title, clause, date) accurate? (accuracy check)

# Run:
#     python -m evals.llm_judge --predicted output/circular_references.json \
#                                --pdf sebi_circular.pdf \
#                                --provider huggingface
# """

# import json
# import argparse
# import re
# from agent.pdf_parser import extract_pages
# from rich.console import Console
# from rich.table import Table

# console = Console()

# JUDGE_PROMPT = """You are a strict fact-checker for regulatory documents.

# Below is a page from a SEBI circular, followed by a reference that an AI agent claims to have found in it.

# Your job: verify whether the reference is genuinely present and accurately described.

# Score each field:
# - is_present: true if the document is actually referenced on this page (not hallucinated)
# - title_accurate: true if the title correctly describes the referenced document
# - circular_number_accurate: true if circular_number matches what's in the text (or both are empty)
# - date_accurate: true if date matches what's in the text (or both are empty)
# - clause_accurate: true if the clause/para number matches what's in the text (or is empty when not mentioned)

# Return ONLY a JSON object with these exact boolean fields:
# {{
#   "is_present": true/false,
#   "title_accurate": true/false,
#   "circular_number_accurate": true/false,
#   "date_accurate": true/false,
#   "clause_accurate": true/false,
#   "reason": "one sentence explanation if anything is wrong"
# }}

# PAGE TEXT:
# {page_text}

# EXTRACTED REFERENCE:
# {reference}
# """


# def judge_reference(ref: dict, pages: list, client, provider: str) -> dict:
#     """Ask the LLM to verify a single extracted reference."""
#     # Find the pages this reference was found on
#     page_texts = []
#     for p in pages:
#         if p.page_number in ref.get("found_on_pages", []):
#             page_texts.append(f"[Page {p.page_number}]\n{p.text[:2000]}")
    
#     if not page_texts:
#         return {"is_present": False, "reason": "Page not found"}

#     prompt = JUDGE_PROMPT.format(
#         page_text="\n\n".join(page_texts),
#         reference=json.dumps(ref, indent=2)
#     )

#     try:
#         if provider == "huggingface":
#             response = client.chat_completion(
#                 messages=[{"role": "user", "content": prompt}],
#                 max_tokens=300,
#                 temperature=0.0,
#             )
#             raw = response.choices[0].message.content.strip()
#         elif provider == "anthropic":
#             response = client.messages.create(
#                 model="claude-3-5-sonnet-20240620",
#                 max_tokens=300,
#                 messages=[{"role": "user", "content": prompt}]
#             )
#             raw = response.content[0].text.strip()
#         elif provider == "gemini":
#             response = client.generate_content(prompt)
#             raw = response.text.strip()

#         raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
#         raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
#         return json.loads(raw.strip())

#     except Exception as e:
#         return {"is_present": False, "reason": str(e)}


# def run_llm_judge(predicted_path: str, pdf_path: str, provider: str, save_path: str = None):
#     import os
#     from huggingface_hub import InferenceClient
#     import anthropic

#     # Load predicted references
#     with open(predicted_path) as f:
#         data = json.load(f)
#     references = data.get("references", [])

#     # Extract pages
#     pages, _ = extract_pages(pdf_path)

#     # Set up client
#     if provider == "huggingface":
#         client = InferenceClient(
#             model="Qwen/Qwen2.5-72B-Instruct",
#             api_key=os.environ["HUGGINGFACE_TOKEN"]
#         )
#     elif provider == "anthropic":
#         client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

#     # Judge each reference
#     results = []
#     print(f"\nJudging {len(references)} references...\n")

#     for ref in references:
#         verdict = judge_reference(ref, pages, client, provider)
#         results.append({"reference": ref, "verdict": verdict})
#         status = "✓" if verdict.get("is_present") else "✗"
#         print(f"  {status} {ref.get('title', '?')[:50]} | clause: {ref.get('clause', '-')}")
#         if not verdict.get("is_present") or verdict.get("reason"):
#             print(f"    → {verdict.get('reason', '')}")

#     # Compute scores
#     total = len(results)
#     present       = sum(1 for r in results if r["verdict"].get("is_present"))
#     title_ok      = sum(1 for r in results if r["verdict"].get("title_accurate"))
#     circnum_ok    = sum(1 for r in results if r["verdict"].get("circular_number_accurate"))
#     date_ok       = sum(1 for r in results if r["verdict"].get("date_accurate"))
#     clause_ok     = sum(1 for r in results if r["verdict"].get("clause_accurate"))

#     console.print("\n")
#     t = Table(title="LLM-as-Judge Results (no ground truth needed)")
#     t.add_column("Check")
#     t.add_column("Score", justify="right")
#     t.add_row("References present in source",  f"{present}/{total} ({present/total:.0%})")
#     t.add_row("Title accuracy",                f"{title_ok}/{total} ({title_ok/total:.0%})")
#     t.add_row("Circular number accuracy",      f"{circnum_ok}/{total} ({circnum_ok/total:.0%})")
#     t.add_row("Date accuracy",                 f"{date_ok}/{total} ({date_ok/total:.0%})")
#     t.add_row("Clause accuracy",               f"{clause_ok}/{total} ({clause_ok/total:.0%})")
#     console.print(t)

#     hallucinations = [r for r in results if not r["verdict"].get("is_present")]
#     if hallucinations:
#         console.print(f"\n[red]Hallucinated references ({len(hallucinations)}):[/red]")
#         for h in hallucinations:
#             console.print(f"  • {h['reference'].get('title', '?')}")

#     if save_path:
#         with open(save_path, "w") as f:
#             json.dump({"total": total, "results": results}, f, indent=2)
#         print(f"\nSaved to {save_path}")


# def main():
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--predicted",  required=True)
#     parser.add_argument("--pdf",        required=True)
#     parser.add_argument("--provider",   default="huggingface",
#                         choices=["anthropic", "gemini", "huggingface"])
#     parser.add_argument("--save",       help="Save results to this JSON file")
#     args = parser.parse_args()

#     run_llm_judge(args.predicted, args.pdf, args.provider, args.save)


# if __name__ == "__main__":
#     main()

"""
LLM-as-Judge Evaluator
======================
Automatically scores agent output WITHOUT needing a ground truth file.

For each extracted reference, asks the LLM:
  1. Is this reference actually present in the source text? (hallucination check)
  2. Are the fields (title, clause, date) accurate? (accuracy check)

Also runs additional automatic checks:
  3. Duplicate detection (same document extracted twice)
  4. Source metadata validation (title, circular_number, date)

Run:
    python -m evals.llm_judge --predicted output/circular_references.json \
                               --pdf sebi_circular.pdf \
                               --provider huggingface
"""

import json
import re
import os
import argparse
from agent.pdf_parser import extract_pages
from rich.console import Console
from rich.table import Table

console = Console()

JUDGE_PROMPT = """You are a strict fact-checker for regulatory documents.

Below is a page from a SEBI circular, followed by a reference that an AI agent claims to have found in it.

Your job: verify whether the reference is genuinely present and accurately described.

Score each field:
- is_present: true if the document is actually referenced on this page (not hallucinated)
- title_accurate: true if the title correctly describes the referenced document
- circular_number_accurate: true if circular_number matches what's in the text (or both are empty)
- date_accurate: true if date matches what's in the text (or both are empty)
- clause_accurate: true if the clause/para number matches what's in the text (or is empty when not mentioned)

Return ONLY a JSON object with these exact boolean fields:
{{
  "is_present": true/false,
  "title_accurate": true/false,
  "circular_number_accurate": true/false,
  "date_accurate": true/false,
  "clause_accurate": true/false,
  "reason": "one sentence explanation if anything is wrong, else empty string"
}}

PAGE TEXT:
{page_text}

EXTRACTED REFERENCE:
{reference}
"""


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _is_vague_title(title: str) -> bool:
    """Same logic as reference_extractor — fewer than 4 words or generic phrase."""
    words = title.strip().split()
    if len(words) < 4:
        return True
    generic = {"sebi circular", "the circular", "said circular", "aforesaid circular"}
    return title.strip().lower() in generic


def _titles_similar(a: str, b: str) -> bool:
    """
    Check if two titles are suspiciously similar.
    Uses token overlap >= 60% — same logic as evaluator.py.
    """
    if not a or not b:
        return False
    na = re.sub(r"[^a-z0-9]", "", a.lower())
    nb = re.sub(r"[^a-z0-9]", "", b.lower())
    if na == nb:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta), len(tb))
    return overlap >= 0.6


def _call_judge(client, provider: str, prompt: str) -> dict:
    """Call the LLM and parse its JSON verdict."""
    if provider == "huggingface":
        response = client.chat.completions.create(
            model="Qwen/Qwen2.5-72B-Instruct",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()
    elif provider == "anthropic":
        response = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
    elif provider == "gemini":
        response = client.generate_content(prompt)
        raw = response.text.strip()
    else:
        return {"is_present": False, "reason": f"Unknown provider: {provider}"}

    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    return json.loads(raw.strip())


def judge_reference(ref: dict, pages: list, client, provider: str) -> dict:
    """Ask the LLM to verify a single extracted reference."""
    page_texts = []
    for p in pages:
        if p.page_number in ref.get("found_on_pages", []):
            page_texts.append(f"[Page {p.page_number}]\n{p.text[:2000]}")

    if not page_texts:
        return {"is_present": False, "reason": "Page not found in document"}

    prompt = JUDGE_PROMPT.format(
        page_text="\n\n".join(page_texts),
        reference=json.dumps(ref, indent=2)
    )

    try:
        return _call_judge(client, provider, prompt)
    except Exception as e:
        return {"is_present": False, "reason": str(e)}


# ─────────────────────────────────────────────
# Duplicate detection (no LLM needed)
# ─────────────────────────────────────────────

def detect_duplicates(references: list) -> list:
    """
    Detect references that are likely duplicates of each other.

    A duplicate is when two entries share:
      - same document_type + same date, with at least one having a vague title, OR
      - same circular_number (non-empty), OR
      - titles with >= 60% token overlap + same document_type

    Returns a list of duplicate pairs with explanation.
    """
    duplicates = []
    n = len(references)

    for i in range(n):
        for j in range(i + 1, n):
            a = references[i]
            b = references[j]

            reason = None

            # Check 1: same non-empty circular number
            cn_a = a.get("circular_number", "").strip()
            cn_b = b.get("circular_number", "").strip()
            if cn_a and cn_b and cn_a.lower() == cn_b.lower():
                reason = f"Same circular_number: '{cn_a}'"

            # Check 2: same date + same document_type + one has vague title
            elif (
                a.get("date") and b.get("date")
                and a["date"].strip().lower() == b["date"].strip().lower()
                and a.get("document_type") == b.get("document_type")
                and (_is_vague_title(a.get("title", "")) or _is_vague_title(b.get("title", "")))
            ):
                reason = (
                    f"Same date ({a['date']}) + type ({a['document_type']}) "
                    f"with vague title"
                )

            # Check 3: similar titles + same document_type
            elif (
                a.get("document_type") == b.get("document_type")
                and _titles_similar(a.get("title", ""), b.get("title", ""))
                and a.get("clause", "") == b.get("clause", "")
            ):
                reason = (
                    f"Similar titles ('{a.get('title','')}' ≈ '{b.get('title','')}') "
                    f"with same clause"
                )

            if reason:
                duplicates.append({
                    "index_a": i,
                    "index_b": j,
                    "title_a": a.get("title", ""),
                    "title_b": b.get("title", ""),
                    "reason": reason,
                })

    return duplicates


# ─────────────────────────────────────────────
# Source metadata validation
# ─────────────────────────────────────────────

def validate_source_metadata(source: dict, pages: list) -> list:
    """
    Check that the source document metadata looks correct.
    Validates circular_number, date, and title against page 1 text.
    Returns a list of warning strings.
    """
    warnings = []
    page1_text = pages[0].text if pages else ""

    # Check circular_number present
    circ = source.get("circular_number", "")
    if not circ:
        warnings.append("circular_number is empty — could not be detected from PDF")
    elif circ.lower() not in page1_text.lower():
        warnings.append(f"circular_number '{circ}' not found verbatim in page 1")

    # Check date present
    date = source.get("date", "")
    if not date:
        warnings.append("date is empty — could not be detected from PDF")

    # Check title doesn't look like a sentence fragment
    title = source.get("title", "")
    if not title:
        warnings.append("title (subject) is empty")
    elif len(title) > 120:
        warnings.append(f"title may be truncated or wrong — very long ({len(title)} chars): '{title[:80]}...'")
    elif title[0].islower():
        warnings.append(f"title starts with lowercase — likely a fragment: '{title[:60]}'")

    # Check addressees
    addressees = source.get("addressees", [])
    if not addressees:
        warnings.append("addressees list is empty — could not be detected from PDF")

    return warnings


# ─────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────

def run_llm_judge(
    predicted_path: str,
    pdf_path: str,
    provider: str,
    save_path: str = None
):
    # ── Load data ────────────────────────────────────────────────────
    with open(predicted_path) as f:
        data = json.load(f)
    references = data.get("references", [])
    source     = data.get("source_document", {})

    pages, _ = extract_pages(pdf_path)

    # ── Set up LLM client ────────────────────────────────────────────
    if provider == "huggingface":
        from huggingface_hub import InferenceClient
        client = InferenceClient(
            api_key=os.environ["HUGGINGFACE_TOKEN"],
            provider="auto"
        )
    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    elif provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        client = genai.GenerativeModel("gemini-2.0-flash")
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # ════════════════════════════════════════
    # CHECK 1 — Per-reference LLM verification
    # ════════════════════════════════════════
    console.print(f"\n[bold]Judging {len(references)} references...[/bold]\n")
    results = []

    for ref in references:
        verdict = judge_reference(ref, pages, client, provider)
        results.append({"reference": ref, "verdict": verdict})
        status = "✓" if verdict.get("is_present") else "✗"
        console.print(
            f"  {status} [cyan]{ref.get('title', '?')[:50]}[/cyan] "
            f"| clause: {ref.get('clause', '-') or '-'}"
        )
        reason = verdict.get("reason", "")
        if reason:
            console.print(f"    [dim]→ {reason}[/dim]")

    # Compute scores
    total        = len(results)
    present      = sum(1 for r in results if r["verdict"].get("is_present"))
    title_ok     = sum(1 for r in results if r["verdict"].get("title_accurate"))
    circnum_ok   = sum(1 for r in results if r["verdict"].get("circular_number_accurate"))
    date_ok      = sum(1 for r in results if r["verdict"].get("date_accurate"))
    clause_ok    = sum(1 for r in results if r["verdict"].get("clause_accurate"))

    t = Table(title="\nLLM-as-Judge Results (per reference)")
    t.add_column("Check")
    t.add_column("Score", justify="right")
    t.add_row("References present in source",  f"{present}/{total} ({present/total:.0%})" if total else "N/A")
    t.add_row("Title accuracy",                f"{title_ok}/{total} ({title_ok/total:.0%})" if total else "N/A")
    t.add_row("Circular number accuracy",      f"{circnum_ok}/{total} ({circnum_ok/total:.0%})" if total else "N/A")
    t.add_row("Date accuracy",                 f"{date_ok}/{total} ({date_ok/total:.0%})" if total else "N/A")
    t.add_row("Clause accuracy",               f"{clause_ok}/{total} ({clause_ok/total:.0%})" if total else "N/A")
    console.print(t)

    hallucinations = [r for r in results if not r["verdict"].get("is_present")]
    if hallucinations:
        console.print(f"\n[red]Hallucinated references ({len(hallucinations)}):[/red]")
        for h in hallucinations:
            console.print(f"  • {h['reference'].get('title', '?')}")
    else:
        console.print("\n[green]✓ No hallucinations detected[/green]")

    # ════════════════════════════════════════
    # CHECK 2 — Duplicate detection
    # ════════════════════════════════════════
    console.print("\n[bold]Duplicate Detection...[/bold]\n")
    duplicates = detect_duplicates(references)

    if duplicates:
        console.print(f"[yellow]⚠ Found {len(duplicates)} possible duplicate(s):[/yellow]")
        for d in duplicates:
            console.print(f"  • Entry {d['index_a']+1}: '{d['title_a'][:50]}'")
            console.print(f"    Entry {d['index_b']+1}: '{d['title_b'][:50]}'")
            console.print(f"    Reason: {d['reason']}\n")
    else:
        console.print("[green]✓ No duplicates detected[/green]")

    # ════════════════════════════════════════
    # CHECK 3 — Source metadata validation
    # ════════════════════════════════════════
    console.print("\n[bold]Source Metadata Validation...[/bold]\n")
    meta_warnings = validate_source_metadata(source, pages)

    if meta_warnings:
        console.print(f"[yellow]⚠ Metadata issues ({len(meta_warnings)}):[/yellow]")
        for w in meta_warnings:
            console.print(f"  • {w}")
    else:
        console.print("[green]✓ Source metadata looks correct[/green]")

    # ════════════════════════════════════════
    # Overall summary
    # ════════════════════════════════════════
    console.print("\n")
    summary = Table(title="Overall Judge Summary")
    summary.add_column("Check")
    summary.add_column("Result", justify="right")

    ref_score = f"{present}/{total} ({present/total:.0%})" if total else "N/A"
    dup_score = f"[red]{len(duplicates)} found[/red]" if duplicates else "[green]None[/green]"
    meta_score = f"[red]{len(meta_warnings)} issues[/red]" if meta_warnings else "[green]OK[/green]"

    summary.add_row("Reference accuracy (LLM)",  ref_score)
    summary.add_row("Duplicates detected",        dup_score)
    summary.add_row("Source metadata",            meta_score)
    console.print(summary)

    # ── Save results ─────────────────────────────────────────────────
    output = {
        "total_references": total,
        "llm_check": {
            "present": present,
            "title_accurate": title_ok,
            "circular_number_accurate": circnum_ok,
            "date_accurate": date_ok,
            "clause_accurate": clause_ok,
            "hallucinations": [r["reference"] for r in results if not r["verdict"].get("is_present")],
        },
        "duplicate_check": {
            "count": len(duplicates),
            "duplicates": duplicates,
        },
        "metadata_check": {
            "warnings": meta_warnings,
        },
        "detailed_results": results,
    }

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(output, f, indent=2)
        console.print(f"\n[dim]Saved to {save_path}[/dim]")

    return output


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LLM-as-Judge evaluation — no ground truth needed"
    )
    parser.add_argument("--predicted",  required=True, help="Agent output JSON")
    parser.add_argument("--pdf",        required=True, help="Original PDF file")
    parser.add_argument("--provider",   default="huggingface",
                        choices=["anthropic", "gemini", "huggingface"])
    parser.add_argument("--save",       help="Save results to this JSON file",
                        default="evals/results/llm_judge_v2.json")
    args = parser.parse_args()

    run_llm_judge(args.predicted, args.pdf, args.provider, args.save)


if __name__ == "__main__":
    main()