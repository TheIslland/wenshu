"""Citation verification (Crossref/OpenAlex) and CSL-based formatting.

Network access is caller-controlled: tests inject an ``httpx.Client`` wrapped in
``respx`` so no public request is ever made by the suite. Formatting prefers
citeproc-py + the bundled CSL styles and falls back to a deterministic built-in
GB/T 7714 formatter if rendering fails.
"""

from __future__ import annotations

import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ..db import json_load
from ..models import now_iso

STATUSES = ("verified", "mismatch", "not_found", "no_doi", "error")

CSL_DIR = Path(__file__).resolve().parents[1] / "static" / "csl"
STYLE_FILES = {
    "gbt7714": "china-national-standard-gb-t-7714-2015-numeric.csl",
    "gb": "china-national-standard-gb-t-7714-2015-numeric.csl",
    "gb-t-7714": "china-national-standard-gb-t-7714-2015-numeric.csl",
    "gb-t-7714-2015": "china-national-standard-gb-t-7714-2015-numeric.csl",
    "apa": "apa.csl",
    "apa7": "apa.csl",
    "apa-7": "apa.csl",
}

CROSSREF_WORK = "https://api.crossref.org/works/{doi}"
OPENALEX_WORK = "https://api.openalex.org/works/https://doi.org/{doi}"

_TYPE_MAP = {
    "journal-article": "article-journal",
    "journal": "article-journal",
    "article": "article-journal",
    "book": "book",
    "monograph": "book",
    "chapter": "chapter",
    "book-chapter": "chapter",
    "conference-paper": "paper-conference",
    "conference": "paper-conference",
    "proceedings-article": "paper-conference",
    "thesis": "thesis",
    "dissertation": "thesis",
    "report": "report",
    "newspaper-article": "article-newspaper",
    "webpage": "webpage",
    "preprint": "article",
    "dataset": "dataset",
}

_TYPE_MARK = {
    "journal-article": "J",
    "journal": "J",
    "article": "J",
    "book": "M",
    "monograph": "M",
    "chapter": "M",
    "book-chapter": "M",
    "conference-paper": "C",
    "conference": "C",
    "proceedings-article": "C",
    "thesis": "D",
    "dissertation": "D",
    "report": "R",
    "newspaper-article": "N",
    "webpage": "EB/OL",
    "preprint": "Z",
    "dataset": "DS",
}

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]")


