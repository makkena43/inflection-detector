"""Page-preserving PDF text extraction with explicit completeness status.

Ported from MakroGraph ``parser/pdf_parser.py`` and ``parser/text_artifacts.py``
at b31bdd0 (see docs/reuse_inventory.md).  Differences from the original:

* pdfplumber only.  The PyMuPDF fallback is not ported because PyMuPDF is
  AGPL-licensed; revisit only after a licence decision;
* hard resource bounds (file size, page count) checked before parsing;
* returns pages as a list and never a flattened string, so evidence can cite
  page numbers;
* no filesystem store here; artifacts are persisted by the caller into
  ``text_artifacts`` / ``text_pages``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

EXTRACTION_METHOD = "pdfplumber"


class ExtractionStatus(str, Enum):
    COMPLETE = "COMPLETE"                       # every page processed and had text
    PARTIAL = "PARTIAL"                         # truncated, or some pages without text
    OCR_REQUIRED = "OCR_REQUIRED"               # pages exist but no text layer
    PARSE_FAILED_RETRYABLE = "PARSE_FAILED_RETRYABLE"
    ENCRYPTED = "ENCRYPTED"
    EMPTY = "EMPTY"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"           # over the configured size bound; not parsed

    @property
    def usable(self) -> bool:
        return self in (ExtractionStatus.COMPLETE, ExtractionStatus.PARTIAL)


@dataclass
class Extraction:
    status: ExtractionStatus
    method: str
    extraction_version: str
    pages: list[str] = field(default_factory=list)
    pages_expected: Optional[int] = None
    quality_issues: list[str] = field(default_factory=list)
    failure_reason: str = ""

    @property
    def pages_with_text(self) -> int:
        return sum(1 for p in self.pages if p.strip())

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256("\f".join(self.pages).encode("utf-8")).hexdigest() if self.pages else ""


def classify_pages(pages: list[str], pages_expected: Optional[int]) -> tuple[ExtractionStatus, list[str]]:
    """Completeness status from per-page text (ported unchanged in behaviour)."""
    issues: list[str] = []
    with_text = sum(1 for p in pages if p.strip())
    if not pages and not pages_expected:
        return ExtractionStatus.EMPTY, ["document has no pages"]
    if with_text == 0:
        return ExtractionStatus.OCR_REQUIRED, ["no text layer on any page (scanned or image-only)"]
    status = ExtractionStatus.COMPLETE
    if pages_expected is not None and len(pages) < pages_expected:
        status = ExtractionStatus.PARTIAL
        issues.append(f"processed {len(pages)} of {pages_expected} pages (page limit)")
    blank = len(pages) - with_text
    if blank:
        status = ExtractionStatus.PARTIAL
        issues.append(f"{blank} page(s) without a text layer (may need OCR)")
    return status, issues


def extract_pdf(path: Path, max_bytes: int = 50 * 1024 * 1024, max_pages: int = 500) -> Extraction:
    import pdfplumber

    version = f"{EXTRACTION_METHOD}-{pdfplumber.__version__}/max{max_pages}"

    def fail(status: ExtractionStatus, reason: str) -> Extraction:
        return Extraction(status, EXTRACTION_METHOD, version, failure_reason=reason)

    path = Path(path)
    size = path.stat().st_size
    if size == 0:
        return fail(ExtractionStatus.EMPTY, "zero-byte file")
    if size > max_bytes:
        return fail(ExtractionStatus.RESOURCE_LIMIT, f"{size} bytes exceeds limit {max_bytes}")
    with open(path, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            return fail(ExtractionStatus.UNSUPPORTED_FORMAT, "not a PDF (missing %PDF header)")
    try:
        with pdfplumber.open(path) as pdf:
            expected = len(pdf.pages)
            pages = [(page.extract_text() or "") for page in pdf.pages[:max_pages]]
    except Exception as exc:  # pdfminer raises a variety of types
        msg = str(exc).lower()
        if "password" in msg or "encrypt" in msg:
            return fail(ExtractionStatus.ENCRYPTED, str(exc))
        return fail(ExtractionStatus.PARSE_FAILED_RETRYABLE, f"{type(exc).__name__}: {exc}")
    status, issues = classify_pages(pages, expected)
    return Extraction(status, EXTRACTION_METHOD, version, pages=pages, pages_expected=expected,
                      quality_issues=issues)
