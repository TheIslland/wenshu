"""Research direction (implemented by the knowledge workstream)."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ModuleUnavailable

router = APIRouter(prefix="/api", tags=["direction"])


@router.post("/direction/explore")
def explore() -> dict:
    raise ModuleUnavailable("研究方向正在接入。")
