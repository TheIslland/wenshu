"""Research workflow tasks (implemented by the knowledge workstream)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["workflow"])


@router.get("/tasks")
def list_tasks() -> list[dict]:
    return []


@router.get("/workflow/gate")
def gate() -> dict:
    return {"ok": True, "blockers": []}
