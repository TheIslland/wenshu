"""Method matrix and trends (implemented by the knowledge workstream)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["methods"])


@router.get("/methods/matrix")
def matrix() -> dict:
    return {"rows": [], "trend": [], "method_trend": [], "conflicts": []}
