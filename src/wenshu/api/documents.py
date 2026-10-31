"""Documents, autosave with optimistic locking, snapshots, outline."""

from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..errors import Conflict, NotFound
from ..models import DocumentCreate, DocumentSave, now_iso
from .deps import get_con

router = APIRouter(prefix="/api", tags=["documents"])

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]")
_LATIN = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def count_words(text: str) -> int:
    return len(_CJK.findall(text)) + len(_LATIN.findall(text))


def _document(con: sqlite3.Connection, document_id: int) -> dict:
    row = con.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not row:
        raise NotFound("文档不存在。")
    return dict(row)


class SnapshotCreate(BaseModel):
    reason: str = ""


@router.get("/projects/{project_id}/documents")
def list_documents(
    project_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> list[dict]:
    if not con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise NotFound("项目不存在。")
    rows = con.execute(
        "SELECT id, project_id, title, kind, word_count, version, created_at, updated_at "
        "FROM documents WHERE project_id=? ORDER BY updated_at DESC",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/projects/{project_id}/documents")
def create_document(
    project_id: int,
    payload: DocumentCreate,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    if not con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise NotFound("项目不存在。")
    now = now_iso()
    cur = con.execute(
        "INSERT INTO documents(project_id, title, kind, content_md, word_count, version, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (
            project_id,
            payload.title.strip(),
            payload.kind,
            payload.content_md,
            count_words(payload.content_md),
            1,
            now,
            now,
        ),
    )
    con.commit()
    return _document(con, int(cur.lastrowid or 0))


@router.get("/documents/{document_id}")
def get_document(
    document_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    return _document(con, document_id)


@router.put("/documents/{document_id}")
def save_document(
    document_id: int,
    payload: DocumentSave,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    current = _document(con, document_id)
    if int(current["version"]) != payload.version:
        raise Conflict(
            "文档已被其他窗口修改，请刷新后再保存。",
            detail={"current_version": current["version"]},
        )
    now = now_iso()
    cur = con.execute(
        "UPDATE documents SET content_md=?, word_count=?, version=version+1, updated_at=? "
        "WHERE id=? AND version=?",
        (payload.content_md, count_words(payload.content_md), now, document_id, payload.version),
    )
    if cur.rowcount == 0:
        raise Conflict("保存冲突，请刷新后重试。")
    con.commit()
    return _document(con, document_id)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    _document(con, document_id)
    con.execute("DELETE FROM documents WHERE id=?", (document_id,))
    con.commit()
    return {"ok": True}


@router.get("/documents/{document_id}/outline")
def outline(
    document_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> list[dict]:
    doc = _document(con, document_id)
    result = []
    for match in _HEADING.finditer(doc["content_md"]):
        title = match.group(2).strip()
        result.append(
            {
                "level": len(match.group(1)),
                "title": title,
                "anchor": re.sub(r"\s+", "-", title.lower()),
                "line": doc["content_md"][: match.start()].count("\n") + 1,
            }
        )
    return result


@router.post("/documents/{document_id}/snapshots")
def create_snapshot(
    document_id: int,
    payload: SnapshotCreate,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    doc = _document(con, document_id)
    now = now_iso()
    cur = con.execute(
        "INSERT INTO snapshots(document_id, content_md, reason, created_at) VALUES(?,?,?,?)",
        (document_id, doc["content_md"], payload.reason.strip(), now),
    )
    con.commit()
    return {"id": int(cur.lastrowid or 0), "created_at": now, "reason": payload.reason.strip()}


@router.get("/documents/{document_id}/snapshots")
def list_snapshots(
    document_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> list[dict]:
    _document(con, document_id)
    rows = con.execute(
        "SELECT id, document_id, reason, LENGTH(content_md) AS chars, created_at "
        "FROM snapshots WHERE document_id=? ORDER BY id DESC LIMIT 50",
        (document_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/documents/{document_id}/restore/{snapshot_id}")
def restore_snapshot(
    document_id: int,
    snapshot_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    _document(con, document_id)
    snap = con.execute(
        "SELECT * FROM snapshots WHERE id=? AND document_id=?", (snapshot_id, document_id)
    ).fetchone()
    if not snap:
        raise NotFound("快照不存在。")
    now = now_iso()
    con.execute(
        "UPDATE documents SET content_md=?, word_count=?, version=version+1, updated_at=? "
        "WHERE id=?",
        (snap["content_md"], count_words(snap["content_md"]), now, document_id),
    )
    con.commit()
    return _document(con, document_id)
