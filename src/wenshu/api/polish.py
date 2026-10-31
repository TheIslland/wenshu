"""Prose polishing (implemented by the style workstream)."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ModuleUnavailable

router = APIRouter(prefix="/api", tags=["polish"])


@router.post("/polish")
def polish() -> dict:
    raise ModuleUnavailable("文笔润色正在接入。")
