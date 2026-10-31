"""Citation verification and formatting (implemented by the knowledge workstream)."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ModuleUnavailable

router = APIRouter(prefix="/api", tags=["citations"])


@router.post("/citations/verify")
def verify() -> dict:
    raise ModuleUnavailable("引用核验正在接入。")


@router.get("/citations/format")
def format_refs() -> dict:
    raise ModuleUnavailable("引用格式化正在接入。")
