"""Import references from RIS, BibTeX, DOI and PDF metadata."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import bibtexparser
import rispy

from ..errors import NotFound, UpstreamError, ValidationFailed
from ..models import SearchHit
from .pdf import extract_text
from .search.base import (
    clean_text,
    guess_language,
    human_error,
    normalize_authors,
    normalize_doi,
    pages_from,
    parse_year,
    retry_once,
    status_of,
)
from .search.crossref import CrossrefAdapter, fetch_doi_work

_RIS_TYPE_MAP = {
    "JOUR": "journal-article",
    "BOOK": "book",
    "CHAP": "book-chapter",
    "CONF": "proceedings-article",
    "THES": "thesis",
    "RPRT": "report",
    "GEN": "document",
    "ELEC": "webpage",
    "NEWS": "newspaper-article",
    "MGZN": "magazine-article",
    "UNPB": "manuscript",
    "PAT": "patent",
    "STAND": "standard",
    "DATA": "dataset",
    "COMP": "software",
    "ADVS": "document",
    "SER": "journal-article",
}

_BIB_TYPE_MAP = {
    "article": "journal-article",
    "book": "book",
    "inbook": "book-chapter",
    "incollection": "book-chapter",
    "inproceedings": "proceedings-article",
    "conference": "proceedings-article",
    "proceedings": "proceedings-article",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "thesis": "thesis",
    "techreport": "report",
    "report": "report",
    "online": "webpage",
    "www": "webpage",
    "unpublished": "manuscript",
    "preprint": "preprint",
    "misc": "document",
    "manual": "document",
    "booklet": "document",
}

_BRACE_RE = re.compile(r"[{}]")
_AND_RE = re.compile(r"\s+\band\b\s+", re.I)
_PDF_AUTHOR_SPLIT = re.compile(r"\s*(?:;|；|,|，|、|\band\b)\s*", re.I)


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return ""


def _unbrace(value: Any) -> str:
    """BibTeX braces only protect capitalization; users never want them."""
    return clean_text(_BRACE_RE.sub("", str(value or "")))


def _ris_hit(record: dict[str, Any]) -> SearchHit | None:
    title = clean_text(_first(record, "title", "primary_title", "secondary_title"))
    if not title:
        return None
    doi = normalize_doi(record.get("doi"))
    ris_type = clean_text(record.get("type_of_reference") or "").upper()
    authors = record.get("authors") or record.get("author") or []
    return SearchHit(
        source="ris",
        source_id=clean_text(record.get("id") or ""),
        doi=doi,
        title=title,
        authors=normalize_authors(authors),
        year=parse_year(_first(record, "year", "publication_year", "date")),
        venue=clean_text(
            _first(record, "journal_name", "secondary_title", "tertiary_title", "publisher")
        ),
        volume=clean_text(record.get("volume") or ""),
        issue=clean_text(record.get("issue") or record.get("number") or ""),
        pages=pages_from(record.get("start_page"), record.get("end_page"))
        or clean_text(record.get("pages") or "").replace("--", "-"),
        type=_RIS_TYPE_MAP.get(ris_type, "journal-article"),
        language=clean_text(record.get("language") or ""),
        abstract=clean_text(record.get("abstract") or ""),
        url=clean_text(record.get("url") or ""),
        raw={"ris_type": ris_type, "keywords": record.get("keywords") or []},
    )


def import_ris(text: str) -> list[SearchHit]:
    if not clean_text(text):
        return []
    try:
        records = rispy.loads(text)
    except Exception as exc:  # noqa: BLE001 - surfaced as a friendly 422
        raise ValidationFailed("RIS 解析失败，请检查文件编码与格式。", detail=str(exc)[:300]) from exc
    hits: list[SearchHit] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        hit = _ris_hit(record)
        if hit is not None:
            hits.append(hit)
    return hits


def _bib_fields(entry: Any) -> dict[str, str]:
    fields: dict[str, str] = {}
    for field in getattr(entry, "fields", None) or []:
        key = clean_text(getattr(field, "key", "")).lower()
        if key:
            fields[key] = str(getattr(field, "value", "") or "")
    return fields


def _bib_hit(entry: Any) -> SearchHit | None:
    fields = _bib_fields(entry)
    title = _unbrace(fields.get("title") or fields.get("booktitle"))
    if not title:
        return None
    raw_author = fields.get("author") or fields.get("editor") or ""
    authors = [part for part in _AND_RE.split(raw_author) if part.strip()]
    entry_type = clean_text(getattr(entry, "entry_type", "")).lower()
    doi = normalize_doi(fields.get("doi"))
    return SearchHit(
        source="bibtex",
        source_id=clean_text(getattr(entry, "key", "") or ""),
        doi=doi,
        title=title,
        authors=normalize_authors(authors),
        year=parse_year(fields.get("year") or fields.get("date")),
        venue=_unbrace(_first(fields, "journal", "journaltitle", "booktitle", "publisher")),
        volume=_unbrace(fields.get("volume") or ""),
        issue=_unbrace(fields.get("number") or fields.get("issue") or ""),
        pages=_unbrace(fields.get("pages") or "").replace("--", "-"),
        type=_BIB_TYPE_MAP.get(entry_type, "journal-article"),
        language=_unbrace(fields.get("language") or ""),
        abstract=_unbrace(fields.get("abstract") or ""),
        url=_unbrace(fields.get("url") or ""),
        raw={
            "bibkey": clean_text(getattr(entry, "key", "") or ""),
            "entry_type": entry_type,
        },
    )


def import_bibtex(text: str) -> list[SearchHit]:
    if not clean_text(text):
        return []
    try:
        library = bibtexparser.parse_string(text)
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed("BibTeX 解析失败，请检查花括号是否配对。", detail=str(exc)[:300]) from exc
    entries = list(getattr(library, "entries", None) or [])
    if not entries:
        failed = getattr(library, "failed_blocks", None) or []
        detail = f"{len(failed)} 个块解析失败" if failed else "没有可识别的条目"
        raise ValidationFailed(f"没有解析出 BibTeX 条目（{detail}）。")
    hits: list[SearchHit] = []
    for entry in entries:
        hit = _bib_hit(entry)
        if hit is not None:
            hits.append(hit)
    return hits


def _lookup_crossref(doi: str) -> dict[str, Any] | None:
    """Indirection for tests: patch this to avoid the network."""
    return retry_once(lambda: fetch_doi_work(doi))


def import_doi(doi: str) -> SearchHit:
    normalized = normalize_doi(doi)
    if not normalized:
        raise ValidationFailed("DOI 格式不对，应形如 10.1234/abcd。")
    try:
        work = _lookup_crossref(normalized)
    except Exception as exc:  # noqa: BLE001 - mapped to app errors
        if status_of(exc) == 404:
            raise NotFound(f"没有找到 DOI：{normalized}") from exc
        raise UpstreamError(human_error("doi", exc)) from exc
    if not work:
        raise NotFound(f"没有找到 DOI：{normalized}")
    hit = CrossrefAdapter()._to_hit(work)
    if hit is None:
        raise NotFound(f"没有找到 DOI：{normalized}")
    hit.source = "doi"
    hit.source_id = normalized
    hit.doi = hit.doi or normalized
    return hit


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = clean_text(line)
        if line:
            return line[:200]
    return ""


def import_pdf(data: bytes, *, filename: str = "") -> tuple[SearchHit, str, dict[str, Any]]:
    """Extract text + metadata and build a SearchHit (no DB writes here)."""
    text, meta = extract_text(data)
    title = clean_text(meta.get("title") or "")
    if not title and filename:
        title = clean_text(Path(filename).stem)
    if not title:
        title = _first_line(text)
    if not title:
        raise ValidationFailed("PDF 没有可用标题与正文；如果是扫描件，请手动填写元数据后再上传。")
    raw_authors = clean_text(meta.get("author") or "")
    authors = [part for part in _PDF_AUTHOR_SPLIT.split(raw_authors) if part.strip()]
    hit = SearchHit(
        source="pdf",
        source_id="",
        doi=normalize_doi(meta.get("doi") or ""),
        title=title,
        authors=normalize_authors(authors),
        year=None,
        venue="",
        type="document",
        language=guess_language(title, text[:500]),
        abstract="",
        url="",
        raw={
            "filename": filename,
            "pages": meta.get("pages", 0),
            "scanned": bool(meta.get("scanned")),
            "characters": meta.get("characters", 0),
        },
    )
    return hit, text, meta
