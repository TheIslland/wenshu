"""Reference library: upsert with dedupe, list/search, patch, PDF attachment."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from ..db import json_load
from ..errors import Conflict, NotFound, ValidationFailed
from ..models import SearchHit, now_iso
from .pdf import extract_text, save_attachment, save_fulltext
from .search.base import (
    clean_text,
    normalize_doi,
    normalize_title,
    parse_year,
    title_similarity,
)

STATUSES = ("inbox", "reading", "read", "cited")

_REF_COLUMNS = (
    "doi",
    "title",
    "authors",
    "year",
    "venue",
    "volume",
    "issue",
    "pages",
    "type",
    "language",
    "abstract",
    "url",
    "source",
    "source_id",
    "bibkey",
    "tags",
    "note",
    "status",
    "pdf_path",
    "fulltext_path",
    "fulltext",
)

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "about",
    "this",
    "that",
    "中国",
    "研究",
}


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _ref_out(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    authors = json_load(data.get("authors"), [])
    tags = json_load(data.get("tags"), [])
    fulltext = data.pop("fulltext", "") or ""
    data["authors"] = authors if isinstance(authors, list) else []
    data["tags"] = tags if isinstance(tags, list) else []
    data["has_fulltext"] = bool(fulltext)
    data["fulltext_chars"] = len(fulltext)
    data.pop("fulltext_path", None)
    if "relevance" in data and data["relevance"] is not None:
        data["relevance"] = float(data["relevance"])
    return data


def _bibkey(authors: list[str], year: int | None, title: str, doi: str | None) -> str:
    first = authors[0] if authors else ""
    ascii_author = re.sub(r"[^A-Za-z0-9]", "", first.split()[-1]) if first else ""
    if not ascii_author:
        ascii_author = re.sub(r"[^A-Za-z0-9]", "", first) or "ref"
    ascii_author = ascii_author.lower()[:24] or "ref"
    word = ""
    for token in re.findall(r"[A-Za-z0-9]+", title.lower()):
        if len(token) > 2 and token not in _STOPWORDS:
            word = token
            break
    if not word:
        salt = doi or normalize_title(title) or title
        word = hashlib.sha1(salt.encode("utf-8")).hexdigest()[:6]
    return f"{ascii_author}{year or ''}{word}"


def _unique_bibkey(con: sqlite3.Connection, base: str, *, exclude_id: int | None = None) -> str:
    candidate = base
    suffix = 0
    while True:
        row = con.execute(
            "SELECT id FROM refs WHERE bibkey=? AND id IS NOT ?", (candidate, exclude_id)
        ).fetchone()
        if not row:
            return candidate
        suffix += 1
        candidate = f"{base}{chr(96 + suffix)}" if suffix <= 26 else f"{base}{suffix}"


def _hit_bibkey(hit: SearchHit) -> str:
    raw = hit.raw if isinstance(hit.raw, dict) else {}
    return clean_text(raw.get("bibkey") or "")


def _find_title_match(con: sqlite3.Connection, hit: SearchHit) -> int | None:
    incoming_key = normalize_title(hit.title)
    if not incoming_key:
        return None
    doi = normalize_doi(hit.doi)
    if hit.year is not None:
        rows = con.execute(
            "SELECT id, doi, title, year FROM refs WHERE year IS NULL OR year=?", (hit.year,)
        ).fetchall()
    else:
        # No year in the incoming record: compare titles against the whole library.
        rows = con.execute("SELECT id, doi, title, year FROM refs LIMIT 5000").fetchall()
    for row in rows:
        candidate_doi = normalize_doi(row["doi"])
        if doi and candidate_doi and candidate_doi != doi:
            continue
        if hit.year is not None and row["year"] is not None and int(row["year"]) != hit.year:
            continue
        candidate_key = normalize_title(row["title"])
        if not candidate_key:
            continue
        if candidate_key == incoming_key:
            return int(row["id"])
        if min(len(candidate_key), len(incoming_key)) < 8:
            continue
        if title_similarity(row["title"], hit.title) >= 0.92:
            return int(row["id"])
    return None


def _merged_values(row: sqlite3.Row, hit: SearchHit) -> dict[str, Any]:
    existing_authors = json_load(row["authors"], [])
    incoming_authors = [clean_text(author) for author in hit.authors if clean_text(author)]
    authors = (
        incoming_authors
        if len(incoming_authors) > len(existing_authors or [])
        else list(existing_authors or [])
    )
    incoming_type = clean_text(hit.type) or "journal-article"
    current_type = clean_text(row["type"]) or "journal-article"
    if current_type in ("", "journal-article") and incoming_type != "journal-article":
        current_type = incoming_type
    incoming_abstract = clean_text(hit.abstract)
    abstract = (
        incoming_abstract
        if len(incoming_abstract) > len(row["abstract"] or "")
        else (row["abstract"] or "")
    )
    doi = normalize_doi(row["doi"]) or normalize_doi(hit.doi)
    bibkey = clean_text(row["bibkey"])
    if not bibkey:
        bibkey = _hit_bibkey(hit) or _bibkey(
            authors, parse_year(row["year"]) or hit.year, row["title"], doi
        )
    return {
        "doi": doi,
        "title": clean_text(row["title"]) or clean_text(hit.title),
        "authors": _json_dump(authors),
        "year": row["year"] if row["year"] is not None else hit.year,
        "venue": clean_text(row["venue"]) or clean_text(hit.venue),
        "volume": clean_text(row["volume"]) or clean_text(hit.volume),
        "issue": clean_text(row["issue"]) or clean_text(hit.issue),
        "pages": clean_text(row["pages"]) or clean_text(hit.pages),
        "type": current_type,
        "language": clean_text(row["language"]) or clean_text(hit.language),
        "abstract": abstract,
        "url": clean_text(row["url"]) or clean_text(hit.url),
        "source": clean_text(row["source"]) or clean_text(hit.source),
        "source_id": clean_text(row["source_id"]) or clean_text(hit.source_id),
        "bibkey": bibkey,
        "tags": row["tags"] or "[]",
        "note": row["note"] or "",
        "status": row["status"] or "inbox",
        "pdf_path": row["pdf_path"],
        "fulltext_path": row["fulltext_path"],
        "fulltext": row["fulltext"] or "",
        "updated_at": now_iso(),
    }


def _link_project(
    con: sqlite3.Connection, project_id: int | None, ref_id: int, relevance: float
) -> None:
    if project_id is None:
        return
    now = now_iso()
    con.execute(
        "INSERT INTO project_refs(project_id, ref_id, relevance, added_at) VALUES(?,?,?,?) "
        "ON CONFLICT(project_id, ref_id) DO UPDATE SET relevance=MAX(relevance, excluded.relevance)",
        (project_id, ref_id, float(relevance), now),
    )


def upsert_ref(
    con: sqlite3.Connection,
    hit: SearchHit,
    project_id: int | None = None,
    *,
    relevance: float = 0.0,
) -> int:
    """Insert or merge one hit; returns the global ref id (DOI unique)."""
    title = clean_text(hit.title)
    if not title:
        raise ValidationFailed("文献标题不能为空。")
    doi = normalize_doi(hit.doi)
    existing = con.execute("SELECT * FROM refs WHERE doi=?", (doi,)).fetchone() if doi else None
    if existing is None:
        match_id = _find_title_match(con, hit)
        if match_id is not None:
            existing = con.execute("SELECT * FROM refs WHERE id=?", (match_id,)).fetchone()

    now = now_iso()
    if existing is not None:
        ref_id = int(existing["id"])
        values = _merged_values(existing, hit)
        if not values["bibkey"]:
            authors_value = json_load(values["authors"], [])
            values["bibkey"] = _unique_bibkey(
                con,
                _bibkey(authors_value, values["year"], values["title"], values["doi"]),
                exclude_id=ref_id,
            )
        columns = ", ".join(f"{column}=?" for column in values)
        con.execute(f"UPDATE refs SET {columns} WHERE id=?", (*values.values(), ref_id))
    else:
        authors = [clean_text(author) for author in hit.authors if clean_text(author)]
        bibkey = _unique_bibkey(
            con,
            _hit_bibkey(hit) or _bibkey(authors, hit.year, title, doi),
            exclude_id=None,
        )
        values = {
            "doi": doi,
            "title": title,
            "authors": _json_dump(authors),
            "year": hit.year,
            "venue": clean_text(hit.venue),
            "volume": clean_text(hit.volume),
            "issue": clean_text(hit.issue),
            "pages": clean_text(hit.pages),
            "type": clean_text(hit.type) or "journal-article",
            "language": clean_text(hit.language),
            "abstract": clean_text(hit.abstract),
            "url": clean_text(hit.url),
            "source": clean_text(hit.source),
            "source_id": clean_text(hit.source_id),
            "bibkey": bibkey,
            "tags": "[]",
            "note": "",
            "status": "inbox",
            "pdf_path": None,
            "fulltext_path": None,
            "fulltext": "",
            "created_at": now,
            "updated_at": now,
        }
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        cursor = con.execute(
            f"INSERT INTO refs({columns}) VALUES({placeholders})", tuple(values.values())
        )
        ref_id = int(cursor.lastrowid or 0)

    _link_project(con, project_id, ref_id, relevance)
    con.commit()
    return ref_id


def get_ref(con: sqlite3.Connection, ref_id: int) -> dict[str, Any]:
    row = con.execute("SELECT * FROM refs WHERE id=?", (ref_id,)).fetchone()
    if not row:
        raise NotFound("文献不存在。")
    return _ref_out(row)


def _fts_clause(con: sqlite3.Connection, query: str) -> tuple[str, list[Any]] | None:
    if len(query) < 3:
        return None
    exists = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='refs_fts'"
    ).fetchone()
    if not exists:
        return None
    tokens = [token for token in query.split() if token]
    if len(tokens) > 1:
        literal = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
    else:
        literal = '"' + query.replace('"', '""') + '"'
    return "r.id IN (SELECT rowid FROM refs_fts WHERE refs_fts MATCH ?)", [literal]


def _like_params(query: str) -> list[str]:
    needle = f"%{query}%"
    return [needle] * 5


def _build_list_sql(
    *,
    project_id: int | None,
    status: str | None,
    tag: str | None,
    fts: tuple[str, list[Any]] | None,
    like_query: str | None,
    limit: int,
    offset: int,
) -> tuple[str, list[Any]]:
    sql = "SELECT r.*"
    params: list[Any] = []
    if project_id is not None:
        sql += ", pr.relevance AS relevance, pr.added_at AS project_added_at"
    sql += " FROM refs r"
    if project_id is not None:
        sql += " JOIN project_refs pr ON pr.ref_id=r.id AND pr.project_id=?"
        params.append(project_id)
    where: list[str] = []
    if status:
        where.append("r.status=?")
        params.append(status)
    if tag:
        where.append("r.tags LIKE ?")
        params.append(f"%{json.dumps(tag, ensure_ascii=False)}%")
    if fts is not None:
        where.append(fts[0])
        params.extend(fts[1])
    elif like_query is not None:
        where.append(
            "(r.title LIKE ? OR r.abstract LIKE ? OR r.note LIKE ? OR "
            "r.fulltext LIKE ? OR r.authors LIKE ?)"
        )
        params.extend(_like_params(like_query))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.updated_at DESC, r.id DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit or 200), 200)), max(0, int(offset or 0))])
    return sql, params


def list_refs(
    con: sqlite3.Connection,
    project_id: int | None = None,
    q: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = clean_text(q or "")
    status_value = clean_text(status or "") or None
    tag_value = clean_text(tag or "") or None
    if status_value and status_value not in STATUSES:
        raise ValidationFailed(
            f"未知的阅读状态：{status_value}。", detail={"allowed": list(STATUSES)}
        )
    fts = _fts_clause(con, query) if query else None
    sql, params = _build_list_sql(
        project_id=project_id,
        status=status_value,
        tag=tag_value,
        fts=fts,
        like_query=query if fts is None and query else None,
        limit=limit,
        offset=offset,
    )
    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # Malformed FTS input or a broken FTS index: fall back to LIKE.
        sql, params = _build_list_sql(
            project_id=project_id,
            status=status_value,
            tag=tag_value,
            fts=None,
            like_query=query or None,
            limit=limit,
            offset=offset,
        )
        rows = con.execute(sql, params).fetchall()
    return [_ref_out(row) for row in rows]


def patch_ref(
    con: sqlite3.Connection, ref_id: int, changes: dict[str, Any]
) -> dict[str, Any]:
    row = con.execute("SELECT * FROM refs WHERE id=?", (ref_id,)).fetchone()
    if not row:
        raise NotFound("文献不存在。")
    allowed = {
        "title",
        "authors",
        "year",
        "venue",
        "volume",
        "issue",
        "pages",
        "doi",
        "url",
        "type",
        "language",
        "abstract",
        "note",
        "tags",
        "status",
        "bibkey",
    }
    fields: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key in ("authors", "tags"):
            fields[key] = _json_dump(list(value or []))
        elif key == "doi":
            if value in (None, ""):
                fields[key] = None
            else:
                normalized = normalize_doi(value)
                if not normalized:
                    raise ValidationFailed("DOI 格式不对，应形如 10.1234/abcd。")
                conflict = con.execute(
                    "SELECT id FROM refs WHERE doi=? AND id IS NOT ?", (normalized, ref_id)
                ).fetchone()
                if conflict:
                    raise Conflict("这篇文献的 DOI 已经存在于文献库中。")
                fields[key] = normalized
        elif key == "status":
            status_value = clean_text(value)
            if status_value not in STATUSES:
                raise ValidationFailed(
                    f"未知的阅读状态：{status_value}。", detail={"allowed": list(STATUSES)}
                )
            fields[key] = status_value
        elif key == "year":
            fields[key] = int(value) if value not in (None, "") else None
        elif key == "bibkey":
            if clean_text(value):
                fields[key] = clean_text(value)
        else:
            fields[key] = clean_text(value)
    if not fields:
        return _ref_out(row)
    fields["updated_at"] = now_iso()
    columns = ", ".join(f"{column}=?" for column in fields)
    con.execute(f"UPDATE refs SET {columns} WHERE id=?", (*fields.values(), ref_id))
    con.commit()
    return get_ref(con, ref_id)


def attach_pdf(
    con: sqlite3.Connection,
    ref_id: int,
    data: bytes,
    attachments_dir: Path,
) -> dict[str, Any]:
    """Save the PDF under its hash name, extract fulltext, refresh FTS."""
    row = con.execute("SELECT * FROM refs WHERE id=?", (ref_id,)).fetchone()
    if not row:
        raise NotFound("文献不存在。")
    text, meta = extract_text(data)
    pdf_path = save_attachment(data, Path(attachments_dir))
    fulltext_path = save_fulltext(text, Path(attachments_dir)) if text else None

    fields: dict[str, Any] = {
        "pdf_path": str(pdf_path),
        "fulltext_path": str(fulltext_path) if fulltext_path else row["fulltext_path"],
        "fulltext": text or row["fulltext"] or "",
        "updated_at": now_iso(),
    }
    if not clean_text(row["title"]) or clean_text(row["title"]) == "未命名 PDF":
        title = clean_text(meta.get("title") or "")
        if title:
            fields["title"] = title
    if not normalize_doi(row["doi"]):
        doi = normalize_doi(meta.get("doi"))
        if doi:
            fields["doi"] = doi
    if not json_load(row["authors"], []):
        author_text = clean_text(meta.get("author") or "")
        authors = [
            part.strip()
            for part in re.split(r"\s*(?:;|；|,|，|、|\band\b)\s*", author_text)
            if part.strip()
        ]
        if authors:
            fields["authors"] = _json_dump(authors)
    columns = ", ".join(f"{column}=?" for column in fields)
    con.execute(f"UPDATE refs SET {columns} WHERE id=?", (*fields.values(), ref_id))
    con.commit()
    return get_ref(con, ref_id)


def get_ref_text(
    con: sqlite3.Connection, ref_id: int, q: str | None = None
) -> dict[str, Any]:
    row = con.execute("SELECT fulltext FROM refs WHERE id=?", (ref_id,)).fetchone()
    if not row:
        raise NotFound("文献不存在。")
    fulltext = row["fulltext"] or ""
    query = clean_text(q or "")
    payload: dict[str, Any] = {
        "ref_id": ref_id,
        "q": query,
        "chars": len(fulltext),
        "matches": [],
    }
    if not query:
        payload["text"] = fulltext[:20000]
        return payload
    lowered = fulltext.lower()
    needle = query.lower()
    start = 0
    while len(payload["matches"]) < 8:
        index = lowered.find(needle, start)
        if index < 0:
            break
        left = max(0, index - 80)
        right = min(len(fulltext), index + len(query) + 80)
        payload["matches"].append(
            {
                "start": index,
                "end": index + len(query),
                "snippet": fulltext[left:right].replace("\n", " "),
            }
        )
        start = index + max(1, len(query))
    return payload
