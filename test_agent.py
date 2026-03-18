"""
Unit tests for the SEBI Knowledge Graph Agent.
Run with: pytest tests/ -v
"""

import pytest
from agent.reference_extractor import deduplicate_references, DocumentReference
from agent.pdf_parser import PageContent
from evals.evaluator import evaluate, _norm, _title_match, _circnum_match


# ─────────────────────────────────────────────
# Deduplication tests
# ─────────────────────────────────────────────

def make_raw_ref(**kwargs):
    defaults = {
        "document_type": "circular",
        "title": "",
        "circular_number": "",
        "date": "",
        "clause": "",
        "context": "",
        "page_number": 1,
    }
    defaults.update(kwargs)
    return defaults


class TestDeduplication:
    def test_same_circular_number_merged(self):
        refs = [
            make_raw_ref(circular_number="SEBI/HO/ABC/2020/1", page_number=1),
            make_raw_ref(circular_number="SEBI/HO/ABC/2020/1", page_number=4),
        ]
        result = deduplicate_references(refs)
        assert len(result) == 1
        assert result[0].found_on_pages == [1, 4]

    def test_different_circulars_not_merged(self):
        refs = [
            make_raw_ref(circular_number="SEBI/HO/ABC/2020/1"),
            make_raw_ref(circular_number="SEBI/HO/ABC/2020/2"),
        ]
        result = deduplicate_references(refs)
        assert len(result) == 2

    def test_title_based_dedup(self):
        refs = [
            make_raw_ref(title="SEBI (LODR) Regulations, 2015", page_number=2),
            make_raw_ref(title="SEBI (LODR) Regulations, 2015", page_number=7),
        ]
        result = deduplicate_references(refs)
        assert len(result) == 1

    def test_longer_title_wins(self):
        refs = [
            make_raw_ref(title="SEBI Act", circular_number="ACT1992", page_number=1),
            make_raw_ref(title="Securities and Exchange Board of India Act, 1992", circular_number="ACT1992", page_number=3),
        ]
        result = deduplicate_references(refs)
        assert result[0].title == "Securities and Exchange Board of India Act, 1992"

    def test_empty_refs_ignored(self):
        refs = [make_raw_ref(title="", circular_number="")]
        result = deduplicate_references(refs)
        assert len(result) == 0


# ─────────────────────────────────────────────
# Evaluator tests
# ─────────────────────────────────────────────

class TestEvaluator:
    def test_perfect_match(self):
        refs = [{"circular_number": "SEBI/HO/1", "title": "Circ One", "document_type": "circular",
                 "date": "", "clause": ""}]
        result = evaluate(refs, refs)
        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.f1 == 1.0

    def test_no_predictions(self):
        gt = [{"circular_number": "SEBI/HO/1", "title": "Circ One", "document_type": "circular",
               "date": "", "clause": ""}]
        result = evaluate([], gt)
        assert result.precision == 0.0
        assert result.recall == 0.0
        assert result.fn == 1

    def test_extra_prediction_is_fp(self):
        gt   = [{"circular_number": "SEBI/1", "title": "A", "document_type": "circular", "date": "", "clause": ""}]
        pred = [
            {"circular_number": "SEBI/1", "title": "A", "document_type": "circular", "date": "", "clause": ""},
            {"circular_number": "SEBI/2", "title": "B", "document_type": "circular", "date": "", "clause": ""},
        ]
        result = evaluate(pred, gt)
        assert result.tp == 1
        assert result.fp == 1
        assert result.fn == 0

    def test_title_fuzzy_match(self):
        pred = [{"circular_number": "", "title": "SEBI LODR Regulations 2015",    "document_type": "regulation", "date": "", "clause": ""}]
        gt   = [{"circular_number": "", "title": "SEBI (LODR) Regulations, 2015", "document_type": "regulation", "date": "", "clause": ""}]
        result = evaluate(pred, gt)
        assert result.tp == 1


class TestNormHelpers:
    def test_norm_strips_special_chars(self):
        assert _norm("SEBI/HO/2020") == "sebiho2020"

    def test_title_match_substring(self):
        assert _title_match("SEBI Act 1992", "Securities and Exchange Board of India Act, 1992")

    def test_circnum_match(self):
        assert _circnum_match("SEBI/HO/CFD/DIL1/CIR/P/2019/62", "sebi/ho/cfd/dil1/cir/p/2019/62")

    def test_circnum_no_match(self):
        assert not _circnum_match("SEBI/HO/1", "SEBI/HO/2")