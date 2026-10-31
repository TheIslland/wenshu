from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from wenshu.errors import PdfError
from wenshu.services import importers, pdf


def make_pdf(
    text: str = "Hello Wenshu",
    *,
    title: str = "Test Paper",
    author: str = "Zhang San; Li Si",
) -> bytes:
    """Build a tiny valid PDF by hand (no extra dependencies, no private pypdf API)."""
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    info_parts = []
    if title:
        info_parts.append(b"/Title (" + title.encode("latin-1") + b")")
    if author:
        info_parts.append(b"/Author (" + author.encode("latin-1") + b")")
    has_info = bool(info_parts)
    if has_info:
        objects.append(b"<< " + b" ".join(info_parts) + b" >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R".encode()
    if has_info:
        trailer += b" /Info 6 0 R"
    trailer += f" >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    out += trailer
    return bytes(out)


def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_extract_text_and_metadata():
    text, meta = pdf.extract_text(make_pdf())
    assert "Hello Wenshu" in text
    assert meta["title"] == "Test Paper"
    assert meta["author"] == "Zhang San; Li Si"
    assert meta["pages"] == 1
    assert meta["scanned"] is False
    assert meta["characters"] == len(text)


def test_extract_blank_pdf_is_scanned_not_error():
    text, meta = pdf.extract_text(make_pdf(text=""))
    assert text == ""
    assert meta["scanned"] is True
    assert meta["pages"] == 1


def test_corrupt_pdf_raises_pdf_error():
    with pytest.raises(PdfError) as excinfo:
        pdf.extract_text(b"%PDF-1.4 this is not really a pdf")
    assert "损坏" in str(excinfo.value)


def test_non_pdf_bytes_raise_pdf_error():
    with pytest.raises(PdfError):
        pdf.extract_text(b"hello world")


def test_encrypted_pdf_raises_pdf_error():
    with pytest.raises(PdfError) as excinfo:
        pdf.extract_text(encrypted_pdf())
    assert "加密" in str(excinfo.value)


def test_attachment_name_is_stable_sha256_prefix():
    data = make_pdf()
    name = pdf.attachment_name(data)
    assert name == pdf.attachment_name(data)
    assert name.endswith(".pdf")
    assert len(name) == 20
    assert name != pdf.attachment_name(data + b"x")


def test_save_attachment_and_fulltext(tmp_path):
    data = make_pdf()
    path = pdf.save_attachment(data, tmp_path / "attachments")
    assert path.exists()
    assert path.parent.name == "attachments"
    assert path.name == pdf.attachment_name(data)
    text_path = pdf.save_fulltext("全文文本", tmp_path / "attachments")
    assert text_path.exists()
    assert text_path.read_text(encoding="utf-8") == "全文文本"


def test_import_pdf_builds_hit():
    hit, text, meta = importers.import_pdf(
        make_pdf(title="A Test Paper", author="Zhang San; Li Si"),
        filename="论文 草稿.pdf",
    )
    assert hit.source == "pdf"
    assert hit.title == "A Test Paper"
    assert hit.authors == ["Zhang San", "Li Si"]
    assert "Hello Wenshu" in text
    assert meta["pages"] == 1
    assert hit.raw["filename"] == "论文 草稿.pdf"


def test_import_pdf_falls_back_to_filename(tmp_path):
    hit, _text, _meta = importers.import_pdf(
        make_pdf(title="", author=""), filename="中文 文件名.pdf"
    )
    assert hit.title == "中文 文件名"


def test_import_pdf_without_text_or_title_raises():
    with pytest.raises(Exception) as excinfo:
        importers.import_pdf(make_pdf(text="", title="", author=""))
    assert "标题" in str(excinfo.value) or "扫描" in str(excinfo.value)
