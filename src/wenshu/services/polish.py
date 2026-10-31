"""Prose polishing: reuses the rewrite safety envelope with a ±15% length budget."""

from __future__ import annotations

from typing import Any

from ..errors import ValidationFailed
from ..models import RewriteResult
from . import rewrite as rewrite_service

POLISH_MODES: tuple[str, ...] = ("academic", "concise", "cohesive", "concrete")

POLISH_MODE_LABELS: dict[str, str] = {
    "academic": "学术化",
    "concise": "简洁",
    "cohesive": "衔接",
    "concrete": "具体化",
}

MAX_DELTA = 0.15


def polish(
    text: str,
    *,
    mode: str = "academic",
    llm: Any = None,
    context_before: str = "",
    context_after: str = "",
    terms: list[str] | None = None,
    citations: list[str] | None = None,
    instruction: str = "",
) -> RewriteResult:
    """Polish one paragraph; citations, quotes, numbers and terms stay untouched."""
    text = text or ""
    mode = (mode or "academic").strip().lower()
    if mode not in POLISH_MODES:
        raise ValidationFailed(
            f"未知的润色模式「{mode}」。可选：{' / '.join(POLISH_MODES)}。"
        )
    if not text.strip():
        raise ValidationFailed("文本为空，没有可润色的内容。")

    if llm is None:
        result = rewrite_service.rewrite(
            text,
            mode=mode,
            llm=None,
            context_before=context_before,
            context_after=context_after,
            terms=terms,
            citations=citations,
            instruction=instruction,
        )
        result.warnings.insert(
            0,
            "润色需要 LLM：当前没有配置，只做了安全修正（删套话 / 还原虚化动词 / 改破折号）。",
        )
        result.mode = mode
        return result

    result = rewrite_service.run_llm_rewrite(
        text,
        mode=mode,
        llm=llm,
        prompt_name="polish.md",
        max_delta=MAX_DELTA,
        context_before=context_before,
        context_after=context_after,
        terms=terms,
        citations=citations,
        instruction=instruction,
    )
    result.mode = mode
    return result
