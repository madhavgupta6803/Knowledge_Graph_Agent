"""
LLM-as-Judge Evaluator
======================
Automatically scores agent output WITHOUT needing a ground truth file.
For each extracted reference, asks the LLM:
  1. Is this reference actually present in the source text? (hallucination check)
  2. Are the fields (title, clause, date) accurate? (accuracy check)

Run:
    python -m evals.llm_judge --predicted output/circular_references.json \
                               --pdf sebi_circular.pdf \
                               --provider huggingface
"""

import json
import argparse
import re
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
  "reason": "one sentence explanation if anything is wrong"
}}

PAGE TEXT:
{page_text}

EXTRACTED REFERENCE:
{reference}
"""


def judge_reference(ref: dict, pages: list, client, provider: str) -> dict:
    """Ask the LLM to verify a single extracted reference."""
    # Find the pages this reference was found on
    page_texts = []
    for p in pages:
        if p.page_number in ref.get("found_on_pages", []):
            page_texts.append(f"[Page {p.page_number}]\n{p.text[:2000]}")
    
    if not page_texts:
        return {"is_present": False, "reason": "Page not found"}

    prompt = JUDGE_PROMPT.format(
        page_text="\n\n".join(page_texts),
        reference=json.dumps(ref, indent=2)
    )

    try:
        if provider == "huggingface":
            response = client.chat_completion(
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

        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
        return json.loads(raw.strip())

    except Exception as e:
        return {"is_present": False, "reason": str(e)}


def run_llm_judge(predicted_path: str, pdf_path: str, provider: str, save_path: str = None):
    import os
    from huggingface_hub import InferenceClient
    import anthropic

    # Load predicted references
    with open(predicted_path) as f:
        data = json.load(f)
    references = data.get("references", [])

    # Extract pages
    pages, _ = extract_pages(pdf_path)

    # Set up client
    if provider == "huggingface":
        client = InferenceClient(
            model="Qwen/Qwen2.5-72B-Instruct",
            api_key=os.environ["HUGGINGFACE_TOKEN"]
        )
    elif provider == "anthropic":
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Judge each reference
    results = []
    print(f"\nJudging {len(references)} references...\n")

    for ref in references:
        verdict = judge_reference(ref, pages, client, provider)
        results.append({"reference": ref, "verdict": verdict})
        status = "✓" if verdict.get("is_present") else "✗"
        print(f"  {status} {ref.get('title', '?')[:50]} | clause: {ref.get('clause', '-')}")
        if not verdict.get("is_present") or verdict.get("reason"):
            print(f"    → {verdict.get('reason', '')}")

    # Compute scores
    total = len(results)
    present       = sum(1 for r in results if r["verdict"].get("is_present"))
    title_ok      = sum(1 for r in results if r["verdict"].get("title_accurate"))
    circnum_ok    = sum(1 for r in results if r["verdict"].get("circular_number_accurate"))
    date_ok       = sum(1 for r in results if r["verdict"].get("date_accurate"))
    clause_ok     = sum(1 for r in results if r["verdict"].get("clause_accurate"))

    console.print("\n")
    t = Table(title="LLM-as-Judge Results (no ground truth needed)")
    t.add_column("Check")
    t.add_column("Score", justify="right")
    t.add_row("References present in source",  f"{present}/{total} ({present/total:.0%})")
    t.add_row("Title accuracy",                f"{title_ok}/{total} ({title_ok/total:.0%})")
    t.add_row("Circular number accuracy",      f"{circnum_ok}/{total} ({circnum_ok/total:.0%})")
    t.add_row("Date accuracy",                 f"{date_ok}/{total} ({date_ok/total:.0%})")
    t.add_row("Clause accuracy",               f"{clause_ok}/{total} ({clause_ok/total:.0%})")
    console.print(t)

    hallucinations = [r for r in results if not r["verdict"].get("is_present")]
    if hallucinations:
        console.print(f"\n[red]Hallucinated references ({len(hallucinations)}):[/red]")
        for h in hallucinations:
            console.print(f"  • {h['reference'].get('title', '?')}")

    if save_path:
        with open(save_path, "w") as f:
            json.dump({"total": total, "results": results}, f, indent=2)
        print(f"\nSaved to {save_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predicted",  required=True)
    parser.add_argument("--pdf",        required=True)
    parser.add_argument("--provider",   default="huggingface",
                        choices=["anthropic", "gemini", "huggingface"])
    parser.add_argument("--save",       help="Save results to this JSON file")
    args = parser.parse_args()

    run_llm_judge(args.predicted, args.pdf, args.provider, args.save)


if __name__ == "__main__":
    main()