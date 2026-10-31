"""Literature search across open sources (implemented by the search workstream)."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ModuleUnavailable

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search")
def search() -> dict:
    raise ModuleUnavailable("检索模块正在接入。")


@router.get("/search/history")
def history() -> list[dict]:
    return []


@router.post("/search/doi")
def by_doi() -> dict:
    raise ModuleUnavailable("DOI 查询正在接入。")
