"""Document export API: Markdown, DOCX, BibTeX, RIS."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from ..errors import NotFound, ValidationFailed
from ..services import citations as citation_service
from ..services import exporters as service
from .deps import get_con

router = APIRouter(prefix="/api", tags=["export"])


class ExportPayload(BaseModel):
    project_id: int | None = None
    document_id: int | None = None
    style: str = "gbt7714"


def _project(con: sqlite3.Connection, project_id: int) -> dict:
    row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise NotFound("项目不存在。")
    return dict(row)


def _document(con: sqlite3.Connection, document_id: int) -> dict:
    row = con.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
    if not row:
        raise NotFound("文档不存在。")
    return dict(row)


def _refs(con: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT r.* FROM refs r JOIN project_refs pr ON pr.ref_id=r.id "
        "WHERE pr.project_id=? ORDER BY r.id",
        (project_id,),
    ).fetchall()
    refs = [dict(row) for row in rows]
    ids = [int(ref["id"]) for ref in refs]
    checks = {
        int(item["ref_id"]): str(item["status"])
        for item in citation_service.latest_checks(con, ids)
    }
    for ref in refs:
        ref["citation_status"] = checks.get(int(ref["id"]), "")
    return refs


def _resolve(
    con: sqlite3.Connection, payload: ExportPayload
) -> tuple[dict, dict]:
    if payload.document_id is not None:
        document = _document(con, payload.document_id)
        if payload.project_id is not None and int(document["project_id"]) != payload.project_id:
            raise ValidationFailed("文档不属于指定项目。")
        project_id = int(document["project_id"])
    elif payload.project_id is not None:
        project_id = payload.project_id
        row = con.execute(
            "SELECT * FROM documents WHERE project_id=? ORDER BY id LIMIT 1", (project_id,)
        ).fetchone()
        project = _project(con, project_id)
        document = (
            dict(row)
            if row
            else {
                "id": 0,
                "project_id": project_id,
                "title": project["name"],
                "content_md": "",
                "kind": "paper",
            }
        )
    else:
        raise ValidationFailed("请提供 project_id 或 document_id。")
    return _project(con, project_id), document


@router.post("/export/{fmt}")
def export(
    fmt: str,
    payload: ExportPayload,
    con: sqlite3.Connection = Depends(get_con),
) -> Response:
    project, document = _resolve(con, payload)
    refs = _refs(con, int(project["id"]))
    name = service.EXPORTERS.get(fmt.lower())
    if name is None:
        raise ValidationFailed(f"不支持的导出格式：{fmt}")
    content = service.export(fmt, project, document, refs, payload.style)
    if name == "docx":
        return Response(
            content=content,
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="wenshu-document-{document["id"]}.docx"'
                )
            },
        )
    media_types = {
        "markdown": "text/markdown; charset=utf-8",
        "bibtex": "application/x-bibtex; charset=utf-8",
        "ris": "application/x-research-info-systems; charset=utf-8",
    }
    extensions = {"markdown": "md", "bibtex": "bib", "ris": "ris"}
    return Response(
        content=content,
        media_type=media_types[name],
        headers={
            "Content-Disposition": (
                f'attachment; filename="wenshu-project-{project["id"]}.{extensions[name]}"'
            )
        },
    )
