"""LLM rewrite core shared by style rewrite, polish and paragraph transforms.

Contract: strict JSON, 60 s wall clock, one retry on malformed JSON (inside
`llm.chat_json`), then the result is checked against the citation/number/term
contract and re-scanned by the style rules. A rewrite that changes protected
text or introduces new lint hits is rejected and the original is returned.
Without an LLM the same entry points fall back to rule-based safe fixes and say
so in `warnings` — they never raise a 500.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import Field

from ..config import RuntimeConfig
from ..errors import ValidationFailed
from ..llm import build_llm, load_prompt, log_ai_call
from ..models import Base, RewriteResult
from .style.engine import (
    analyze,
    apply_safe_fixes,
    call_json_with_retry,
    char_diff,
    check_preserved,
    introduced_rule_ids,
)
from .style.rules import RULE_META

PROMPT_SEPARATOR = "<!-- USER PROMPT -->"

REWRITE_MODES: tuple[str, ...] = ("safe", "academic", "concise", "cohesive", "concrete")

MODE_LABELS: dict[str, str] = {
    "safe": "安全修正",
    "academic": "学术化",
    "concise": "简洁",
    "cohesive": "衔接",
    "concrete": "具体化",
}

MAX_DELTA = 0.20


class LLMOutput(Base):
    """Strict JSON contract returned by every rewrite-style prompt."""

    revised: str = ""
    ops: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    preserved: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def resolve_llm(
    con: sqlite3.Connection, cfg: RuntimeConfig, use_llm: bool = True
) -> Any:
    """Return an LLM client, FakeLLM in demo mode, or None when the caller opted out."""
    if not use_llm:
        return None
    return build_llm(con, cfg)


def _fill(template: str, values: dict[str, str]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text.strip()


def join_or_none(items: list[str] | None) -> str:
    cleaned = [str(item).strip() for item in (items or []) if str(item).strip()]
    return "、".join(cleaned) if cleaned else "（无）"


def build_messages(prompt_name: str, values: dict[str, str]) -> list[dict[str, str]]:
    """Split a prompt file into system/user messages and fill placeholders."""
    template = load_prompt(prompt_name)
    system, _, user = template.partition(PROMPT_SEPARATOR)
    messages = [{"role": "system", "content": _fill(system, values)}]
    user_content = _fill(user, values)
    if user_content:
        messages.append({"role": "user", "content": user_content})
    return messages


def log_llm_call(
    con: sqlite3.Connection | None,
    llm: Any,
    task: str,
    *,
    ok: bool = True,
    error: str = "",
) -> None:
    """Write one `ai_logs` row per LLM call (design §6); never records the key."""
    if con is None or llm is None:
        return
    log_ai_call(con, task=task, llm=llm, ok=ok, error=error)


def _provider(llm: Any) -> str:
    return str(getattr(llm, "provider", "") or "")


def _model(llm: Any) -> str:
    return str(getattr(llm, "model", "") or "")


def safe_result(
    text: str,
    *,
    mode: str,
    llm: Any,
    analysis: Any = None,
    extra_warnings: list[str] | None = None,
) -> RewriteResult:
    """Rule-only fallback: never touches citations, numbers or quotes."""
    report = analysis if analysis is not None else analyze(text)
    fixed = apply_safe_fixes(text, report.findings)
    warnings = list(extra_warnings or []) + list(fixed["warnings"])
    return RewriteResult(
        original=text,
        revised=fixed["revised"],
        diff=fixed["diff"],
        ops=fixed["applied"],
        gaps=[],
        warnings=warnings,
        provider=_provider(llm),
        model=_model(llm),
        mode=mode,
    )


def run_llm_rewrite(
    text: str,
    *,
    mode: str,
    llm: Any,
    prompt_name: str,
    max_delta: float = MAX_DELTA,
    context_before: str = "",
    context_after: str = "",
    terms: list[str] | None = None,
    citations: list[str] | None = None,
    instruction: str = "",
) -> RewriteResult:
    """One LLM rewrite with the full safety envelope."""
    report = analyze(text)
    values = {
        "MODE_LABEL": MODE_LABELS.get(mode, mode),
        "INSTRUCTION": instruction.strip() or "（无）",
        "CONTEXT_BEFORE": context_before.strip() or "（无）",
        "CONTEXT_AFTER": context_after.strip() or "（无）",
        "TERMS": join_or_none(terms),
        "CITATIONS": join_or_none(citations),
        "TEXT": text,
    }
    messages = build_messages(prompt_name, values)
    output = call_json_with_retry(llm, messages, LLMOutput)
    revised = (output.revised or "").strip()
    warnings = [item.strip() for item in output.warnings if item and item.strip()]
    provider = _provider(llm)
    model = _model(llm)

    if not revised:
        return safe_result(
            text,
            mode=mode,
            llm=llm,
            analysis=report,
            extra_warnings=warnings
            + ["LLM 没有返回改写结果，已退回安全修正（删套话 / 还原虚化动词 / 改破折号）。"],
        )
    if revised == text.strip():
        warnings.append("LLM 没有改动这一段，未产生 diff。")
        return RewriteResult(
            original=text,
            revised=text,
            diff=[],
            ops=[],
            gaps=output.gaps,
            warnings=warnings,
            provider=provider,
            model=model,
            mode=mode,
        )

    rejection = ""
    violations = check_preserved(text, revised, terms)
    if violations:
        rejection = "改写结果改动了引用/数字/引文/术语：" + "；".join(violations)
    else:
        delta = abs(len(revised) - len(text)) / max(1, len(text))
        if delta > max_delta + 1e-9:
            rejection = f"改写后字数变动 {delta:.0%}，超过上限 {max_delta:.0%}"
        else:
            introduced = introduced_rule_ids(text, revised)
            if introduced:
                names = "、".join(str(RULE_META[rule_id]["name"]) for rule_id in introduced)
                rejection = f"改写结果引入了新的风格问题（{names}）"
    if rejection:
        warnings.append(rejection + "，已拒绝并保留原文。")
        return RewriteResult(
            original=text,
            revised=text,
            diff=[],
            ops=[{"action": "rejected", "reason": rejection}],
            gaps=output.gaps,
            warnings=warnings,
            provider=provider,
            model=model,
            mode=mode,
        )

    return RewriteResult(
        original=text,
        revised=revised,
        diff=char_diff(text, revised),
        ops=output.ops,
        gaps=output.gaps,
        warnings=warnings,
        provider=provider,
        model=model,
        mode=mode,
    )


def rewrite(
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
    """Style rewrite entry point (`safe` = rule-only, no LLM)."""
    text = text or ""
    mode = (mode or "academic").strip().lower()
    if mode not in REWRITE_MODES:
        raise ValidationFailed(
            f"未知的改写模式「{mode}」。可选：{' / '.join(REWRITE_MODES)}。"
        )
    if not text.strip():
        raise ValidationFailed("文本为空，没有可改写的内容。")
    if mode == "safe" or llm is None:
        result = safe_result(text, mode=mode, llm=llm)
        if llm is None:
            result.warnings.insert(
                0,
                "没有配置 LLM：只做了安全修正（删套话 / 还原虚化动词 / 改破折号）；"
                "语义改写需要到设置页配置 LLM。",
            )
        return result
    return run_llm_rewrite(
        text,
        mode=mode,
        llm=llm,
        prompt_name="style_rewrite.md",
        max_delta=MAX_DELTA,
        context_before=context_before,
        context_after=context_after,
        terms=terms,
        citations=citations,
        instruction=instruction,
    )
