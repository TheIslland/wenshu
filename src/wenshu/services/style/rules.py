"""The 16 style rules from design §7: 13 offline lint rules + 3 LLM-only rules.

Rules are paragraph-scoped where possible and always report a span
(`start`/`end`/`text`) plus a human-readable explanation and suggestion. The
score is the sum of rule weights × intensity, capped at 100 — it is a *style
risk*, never an "AI probability".
"""

from __future__ import annotations

import re

from ...models import StyleFinding
from . import metrics
from .metrics import Span, body_paragraphs, sentence_spans, visible_len

LLM_RULE_IDS: tuple[str, ...] = ("argument_jump", "concept_drift", "concession_gap")

RULE_META: dict[str, dict[str, object]] = {
    "sentence_variance": {
        "name": "句长变异不足",
        "weight": 7.0,
        "severity": "warn",
        "metric": "sentence_cv",
        "suggestion": "长短句交替：在长句后插一个短句，或把并列长句拆成两句。",
    },
    "same_length_run": {
        "name": "连续同长句",
        "weight": 8.0,
        "severity": "warn",
        "metric": "same_len_run",
        "suggestion": "在四句同节奏中插一个短句或一个长句，打破匀速。",
    },
    "paragraph_evenness": {
        "name": "段长过于均匀",
        "weight": 5.0,
        "severity": "warn",
        "metric": "paragraph_cv",
        "suggestion": "按论证单元重切段落：一处只放一个判断，别按字数排。",
    },
    "connective_density": {
        "name": "连接词过密",
        "weight": 8.0,
        "severity": "warn",
        "metric": "connective_per_k",
        "suggestion": "能删就删，改用隐性衔接（重复关键词、指代前句事实）。",
    },
    "connective_diversity": {
        "name": "连接词单一",
        "weight": 4.0,
        "severity": "info",
        "metric": "connective_ttr",
        "suggestion": "先减总量，不要用同义词轮换充多样性。",
    },
    "four_char_runs": {
        "name": "四字格/三连排比",
        "weight": 7.0,
        "severity": "warn",
        "metric": "four_char_runs",
        "suggestion": "留一项，其余换成具体的人、事、材料或机制。",
    },
    "boilerplate": {
        "name": "总分总套话",
        "weight": 8.0,
        "severity": "warn",
        "metric": "boilerplate_per_k",
        "suggestion": "删掉壳子，直接从事实、材料或判断开始。",
    },
    "meaning_inflation": {
        "name": "意义拔高",
        "weight": 9.0,
        "severity": "high",
        "metric": "inflation_per_k",
        "suggestion": "停在事实，或写清中间的机制；不要用一个词把意义顶上去。",
    },
    "pseudo_depth": {
        "name": "假深刻否定",
        "weight": 8.0,
        "severity": "high",
        "metric": "pseudo_depth_per_k",
        "suggestion": "还原成直接判断：先说你主张什么，再说它反对什么。",
    },
    "dash_quotes": {
        "name": "破折号/装饰引号",
        "weight": 4.0,
        "severity": "info",
        "metric": "dash_per_k",
        "suggestion": "破折号改冒号或句号；装饰引号直接去掉。",
    },
    "vague_verb": {
        "name": "虚化动词/性化度",
        "weight": 8.0,
        "severity": "warn",
        "metric": "vague_verb_per_k",
        "suggestion": "把「进行/加以 + 名词」还原成动词，X性/X化 落到具体属性。",
    },
    "concreteness_gap": {
        "name": "具体性缺失",
        "weight": 5.0,
        "severity": "info",
        "metric": "anchor_per_100",
        "suggestion": "标「待补材料」：补年份、数字、《书名》或引用标记；不生成占位内容。",
    },
    "de_chain": {
        "name": "「的」字链",
        "weight": 6.0,
        "severity": "warn",
        "metric": "max_de",
        "suggestion": "拆句，把「的」后面的修饰改成一个独立短句。",
    },
    "argument_jump": {
        "name": "论证跳跃",
        "weight": 6.0,
        "severity": "warn",
        "metric": "",
        "suggestion": "补上锚点（材料/引文）或把这句降级为假设。",
    },
    "concept_drift": {
        "name": "概念漂移",
        "weight": 5.0,
        "severity": "warn",
        "metric": "",
        "suggestion": "按术语表统一说法，前后同一个概念用同一个词。",
    },
    "concession_gap": {
        "name": "让步缺失",
        "weight": 5.0,
        "severity": "warn",
        "metric": "",
        "suggestion": "补最强反例，再写一句回应；没有反例的判断容易被审稿人打回。",
    },
}

