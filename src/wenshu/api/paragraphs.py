"""Paragraph transformations (implemented by the style workstream)."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ModuleUnavailable

router = APIRouter(prefix="/api", tags=["paragraphs"])


@router.post("/paragraphs/transform")
def transform() -> dict:
    raise ModuleUnavailable("段落调整正在接入。")
