"""Style diagnostics: rule lint, safe auto-fixes, LLM rewrite, personal baseline."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError

from ..config import RuntimeConfig
from ..errors import NotFound, ValidationFailed
from ..models import StyleFinding
from ..services import rewrite as rewrite_service
from ..services.style import baseline as baseline_service
from ..services.style.engine import analyze, apply_safe_fixes
from .deps import get_cfg, get_con

router = APIRouter(prefix="/api", tags=["style"])


class AnalyzePayload(BaseModel):
    text: str = ""
    document_id: int | None = None
    project_id: int | None = None
    use_llm: bool = True
    baseline: dict[str, Any] | None = None


class FixPayload(BaseModel):
    text: str = ""
    findings: list[dict[str, Any]] = Field(default_factory=list)


class RewritePayload(BaseModel):
    text: str = ""
    mode: str = "academic"
    context_before: str = ""
    context_after: str = ""
    terms: list[str] | None = None
    citations: list[str] | None = None
    instruction: str = ""
    use_llm: bool = True


class BaselinePayload(BaseModel):
    texts: list[str] = Field(default_factory=list)


def _resolve_text(payload: AnalyzePayload, con: sqlite3.Connection) -> str:
    text = payload.text or ""
    if text.strip() or not payload.document_id:
        return text
    row = con.execute(
        "SELECT content_md FROM documents WHERE id=?", (payload.document_id,)
    ).fetchone()
    if not row:
        raise NotFound("文档不存在，取不到正文。")
    return str(row["content_md"] or "")


@router.post("/style/analyze")
def analyze_text(
    payload: AnalyzePayload,
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    text = _resolve_text(payload, con)
    llm = rewrite_service.resolve_llm(con, cfg, payload.use_llm) if text.strip() else None
    try:
        report = analyze(text, baseline=payload.baseline, llm=llm)
    except Exception as exc:
        rewrite_service.log_llm_call(con, llm, "style_review", ok=False, error=str(exc))
        raise
    if llm is not None and report.llm_used:
        rewrite_service.log_llm_call(con, llm, "style_review")
    return report.model_dump()


@router.post("/style/fix")
def fix_text(
    payload: FixPayload,
) -> dict:
    if payload.findings:
        try:
            findings = [StyleFinding.model_validate(item) for item in payload.findings]
        except ValidationError as exc:
            raise ValidationFailed(
                "findings 的字段不合法，无法应用安全修正。", detail=exc.errors()
            ) from exc
    else:
        findings = analyze(payload.text or "").findings
    return apply_safe_fixes(payload.text or "", findings)


@router.post("/style/rewrite")
def rewrite_text(
    payload: RewritePayload,
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    llm = rewrite_service.resolve_llm(con, cfg, payload.use_llm)
    try:
        result = rewrite_service.rewrite(
            payload.text,
            mode=payload.mode,
            llm=llm,
            context_before=payload.context_before,
            context_after=payload.context_after,
            terms=payload.terms,
            citations=payload.citations,
            instruction=payload.instruction,
        )
    except Exception as exc:
        rewrite_service.log_llm_call(con, llm, "style_rewrite", ok=False, error=str(exc))
        raise
    if llm is not None:
        rewrite_service.log_llm_call(con, llm, "style_rewrite")
    return result.model_dump()


@router.post("/style/baseline")
def build_baseline(payload: BaselinePayload) -> dict:
    return baseline_service.build(payload.texts)
