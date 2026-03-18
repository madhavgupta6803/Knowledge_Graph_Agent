"""
Evaluation Framework for the SEBI Knowledge Graph Agent

Evaluates agent output against a hand-annotated ground truth file and
computes Precision, Recall, F1 per field and in aggregate.

Ground truth format (JSON):
{
  "source_circular": "SEBI/HO/CFD/...",
  "references": [
    {
      "document_type": "circular",
      "title": "...",
      "circular_number": "SEBI/...",
      "date": "...",
      "clause": "...",
      "found_on_pages": [3, 5]
    },
    ...
  ]
}

Run:
    python -m evals.evaluator --predicted output/xyz_references.json \
                               --ground-truth evals/ground_truth/xyz.json

Or call `evaluate()` programmatically.
"""

from __future__ import annotations

import json
import re
import argparse
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from rich.console import Console
from rich.table import Table


console = Console()


# ─────────────────────────────────────────────
# Scoring helpers
# ─────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normalise a string for fuzzy comparison."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9/]", "", s)
    return s


def _title_match(a: str, b: str) -> bool:
    """
    Two titles match if either:
      • they share ≥60 % token overlap  (handles minor wording differences)
      • one is a substring of the other
    """
    if not a or not b:
        return False
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    # Token overlap
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta), len(tb))
    return overlap >= 0.6


def _circnum_match(a: str, b: str) -> bool:
    """Circular numbers match if both non-empty and normalised strings match."""
    if not a or not b:
        return bool(not a and not b)   # both empty → match
    return _norm(a) == _norm(b)


def _ref_matches(pred: Dict, gt: Dict) -> bool:
    """
    A predicted reference matches a ground-truth one if:
      • circular_number matches (when both present), OR
      • title fuzzy-matches (when circular_number absent in either)
    """
    if pred.get("circular_number") and gt.get("circular_number"):
        return _circnum_match(pred["circular_number"], gt["circular_number"])
    return _title_match(pred.get("title", ""), gt.get("title", ""))


# ─────────────────────────────────────────────
# Per-field scoring
# ─────────────────────────────────────────────

@dataclass
class FieldScores:
    field: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


# ─────────────────────────────────────────────
# Main evaluation logic
# ─────────────────────────────────────────────

@dataclass
class EvaluationResult:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    field_scores: Dict[str, FieldScores] = field(default_factory=dict)
    false_positives: List[Dict] = field(default_factory=list)
    false_negatives: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "field_scores": {
                k: {
                    "precision": round(v.precision, 4),
                    "recall": round(v.recall, 4),
                    "f1": round(v.f1, 4),
                }
                for k, v in self.field_scores.items()
            },
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
        }
        return d


