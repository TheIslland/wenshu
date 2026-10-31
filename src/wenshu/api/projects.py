"""Project CRUD."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..db import Database, rows_to_dicts
from ..errors import NotFound
from ..models import Project, ProjectCreate, ProjectPatch, now_iso
from .deps import get_con, get_db

router = APIRouter(prefix="/api", tags=["projects"])


def _get(con: sqlite3.Connection, project_id: int) -> dict:
    row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise NotFound("项目不存在。")
    return dict(row)


@router.get("/projects")
def list_projects(
    con: sqlite3.Connection = Depends(get_con),
) -> list[dict]:
    rows = con.execute(
        "SELECT p.*, "
        "(SELECT COUNT(*) FROM documents d WHERE d.project_id=p.id) AS document_count, "
        "(SELECT COUNT(*) FROM project_refs r WHERE r.project_id=p.id) AS ref_count "
        "FROM projects p ORDER BY p.updated_at DESC"
    ).fetchall()
    return rows_to_dicts(rows)


@router.post("/projects")
def create_project(
    payload: ProjectCreate,
    con: sqlite3.Connection = Depends(get_con),
    db: Database = Depends(get_db),
) -> dict:
    now = now_iso()
    cur = con.execute(
        "INSERT INTO projects(name, field, question, description, status, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            payload.name.strip(),
            payload.field.strip(),
            payload.question.strip(),
            payload.description.strip(),
            "active",
            now,
            now,
        ),
    )
    project_id = int(cur.lastrowid or 0)
    con.execute(
        "INSERT INTO documents(project_id, title, kind, content_md, word_count, version, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (project_id, payload.name.strip(), "paper", "", 0, 1, now, now),
    )
    con.commit()
    return Project(**_get(con, project_id)).model_dump()


@router.get("/projects/{project_id}")
def get_project(
    project_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    data = _get(con, project_id)
    data["document_count"] = con.execute(
        "SELECT COUNT(*) FROM documents WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    data["ref_count"] = con.execute(
        "SELECT COUNT(*) FROM project_refs WHERE project_id=?", (project_id,)
    ).fetchone()[0]
    return data


@router.patch("/projects/{project_id}")
def patch_project(
    project_id: int,
    payload: ProjectPatch,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    current = _get(con, project_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return current
    allowed = {"name", "field", "question", "description", "status"}
    fields = [key for key in changes if key in allowed]
    if not fields:
        return current
    values = [str(changes[key]).strip() if changes[key] is not None else "" for key in fields]
    values.append(now_iso())
    values.append(project_id)
    con.execute(
        f"UPDATE projects SET {', '.join(f'{key}=?' for key in fields)}, updated_at=? WHERE id=?",
        values,
    )
    con.commit()
    return _get(con, project_id)


@router.delete("/projects/{project_id}")
def delete_project(
    project_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    _get(con, project_id)
    con.execute("DELETE FROM projects WHERE id=?", (project_id,))
    con.commit()
    return {"ok": True}
