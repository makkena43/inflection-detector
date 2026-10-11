"""Attachment download into a content-addressed archive.

Ported from MakroGraph ``IntelligencePipeline.run_pdf_fetch_india._download_pdf`` at b31bdd0:
the BSE AttachLive -> AttachHis retry on 404 and unwrapping of ZIPs served at PDF URLs.
Changes in the port:

* plain HTTP; no curl_cffi impersonation;
* the original bytes are always archived by SHA-256, and every PDF inside a ZIP is kept
  (MakroGraph kept only the first and discarded the ZIP);
* explicit statuses instead of "ok"/"zip"/"fail", and a zero-byte body is EMPTY rather than
  MakroGraph's "> 500 bytes" test;
* text extraction is separate (``inflection.text_extraction``); nothing is deleted after parsing.
"""

from __future__ import annotations

import hashlib
import io
import os
import threading
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .bse import ATTACH_HIS, ATTACH_LIVE
from .http import HttpClient

ZIP_MAGIC = b"PK\x03\x04"
PDF_MAGIC = b"%PDF"
MAX_ZIP_MEMBER_BYTES = 200 * 1024 * 1024


class DownloadStatus(str, Enum):
    OK = "OK"
    ZIP_NO_PDF = "ZIP_NO_PDF"               # archive kept; nothing in it to extract text from
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    EMPTY = "EMPTY"
    NOT_FOUND = "NOT_FOUND"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    path: Path
    size: int
    name: str           # member name inside a ZIP, or the URL's last segment


@dataclass
class DownloadResult:
    url: str
    status: DownloadStatus
    final_url: str = ""
    http_status: Optional[int] = None
    original: Optional[StoredFile] = None           # exactly the bytes served
    pdfs: list[StoredFile] = field(default_factory=list)
    note: str = ""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Archive:
    """Write-once, content-addressed blob store: ``root/ab/abcdef...``.  Rewriting the same bytes is a no-op."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, data: bytes, name: str) -> StoredFile:
        h = sha256(data)
        path = self.root / h[:2] / h
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")   # unique per writer
            tmp.write_bytes(data)
            tmp.replace(path)
        return StoredFile(h, path, len(data), name)


def candidate_urls(url: str) -> list[str]:
    urls = [url]
    if url.startswith(ATTACH_LIVE):
        urls.append(ATTACH_HIS + url[len(ATTACH_LIVE):])
    return urls


def download(url: str, archive: Archive, client: Optional[HttpClient] = None, referer: str = "") -> DownloadResult:
    client = client or HttpClient()
    last = None
    for u in candidate_urls(url):
        resp = client.get(u, referer=referer, accept="*/*")
        last = resp
        if resp.status == 404:
            continue
        break
    assert last is not None
    result = DownloadResult(url, DownloadStatus.FAILED, final_url=last.url, http_status=last.status)
    if last.status == 404:
        result.status, result.note = DownloadStatus.NOT_FOUND, "404 on " + ", ".join(candidate_urls(url))
        return result
    if last.blocked:
        result.status, result.note = DownloadStatus.BLOCKED, f"HTTP {last.status}"
        return result
    if last.status != 200:
        result.note = last.error or f"HTTP {last.status}"
        return result
    body = last.body
    if not body:
        result.status, result.note = DownloadStatus.EMPTY, "zero-byte response"
        return result
    name = last.url.rstrip("/").rsplit("/", 1)[-1]
    result.original = archive.put(body, name)
    if body[:4] == PDF_MAGIC:
        result.status, result.pdfs = DownloadStatus.OK, [result.original]
    elif body[:4] == ZIP_MAGIC:
        result.status, result.pdfs, result.note = _unzip(body, archive)
    elif body.lstrip()[:1] == b"<" and b"<html" in body[:2000].lower():
        result.status, result.note = DownloadStatus.BLOCKED, "HTML page instead of a document (likely a block page)"
    else:
        result.status, result.note = DownloadStatus.UNSUPPORTED_FORMAT, f"starts with {body[:8]!r}"
    return result


def _unzip(body: bytes, archive: Archive) -> tuple[DownloadStatus, list[StoredFile], str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        return DownloadStatus.UNSUPPORTED_FORMAT, [], f"bad zip: {exc}"
    pdfs, skipped = [], []
    for info in zf.infolist():
        if info.is_dir():
            continue
        if not info.filename.lower().endswith(".pdf") or info.file_size > MAX_ZIP_MEMBER_BYTES:
            skipped.append(info.filename)
            continue
        pdfs.append(archive.put(zf.read(info), info.filename))
    note = f"zip members not extracted: {', '.join(skipped)}" if skipped else ""
    return (DownloadStatus.OK if pdfs else DownloadStatus.ZIP_NO_PDF), pdfs, note
