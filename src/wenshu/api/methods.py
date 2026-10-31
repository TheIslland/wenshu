"""Method matrix: extraction, matrix + trends, editable cells."""

from __future__ import annotations

import sqlite3

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..config import RuntimeConfig
from ..llm import build_llm
from ..services import methods as service
from .deps import get_cfg, get_con

router = APIRouter(prefix="/api", tags=["methods"])


class ExtractPayload(BaseModel):
    project_id: int
    ref_ids: list[int] | None = None


class RowPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str | None = None
    data: str | None = None
    sample: str | None = None
    theory: str | None = None
    finding: str | None = None
    limitation: str | None = None


@router.post("/methods/extract")
def extract(
    payload: ExtractPayload,
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    llm = build_llm(con, cfg)
    return service.extract(con, payload.project_id, payload.ref_ids, llm)


@router.get("/methods/matrix")
def matrix(
    project_id: int,
    external: bool = False,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    client = httpx.Client(timeout=15, follow_redirects=True) if external else None
    try:
        return service.matrix(con, project_id, client=client)
    finally:
        if client is not None:
            client.close()


@router.patch("/methods/rows/{row_id}")
def patch_row(
    row_id: int,
    payload: RowPatch,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    return service.update_row(con, row_id, payload.model_dump(exclude_unset=True))