METRIC_OF_RULE: dict[str, str] = {
    rule_id: str(meta["metric"]) for rule_id, meta in RULE_META.items() if meta["metric"]
}

AUTO_FIXABLE_RULES = frozenset({"boilerplate", "vague_verb", "dash_quotes"})

_FINDING_MAX_TEXT = 80


def make_finding(
    rule_id: str,
    text: str,
    start: int,
    end: int,
    message: str,
    suggestion: str | None = None,
    *,
    severity: str | None = None,
    auto_fixable: bool = False,
    weight: float = 0.0,
    max_text: int = _FINDING_MAX_TEXT,
) -> StyleFinding:
    """Build a finding whose `text` is always exactly `text[start:end]`."""
    meta = RULE_META[rule_id]
    start = max(0, min(int(start), len(text)))
    end = max(start, min(int(end), len(text)))
    if end - start > max_text:
        end = start + max_text
    return StyleFinding(
        rule_id=rule_id,
        name=str(meta["name"]),
        severity=severity or str(meta["severity"]),  # type: ignore[arg-type]
        start=start,
        end=end,
        text=text[start:end],
        message=message,
        suggestion=suggestion if suggestion is not None else str(meta["suggestion"]),
        auto_fixable=auto_fixable,
        weight=weight,
    )


def _finalize(
    rule_id: str, findings: list[StyleFinding], intensity: float
) -> list[StyleFinding]:
    """Share one rule's points across its findings so counts cannot inflate the score."""
    if not findings:
        return []
    base = float(RULE_META[rule_id]["weight"])  # type: ignore[arg-type]
    intensity = max(0.0, min(1.0, intensity))
    share = round(base * intensity / len(findings), 3)
    for finding in findings:
        finding.weight = share
    return findings


def _repeat_findings(
    rule_id: str,
    text: str,
    matches: list[re.Match[str]],
    message: str,
    *,
    auto_fixable: bool = False,
    cap: int = 12,
    extend_punctuation: bool = False,
    severity: str | None = None,
) -> list[StyleFinding]:
    findings: list[StyleFinding] = []
    for match in matches[:cap]:
        start, end = match.start(), match.end()
        if extend_punctuation:
            while end < len(text) and text[end] in "，,、；;：:":
                end += 1
        findings.append(
            make_finding(
                rule_id,
                text,
                start,
                end,
                message.format(text=match.group(0)),
                severity=severity,
                auto_fixable=auto_fixable,
            )
        )
    return findings


def _repeat_spans(
    rule_id: str,
    text: str,
    spans: list[Span],
    message: str,
    *,
    auto_fixable: bool = False,
    cap: int = 12,
) -> list[StyleFinding]:
    return [
        make_finding(
            rule_id,
            text,
            span.start,
            span.end,
            message.format(text=span.text),
            auto_fixable=auto_fixable,
        )
        for span in spans[:cap]
    ]


