# """
# PDF Parser: Extracts text content page-by-page from PDF files.
# """

# import pdfplumber
# from dataclasses import dataclass, field
# from typing import List, Optional
# import re


# @dataclass
# class PageContent:
#     page_number: int
#     text: str
#     word_count: int = 0

#     def __post_init__(self):
#         self.word_count = len(self.text.split())


# @dataclass
# class DocumentMetadata:
#     title: str = ""
#     circular_number: str = ""
#     date: str = ""
#     issuing_authority: str = ""
#     total_pages: int = 0
#     file_path: str = ""


# def extract_document_metadata(pages: List[PageContent]) -> DocumentMetadata:
#     """
#     Heuristically extract metadata from the first 2 pages of the document.
#     Looks for SEBI circular patterns in the header text.
#     """
#     meta = DocumentMetadata(total_pages=len(pages))
#     header_text = " ".join(p.text for p in pages[:2])

#     # SEBI circular number pattern: SEBI/HO/CFD/.../CIR/P/YYYY/NNN
#     circ_match = re.search(
#         r"(SEBI/[A-Z0-9/]+/CIR/[A-Z]/\d{4}/\d+)", header_text
#     )
#     if circ_match:
#         meta.circular_number = circ_match.group(1)

#     # Date pattern
#     date_match = re.search(
#         r"(\w+ \d{1,2},?\s*\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})", header_text
#     )
#     if date_match:
#         meta.date = date_match.group(1)

#     # Title: usually the first non-empty meaningful line
#     for line in header_text.splitlines():
#         line = line.strip()
#         if len(line) > 20 and "SEBI" in line and "circular" in line.lower():
#             meta.title = line
#             break

#     meta.issuing_authority = "Securities and Exchange Board of India (SEBI)"
#     return meta


# def extract_pages(pdf_path: str) -> tuple[List[PageContent], DocumentMetadata]:
#     """
#     Extract text from every page of a PDF, preserving page numbers.
#     Returns a list of PageContent objects and document metadata.
#     """
#     pages: List[PageContent] = []

#     with pdfplumber.open(pdf_path) as pdf:
#         for i, page in enumerate(pdf.pages, start=1):
#             raw_text = page.extract_text() or ""
#             # Normalize whitespace but keep line breaks for context
#             cleaned = re.sub(r"[ \t]+", " ", raw_text).strip()
#             pages.append(PageContent(page_number=i, text=cleaned))

#     metadata = extract_document_metadata(pages)
#     metadata.file_path = pdf_path
#     return pages, metadata

"""
PDF Parser: Extracts text content page-by-page from PDF files.
"""

import pdfplumber
from dataclasses import dataclass, field
from typing import List, Optional
import re


@dataclass
class PageContent:
    page_number: int
    text: str
    word_count: int = 0

    def __post_init__(self):
        self.word_count = len(self.text.split())


@dataclass
class DocumentMetadata:
    title: str = ""                                      # subject line from the circular
    circular_number: str = ""                           # reference number on page 1
    date: str = ""                                      # date on page 1
    issuing_authority: str = ""
    addressees: List[str] = field(default_factory=list) # who it is addressed to
    total_pages: int = 0
    file_path: str = ""


# ─────────────────────────────────────────────
# Circular number patterns
# ─────────────────────────────────────────────

CIRCULAR_NUMBER_PATTERNS = [
    # Format A, C, D — starts with SEBI/
    r"(SEBI/HO/[A-Z0-9\-/]+/(?:CIR|P)/[A-Z0-9/]+)",
    # Format B — HO/ with optional parens, digits, dashes
    r"(HO/[\w()\-]+/[A-Z]/\d+/\d{4})",
    # Generic fallback
    r"([A-Z]{2,}/[\w()\-/]{10,}/\d{4})",
]


def _extract_circular_number(text: str) -> str:
    for pattern in CIRCULAR_NUMBER_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


# ─────────────────────────────────────────────
# Subject extraction
# ─────────────────────────────────────────────

