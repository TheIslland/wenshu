"""Document export (implemented by the knowledge workstream)."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ModuleUnavailable

router = APIRouter(prefix="/api", tags=["export"])


@router.post("/export/{fmt}")
def export(fmt: str) -> dict:
    raise ModuleUnavailable(f"导出格式 {fmt} 正在接入。")