def _sentence_variance(text: str, paragraphs: list[Span]) -> list[StyleFinding]:
    findings: list[StyleFinding] = []
    intensity = 0.0
    threshold = metrics.THRESHOLDS["sentence_cv"]
    for paragraph in paragraphs:
        sentences = sentence_spans(paragraph)
        lengths = [float(visible_len(s.text)) for s in sentences]
        if len(lengths) < 4 or visible_len(paragraph.text) < 60:
            continue
        value = metrics.coefficient_of_variation(lengths)
        if value >= threshold:
            continue
        intensity = max(intensity, 0.5 + 0.5 * min(1.0, (threshold - value) / threshold))
        findings.append(
            make_finding(
                "sentence_variance",
                text,
                paragraph.start,
                paragraph.end,
                f"本段 {len(lengths)} 句，句长变异系数 {value:.2f}，低于 {threshold:.2f}：读起来是同一种节奏。",
            )
        )
    return _finalize("sentence_variance", findings, intensity or 0.5)


def _same_length_run(text: str, paragraphs: list[Span]) -> list[StyleFinding]:
    findings: list[StyleFinding] = []
    intensity = 0.0
    for paragraph in paragraphs:
        sentences = sentence_spans(paragraph)
        lengths = [visible_len(s.text) for s in sentences]
        if len(lengths) < 4:
            continue
        best_length = 0
        best_range = (0, 0)
        run_start = 0
        for index in range(1, len(lengths)):
            if abs(lengths[index] - lengths[index - 1]) > 8:
                run_start = index
            run_length = index - run_start + 1
            if run_length > best_length:
                best_length = run_length
                best_range = (run_start, index)
        if best_length < 4:
            continue
        first, last = best_range
        intensity = max(intensity, min(1.0, 0.6 + 0.1 * (best_length - 4)))
        findings.append(
            make_finding(
                "same_length_run",
                text,
                sentences[first].start,
                sentences[last].end,
                f"连续 {best_length} 句长度差不超过 8 字（{lengths[first]}–{lengths[last]} 字），是匀速排比。",
            )
        )
    return _finalize("same_length_run", findings, intensity or 0.6)


def _paragraph_evenness(text: str, paragraphs: list[Span]) -> list[StyleFinding]:
    if len(paragraphs) < 5:
        return []
    lengths = [float(visible_len(p.text)) for p in paragraphs]
    value = metrics.coefficient_of_variation(lengths)
    threshold = metrics.THRESHOLDS["paragraph_cv"]
    if value >= threshold:
        return []
    intensity = 0.5 + 0.5 * min(1.0, (threshold - value) / threshold)
    finding = make_finding(
        "paragraph_evenness",
        text,
        paragraphs[0].start,
        paragraphs[-1].end,
        f"{len(lengths)} 段长度变异系数 {value:.2f}，低于 {threshold:.2f}：段段齐整，像按字数排的。",
    )
    return _finalize("paragraph_evenness", [finding], intensity)


def _connective_density(text: str, paragraphs: list[Span]) -> list[StyleFinding]:
    matches = list(metrics.CONNECTIVE_RE.finditer(text))
    units = metrics.density_unit(text)
    density = len(matches) * 1000.0 / units
    threshold = metrics.THRESHOLDS["connective_per_k"]
    findings: list[StyleFinding] = []
    intensity = 0.0
    for paragraph in paragraphs:
        local = list(metrics.CONNECTIVE_RE.finditer(paragraph.text))
        if len(local) < 3:
            continue
        findings.append(
            make_finding(
                "connective_density",
                text,
                paragraph.start,
                paragraph.end,
                f"本段有 {len(local)} 个连接词："
                + "、".join(sorted({m.group(0) for m in local})[:6]),
            )
        )
        intensity = max(intensity, 0.5 + 0.5 * min(1.0, len(local) / 6))
    if not findings and density > threshold:
        findings.append(
            make_finding(
                "connective_density",
                text,
                0,
                len(text),
                f"连接词密度 {density:.1f}/千字，高于 {threshold:.0f}：逻辑关系全靠连接词明说。",
            )
        )
        intensity = max(intensity, 0.5 + 0.5 * min(1.0, density / (threshold * 2)))
    return _finalize("connective_density", findings, intensity)