def _extract_subject(text: str) -> str:
    """
    Extract the subject line explicitly labelled 'Subject:' on page 1.

    Stops at the FIRST of:
      - A blank line
      - A numbered paragraph  e.g. "1."
      - A lettered section    e.g. "A." / "A. Intraday..."
      - End of string
    """
    subject_match = re.search(
        r"Subject\s*:\s*(.+?)(?=\n\s*\n|\n\s*\d+\.|\n\s*[A-Z]\.\s|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if subject_match:
        raw = subject_match.group(1)
        # Collapse internal newlines / extra whitespace
        cleaned = re.sub(r"\s+", " ", raw).strip()
        # Strip trailing footnote superscripts
        cleaned = re.sub(r"[\u00b9\u00b2\u00b3\u2070-\u2079\d]+$", "", cleaned).strip()
        return cleaned
    return ""


# ─────────────────────────────────────────────
# Addressee extraction
# ─────────────────────────────────────────────

def _extract_addressees(text: str) -> List[str]:
    """
    Extract the list of entities the circular is addressed to.

    Handles TWO layouts seen in SEBI circulars:

    Layout 1 — explicit 'To,' header (most circulars):
        To,
        All Mutual Funds/
        All Asset Management Companies (AMCs)/
        Sir / Madam,

    Layout 2 — no 'To,' line (some circulars like the MF borrowing one):
        HO/(92)2026-...  March 13, 2026
        All Mutual Funds/
        All Asset Management Companies (AMCs)/
        Sir / Madam,

    In both cases the addressees end at 'Sir' / 'Madam' / 'Dear'.
    """

    # ── Layout 1: explicit "To," present ────────────────────────────
    to_block = re.search(
        r"To\s*,\s*\n(.*?)(?=\n\s*(?:Madam|Sir|Dear)\b)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if to_block:
        return _parse_addressee_block(to_block.group(1))

    # ── Layout 2: no "To," — find block before "Sir / Madam" ────────
    sir_madam_match = re.search(
        r"\n(.*?)(?=\n\s*(?:Sir\s*/\s*Madam|Madam\s*/\s*Sir|Dear\s+Sir|Dear\s+Madam))",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if sir_madam_match:
        block = sir_madam_match.group(1)
        candidates = _parse_addressee_block(block)
        # Filter out the circular number / date line and page markers
        filtered = [
            line for line in candidates
            if not re.search(r"\d{4}$", line)
            and not re.search(r"^Page\s+\d+", line)
            and not re.search(r"^CIRCULAR\s*$", line, re.IGNORECASE)
        ]
        return filtered

    return []


def _parse_addressee_block(block: str) -> List[str]:
    """
    Split a raw text block into individual addressee strings.
    Strips trailing '/' characters used as line separators in SEBI circulars.
    """
    addressees = []
    for line in block.splitlines():
        cleaned = line.strip().rstrip("/").strip()
        if cleaned and len(cleaned) > 3:
            addressees.append(cleaned)
    return addressees


# ─────────────────────────────────────────────
# Date extraction
# ─────────────────────────────────────────────

def _extract_date(text: str) -> str:
    date_pattern = (
        r"((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},?\s*\d{4})"
        r"|(\d{1,2}[/-]\d{1,2}[/-]\d{4})"
    )
    match = re.search(date_pattern, text, re.IGNORECASE)
    if match:
        return (match.group(1) or match.group(2)).strip()
    return ""


# ─────────────────────────────────────────────
# Main metadata extractor
# ─────────────────────────────────────────────

def extract_document_metadata(pages: List[PageContent]) -> DocumentMetadata:
    """
    Extract metadata from page 1 of the circular.

    Extraction strategy per field:
      - circular_number : line immediately after "CIRCULAR" heading, then full-page fallback
      - date            : same line as circular number
      - title           : explicitly labelled "Subject:" block, stops at first section header
      - addressees      : block between date line and "Sir/Madam" (with or without "To,")
    """
    meta = DocumentMetadata(total_pages=len(pages))

    if not pages:
        return meta

    page1_text = pages[0].text

    # ── Circular number ──────────────────────────────────────────────
    circ_line_match = re.search(
        r"CIRCULAR\s*\n\s*(.+)", page1_text, re.IGNORECASE
    )
    if circ_line_match:
        meta.circular_number = _extract_circular_number(circ_line_match.group(1))
    if not meta.circular_number:
        meta.circular_number = _extract_circular_number(page1_text)

    # ── Date ─────────────────────────────────────────────────────────
    if circ_line_match:
        meta.date = _extract_date(circ_line_match.group(1))
    if not meta.date:
        meta.date = _extract_date(page1_text)

    # ── Subject (title) ──────────────────────────────────────────────
    meta.title = _extract_subject(page1_text)

    # ── Addressees ───────────────────────────────────────────────────
    meta.addressees = _extract_addressees(page1_text)

    meta.issuing_authority = "Securities and Exchange Board of India (SEBI)"
    return meta


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────

def extract_pages(pdf_path: str) -> tuple[List[PageContent], DocumentMetadata]:
    """
    Extract text from every page of a PDF, preserving page numbers.
    Returns a list of PageContent objects and document metadata.
    """
    pages: List[PageContent] = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw_text = page.extract_text() or ""
            cleaned = re.sub(r"[ \t]+", " ", raw_text).strip()
            pages.append(PageContent(page_number=i, text=cleaned))

    metadata = extract_document_metadata(pages)
    metadata.file_path = pdf_path
    return pages, metadata