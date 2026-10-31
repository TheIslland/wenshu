"""Reference library (implemented by the search workstream)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["library"])


@router.get("/refs")
def list_refs() -> list[dict]:
    return []


@router.get("/zotero/status")
def zotero_status() -> dict:
    return {"running": False, "message": "Zotero 本地接口未检测。"}
