# """
# Reference Extractor: Uses an LLM to identify and structure all references
# to external documents found in a SEBI circular.

# Supports both Anthropic Claude and Google Gemini as backends.
# """

# import json
# import re
# import time
# from dataclasses import dataclass, field, asdict
# from typing import List, Dict, Optional, Literal
# from pdf_parser import PageContent


# # ─────────────────────────────────────────────
# # Data model
# # ─────────────────────────────────────────────

# @dataclass
# class DocumentReference:
#     document_type: str          # circular | regulation | act | notification | master_circular | other
#     title: str
#     circular_number: str = ""
#     date: str = ""
#     clause: str = ""            # specific section/clause referenced
#     context: str = ""           # why it is referenced
#     found_on_pages: List[int] = field(default_factory=list)
#     confidence: float = 1.0     # 0-1, set during evaluation

#     def dedup_key(self) -> str:
#         """Canonical key used to merge duplicates across pages."""
#         return (self.circular_number or self.title).strip().lower()

#     def to_dict(self) -> Dict:
#         return asdict(self)


# # ─────────────────────────────────────────────
# # Prompts
# # ─────────────────────────────────────────────

# SYSTEM_PROMPT = """You are an expert regulatory analyst specialising in Indian securities law.
# Your job is to extract every reference to an external document from a page of a SEBI circular.

# External documents include, but are not limited to:
#   • Other SEBI circulars (e.g. SEBI/HO/…/CIR/P/2019/62)
#   • SEBI Regulations (e.g. SEBI (LODR) Regulations, 2015)
#   • Acts of Parliament (e.g. SCRA 1956, Companies Act 2013)
#   • Master Circulars, Guidelines, Directions, Notifications
#   • RBI/IRDAI/other-regulator documents referenced in the text

# Rules:
# 1. Return ONLY a valid JSON array — no prose, no markdown fences.
# 2. Each element must have these exact keys:
#      document_type, title, circular_number, date, clause, context
# 3. If a field is unknown, use an empty string "".
# 4. document_type must be one of:
#      circular | regulation | act | notification | master_circular | other
# 5. Include the page_number field set to the integer provided.
# 6. Do NOT invent references not present in the text.
# 7. If the page has no external references, return [].
# """

# PAGE_USER_PROMPT = """Page number: {page_number}

# --- BEGIN PAGE TEXT ---
# {text}
# --- END PAGE TEXT ---

# Extract all references to external documents from this page."""


# # ─────────────────────────────────────────────
# # LLM client wrappers
# # ─────────────────────────────────────────────

# def _call_anthropic(client, text: str, page_number: int) -> str:
#     response = client.messages.create(
#         model="claude-sonnet-4-20250514",
#         max_tokens=2000,
#         system=SYSTEM_PROMPT,
#         messages=[{
#             "role": "user",
#             "content": PAGE_USER_PROMPT.format(
#                 page_number=page_number,
#                 text=text[:5000]          # stay well within context limits
#             )
#         }]
#     )
#     return response.content[0].text.strip()


# def _call_gemini(model, text: str, page_number: int) -> str:
#     prompt = SYSTEM_PROMPT + "\n\n" + PAGE_USER_PROMPT.format(
#         page_number=page_number,
#         text=text[:5000]
#     )
#     response = model.generate_content(prompt)
#     return response.text.strip()


# # ─────────────────────────────────────────────
# # Parsing helper
# # ─────────────────────────────────────────────

# def _parse_llm_response(raw: str, page_number: int) -> List[Dict]:
#     """Robustly parse the LLM's JSON output, stripping markdown fences if present."""
#     # Strip ```json ... ``` fences
#     raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
#     raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
#     raw = raw.strip()

#     if not raw or raw == "[]":
#         return []

#     try:
#         data = json.loads(raw)
#     except json.JSONDecodeError:
#         # Attempt to find a JSON array anywhere in the output
#         m = re.search(r"\[.*\]", raw, re.DOTALL)
#         if m:
#             try:
#                 data = json.loads(m.group())
#             except Exception:
#                 return []
#         else:
#             return []

