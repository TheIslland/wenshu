"""Export documents and reference lists: Markdown, DOCX, BibTeX, RIS."""

from __future__ import annotations

import io
import json
import re
import sqlite3
from typing import Any

from docx import Document as DocxDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from ..errors import ValidationFailed
from .citations import format_refs_report

CJK_FONT = "宋体"
LATIN_FONT = "Times New Roman"
BODY_SIZE = 12  # 小四
LINE_SPACING = 1.5

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.+)$")
_NUMBERED = re.compile(r"^\s*\d+[.)、]\s+(.+)$")
_CITATION = re.compile(r"\[@([^\]]+)\]")
_INLINE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`|\*(.+?)\*")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    if isinstance(obj, sqlite3.Row):
        return obj[key] if key in obj.keys() else default
    value = getattr(obj, key, default)
    return default if value is None else value


def _as_dicts(refs: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ref in refs or []:
        if isinstance(ref, dict):
            data = dict(ref)
        elif isinstance(ref, sqlite3.Row):
            data = dict(ref)
        elif hasattr(ref, "model_dump"):
            data = ref.model_dump()
        else:
            data = {
                key: getattr(ref, key)
                for key in ("title", "authors", "year", "venue", "volume", "issue", "pages")
                if hasattr(ref, key)
            }
        for key in ("authors", "tags"):
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except ValueError:
                    data[key] = []
        result.append(data)
    return result


def _citation_status(ref: dict[str, Any]) -> str:
    for key in ("citation_status", "check_status"):
        value = ref.get(key)
        if value:
            return str(value)
    return ""


def _unverified(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [ref for ref in refs if _citation_status(ref) != "verified"]


def _status_label(ref: dict[str, Any]) -> str:
    status = _citation_status(ref)
    return {
        "verified": "已核",
        "mismatch": "不匹配",
        "not_found": "未找到",
        "no_doi": "无 DOI",
        "error": "核验出错",
    }.get(status, "未核引")


def _render_citations(text: str, refs: list[dict[str, Any]]) -> str:
    """Replace ``[@bibkey]`` markers with numeric citations; unknown keys raise."""
    numbers: dict[str, int] = {}
    for index, ref in enumerate(refs, start=1):
        keys = []
        bibkey = str(ref.get("bibkey") or "").strip()
        if bibkey:
            keys.append(bibkey)
        ref_id = ref.get("id") or ref.get("ref_id")
        if ref_id is not None:
            keys.append(f"ref-{ref_id}")
        for key in keys:
            numbers.setdefault(key, index)

    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        parts = [part.strip().lstrip("@") for part in re.split(r"[;,]", match.group(1))]
        resolved: list[int] = []
        for part in parts:
            if part in numbers:
                resolved.append(numbers[part])
            elif part.isdigit() and 1 <= int(part) <= len(refs):
                resolved.append(int(part))
            else:
                missing.append(part)
        if not resolved:
            return match.group(0)
        return "[" + ", ".join(str(number) for number in sorted(set(resolved))) + "]"

    rendered = _CITATION.sub(replace, text)
    if missing:
        raise ValidationFailed(
            "文档引用了不存在的文献标签。",
            detail={"missing": sorted(set(missing))},
        )
    return rendered


def _unverified_markdown(refs: list[dict[str, Any]]) -> str:
    entries = _unverified(refs)
    if not entries:
        return ""
    lines = ["## 未核引清单", ""]
    for ref in entries:
        ref_id = ref.get("id") or ref.get("ref_id") or "?"
        lines.append(f"- [{ref_id}] {ref.get('title', '无题名')}（{_status_label(ref)}）")
    return "\n".join(lines) + "\n"


def markdown(
    project: Any,
    document: Any,
    refs: Any,
    style: str = "gbt7714",
) -> str:
    """Markdown export with resolved citation markers and the unverified list."""
    items = _as_dicts(refs)
    title = str(_get(document, "title") or _get(project, "name") or "未命名文档").strip()
    body = _render_citations(str(_get(document, "content_md") or ""), items)
    report = format_refs_report(items, style)
    parts = [f"# {title}", "", body.strip(), ""]
    if items:
        parts.extend(["## 参考文献", "", report["text"], ""])
    unverified = _unverified_markdown(items)
    if unverified:
        parts.append(unverified)
    return "\n".join(parts).strip() + "\n"


def _set_style_font(style: Any, *, size: float, bold: bool | None = None) -> None:
    style.font.name = LATIN_FONT
    style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), LATIN_FONT)
    rfonts.set(qn("w:hAnsi"), LATIN_FONT)
    rfonts.set(qn("w:eastAsia"), CJK_FONT)


def _font_run(run: Any, *, size: float, bold: bool | None = None) -> None:
    run.font.name = LATIN_FONT
    run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), LATIN_FONT)
    rfonts.set(qn("w:hAnsi"), LATIN_FONT)
    rfonts.set(qn("w:eastAsia"), CJK_FONT)


def _strip_inline(text: str) -> str:
    text = _LINK.sub(lambda match: match.group(1), text)
    return _INLINE.sub(
        lambda match: next(
            (group for group in match.groups() if group is not None), match.group(0)
        ),
        text,
    )


def _new_document() -> Any:
    doc = DocxDocument()
    normal = doc.styles["Normal"]
    _set_style_font(normal, size=BODY_SIZE)
    normal.paragraph_format.line_spacing = LINE_SPACING
    normal.paragraph_format.space_after = Pt(0)
    sizes = {"Title": 18, "Heading 1": 16, "Heading 2": 14, "Heading 3": 12, "Heading 4": 12}
    for name, size in sizes.items():
        if name in doc.styles:
            style = doc.styles[name]
            _set_style_font(style, size=size, bold=name != "Title")
            style.paragraph_format.line_spacing = LINE_SPACING
    return doc


def _add_paragraph(doc: Any, text: str, *, style_name: str | None = None, size: float = BODY_SIZE):
    paragraph = doc.add_paragraph(style=style_name)
    paragraph.paragraph_format.line_spacing = LINE_SPACING
    run = paragraph.add_run(_strip_inline(text))
    _font_run(run, size=size)
    return paragraph


def docx(
    project: Any,
    document: Any,
    refs: Any,
    style: str = "gbt7714",
) -> bytes:
    """Build a Chinese-formatted DOCX (宋体/Times New Roman, 小四, 1.5 倍行距)."""
    items = _as_dicts(refs)
    title = str(_get(document, "title") or _get(project, "name") or "未命名文档").strip()
    body = _render_citations(str(_get(document, "content_md") or ""), items)
    report = format_refs_report(items, style)

    doc = _new_document()
    title_paragraph = doc.add_paragraph(style="Title")
    title_paragraph.paragraph_format.line_spacing = LINE_SPACING
    title_run = title_paragraph.add_run(title)
    _font_run(title_run, size=18, bold=True)

    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        heading = _HEADING.match(line)
        if heading:
            level = min(len(heading.group(1)), 4)
            paragraph = doc.add_paragraph(style=f"Heading {level}")
            paragraph.paragraph_format.line_spacing = LINE_SPACING
            run = paragraph.add_run(_strip_inline(heading.group(2)))
            _font_run(run, size={1: 16, 2: 14, 3: 12, 4: 12}[level], bold=True)
            continue
        bullet = _BULLET.match(line)
        if bullet:
            _add_paragraph(doc, bullet.group(1), style_name="List Bullet")
            continue
        numbered = _NUMBERED.match(line)
        if numbered:
            _add_paragraph(doc, numbered.group(1), style_name="List Number")
            continue
        if line.lstrip().startswith(">"):
            _add_paragraph(doc, line.lstrip()[1:].strip(), style_name="Quote")
            continue
        _add_paragraph(doc, line)

    if items:
        heading = doc.add_paragraph(style="Heading 1")
        heading.paragraph_format.line_spacing = LINE_SPACING
        heading_run = heading.add_run("参考文献")
        _font_run(heading_run, size=16, bold=True)
        for entry in report["text"].splitlines():
            entry = entry.strip()
            if entry:
                paragraph = doc.add_paragraph()
                paragraph.paragraph_format.line_spacing = LINE_SPACING
                paragraph.paragraph_format.left_indent = Pt(0)
                run = paragraph.add_run(entry)
                _font_run(run, size=BODY_SIZE)

    unverified = _unverified(items)
    if unverified:
        heading = doc.add_paragraph(style="Heading 1")
        heading.paragraph_format.line_spacing = LINE_SPACING
        heading_run = heading.add_run("未核引清单")
        _font_run(heading_run, size=16, bold=True)
        for ref in unverified:
            ref_id = ref.get("id") or ref.get("ref_id") or "?"
            _add_paragraph(
                doc,
                f"[{ref_id}] {ref.get('title', '无题名')}（{_status_label(ref)}）",
                style_name="List Bullet",
            )

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


BIBTEX_TYPES = {
    "journal-article": "article",
    "journal": "article",
    "article": "article",
    "book": "book",
    "monograph": "book",
    "chapter": "incollection",
    "book-chapter": "incollection",
    "conference-paper": "inproceedings",
    "conference": "inproceedings",
    "proceedings-article": "inproceedings",
    "thesis": "phdthesis",
    "dissertation": "phdthesis",
    "report": "techreport",
    "webpage": "misc",
    "preprint": "misc",
}

RIS_TYPES = {
    "journal-article": "JOUR",
    "journal": "JOUR",
    "article": "JOUR",
    "book": "BOOK",
    "monograph": "BOOK",
    "chapter": "CHAP",
    "book-chapter": "CHAP",
    "conference-paper": "CONF",
    "conference": "CONF",
    "proceedings-article": "CONF",
    "thesis": "THES",
    "dissertation": "THES",
    "report": "RPRT",
    "webpage": "ELEC",
    "preprint": "GEN",
}


def _bibkey(ref: dict[str, Any], index: int) -> str:
    key = str(ref.get("bibkey") or "").strip()
    if key:
        return key
    ref_id = ref.get("id") or ref.get("ref_id")
    if ref_id is not None:
        return f"ref{ref_id}"
    return f"ref{index}"


def bibtex(refs: Any) -> str:
    """Deterministic BibTeX export without new dependencies."""
    items = _as_dicts(refs)
    entries: list[str] = []
    used: set[str] = set()
    for index, ref in enumerate(items, start=1):
        key = _bibkey(ref, index)
        candidate = key
        counter = 2
        while candidate in used:
            candidate = f"{key}{counter}"
            counter += 1
        used.add(candidate)
        entry_type = BIBTEX_TYPES.get(str(ref.get("type") or ""), "misc")
        fields: list[tuple[str, str]] = []
        authors = [str(name).strip() for name in (ref.get("authors") or []) if str(name).strip()]
        if authors:
            fields.append(("author", " and ".join(authors)))
        if ref.get("title"):
            fields.append(("title", f"{{{ref['title']}}}"))
        venue_field = {
            "article": "journal",
            "incollection": "booktitle",
            "inproceedings": "booktitle",
            "phdthesis": "school",
            "techreport": "institution",
            "book": "publisher",
        }.get(entry_type, "howpublished")
        if ref.get("venue"):
            fields.append((venue_field, str(ref["venue"])))
        for source, target in (
            ("year", "year"),
            ("volume", "volume"),
            ("issue", "number"),
            ("pages", "pages"),
            ("doi", "doi"),
            ("url", "url"),
            ("language", "language"),
        ):
            if ref.get(source):
                fields.append((target, str(ref[source])))
        body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
        entries.append(f"@{entry_type}{{{candidate},\n{body}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def _ris_pages(pages: Any) -> tuple[str, str]:
    match = re.match(r"\s*(\S+?)\s*[-–—]\s*(\S+)\s*$", str(pages or ""))
    if match:
        return match.group(1), match.group(2)
    return str(pages or "").strip(), ""


def ris(refs: Any) -> str:
    """Deterministic RIS export."""
    items = _as_dicts(refs)
    blocks: list[str] = []
    for ref in items:
        lines = [f"TY  - {RIS_TYPES.get(str(ref.get('type') or ''), 'GEN')}"]
        for name in ref.get("authors") or []:
            if str(name).strip():
                lines.append(f"AU  - {name}")
        for tag, key in (
            ("TI", "title"),
            ("JO", "venue"),
            ("VL", "volume"),
            ("IS", "issue"),
            ("DO", "doi"),
            ("UR", "url"),
            ("LA", "language"),
        ):
            if ref.get(key):
                lines.append(f"{tag}  - {ref[key]}")
        if ref.get("year"):
            lines.append(f"PY  - {ref['year']}")
        start, end = _ris_pages(ref.get("pages"))
        if start:
            lines.append(f"SP  - {start}")
        if end:
            lines.append(f"EP  - {end}")
        lines.append("ER  - ")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


EXPORTERS = {
    "md": "markdown",
    "markdown": "markdown",
    "docx": "docx",
    "bibtex": "bibtex",
    "bib": "bibtex",
    "ris": "ris",
}


def export(fmt: str, project: Any, document: Any, refs: Any, style: str = "gbt7714") -> Any:
    name = EXPORTERS.get((fmt or "").strip().lower())
    if name is None:
        raise ValidationFailed(f"不支持的导出格式：{fmt}")
    if name == "markdown":
        return markdown(project, document, refs, style)
    if name == "docx":
        return docx(project, document, refs, style)
    if name == "bibtex":
        return bibtex(refs)
    return ris(refs)