def _coerce_refs(refs: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for ref in refs or []:
        if isinstance(ref, dict):
            data = dict(ref)
        elif isinstance(ref, (str, bytes)):
            continue
        elif hasattr(ref, "model_dump"):
            data = ref.model_dump()
        elif isinstance(ref, sqlite3.Row):
            data = dict(ref)
        else:
            data = {key: getattr(ref, key) for key in dir(ref) if not key.startswith("_")}
            data = {key: value for key, value in data.items() if not callable(value)}
        for key in ("authors", "tags"):
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except ValueError:
                    data[key] = []
        result.append(data)
    return result


def normalize_doi(doi: str | None) -> str:
    value = (doi or "").strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.strip().rstrip(".")


def _norm_title(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def _name_tokens(name: str) -> set[str]:
    cleaned = re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", " ", (name or "").lower())
    tokens = {
        token
        for token in cleaned.split()
        if token and (len(token) >= 2 or _CJK.fullmatch(token))
    }
    return tokens or ({cleaned.strip()} if cleaned.strip() else set())


def _authors_match(local: list[str], remote: list[str]) -> bool:
    local_tokens = [_name_tokens(name) for name in local if str(name).strip()]
    remote_tokens = [_name_tokens(name) for name in remote if str(name).strip()]
    return any(a & b for a in local_tokens for b in remote_tokens)


def _remote_year(value: Any) -> int | None:
    try:
        year = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return year if 1000 <= year <= 2200 else None


def _crossref_metadata(message: dict[str, Any]) -> dict[str, Any]:
    titles = message.get("title") or []
    authors = []
    for author in message.get("author") or []:
        name = " ".join(
            part for part in (author.get("family"), author.get("given")) if part
        ).strip()
        if name:
            authors.append(name)
    date_parts = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    year = _remote_year(date_parts[0]) if date_parts else None
    return {
        "title": str(titles[0]).strip() if titles else "",
        "authors": authors,
        "year": year,
        "venue": str((message.get("container-title") or [""])[0] or "").strip(),
        "doi": normalize_doi(message.get("DOI")),
        "type": message.get("type", ""),
    }


def _openalex_metadata(data: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for authorship in data.get("authorships") or []:
        name = ((authorship or {}).get("author") or {}).get("display_name")
        if name:
            authors.append(str(name))
    return {
        "title": str(data.get("title") or data.get("display_name") or "").strip(),
        "authors": authors,
        "year": _remote_year(data.get("publication_year")),
        "venue": str(
            ((data.get("primary_location") or {}).get("source") or {}).get("display_name")
            or ""
        ).strip(),
        "doi": normalize_doi(data.get("doi")),
        "type": data.get("type", ""),
    }


def _lookup(
    client: httpx.Client, url: str, *, headers: dict[str, str] | None = None
) -> dict[str, Any] | None:
    response = client.get(url, headers=headers or {})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    if "message" in payload and isinstance(payload["message"], dict):
        return payload["message"]
    return payload


def _mailto(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT value FROM settings WHERE key='search.mailto'").fetchone()
    return str(row["value"]).strip() if row else ""


def _compare(ref: dict[str, Any], remote: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    local_title = str(ref.get("title") or "").strip()
    remote_title = str(remote.get("title") or "").strip()
    if remote_title:
        ratio = SequenceMatcher(None, _norm_title(local_title), _norm_title(remote_title)).ratio()
        if ratio < 0.9:
            issues.append(
                {
                    "field": "title",
                    "message": "标题与远端元数据不一致。",
                    "local": local_title,
                    "remote": remote_title,
                    "similarity": round(ratio, 3),
                }
            )
    else:
        issues.append({"field": "title", "message": "远端缺少标题，无法比对。"})

    local_year = ref.get("year")
    remote_year = remote.get("year")
    if local_year and remote_year and int(local_year) != int(remote_year):
        issues.append(
            {
                "field": "year",
                "message": "年份与远端元数据不一致。",
                "local": int(local_year),
                "remote": int(remote_year),
            }
        )

    local_authors = [str(name) for name in (ref.get("authors") or []) if str(name).strip()]
    remote_authors = [str(name) for name in (remote.get("authors") or []) if str(name).strip()]
    if local_authors and remote_authors and not _authors_match(local_authors, remote_authors):
        issues.append(
            {
                "field": "authors",
                "message": "作者与远端元数据不一致。",
                "local": local_authors,
                "remote": remote_authors,
            }
        )
    return issues


def _save_check(
    con: sqlite3.Connection, ref_id: int, status: str, detail: dict[str, Any]
) -> None:
    con.execute(
        "INSERT INTO citation_checks(ref_id, status, detail, checked_at) VALUES(?,?,?,?)",
        (ref_id, status, json.dumps(detail, ensure_ascii=False), now_iso()),
    )
    con.commit()


def _verify_one(
    con: sqlite3.Connection, ref: dict[str, Any], client: httpx.Client, mailto: str
) -> dict[str, Any]:
    ref_id = int(ref["id"])
    doi = normalize_doi(ref.get("doi"))
    if not doi:
        detail = {"reason": "文献没有 DOI，需人工核对。", "tried": []}
        _save_check(con, ref_id, "no_doi", detail)
        return {"ref_id": ref_id, "status": "no_doi", "detail": detail}

    headers = {"User-Agent": f"Wenshu/0.1 (mailto:{mailto})"} if mailto else {}
    remote: dict[str, Any] | None = None
    via = ""
    errors: list[str] = []
    tried: list[str] = []
    try:
        tried.append("crossref")
        message = _lookup(client, CROSSREF_WORK.format(doi=quote(doi, safe="/")), headers=headers)
        if message:
            remote = _crossref_metadata(message)
            via = "crossref"
    except httpx.HTTPError as exc:
        errors.append(f"Crossref 查询失败：{exc}")
    if remote is None:
        try:
            tried.append("openalex")
            data = _lookup(client, OPENALEX_WORK.format(doi=quote(doi, safe="/")))
            if data:
                remote = _openalex_metadata(data)
                via = "openalex"
        except httpx.HTTPError as exc:
            errors.append(f"OpenAlex 查询失败：{exc}")

    if remote is None:
        if errors and len(errors) >= len(tried):
            status = "error"
            detail = {"reason": "核对服务不可用。", "tried": tried, "errors": errors, "doi": doi}
        else:
            status = "not_found"
            detail = {
                "reason": "Crossref 与 OpenAlex 都找不到这个 DOI。",
                "tried": tried,
                "errors": errors,
                "doi": doi,
            }
        _save_check(con, ref_id, status, detail)
        return {"ref_id": ref_id, "status": status, "detail": detail}

    issues = _compare(ref, remote)
    status = "mismatch" if issues else "verified"
    detail = {
        "doi": doi,
        "source": via,
        "remote": remote,
        "issues": issues,
        "errors": errors,
    }
    _save_check(con, ref_id, status, detail)
    return {"ref_id": ref_id, "status": status, "detail": detail}


def verify(
    con: sqlite3.Connection,
    ref_ids: list[int] | None = None,
    *,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Verify references by DOI against Crossref, then OpenAlex."""
    if ref_ids is not None:
        unique_ids = list(dict.fromkeys(int(ref_id) for ref_id in ref_ids))
        if not unique_ids:
            return []
        placeholders = ",".join("?" for _ in unique_ids)
        rows = con.execute(
            f"SELECT * FROM refs WHERE id IN ({placeholders}) ORDER BY id", unique_ids
        ).fetchall()
    else:
        rows = con.execute("SELECT * FROM refs ORDER BY id").fetchall()
    refs = _coerce_refs(rows)
    mailto = _mailto(con)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=15, follow_redirects=True)
    try:
        results = []
        for ref in refs:
            try:
                results.append(_verify_one(con, ref, client, mailto))
            except Exception as exc:  # noqa: BLE001 - one bad ref must not stop the batch
                ref_id = int(ref["id"])
                detail = {"reason": f"核验过程出错：{exc}", "tried": []}
                _save_check(con, ref_id, "error", detail)
                results.append({"ref_id": ref_id, "status": "error", "detail": detail})
        return results
    finally:
        if owns_client:
            client.close()


def _style_path(style: str) -> Path:
    filename = STYLE_FILES.get((style or "gbt7714").strip().lower())
    if filename is None:
        raise ValueError(f"未知引用样式：{style}")
    return CSL_DIR / filename


def _parse_author(name: str) -> dict[str, str]:
    clean = re.sub(r"\s+", " ", str(name or "")).strip()
    if not clean:
        return {"literal": ""}
    if "," in clean:
        family, given = clean.split(",", 1)
        return {"family": family.strip(), "given": given.strip()}
    if _CJK.search(clean) and " " not in clean:
        return {"family": clean}
    parts = clean.split(" ")
    if len(parts) == 1:
        return {"family": parts[0]}
    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def _to_csl_json(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, ref in enumerate(refs, start=1):
        record: dict[str, Any] = {
            "id": str(index),
            "type": _TYPE_MAP.get(str(ref.get("type") or ""), "article-journal"),
            "title": str(ref.get("title") or "无题名"),
            "author": [
                parsed
                for parsed in (_parse_author(name) for name in (ref.get("authors") or []))
                if parsed.get("family") or parsed.get("literal")
            ],
        }
        if ref.get("year"):
            record["issued"] = {"date-parts": [[int(ref["year"])]]}
        for source, target in (
            ("venue", "container-title"),
            ("volume", "volume"),
            ("issue", "issue"),
            ("pages", "page"),
            ("doi", "DOI"),
            ("url", "URL"),
            ("language", "language"),
        ):
            value = ref.get(source)
            if value not in (None, ""):
                record[target] = str(value)
        if not record["author"]:
            record.pop("author")
        records.append(record)
    return records


def _render_citeproc(refs: list[dict[str, Any]], style: str) -> str:
    import citeproc
    from citeproc import (
        Citation,
        CitationItem,
        CitationStylesBibliography,
        CitationStylesStyle,
    )
    from citeproc.source.json import CiteProcJSON

    path = _style_path(style)
    if not path.exists():
        raise FileNotFoundError(f"缺少 CSL 样式文件：{path.name}")
    records = _to_csl_json(refs)
    source = CiteProcJSON(records)
    csl_style = CitationStylesStyle(str(path), validate=False)
    bibliography = CitationStylesBibliography(csl_style, source, citeproc.formatter.plain)
    for record in records:
        bibliography.register(Citation([CitationItem(record["id"])]))
    entries = bibliography.bibliography()
    lines: list[str] = []
    for entry in entries:
        text = "".join(str(part) for part in entry) if isinstance(entry, list) else str(entry)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            lines.append(text)
    if not lines:
        raise ValueError("CSL 渲染结果为空")
    return "\n".join(lines)


def _format_author_gbt(name: str) -> str:
    clean = re.sub(r"\s+", " ", str(name or "")).strip()
    if not clean:
        return ""
    if _CJK.search(clean):
        return clean
    if "," in clean:
        family, given = (part.strip() for part in clean.split(",", 1))
    else:
        parts = clean.split(" ")
        family, given = parts[-1], " ".join(parts[:-1])
    initials = "".join(part[0].upper() for part in re.split(r"[.\s-]+", given) if part)
    return f"{family.upper()} {initials}".strip()


def format_gbt7714(refs: Any) -> str:
    """Deterministic built-in GB/T 7714-2015 numeric fallback."""
    items = _coerce_refs(refs)
    lines: list[str] = []
    for index, ref in enumerate(items, start=1):
        authors = [
            _format_author_gbt(name)
            for name in (ref.get("authors") or [])
            if str(name).strip()
        ]
        suffix = ""
        if len(authors) > 3:
            authors = authors[:3]
            suffix = ", 等" if any(_CJK.search(name) for name in authors) else ", et al."
        author_text = ", ".join(authors) + suffix
        title = str(ref.get("title") or "无题名").strip()
        marker = _TYPE_MARK.get(str(ref.get("type") or ""), "Z")
        line = f"[{index}] "
        if author_text:
            line += f"{author_text}. "
        line += f"{title}[{marker}]."
        venue = str(ref.get("venue") or "").strip()
        if venue:
            line += f" {venue},"
        if ref.get("year"):
            line += f" {int(ref['year'])}"
        if ref.get("volume"):
            line += f", {ref['volume']}"
        if ref.get("issue"):
            line += f"({ref['issue']})"
        if ref.get("pages"):
            line += f": {ref['pages']}"
        if not line.endswith("."):
            line += "."
        url = str(ref.get("url") or "").strip()
        if url and marker in {"EB/OL", "Z"}:
            line += f" {url}."
        lines.append(line)
    return "\n".join(lines)


def format_refs_report(refs: Any, style: str = "gbt7714") -> dict[str, Any]:
    """Format references and report which engine was used plus fallback warnings."""
    items = _coerce_refs(refs)
    resolved = (style or "gbt7714").strip().lower()
    warnings: list[str] = []
    if not items:
        return {"text": "", "style": resolved, "engine": "builtin", "warnings": warnings}
    if resolved not in STYLE_FILES:
        warnings.append(f"未知引用样式「{style}」，已回退 GB/T 7714。")
        resolved = "gbt7714"
    try:
        text = _render_citeproc(items, resolved)
        return {"text": text, "style": resolved, "engine": "citeproc", "warnings": warnings}
    except Exception as exc:  # noqa: BLE001 - guaranteed fallback path
        warnings.append(
            f"citeproc 渲染失败，已回退内置 GB/T 7714 格式化（样式 {resolved} 未生效）：{exc}"
        )
        return {
            "text": format_gbt7714(items),
            "style": resolved,
            "engine": "builtin",
            "warnings": warnings,
        }


def format_refs(refs: Any, style: str = "gbt7714") -> str:
    return format_refs_report(refs, style)["text"]


def latest_checks(con: sqlite3.Connection, ref_ids: list[int] | None = None) -> list[dict]:
    """Return the latest citation check per reference."""
    sql = (
        "SELECT c.* FROM citation_checks c JOIN ("
        "SELECT ref_id, MAX(id) AS mid FROM citation_checks GROUP BY ref_id"
        ") latest ON latest.mid=c.id"
    )
    params: list[Any] = []
    if ref_ids is not None:
        if not ref_ids:
            return []
        placeholders = ",".join("?" for _ in ref_ids)
        sql += f" WHERE c.ref_id IN ({placeholders})"
        params.extend(int(ref_id) for ref_id in ref_ids)
    sql += " ORDER BY c.ref_id"
    result = []
    for row in con.execute(sql, params).fetchall():
        data = dict(row)
        data["detail"] = json_load(data.get("detail"), {})
        result.append(data)
    return result
