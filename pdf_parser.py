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
    title: str = ""
    circular_number: str = ""
    date: str = ""
    issuing_authority: str = ""
    total_pages: int = 0
    file_path: str = ""


def extract_document_metadata(pages: List[PageContent]) -> DocumentMetadata:
    """
    Heuristically extract metadata from the first 2 pages of the document.
    Looks for SEBI circular patterns in the header text.
    """
    meta = DocumentMetadata(total_pages=len(pages))
    header_text = " ".join(p.text for p in pages[:2])

    # SEBI circular number pattern: SEBI/HO/CFD/.../CIR/P/YYYY/NNN
    circ_match = re.search(
        r"(SEBI/[A-Z0-9/]+/CIR/[A-Z]/\d{4}/\d+)", header_text
    )
    if circ_match:
        meta.circular_number = circ_match.group(1)

    # Date pattern
    date_match = re.search(
        r"(\w+ \d{1,2},?\s*\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})", header_text
    )
    if date_match:
        meta.date = date_match.group(1)

    # Title: usually the first non-empty meaningful line
    for line in header_text.splitlines():
        line = line.strip()
        if len(line) > 20 and "SEBI" in line and "circular" in line.lower():
            meta.title = line
            break

    meta.issuing_authority = "Securities and Exchange Board of India (SEBI)"
    return meta


def extract_pages(pdf_path: str) -> tuple[List[PageContent], DocumentMetadata]:
    """
    Extract text from every page of a PDF, preserving page numbers.
    Returns a list of PageContent objects and document metadata.
    """
    pages: List[PageContent] = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw_text = page.extract_text() or ""
            # Normalize whitespace but keep line breaks for context
            cleaned = re.sub(r"[ \t]+", " ", raw_text).strip()
            pages.append(PageContent(page_number=i, text=cleaned))

    metadata = extract_document_metadata(pages)
    metadata.file_path = pdf_path
    return pages, metadata