#     # Ensure page_number is set and types are correct
#     results = []
#     for item in data:
#         if not isinstance(item, dict):
#             continue
#         item["page_number"] = page_number
#         item.setdefault("document_type", "other")
#         item.setdefault("title", "")
#         item.setdefault("circular_number", "")
#         item.setdefault("date", "")
#         item.setdefault("clause", "")
#         item.setdefault("context", "")
#         results.append(item)
#     return results


# # ─────────────────────────────────────────────
# # Main extraction logic
# # ─────────────────────────────────────────────

# def extract_references_from_page(
#     page: PageContent,
#     client,
#     provider: Literal["anthropic", "gemini"] = "anthropic",
#     retry_on_error: bool = True,
# ) -> List[Dict]:
#     """Extract references from a single page using the chosen LLM provider."""
#     if not page.text.strip():
#         return []

#     for attempt in range(2):
#         try:
#             if provider == "anthropic":
#                 raw = _call_anthropic(client, page.text, page.page_number)
#             else:
#                 raw = _call_gemini(client, page.text, page.page_number)
#             return _parse_llm_response(raw, page.page_number)
#         except Exception as e:
#             if attempt == 0 and retry_on_error:
#                 time.sleep(2)
#             else:
#                 print(f"  [WARNING] Page {page.page_number} extraction failed: {e}")
#                 return []
#     return []


# def deduplicate_references(raw_refs: List[Dict]) -> List[DocumentReference]:
#     """
#     Merge references to the same document found on multiple pages.
#     Deduplication is based on circular_number (preferred) or normalised title.
#     """
#     merged: Dict[str, DocumentReference] = {}

#     for r in raw_refs:
#         ref = DocumentReference(
#             document_type=r.get("document_type", "other"),
#             title=r.get("title", ""),
#             circular_number=r.get("circular_number", ""),
#             date=r.get("date", ""),
#             clause=r.get("clause", ""),
#             context=r.get("context", ""),
#             found_on_pages=[r.get("page_number", 0)],
#         )
#         key = ref.dedup_key()
#         if not key:
#             continue

#         if key in merged:
#             existing = merged[key]
#             # Merge page numbers
#             page = r.get("page_number", 0)
#             if page and page not in existing.found_on_pages:
#                 existing.found_on_pages.append(page)
#             # Fill empty fields
#             if not existing.circular_number and ref.circular_number:
#                 existing.circular_number = ref.circular_number
#             if not existing.date and ref.date:
#                 existing.date = ref.date
#             if not existing.clause and ref.clause:
#                 existing.clause = ref.clause
#             if len(ref.title) > len(existing.title):
#                 existing.title = ref.title
#         else:
#             merged[key] = ref

#     # Sort page numbers
#     for ref in merged.values():
#         ref.found_on_pages = sorted(set(ref.found_on_pages))

#     return list(merged.values())


# """
# Reference Extractor: Uses an LLM to identify and structure all references
# to external documents found in a SEBI circular.

# Supports Anthropic Claude, Google Gemini, and Hugging Face (Qwen) as backends.
# """

# import json
# import re
# import time
# from dataclasses import dataclass, field, asdict
# from typing import List, Dict, Optional, Literal
# from .pdf_parser import PageContent


# # ─────────────────────────────────────────────
# # Data model
# # ─────────────────────────────────────────────

# @dataclass
# class DocumentReference:
#     document_type: str          # circular | regulation | act | notification | master_circular | other
#     title: str
#     circular_number: str = ""
#     date: str = ""
#     clause: str = ""            # specific section/clause referenced
#     context: str = ""           # why it is referenced
#     found_on_pages: List[int] = field(default_factory=list)
#     confidence: float = 1.0     # 0-1, set during evaluation

#     def dedup_key(self) -> str:
#         """Canonical key used to merge duplicates across pages."""
#         return (self.circular_number or self.title).strip().lower()

#     def to_dict(self) -> Dict:
#         return asdict(self)


# # ─────────────────────────────────────────────
# # Prompts
# # ─────────────────────────────────────────────

# # SYSTEM_PROMPT = """You are an expert regulatory analyst specialising in Indian securities law.
# # Your job is to extract every reference to an external document from a page of a SEBI circular.

