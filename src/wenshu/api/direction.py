"""Research-direction exploration API."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import RuntimeConfig
from ..llm import build_llm
from ..services import direction as service
from .deps import get_cfg, get_con

router = APIRouter(prefix="/api", tags=["direction"])


class ExplorePayload(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    project_id: int | None = None
    years: int = Field(default=10, ge=1, le=100)
    language: str | None = None
    hits: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/direction/explore")
def explore(
    payload: ExplorePayload,
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    llm = build_llm(con, cfg)
    return service.explore(
        con,
        payload.topic,
        llm=llm,
        project_id=payload.project_id,
        years=payload.years,
        language=payload.language,
        hits=payload.hits,
    )
