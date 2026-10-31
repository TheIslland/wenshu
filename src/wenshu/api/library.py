"""Reference library API: import (DOI/RIS/BibTeX/PDF/Zotero), list, patch, attach."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from ..config import RuntimeConfig
from ..errors import NotFound, UpstreamError, ValidationFailed
from ..models import ImportResult, RefPatch, SearchHit
from ..services import importers, library, pdf
from ..services.search.base import SourceError
from ..services.search.dedupe import dedupe
from ..services.search.zotero import ZoteroClient
from .deps import get_cfg, get_con

router = APIRouter(prefix="/api", tags=["library"])


class ImportPayload(BaseModel):
    project_id: int | None = None
    kind: str = "doi"
    payload: str = ""
    hits: list[SearchHit] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=100)


class ZoteroImportPayload(BaseModel):
    project_id: int | None = None
    limit: int = Field(default=100, ge=1, le=100)


def _ensure_project(con: sqlite3.Connection, project_id: int | None) -> None:
    if project_id is None:
        return
    if not con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise NotFound("项目不存在。")


def _import_hits(
    con: sqlite3.Connection,
    hits: list[SearchHit],
    project_id: int | None,
    warnings: list[str] | None = None,
) -> dict:
    unique = dedupe(hits)
    skipped = max(0, len(hits) - len(unique))
    refs = []
    for hit in unique:
        ref_id = library.upsert_ref(con, hit, project_id)
        refs.append(library.get_ref(con, ref_id))
    return ImportResult(
        imported=len(refs),
        skipped=skipped,
        refs=refs,
        warnings=list(warnings or []),
    ).model_dump()


def _decode_upload(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


@router.get("/refs")
def list_refs(
    project_id: int | None = None,
    q: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    con: sqlite3.Connection = Depends(get_con),
) -> list[dict]:
    _ensure_project(con, project_id)
    return library.list_refs(
        con,
        project_id=project_id,
        q=q,
        status=status,
        tag=tag,
        limit=limit,
        offset=offset,
    )


@router.post("/refs")
def create_ref(
    payload: SearchHit,
    project_id: int | None = Query(default=None),
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    _ensure_project(con, project_id)
    if not payload.source:
        payload.source = "manual"
    ref_id = library.upsert_ref(con, payload, project_id)
    return library.get_ref(con, ref_id)


@router.post("/refs/import")
def import_refs(
    payload: ImportPayload,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    _ensure_project(con, payload.project_id)
    kind = (payload.kind or "").strip().lower()
    warnings: list[str] = []
    if kind == "doi":
        if not payload.payload.strip():
            raise ValidationFailed("DOI 不能为空。")
        hits = [importers.import_doi(payload.payload)]
    elif kind == "ris":
        hits = importers.import_ris(payload.payload)
        if not hits:
            warnings.append("RIS 文本里没有可导入的条目。")
    elif kind == "bibtex":
        hits = importers.import_bibtex(payload.payload)
        if not hits:
            warnings.append("BibTeX 文本里没有可导入的条目。")
    elif kind == "zotero":
        try:
            hits = ZoteroClient().fetch_items(limit=payload.limit)
        except SourceError as exc:
            raise UpstreamError(exc.message) from exc
        warnings.append("Zotero 本地库为只读导入，不会修改 Zotero 数据。")
    elif kind == "hits":
        if not payload.hits:
            raise ValidationFailed("没有要入库的检索结果。")
        hits = list(payload.hits)
    else:
        raise ValidationFailed(
            f"不支持的导入类型：{payload.kind}。可用：doi、ris、bibtex、zotero、hits。"
        )
    return _import_hits(con, hits, payload.project_id, warnings)


@router.post("/refs/import/file")
async def import_file(
    file: UploadFile = File(...),
    project_id: int | None = Form(default=None),
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    _ensure_project(con, project_id)
    data = await file.read()
    if not data:
        raise ValidationFailed("上传的文件是空的。")
    name = (file.filename or "").lower()
    if name.endswith(".pdf") or pdf.looks_like_pdf(data):
        hit, text, _meta = importers.import_pdf(data, filename=file.filename or "")
        ref_id = library.upsert_ref(con, hit, project_id)
        ref = library.attach_pdf(con, ref_id, data, cfg.attachments_dir)
        warning = (
            "PDF 已入库并抽取全文。"
            if text
            else "PDF 已入库，但没有可抽取的文本（可能是扫描件）。"
        )
        return ImportResult(imported=1, refs=[ref], warnings=[warning]).model_dump()
    text = _decode_upload(data)
    if name.endswith((".bib", ".bibtex")):
        hits = importers.import_bibtex(text)
    else:
        hits = importers.import_ris(text)
    if not hits:
        raise ValidationFailed("文件里没有解析出可导入的文献。")
    return _import_hits(con, hits, project_id)


@router.get("/refs/{ref_id}")
def get_ref(
    ref_id: int,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    return library.get_ref(con, ref_id)


@router.patch("/refs/{ref_id}")
def patch_ref(
    ref_id: int,
    payload: RefPatch,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    return library.patch_ref(con, ref_id, changes)


@router.post("/refs/{ref_id}/attach")
@router.post("/refs/{ref_id}/pdf")
async def attach_pdf(
    ref_id: int,
    file: UploadFile = File(...),
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    data = await file.read()
    if not data:
        raise ValidationFailed("上传的 PDF 是空的。")
    return library.attach_pdf(con, ref_id, data, cfg.attachments_dir)


@router.get("/refs/{ref_id}/text")
def ref_text(
    ref_id: int,
    q: str | None = None,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    return library.get_ref_text(con, ref_id, q)


@router.get("/zotero/status")
def zotero_status() -> dict:
    return ZoteroClient().status()


@router.post("/zotero/import")
def zotero_import(
    payload: ZoteroImportPayload,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    _ensure_project(con, payload.project_id)
    try:
        hits = ZoteroClient().fetch_items(limit=payload.limit)
    except SourceError as exc:
        raise UpstreamError(exc.message) from exc
    return _import_hits(
        con,
        hits,
        payload.project_id,
        ["Zotero 本地库为只读导入，不会修改 Zotero 数据。"],
    )