# # External documents include, but are not limited to:
# #   • Other SEBI circulars (e.g. SEBI/HO/…/CIR/P/2019/62)
# #   • SEBI Regulations (e.g. SEBI (LODR) Regulations, 2015)
# #   • Acts of Parliament (e.g. SCRA 1956, Companies Act 2013)
# #   • Master Circulars, Guidelines, Directions, Notifications
# #   • RBI/IRDAI/other-regulator documents referenced in the text

# # Rules:
# # 1. Return ONLY a valid JSON array — no prose, no markdown fences.
# # 2. Each element must have these exact keys:
# #      document_type, title, circular_number, date, clause, context
# # 3. If a field is unknown, use an empty string "".
# # 4. document_type must be one of:
# #      circular | regulation | act | notification | master_circular | other
# # 5. Include the page_number field set to the integer provided.
# # 6. Do NOT invent references not present in the text.
# # 7. If the page has no external references, return [].
# # """

# SYSTEM_PROMPT = SYSTEM_PROMPT = """You are an expert regulatory analyst specialising in Indian securities law.
# Your job is to extract every reference to an external document from a page of a SEBI circular.

# External documents include, but are not limited to:
#   • Other SEBI circulars (e.g. SEBI/HO/…/CIR/P/2019/62)
#   • SEBI Regulations (e.g. SEBI (LODR) Regulations, 2015)
#   • Acts of Parliament (e.g. SCRA 1956, Companies Act 2013)
#   • Master Circulars, Guidelines, Directions, Notifications
#   • RBI/IRDAI/other-regulator documents referenced in the text

# Rules:
# 1. Return ONLY a valid JSON array — no prose, no markdown fences.
# 2. Each element must have these exact keys:
#      document_type, title, circular_number, date, clause, context
# 3. If a field is unknown, use an empty string "".
# 4. document_type must be one of:
#      circular | regulation | act | notification | master_circular | other
# 5. Include the page_number field set to the integer provided.
# 6. Do NOT invent references not present in the text.
# 7. If the page has no external references, return [].
# 8. If the SAME document is referenced with DIFFERENT clauses or paragraphs,
#    extract it as a SEPARATE entry for each distinct clause/paragraph reference.
#    Example: para 10.9 and para 16.8 of the same Master Circular = two entries.
# 9. NEVER put a date in the circular_number field. If you cannot find the
#    circular number, leave circular_number as empty string "".
# 10. When a document was already referenced earlier with a full circular number,
#     and is referenced again only by date or partial name, still populate
#     circular_number with the full number you saw earlier on the same page.
# """

# PAGE_USER_PROMPT = """Page number: {page_number}

# --- BEGIN PAGE TEXT ---
# {text}
# --- END PAGE TEXT ---

# Extract all references to external documents from this page."""


# # ─────────────────────────────────────────────
# # LLM client wrappers
# # ─────────────────────────────────────────────

# def _call_anthropic(client, text: str, page_number: int) -> str:
#     response = client.messages.create(
#         model="claude-3-5-sonnet-20240620",
#         max_tokens=2000,
#         system=SYSTEM_PROMPT,
#         messages=[{
#             "role": "user",
#             "content": PAGE_USER_PROMPT.format(
#                 page_number=page_number,
#                 text=text[:5000]
#             )
#         }]
#     )
#     return response.content[0].text.strip()


# def _call_gemini(model, text: str, page_number: int) -> str:
#     # Gemini 1.5/2.0 use generate_content
#     prompt = SYSTEM_PROMPT + "\n\n" + PAGE_USER_PROMPT.format(
#         page_number=page_number,
#         text=text[:5000]
#     )
#     response = model.generate_content(prompt)
#     return response.text.strip()


# def _call_huggingface(client, text: str, page_number: int) -> str:
#     # Hugging Face InferenceClient uses chat_completion
#     # Combined System and User prompt for models that prefer single-turn instructions
#     full_prompt = f"{SYSTEM_PROMPT}\n\n{PAGE_USER_PROMPT.format(page_number=page_number, text=text[:5000])}"
    
#     response = client.chat_completion(
#         messages=[{"role": "user", "content": full_prompt}],
#         max_tokens=2000,
#         temperature=0.1
#     )
#     return response.choices[0].message.content.strip()


# # ─────────────────────────────────────────────
# # Parsing helper
# # ─────────────────────────────────────────────