def _connective_diversity(text: str) -> list[StyleFinding]:
    matches = metrics.CONNECTIVE_RE.findall(text)
    if len(matches) < 5:
        return []
    ttr = len(set(matches)) / len(matches)
    density = len(matches) * 1000.0 / metrics.density_unit(text)
    if ttr >= metrics.THRESHOLDS["connective_ttr"] or density <= 10:
        return []
    intensity = 0.5 + 0.5 * min(1.0, (metrics.THRESHOLDS["connective_ttr"] - ttr) / 0.55)
    finding = make_finding(
        "connective_diversity",
        text,
        0,
        len(text),
        f"{len(matches)} 个连接词只用了 {len(set(matches))} 种（TTR {ttr:.2f}），集中在「"
        + "、".join(sorted(set(matches))[:5])
        + "」。",
    )
    return _finalize("connective_diversity", [finding], intensity)


def _four_char_runs(text: str) -> list[StyleFinding]:
    matches = list(metrics.FOUR_CHAR_RUN.finditer(text)) + list(
        metrics.TRIPLE_PARALLEL.finditer(text)
    )
    if not matches:
        return []
    matches.sort(key=lambda m: m.start())
    findings = _repeat_findings(
        "four_char_runs", text, matches, "排比/三连：「{text}」：三项同构容易空转。"
    )
    intensity = min(1.0, 0.55 + 0.15 * (len(findings) - 1))
    return _finalize("four_char_runs", findings, intensity)


def _boilerplate(text: str) -> list[StyleFinding]:
    matches = list(metrics.BOILERPLATE_RE.finditer(text))
    if len(matches) < 2:
        return []
    findings = _repeat_findings(
        "boilerplate",
        text,
        matches,
        "套话：「{text}」是总分总的壳子，信息量为零。",
        auto_fixable=True,
        extend_punctuation=True,
    )
    intensity = min(1.0, 0.5 + 0.15 * (len(matches) - 2))
    return _finalize("boilerplate", findings, intensity)


def _meaning_inflation(text: str) -> list[StyleFinding]:
    matches = list(metrics.INFLATION_RE.finditer(text))
    if not matches:
        return []
    rate = len(matches) * 1000.0 / metrics.density_unit(text)
    if rate < metrics.THRESHOLDS["inflation_per_k"]:
        return []
    findings = _repeat_findings(
        "meaning_inflation", text, matches, "意义拔高：「{text}」把一个事实顶成了意义。"
    )
    intensity = 0.5 + 0.5 * min(1.0, rate / 8.0)
    return _finalize("meaning_inflation", findings, intensity)


def _pseudo_depth(text: str) -> list[StyleFinding]:
    matches = list(metrics.PSEUDO_DEPTH.finditer(text))
    if not matches:
        return []
    rate = len(matches) * 1000.0 / metrics.density_unit(text)
    if rate < metrics.THRESHOLDS["pseudo_depth_per_k"]:
        return []
    findings = _repeat_findings(
        "pseudo_depth",
        text,
        matches,
        "假深刻否定：「{text}」先立一个假靶子再否定，绕开了直接判断。",
    )
    intensity = 0.5 + 0.5 * min(1.0, rate / 4.0)
    return _finalize("pseudo_depth", findings, intensity)


def _dash_quotes(text: str) -> list[StyleFinding]:
    dashes = list(metrics.DASH.finditer(text))
    quotes = list(metrics.QUOTE_PAIR.finditer(text))
    dash_rate = len(dashes) * 1000.0 / metrics.density_unit(text)
    quote_rate = len(quotes) * 1000.0 / metrics.density_unit(text)
    findings: list[StyleFinding] = []
    intensity = 0.0
    if dash_rate > metrics.THRESHOLDS["dash_per_k"]:
        findings.extend(
            _repeat_findings(
                "dash_quotes",
                text,
                dashes,
                f"破折号「—」是装饰性停顿（全文 {len(dashes)} 处），改冒号或句号。",
                auto_fixable=True,
            )
        )
        intensity = max(intensity, 0.6)
    if len(quotes) >= 3 and quote_rate > metrics.THRESHOLDS["quote_per_k"]:
        findings.extend(
            _repeat_findings(
                "dash_quotes",
                text,
                quotes,
                "装饰引号「{text}」：概念加引号不产生距离感，去掉或给出具体所指。",
            )
        )
        intensity = max(intensity, 0.5)
    return _finalize("dash_quotes", findings, intensity)


