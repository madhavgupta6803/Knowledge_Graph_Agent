"""
Reference Extractor: Uses an LLM to identify and structure all references
to external documents found in a SEBI circular.

Supports both Anthropic Claude and Google Gemini as backends.
"""

import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Literal
from .pdf_parser import PageContent


# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────

@dataclass
class DocumentReference:
    document_type: str          # circular | regulation | act | notification | master_circular | other
    title: str
    circular_number: str = ""
    date: str = ""
    clause: str = ""            # specific section/clause referenced
    context: str = ""           # why it is referenced
    found_on_pages: List[int] = field(default_factory=list)
    confidence: float = 1.0     # 0-1, set during evaluation

    def dedup_key(self) -> str:
        """Canonical key used to merge duplicates across pages."""
        return (self.circular_number or self.title).strip().lower()

    def to_dict(self) -> Dict:
        return asdict(self)


# ─────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert regulatory analyst specialising in Indian securities law.
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

PAGE_USER_PROMPT = """Page number: {page_number}

--- BEGIN PAGE TEXT ---
{text}
--- END PAGE TEXT ---

Extract all references to external documents from this page."""


# ─────────────────────────────────────────────
# LLM client wrappers
# ─────────────────────────────────────────────

def _call_anthropic(client, text: str, page_number: int) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": PAGE_USER_PROMPT.format(
                page_number=page_number,
                text=text[:5000]          # stay well within context limits
            )
        }]
    )
    return response.content[0].text.strip()


def _call_gemini(model, text: str, page_number: int) -> str:
    prompt = SYSTEM_PROMPT + "\n\n" + PAGE_USER_PROMPT.format(
        page_number=page_number,
        text=text[:5000]
    )
    response = model.generate_content(prompt)
    return response.text.strip()


# ─────────────────────────────────────────────
# Parsing helper
# ─────────────────────────────────────────────

def _parse_llm_response(raw: str, page_number: int) -> List[Dict]:
    """Robustly parse the LLM's JSON output, stripping markdown fences if present."""
    # Strip ```json ... ``` fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    if not raw or raw == "[]":
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Attempt to find a JSON array anywhere in the output
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except Exception:
                return []
        else:
            return []

    # Ensure page_number is set and types are correct
    results = []
    for item in data:
        if not isinstance(item, dict):
            continue
        item["page_number"] = page_number
        item.setdefault("document_type", "other")
        item.setdefault("title", "")
        item.setdefault("circular_number", "")
        item.setdefault("date", "")
        item.setdefault("clause", "")
        item.setdefault("context", "")
        results.append(item)
    return results


# ─────────────────────────────────────────────
# Main extraction logic
# ─────────────────────────────────────────────

def extract_references_from_page(
    page: PageContent,
    client,
    provider: Literal["anthropic", "gemini"] = "anthropic",
    retry_on_error: bool = True,
) -> List[Dict]:
    """Extract references from a single page using the chosen LLM provider."""
    if not page.text.strip():
        return []

    for attempt in range(2):
        try:
            if provider == "anthropic":
                raw = _call_anthropic(client, page.text, page.page_number)
            else:
                raw = _call_gemini(client, page.text, page.page_number)
            return _parse_llm_response(raw, page.page_number)
        except Exception as e:
            if attempt == 0 and retry_on_error:
                time.sleep(2)
            else:
                print(f"  [WARNING] Page {page.page_number} extraction failed: {e}")
                return []
    return []


def deduplicate_references(raw_refs: List[Dict]) -> List[DocumentReference]:
    """
    Merge references to the same document found on multiple pages.
    Deduplication is based on circular_number (preferred) or normalised title.
    """
    merged: Dict[str, DocumentReference] = {}

    for r in raw_refs:
        ref = DocumentReference(
            document_type=r.get("document_type", "other"),
            title=r.get("title", ""),
            circular_number=r.get("circular_number", ""),
            date=r.get("date", ""),
            clause=r.get("clause", ""),
            context=r.get("context", ""),
            found_on_pages=[r.get("page_number", 0)],
        )
        key = ref.dedup_key()
        if not key:
            continue

        if key in merged:
            existing = merged[key]
            # Merge page numbers
            page = r.get("page_number", 0)
            if page and page not in existing.found_on_pages:
                existing.found_on_pages.append(page)
            # Fill empty fields
            if not existing.circular_number and ref.circular_number:
                existing.circular_number = ref.circular_number
            if not existing.date and ref.date:
                existing.date = ref.date
            if not existing.clause and ref.clause:
                existing.clause = ref.clause
            if len(ref.title) > len(existing.title):
                existing.title = ref.title
        else:
            merged[key] = ref

    # Sort page numbers
    for ref in merged.values():
        ref.found_on_pages = sorted(set(ref.found_on_pages))

    return list(merged.values())