# def _parse_llm_response(raw: str, page_number: int) -> List[Dict]:
#     """Robustly parse the LLM's JSON output, stripping markdown fences if present."""
#     # Strip ```json ... ``` fences
#     raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
#     raw = raw.strip()

#     if not raw or raw == "[]":
#         return []

#     try:
#         data = json.loads(raw)
#     except json.JSONDecodeError:
#         # Attempt to find a JSON array anywhere in the output
#         m = re.search(r"\[.*\]", raw, re.DOTALL)
#         if m:
#             try:
#                 data = json.loads(m.group())
#             except Exception:
#                 return []
#         else:
#             return []

#     # Ensure page_number is set and types are correct
#     results = []
#     if isinstance(data, list):
#         for item in data:
#             if not isinstance(item, dict):
#                 continue
#             item["page_number"] = page_number
#             item.setdefault("document_type", "other")
#             item.setdefault("title", "")
#             item.setdefault("circular_number", "")
#             item.setdefault("date", "")
#             item.setdefault("clause", "")
#             item.setdefault("context", "")
#             results.append(item)
#     return results


# # ─────────────────────────────────────────────
# # Main extraction logic
# # ─────────────────────────────────────────────

# def extract_references_from_page(
#     page: PageContent,
#     client,
#     provider: Literal["anthropic", "gemini", "huggingface"] = "anthropic",
#     retry_on_error: bool = True,
# ) -> List[Dict]:
#     """Extract references from a single page using the chosen LLM provider."""
#     if not page.text.strip():
#         return []

#     for attempt in range(2):
#         try:
#             if provider == "anthropic":
#                 raw = _call_anthropic(client, page.text, page.page_number)
#             elif provider == "gemini":
#                 raw = _call_gemini(client, page.text, page.page_number)
#             elif provider == "huggingface":
#                 raw = _call_huggingface(client, page.text, page.page_number)
#             else:
#                 raise ValueError(f"Unsupported provider: {provider}")
                
#             return _parse_llm_response(raw, page.page_number)
#         except Exception as e:
#             if attempt == 0 and retry_on_error:
#                 time.sleep(3) # Slightly longer sleep for API cooling
#             else:
#                 print(f"  [WARNING] Page {page.page_number} extraction failed: {e}")
#                 return []
#     return []


# def deduplicate_references(raw_refs: List[Dict]) -> List[DocumentReference]:
#     """
#     Merge references to the same document found on multiple pages.
#     """
#     merged: Dict[str, DocumentReference] = {}

#     for r in raw_refs:
#         ref = DocumentReference(
#             document_type=r.get("document_type", "other"),
#             title=r.get("title", ""),
#             circular_number=r.get("circular_number", ""),
#             date=r.get("date", ""),
#             clause=r.get("clause", ""),
#             context=r.get("context", ""),
#             found_on_pages=[r.get("page_number", 0)],
#         )
#         key = ref.dedup_key()
#         if not key:
#             continue

#         if key in merged:
#             existing = merged[key]
#             page = r.get("page_number", 0)
#             if page and page not in existing.found_on_pages:
#                 existing.found_on_pages.append(page)
#             if not existing.circular_number and ref.circular_number:
#                 existing.circular_number = ref.circular_number
#             if not existing.date and ref.date:
#                 existing.date = ref.date
#             if not existing.clause and ref.clause:
#                 existing.clause = ref.clause
#             if len(ref.title) > len(existing.title):
#                 existing.title = ref.title
#         else:
#             merged[key] = ref

#     for ref in merged.values():
#         ref.found_on_pages = sorted(set(ref.found_on_pages))

#     return list(merged.values())

