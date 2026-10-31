"""Prose polishing endpoint."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import RuntimeConfig
from ..services import polish as polish_service
from ..services import rewrite as rewrite_service
from .deps import get_cfg, get_con

router = APIRouter(prefix="/api", tags=["polish"])


class PolishPayload(BaseModel):
    text: str = ""
    mode: str = "academic"
    context_before: str = ""
    context_after: str = ""
    terms: list[str] | None = None
    citations: list[str] | None = None
    instruction: str = ""
    use_llm: bool = True


@router.post("/polish")
def polish_text(
    payload: PolishPayload,
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    llm = rewrite_service.resolve_llm(con, cfg, payload.use_llm)
    try:
        result = polish_service.polish(
            payload.text,
            mode=payload.mode,
            llm=llm,
            context_before=payload.context_before,
            context_after=payload.context_after,
            terms=payload.terms,
            citations=payload.citations,
            instruction=payload.instruction,
        )
    except Exception as exc:
        rewrite_service.log_llm_call(con, llm, "polish", ok=False, error=str(exc))
        raise
    if llm is not None:
        rewrite_service.log_llm_call(con, llm, "polish")
    return result.model_dump()