def _vague_verbs(text: str) -> list[StyleFinding]:
    vague = list(metrics.VAGUE_VERB.finditer(text))
    nominal = metrics.nominalization_hits(text)
    rate = (len(vague) + len(nominal)) * 1000.0 / metrics.density_unit(text)
    if rate < metrics.THRESHOLDS["vague_verb_per_k"]:
        return []
    findings = _repeat_spans(
        "vague_verb",
        text,
        nominal,
        "性化/化：「{text}」把属性做成了名词后缀，落到具体属性上。",
    )
    findings.extend(
        _repeat_findings(
            "vague_verb",
            text,
            vague,
            "虚化动词：「{text}」把动作包进了名词，还原成动词。",
            auto_fixable=True,
        )
    )
    intensity = 0.5 + 0.5 * min(1.0, rate / 10.0)
    return _finalize("vague_verb", findings, intensity)


def _concreteness_gap(text: str, paragraphs: list[Span]) -> list[StyleFinding]:
    findings: list[StyleFinding] = []
    intensity = 0.0
    for paragraph in paragraphs:
        if visible_len(paragraph.text) < 80:
            continue
        units = metrics.density_unit(paragraph.text)
        anchors = metrics.anchor_spans(paragraph.text)
        rate = len(anchors) * 100.0 / units
        if rate >= metrics.THRESHOLDS["anchor_per_100"]:
            continue
        intensity = max(intensity, 0.6 + 0.4 * (1.0 - min(1.0, rate)))
        findings.append(
            make_finding(
                "concreteness_gap",
                text,
                paragraph.start,
                paragraph.end,
                f"本段可核验锚点 {len(anchors)} 个（{rate:.1f}/百字）：没有年份、数字、《书名》或引用标记。",
                "待补材料：这一段还挂不上材料，补证据后再写；系统不会替你编。",
            )
        )
    return _finalize("concreteness_gap", findings, intensity or 0.5)


def _de_chain(text: str, paragraphs: list[Span]) -> list[StyleFinding]:
    findings: list[StyleFinding] = []
    threshold = int(metrics.THRESHOLDS["de_chain"])
    for paragraph in paragraphs:
        for sentence in sentence_spans(paragraph):
            count = sentence.text.count("的")
            if count < threshold:
                continue
            findings.append(
                make_finding(
                    "de_chain",
                    text,
                    sentence.start,
                    sentence.end,
                    f"这一句有 {count} 个「的」：定语套定语，读起来要断气。",
                )
            )
    intensity = min(1.0, 0.6 + 0.2 * (len(findings) - 1)) if findings else 0.0
    return _finalize("de_chain", findings, intensity)


def detect(text: str) -> list[StyleFinding]:
    """Run the 13 offline rules; the 3 LLM-only rules are added by the engine."""
    text = text or ""
    if not text.strip():
        return []
    paragraphs = body_paragraphs(text)
    findings: list[StyleFinding] = []
    findings.extend(_sentence_variance(text, paragraphs))
    findings.extend(_same_length_run(text, paragraphs))
    findings.extend(_paragraph_evenness(text, paragraphs))
    findings.extend(_connective_density(text, paragraphs))
    findings.extend(_connective_diversity(text))
    findings.extend(_four_char_runs(text))
    findings.extend(_boilerplate(text))
    findings.extend(_meaning_inflation(text))
    findings.extend(_pseudo_depth(text))
    findings.extend(_dash_quotes(text))
    findings.extend(_vague_verbs(text))
    findings.extend(_concreteness_gap(text, paragraphs))
    findings.extend(_de_chain(text, paragraphs))
    findings.sort(key=lambda f: (f.start, f.rule_id))
    return findings


def rule_ids(text: str) -> set[str]:
    return {finding.rule_id for finding in detect(text)}
