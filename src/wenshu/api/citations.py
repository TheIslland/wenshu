"""Citation verification and formatting API."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..db import json_load
from ..errors import ValidationFailed
from ..services import citations as service
from .deps import get_con

router = APIRouter(prefix="/api", tags=["citations"])


class VerifyPayload(BaseModel):
    project_id: int | None = None
    ref_ids: list[int] | None = None


def _project_ref_ids(con: sqlite3.Connection, project_id: int) -> list[int]:
    rows = con.execute(
        "SELECT ref_id FROM project_refs WHERE project_id=? ORDER BY ref_id", (project_id,)
    ).fetchall()
    return [int(row["ref_id"]) for row in rows]


def _refs(con: sqlite3.Connection, project_id: int | None, ref_ids: list[int] | None) -> list[dict]:
    if ref_ids is None and project_id is not None:
        ref_ids = _project_ref_ids(con, project_id)
    sql = "SELECT * FROM refs"
    params: list[int] = []
    if ref_ids is not None:
        if not ref_ids:
            return []
        placeholders = ",".join("?" for _ in ref_ids)
        sql += f" WHERE id IN ({placeholders})"
        params.extend(int(ref_id) for ref_id in ref_ids)
    sql += " ORDER BY id"
    return [dict(row) for row in con.execute(sql, params).fetchall()]


@router.post("/citations/verify")
def verify(
    payload: VerifyPayload,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    ref_ids = payload.ref_ids
    if ref_ids is None and payload.project_id is not None:
        ref_ids = _project_ref_ids(con, payload.project_id)
    results = service.verify(con, ref_ids)
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"results": results, "counts": counts}


@router.get("/citations/format")
def format_refs(
    con: sqlite3.Connection = Depends(get_con),
    project_id: int | None = None,
    ref_ids: str | None = None,
    style: str = "gbt7714",
) -> dict:
    parsed_ids = None
    if ref_ids:
        try:
            parsed_ids = [int(part) for part in ref_ids.split(",") if part.strip()]
        except ValueError as exc:
            raise ValidationFailed("ref_ids 必须是逗号分隔的整数。") from exc
    items = _refs(con, project_id, parsed_ids)
    report = service.format_refs_report(items, style)
    return {**report, "count": len(items)}


@router.get("/citations/checks")
def latest_checks(
    con: sqlite3.Connection = Depends(get_con),
    project_id: int | None = None,
) -> list[dict]:
    ref_ids = _project_ref_ids(con, project_id) if project_id is not None else None
    checks = service.latest_checks(con, ref_ids)
    titles = {
        int(row["id"]): row["title"]
        for row in con.execute("SELECT id, title FROM refs").fetchall()
    }
    for item in checks:
        item["detail"] = json_load(item.get("detail"), {})
        item["title"] = titles.get(int(item["ref_id"]), "")
    return checks
