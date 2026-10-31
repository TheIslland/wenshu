"""Style diagnostics (implemented by the style workstream)."""

from __future__ import annotations

from fastapi import APIRouter

from ..errors import ModuleUnavailable

router = APIRouter(prefix="/api", tags=["style"])


@router.post("/style/analyze")
def analyze() -> dict:
    raise ModuleUnavailable("风格体检正在接入。")


@router.post("/style/fix")
def fix() -> dict:
    raise ModuleUnavailable("安全修正正在接入。")


@router.post("/style/rewrite")
def rewrite() -> dict:
    raise ModuleUnavailable("风格改写正在接入。")


@router.post("/style/baseline")
def baseline() -> dict:
    raise ModuleUnavailable("个人基线正在接入。")
