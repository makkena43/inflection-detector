"""Tiny dependency-free PDF writer for tests (one Helvetica text block per page)."""

from pathlib import Path


def make_pdf(path: Path, pages: list[str]) -> Path:
    """Each string is one page; "" gives a page with no text layer."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pages_id = len(objs) + 2 * len(pages) + 1       # reserved below
    kids = []
    for text in pages:
        ops = []
        if text:
            ops.append(b"BT /F1 9 Tf 40 760 Td 11 TL")
            for line in text.split("\n"):
                esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                ops.append(f"({esc}) Tj T*".encode("latin-1"))
            ops.append(b"ET")
        stream = b"\n".join(ops)
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                        b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                        % (pages_id, font, content)))
    assert add(b"<< /Type /Pages /Kids [%s] /Count %d >>"
               % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, xref)
    Path(path).write_bytes(bytes(out))
    return Path(path)
