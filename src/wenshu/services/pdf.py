"""PDF attachment handling: pypdf text/metadata extraction, hash file names."""

from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ..errors import PdfError

_HASH_RE = re.compile(r"^[0-9a-f]{16}\.pdf$")


def attachment_name(data: bytes) -> str:
    """`sha256[:16].pdf`, as required by design §5.3 (macOS 255-byte names)."""
    return hashlib.sha256(data).hexdigest()[:16] + ".pdf"


def looks_like_pdf(data: bytes) -> bool:
    return bool(data) and data.lstrip()[:5] == b"%PDF-"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for encoding in ("utf-8", "gb18030", "latin-1"):
            try:
                value = value.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            value = value.decode("utf-8", errors="replace")
    text = str(value).replace("\x00", " ")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _metadata(reader: PdfReader) -> dict[str, str]:
    info = getattr(reader, "metadata", None)
    if not info:
        return {}
    keys = {
        "title": "/Title",
        "author": "/Author",
        "subject": "/Subject",
        "creator": "/Creator",
        "producer": "/Producer",
        "creation_date": "/CreationDate",
    }
    result: dict[str, str] = {}
    for name, key in keys.items():
        try:
            value = info.get(key)
        except (KeyError, AttributeError, TypeError):
            value = None
        cleaned = _clean(value)
        if cleaned:
            result[name] = cleaned
    return result


def extract_text(data: bytes) -> tuple[str, dict[str, Any]]:
    """Extract full text + metadata. Corrupt/encrypted files raise PdfError."""
    if not looks_like_pdf(data):
        raise PdfError("这不是有效的 PDF 文件。")
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pypdf raises many exception types
        raise PdfError("PDF 无法解析，文件可能已损坏。", detail=str(exc)[:300]) from exc

    if getattr(reader, "is_encrypted", False):
        try:
            decrypted = reader.decrypt("")
        except Exception:  # noqa: BLE001 - wrong password path
            decrypted = 0
        if not decrypted:
            raise PdfError("PDF 已加密，无法读取正文。")

    try:
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise PdfError("PDF 页面结构损坏，无法读取。", detail=str(exc)[:300]) from exc

    chunks: list[str] = []
    for page in reader.pages:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - keep whatever other pages yield
            chunks.append("")

    text = _clean("\n\n".join(chunks))
    meta: dict[str, Any] = _metadata(reader)
    meta.update(
        {
            "pages": page_count,
            "characters": len(text),
            "scanned": page_count > 0 and not text,
        }
    )
    return text, meta


def save_attachment(data: bytes, attachments_dir: Path) -> Path:
    """Write the PDF under its hash name; return the absolute path."""
    directory = Path(attachments_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = (directory / attachment_name(data)).resolve()
    if not _HASH_RE.match(path.name):
        raise PdfError("附件命名异常，已取消保存。")
    if not path.exists():
        path.write_bytes(data)
    return path


def save_fulltext(text: str, attachments_dir: Path) -> Path:
    """Store extracted text next to the PDF as `<sha256[:16]>.txt`."""
    path = save_attachment_path_guard(attachments_dir, text)
    if not path.exists():
        path.write_text(text, encoding="utf-8", newline="\n")
    return path


def save_attachment_path_guard(attachments_dir: Path, text: str) -> Path:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    directory = Path(attachments_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return (directory / f"{digest}.txt").resolve()