def evaluate(
    predicted_refs: List[Dict],
    ground_truth_refs: List[Dict],
) -> EvaluationResult:
    """
    Compute precision / recall / F1 for reference extraction.

    Strategy:
      1. Build a bipartite matching between predicted and GT references.
      2. For each matched pair, score individual fields.
      3. Unmatched predictions → FP; unmatched GT → FN.
    """
    gt_matched = [False] * len(ground_truth_refs)
    pred_matched = [False] * len(predicted_refs)

    # Greedy matching (good enough at the scale of a single circular)
    for pi, pred in enumerate(predicted_refs):
        for gi, gt in enumerate(ground_truth_refs):
            if not gt_matched[gi] and _ref_matches(pred, gt):
                pred_matched[pi] = True
                gt_matched[gi] = True
                break

    tp = sum(pred_matched)
    fp = sum(not m for m in pred_matched)
    fn = sum(not m for m in gt_matched)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # Field-level scoring for matched pairs
    fields = ["document_type", "title", "circular_number", "date", "clause"]
    field_scores = {f: FieldScores(field=f) for f in fields}

    for pi, pred in enumerate(predicted_refs):
        for gi, gt in enumerate(ground_truth_refs):
            if pred_matched[pi] and gt_matched[gi] and _ref_matches(pred, gt):
                for f in fields:
                    pv = _norm(pred.get(f, "") or "")
                    gv = _norm(gt.get(f, "") or "")
                    if f == "title":
                        hit = _title_match(pred.get(f, ""), gt.get(f, ""))
                    else:
                        hit = pv == gv
                    if hit:
                        field_scores[f].tp += 1
                    else:
                        field_scores[f].fp += 1
                        field_scores[f].fn += 1

    false_positives = [predicted_refs[i] for i, m in enumerate(pred_matched) if not m]
    false_negatives = [ground_truth_refs[i] for i, m in enumerate(gt_matched) if not m]

    return EvaluationResult(
        precision=precision,
        recall=recall,
        f1=f1,
        tp=tp,
        fp=fp,
        fn=fn,
        field_scores=field_scores,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


# ─────────────────────────────────────────────
# Rich console report
# ─────────────────────────────────────────────

def print_report(result: EvaluationResult, label: str = "Evaluation") -> None:
    console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
    console.print(f"[bold]{label}[/bold]")
    console.print(f"[bold cyan]{'='*60}[/bold cyan]\n")

    # Top-level metrics
    t = Table(title="Overall Reference Detection", show_header=True)
    t.add_column("Metric", style="bold")
    t.add_column("Value", justify="right")
    t.add_row("Precision",  f"{result.precision:.1%}")
    t.add_row("Recall",     f"{result.recall:.1%}")
    t.add_row("F1 Score",   f"[bold green]{result.f1:.1%}[/bold green]")
    t.add_row("TP / FP / FN", f"{result.tp} / {result.fp} / {result.fn}")
    console.print(t)

    # Field-level metrics
    f = Table(title="\nPer-field Accuracy (matched pairs)", show_header=True)
    f.add_column("Field")
    f.add_column("Precision", justify="right")
    f.add_column("Recall", justify="right")
    f.add_column("F1", justify="right")
    for fname, fs in result.field_scores.items():
        f.add_row(fname, f"{fs.precision:.1%}", f"{fs.recall:.1%}", f"{fs.f1:.1%}")
    console.print(f)

    # False positives
    if result.false_positives:
        console.print(f"\n[yellow]False Positives ({len(result.false_positives)}):[/yellow]")
        for fp in result.false_positives[:5]:
            console.print(f"  • {fp.get('title', '?')[:70]}")

    # False negatives
    if result.false_negatives:
        console.print(f"\n[red]False Negatives ({len(result.false_negatives)}):[/red]")
        for fn in result.false_negatives[:5]:
            console.print(f"  • {fn.get('title', '?')[:70]}")


# ─────────────────────────────────────────────
# Comparison helper (before vs after improvement)
# ─────────────────────────────────────────────

def compare_runs(before: EvaluationResult, after: EvaluationResult) -> None:
    console.print("\n[bold magenta]Before vs After Comparison[/bold magenta]\n")
    t = Table(show_header=True)
    t.add_column("Metric")
    t.add_column("Before", justify="right")
    t.add_column("After", justify="right")
    t.add_column("Delta", justify="right")

    for label, bv, av in [
        ("Precision", before.precision, after.precision),
        ("Recall",    before.recall,    after.recall),
        ("F1",        before.f1,        after.f1),
    ]:
        delta = av - bv
        color = "green" if delta > 0 else "red" if delta < 0 else "white"
        t.add_row(
            label,
            f"{bv:.1%}",
            f"{av:.1%}",
            f"[{color}]{delta:+.1%}[/{color}]",
        )
    console.print(t)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Evaluate agent output against ground truth")
    parser.add_argument("--predicted",    required=True, help="Agent output JSON (from main.py)")
    parser.add_argument("--ground-truth", required=True, help="Hand-annotated ground truth JSON")
    parser.add_argument("--save",         help="Save evaluation result to this JSON file")
    args = parser.parse_args()

    with open(args.predicted) as f:
        predicted_data = json.load(f)
    with open(args.ground_truth) as f:
        gt_data = json.load(f)

    predicted_refs = predicted_data.get("references", [])
    gt_refs        = gt_data.get("references", [])

    result = evaluate(predicted_refs, gt_refs)
    print_report(result, label=f"Evaluation: {Path(args.predicted).stem}")

    if args.save:
        with open(args.save, "w") as f:
            json.dump(result.to_dict(), f, indent=2)
        console.print(f"\n[dim]Saved to {args.save}[/dim]")


if __name__ == "__main__":
    main()