"""
Reference Extractor: Uses an LLM to identify and structure all references
to external documents found in a SEBI circular.

Supports Anthropic Claude, Google Gemini, and Hugging Face (Qwen) as backends.
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

    # def dedup_key(self) -> str:
    #     """Canonical key used to merge duplicates across pages."""
    #     return (self.circular_number or self.title).strip().lower()

    def dedup_key(self) -> str:
        title_part = self.title.strip().lower()
        # Normalize clause: strip "para ", "regulation ", "section " prefixes
        clause_raw = self.clause.strip().lower()
        clause_part = re.sub(r"^(para|regulation|section|reg\.?)\s+", "", clause_raw)
        return f"{title_part}::{clause_part}" if clause_part else title_part

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
8. If the SAME document is referenced with DIFFERENT clauses or paragraphs,
   extract it as a SEPARATE entry for each distinct clause/paragraph reference.
   Example: para 10.9 and para 16.8 of the same Master Circular = two entries.
9. NEVER put a date in the circular_number field. If you cannot find the
   circular number, leave circular_number as empty string "".
10. When a document was already referenced earlier with a full circular number,
    and is referenced again only by date or partial name, still populate
    circular_number with the full number you saw earlier on the same page.
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
        model="claude-3-5-sonnet-20240620",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": PAGE_USER_PROMPT.format(
                page_number=page_number,
                text=text[:5000]
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


def _call_huggingface(client, text: str, page_number: int) -> str:
    full_prompt = f"{SYSTEM_PROMPT}\n\n{PAGE_USER_PROMPT.format(page_number=page_number, text=text[:5000])}"
    response = client.chat_completion(
        messages=[{"role": "user", "content": full_prompt}],
        max_tokens=2000,
        temperature=0.1
    )
    return response.choices[0].message.content.strip()

def _clean_circular_number(value: str) -> str:
    """Remove values that are clearly dates, not circular numbers."""
    if not value:
        return ""
    if re.match(r"^dated\b", value.strip(), re.IGNORECASE):
        return ""
    if re.match(r"^\d{1,2}\s+\w+\s+\d{4}$", value.strip()):
        return ""
    return value

# ─────────────────────────────────────────────
# Parsing helper
# ─────────────────────────────────────────────

def _parse_llm_response(raw: str, page_number: int) -> List[Dict]:
    """Robustly parse the LLM's JSON output, stripping markdown fences if present."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    if not raw or raw == "[]":
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except Exception:
                return []
        else:
            return []

    results = []
    if isinstance(data, list):
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
            item["circular_number"] = _clean_circular_number(item.get("circular_number", ""))
            results.append(item)
    return results


# ─────────────────────────────────────────────
# Main extraction logic
# ─────────────────────────────────────────────

def extract_references_from_page(
    page: PageContent,
    client,
    provider: Literal["anthropic", "gemini", "huggingface"] = "anthropic",
    retry_on_error: bool = True,
) -> List[Dict]:
    """Extract references from a single page using the chosen LLM provider."""
    if not page.text.strip():
        return []

    for attempt in range(2):
        try:
            if provider == "anthropic":
                raw = _call_anthropic(client, page.text, page.page_number)
            elif provider == "gemini":
                raw = _call_gemini(client, page.text, page.page_number)
            elif provider == "huggingface":
                raw = _call_huggingface(client, page.text, page.page_number)
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            return _parse_llm_response(raw, page.page_number)
        except Exception as e:
            if attempt == 0 and retry_on_error:
                time.sleep(3)
            else:
                print(f"  [WARNING] Page {page.page_number} extraction failed: {e}")
                return []
    return []


# ─────────────────────────────────────────────
# FIX 1 — Date-based dedup fallback
# ─────────────────────────────────────────────

def _is_vague_title(title: str) -> bool:
    """A title is vague if it's fewer than 4 words or is a generic placeholder."""
    words = title.strip().split()
    if len(words) < 4:
        return True
    generic = {"sebi circular", "the circular", "said circular", "aforesaid circular"}
    if title.strip().lower() in generic:
        return True
    return False


def _date_and_type_match(a: DocumentReference, b: DocumentReference) -> bool:
    """
    Last-resort dedup match: same document_type + same date + at least one vague title.
    Catches cases like 'SEBI circular dated Jan 16' matching the full entry found earlier.
    """
    if not a.date or not b.date:
        return False
    if a.date.strip().lower() != b.date.strip().lower():
        return False
    if a.document_type != b.document_type:
        return False
    return _is_vague_title(a.title) or _is_vague_title(b.title)


# ─────────────────────────────────────────────
# FIX 2 — Verification pass for Master Circular clauses
# ─────────────────────────────────────────────

