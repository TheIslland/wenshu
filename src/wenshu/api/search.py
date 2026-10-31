"""Literature search API: multi-source search, history, DOI lookup."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..db import Database, json_load
from ..errors import NotFound, ValidationFailed
from ..models import SearchResponse
from ..services import search as search_service
from ..services.importers import import_doi
from .deps import get_con, get_db

router = APIRouter(prefix="/api", tags=["search"])


class SearchFilters(BaseModel):
    year_from: int | None = Field(default=None, ge=1500, le=2200)
    year_to: int | None = Field(default=None, ge=1500, le=2200)
    language: str | None = None
    limit: int | None = Field(default=None, ge=1, le=100)


class SearchPayload(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    sources: list[str] = Field(default_factory=list)
    year_from: int | None = Field(default=None, ge=1500, le=2200)
    year_to: int | None = Field(default=None, ge=1500, le=2200)
    language: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    project_id: int | None = None
    use_cache: bool = True
    filters: SearchFilters | None = None


class DOIRequest(BaseModel):
    doi: str = Field(min_length=1, max_length=300)


def _search_options(con: sqlite3.Connection) -> tuple[str, str]:
    rows = {row["key"]: row["value"] for row in con.execute("SELECT key, value FROM settings")}
    return rows.get("search.mailto", ""), rows.get("search.s2_api_key", "")


def _ensure_project(con: sqlite3.Connection, project_id: int | None) -> None:
    if project_id is None:
        return
    row = con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise NotFound("项目不存在。")


@router.post("/search")
def search(
    payload: SearchPayload,
    con: sqlite3.Connection = Depends(get_con),
    db: Database = Depends(get_db),
) -> dict:
    _ensure_project(con, payload.project_id)
    year_from = payload.year_from
    year_to = payload.year_to
    language = payload.language
    limit = payload.limit
    if payload.filters is not None:
        extra = payload.filters.model_dump(exclude_none=True)
        year_from = extra.get("year_from", year_from)
        year_to = extra.get("year_to", year_to)
        language = extra.get("language", language)
        limit = extra.get("limit", limit)
    if year_from and year_to and year_from > year_to:
        raise ValidationFailed("起始年份不能晚于结束年份。")

    mailto, s2_api_key = _search_options(con)
    meta: dict = {}
    hits, errors = search_service.search_all(
        db,
        payload.query,
        payload.sources,
        limit=limit,
        year_from=year_from,
        year_to=year_to,
        language=language,
        project_id=payload.project_id,
        use_cache=payload.use_cache,
        mailto=mailto,
        s2_api_key=s2_api_key,
        meta=meta,
    )
    response = SearchResponse(
        query=payload.query.strip(),
        results=hits,
        errors=errors,
        cached=bool(meta.get("cached", False)),
        took_ms=int(meta.get("took_ms", 0)),
    )
    return response.model_dump()


@router.get("/search/history")
def history(
    project_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    con: sqlite3.Connection = Depends(get_con),
) -> list[dict]:
    sql = "SELECT id, project_id, source, query, filters, count, created_at FROM searches"
    params: list = []
    if project_id is not None:
        _ensure_project(con, project_id)
        sql += " WHERE project_id=?"
        params.append(project_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["filters"] = json_load(item.get("filters"), {})
        result.append(item)
    return result


@router.get("/search/sources")
def sources() -> list[dict]:
    return [
        {"name": name, "label": adapter.label}
        for name, adapter in search_service.ADAPTERS.items()
    ]


@router.post("/search/doi")
def by_doi(payload: DOIRequest) -> dict:
    return import_doi(payload.doi).model_dump()
