"""Paragraph transforms: compress / expand / reorder / argument.

Hard limits: citations, quotes, numbers and terms stay untouched; length moves
within ±20%; missing evidence goes into `gaps` instead of being invented; the
result is re-scanned by the style rules and rejected if it introduces new hits.
"""

from __future__ import annotations

from typing import Any

from ..errors import ValidationFailed
from ..models import RewriteResult
from . import rewrite as rewrite_service
from .style.engine import (
    analyze,
    apply_safe_fixes,
    call_json_with_retry,
    char_diff,
    check_preserved,
    introduced_rule_ids,
)
from .style.rules import RULE_META

OPS: tuple[str, ...] = ("compress", "expand", "reorder", "argument")

OP_LABELS: dict[str, str] = {
    "compress": "压缩",
    "expand": "扩写",
    "reorder": "重排",
    "argument": "补论证",
}

ROLES: tuple[str, ...] = ("analysis", "review", "theory", "case", "conclusion")

ROLE_LABELS: dict[str, str] = {
    "analysis": "分析",
    "review": "综述",
    "theory": "理论",
    "case": "个案",
    "conclusion": "结论",
    "intro": "引言",
}

MAX_DELTA = 0.20


def _delta_limit(max_delta: float | None) -> float:
    if max_delta is None:
        return MAX_DELTA
    value = abs(float(max_delta))
    if value <= 0:
        return MAX_DELTA
    return min(value, MAX_DELTA)


def _fallback(
    text: str,
    *,
    op: str,
    llm: Any,
    gaps: list[str],
    warnings: list[str],
) -> RewriteResult:
    """No LLM / empty LLM answer: do what rules can do, say what they cannot."""
    if op == "compress":
        report = analyze(text)
        fixed = apply_safe_fixes(text, report.findings)
        return RewriteResult(
            original=text,
            revised=fixed["revised"],
            diff=fixed["diff"],
            ops=fixed["applied"],
            gaps=gaps
            + ["没有配置 LLM：只删了套话，合并同义句与段内重切没有执行。"],
            warnings=list(warnings) + list(fixed["warnings"]),
            provider=str(getattr(llm, "provider", "") or ""),
            model=str(getattr(llm, "model", "") or ""),
            mode=op,
        )
    return RewriteResult(
        original=text,
        revised=text,
        diff=[],
        ops=[],
        gaps=gaps,
        warnings=list(warnings),
        provider=str(getattr(llm, "provider", "") or ""),
        model=str(getattr(llm, "model", "") or ""),
        mode=op,
    )


def transform(
    text: str,
    *,
    op: str,
    llm: Any = None,
    context_before: str = "",
    context_after: str = "",
    role: str = "analysis",
    max_delta: float = MAX_DELTA,
    evidence: list[str] | None = None,
    terms: list[str] | None = None,
) -> RewriteResult:
    text = text or ""
    op = (op or "").strip().lower()
    if op not in OPS:
        raise ValidationFailed(f"未知的调段操作「{op}」。可选：{' / '.join(OPS)}。")
    role = (role or "analysis").strip().lower()
    if role not in ROLES:
        raise ValidationFailed(f"未知的章节角色「{role}」。可选：{' / '.join(ROLES)}。")
    if not text.strip():
        raise ValidationFailed("文本为空，没有可调整的内容。")

    limit = _delta_limit(max_delta)
    evidence_items = [str(item).strip() for item in (evidence or []) if str(item).strip()]
    evidence_text = "\n".join(evidence_items)
    missing_evidence = op in ("expand", "argument") and not evidence_items

    if llm is None:
        gaps: list[str] = []
        if missing_evidence:
            gaps.append("缺证据池：扩写/补论证只能补原文和证据池里的材料，请先在文献库补证据。")
        if op == "reorder":
            warnings = ["重排需要 LLM 才能保住原意，没有配置 LLM，这一段未改动。"]
        elif op in ("expand", "argument"):
            warnings = [f"{OP_LABELS[op]}需要 LLM，没有配置 LLM，这一段未改动。"]
        else:
            warnings = ["没有配置 LLM：只做了删套话的安全压缩。"]
        return _fallback(text, op=op, llm=llm, gaps=gaps, warnings=warnings)

    values = {
        "OP": op,
        "OP_LABEL": OP_LABELS[op],
        "ROLE": ROLE_LABELS.get(role, role),
        "MAX_DELTA_PERCENT": f"{round(limit * 100)}",
        "CONTEXT_BEFORE": context_before.strip() or "（无）",
        "CONTEXT_AFTER": context_after.strip() or "（无）",
        "EVIDENCE": _join_evidence(evidence_items),
        "TERMS": rewrite_service.join_or_none(terms),
        "TEXT": text,
    }
    messages = rewrite_service.build_messages("paragraph_transform.md", values)
    output = call_json_with_retry(llm, messages, rewrite_service.LLMOutput)
    revised = (output.revised or "").strip()
    provider = str(getattr(llm, "provider", "") or "")
    model = str(getattr(llm, "model", "") or "")
    warnings = [item.strip() for item in output.warnings if item and item.strip()]
    gaps = [item.strip() for item in output.gaps if item and item.strip()]
    if missing_evidence:
        gaps.append("证据池为空：扩写/补论证里新增的材料需要有出处，系统不会替你编。")

    if not revised:
        fallback = _fallback(
            text,
            op=op,
            llm=llm,
            gaps=gaps,
            warnings=warnings,
        )
        fallback.warnings.append("LLM 没有返回调段结果，已退回规则能做的部分。")
        return fallback

    ops: list[dict[str, Any]] = list(output.ops)
    if output.anchors:
        ops.append({"action": "anchors", "items": output.anchors[:20]})
    if output.preserved:
        ops.append({"action": "preserved", "items": output.preserved[:20]})

    rejection = ""
    violations = check_preserved(text, revised, terms, allowed_extra=evidence_text)
    if violations:
        rejection = "调段结果改动了引用/数字/引文/术语：" + "；".join(violations)
    else:
        delta = abs(len(revised) - len(text)) / max(1, len(text))
        if delta > limit + 1e-9:
            rejection = f"调段后字数变动 {delta:.0%}，超过 ±{limit:.0%} 上限"
        else:
            introduced = introduced_rule_ids(text, revised)
            if introduced:
                names = "、".join(str(RULE_META[rule_id]["name"]) for rule_id in introduced)
                rejection = f"调段结果引入了新的风格问题（{names}）"
    if rejection:
        warnings.append(rejection + "，已拒绝并保留原文。")
        return RewriteResult(
            original=text,
            revised=text,
            diff=[],
            ops=[{"action": "rejected", "reason": rejection}],
            gaps=gaps,
            warnings=warnings,
            provider=provider,
            model=model,
            mode=op,
        )

    return RewriteResult(
        original=text,
        revised=revised,
        diff=char_diff(text, revised),
        ops=ops,
        gaps=gaps,
        warnings=warnings,
        provider=provider,
        model=model,
        mode=op,
    )


def _join_evidence(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "（空：没有可用的证据池）"