def verify_master_circular_clauses(
    pages: List[PageContent],
    client,
    provider: str,
) -> List[Dict]:
    """
    Second LLM pass: for any page that mentions 'Master Circular',
    explicitly ask the model to enumerate EVERY paragraph/clause reference.

    This catches cases where the main pass collapses multiple clause
    references (e.g. para 10.9 and para 16.8) into a single entry.
    """
    extra_refs = []

    for page in pages:
        if "master circular" not in page.text.lower():
            continue

        # prompt = (
        #     "Read the following page carefully.\n"
        #     "List EVERY distinct paragraph or clause number referenced from the "
        #     "'SEBI Master Circular for Mutual Funds'.\n"
        #     "Return ONLY a JSON array of objects with keys: clause, context.\n"
        #     "If none found, return [].\n\n"
        #     f"Page {page.page_number}:\n{page.text[:3000]}"
        # )
        prompt = (
            "Read the following page carefully.\n"
            "List EVERY distinct paragraph number referenced FROM the "
            "'SEBI Master Circular for Mutual Funds' document.\n"
            "IMPORTANT: Only extract references that use the format 'para X.Y' "
            "where X.Y is a paragraph number INSIDE the Master Circular.\n"
            "Do NOT extract paragraph numbers of the current circular being read "
            "(e.g. 4.4, 4.5 are sections of the current circular, NOT master circular references).\n"
            "Valid examples: 'para 10.9', 'para 16.8'\n"
            "Invalid examples: '4.4', '4.5' (these are sections of the current document)\n"
            "Return ONLY a JSON array of objects with keys: clause, context.\n"
            "If none found, return [].\n\n"
            f"Page {page.page_number}:\n{page.text[:3000]}"
        )

        try:
            if provider == "anthropic":
                resp = client.messages.create(
                    model="claude-3-5-sonnet-20240620",
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}]
                )
                raw = resp.content[0].text.strip()
            elif provider == "gemini":
                resp = client.generate_content(prompt)
                raw = resp.text.strip()
            elif provider == "huggingface":
                resp = client.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=500,
                    temperature=0.1,
                )
                raw = resp.choices[0].message.content.strip()
            else:
                continue

            raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
            raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
            clauses = json.loads(raw.strip())

            for c in clauses:
                if not isinstance(c, dict) or not c.get("clause"):
                    continue
                extra_refs.append({
                    "document_type": "master_circular",
                    "title": "SEBI Master Circular for Mutual Funds",
                    "circular_number": "",
                    "date": "June 27, 2024",
                    "clause": c.get("clause", ""),
                    "context": c.get("context", ""),
                    "page_number": page.page_number,
                })

        except Exception as e:
            print(f"  [WARNING] Verification pass failed on page {page.page_number}: {e}")

    return extra_refs


# ─────────────────────────────────────────────
# Deduplication (with FIX 1 applied)
# ─────────────────────────────────────────────

def deduplicate_references(raw_refs: List[Dict]) -> List[DocumentReference]:
    """
    Merge references to the same document found on multiple pages.

    Three-tier matching:
      1. Exact circular_number match (normalised)
      2. Fuzzy title key match (existing behaviour)
      3. Date + document_type fallback for vague titles (FIX 1)
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

        # Tier 1 & 2: existing key-based lookup
        if key in merged:
            _merge_into(merged[key], ref, r.get("page_number", 0))
            continue

        # Tier 3: date + type fallback for vague titles
        matched = False
        for existing in merged.values():
            if _date_and_type_match(existing, ref):
                # Keep the less-vague title
                if _is_vague_title(existing.title) and not _is_vague_title(ref.title):
                    existing.title = ref.title
                _merge_into(existing, ref, r.get("page_number", 0))
                matched = True
                break

        if not matched:
            merged[key] = ref

    for ref in merged.values():
        ref.found_on_pages = sorted(set(ref.found_on_pages))

    return list(merged.values())


def _merge_into(existing: DocumentReference, ref: DocumentReference, page: int) -> None:
    """Copy non-empty fields from ref into existing, and add the page number."""
    if page and page not in existing.found_on_pages:
        existing.found_on_pages.append(page)
    if not existing.circular_number and ref.circular_number:
        existing.circular_number = ref.circular_number
    if not existing.date and ref.date:
        existing.date = ref.date
    if not existing.clause and ref.clause:
        existing.clause = ref.clause
    if len(ref.title) > len(existing.title):
        existing.title = ref.title