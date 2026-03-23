"""
Regex Cross-Check: zero-cost automatic verification.
Checks that circular numbers, dates, and clause numbers
extracted by the agent actually appear in the PDF text.
"""

import json
import re
import argparse
from agent.pdf_parser import extract_pages
from rich.console import Console
from rich.table import Table

console = Console()

def check_field_present(value: str, full_text: str) -> bool:
    """Check if a value appears verbatim in the document text."""
    if not value:
        return True   # empty fields are not wrong
    return value.strip().lower() in full_text.lower()

def run_regex_check(predicted_path: str, pdf_path: str):
    with open(predicted_path) as f:
        data = json.load(f)
    references = data.get("references", [])

    pages, _ = extract_pages(pdf_path)
    full_text = " ".join(p.text for p in pages)

    results = []
    for ref in references:
        row = {
            "title":           ref.get("title", ""),
            "circular_number": ref.get("circular_number", ""),
            "date":            ref.get("date", ""),
            "clause":          ref.get("clause", ""),
            "circnum_found":   check_field_present(ref.get("circular_number",""), full_text),
            "date_found":      check_field_present(ref.get("date",""), full_text),
            # Normalize clause check: strip "para " prefix
            "clause_found":    check_field_present(
                re.sub(r"^para\s+", "", ref.get("clause",""), flags=re.IGNORECASE),
                full_text
            ),
        }
        row["all_ok"] = row["circnum_found"] and row["date_found"] and row["clause_found"]
        results.append(row)

    total   = len(results)
    all_ok  = sum(1 for r in results if r["all_ok"])

    t = Table(title="Regex Cross-Check Results")
    t.add_column("Title", max_width=40)
    t.add_column("Circ#", justify="center")
    t.add_column("Date",  justify="center")
    t.add_column("Clause",justify="center")
    for r in results:
        t.add_row(
            r["title"][:40],
            "✓" if r["circnum_found"] else "✗",
            "✓" if r["date_found"]    else "✗",
            "✓" if r["clause_found"]  else "✗",
        )
    console.print(t)
    console.print(f"\n[bold]Overall: {all_ok}/{total} references fully verified[/bold]")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predicted", required=True)
    parser.add_argument("--pdf",       required=True)
    args = parser.parse_args()
    run_regex_check(args.predicted, args.pdf)

if __name__ == "__main__":
    main()