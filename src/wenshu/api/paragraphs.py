"""Paragraph transform endpoint: compress / expand / reorder / argument."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import RuntimeConfig
from ..services import paragraphs as paragraph_service
from ..services import rewrite as rewrite_service
from .deps import get_cfg, get_con

router = APIRouter(prefix="/api", tags=["paragraphs"])


class TransformPayload(BaseModel):
    text: str = ""
    op: str = "compress"
    role: str = "analysis"
    context_before: str = ""
    context_after: str = ""
    max_delta: float = paragraph_service.MAX_DELTA
    evidence: list[str] | None = None
    terms: list[str] | None = None
    use_llm: bool = True


@router.post("/paragraphs/transform")
def transform_paragraph(
    payload: TransformPayload,
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    llm = rewrite_service.resolve_llm(con, cfg, payload.use_llm)
    try:
        result = paragraph_service.transform(
            payload.text,
            op=payload.op,
            llm=llm,
            context_before=payload.context_before,
            context_after=payload.context_after,
            role=payload.role,
            max_delta=payload.max_delta,
            evidence=payload.evidence,
            terms=payload.terms,
        )
    except Exception as exc:
        rewrite_service.log_llm_call(con, llm, "paragraph_transform", ok=False, error=str(exc))
        raise
    if llm is not None:
        rewrite_service.log_llm_call(con, llm, "paragraph_transform")
    return result.model_dump()
