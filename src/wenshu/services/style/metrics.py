"""Character-counted style metrics behind the 16-rule lint engine.

Every number here is explainable from the text alone: no network, no model, no
statistical claim about who wrote it. Densities use Chinese characters as their
unit ("中文按字符计") and fall back to visible characters for pure-English
input, so empty or non-CJK text never divides by zero.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]")
SPACES = re.compile(r"\s+")
PARA_BREAK = re.compile(r"\n[ \t\r]*\n+")
SENT_END = re.compile(r"[。！？!?；;…]+[”’\"'」』）)]*")
HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]")

CONNECTIVES: tuple[str, ...] = (
    "综上所述",
    "总而言之",
    "总的来说",
    "值得注意的是",
    "由此可见",
    "与此同时",
    "换言之",
    "也就是说",
    "一方面",
    "另一方面",
    "首先",
    "其次",
    "再次",
    "此外",
    "另外",
    "同时",
    "然而",
    "但是",
    "因此",
    "所以",
    "从而",
    "进而",
    "并且",
    "而且",
    "不仅",
    "总之",
    "综上",
    "事实上",
    "实际上",
)

BOILERPLATE: tuple[str, ...] = (
    "综上所述",
    "总而言之",
    "总的来说",
    "值得注意的是",
    "由此可见",
    "毋庸置疑",
    "众所周知",
    "不难发现",
    "换言之",
    "综上",
    "首先",
    "其次",
    "再次",
    "最后",
)

INFLATION: tuple[str, ...] = ("标志着", "体现了", "彰显", "深刻", "昭示", "折射出")

DASH = re.compile(r"—{1,2}")
QUOTE_PAIR = re.compile(r"“[^”\n]{1,15}”|「[^」\n]{1,15}」")
PSEUDO_DEPTH = re.compile(
    r"不是[^。！？\n]{0,30}?而是|并非[^。！？\n]{0,30}?而是|与其说[^。！？\n]{0,20}?不如说"
)
VAGUE_VERB = re.compile(
    r"(?:进行|加以|作出|予以|给予)(?:了|着|过)?[^。！？\n，；]{0,6}?"
    r"(?:分析|研究|讨论|考察|论证|梳理|比较|说明|描述|处理|判断|评价|检验|测量|观察|"
    r"访谈|调查|统计|呈现|探讨|阐释|界定|反思|回应|补充|把握|解读)"
)
NOMINAL_SUFFIX = re.compile(r"[性化]")
NOMINAL_WORD_BLACKLIST = frozenset(
    {
        "文化",
        "变化",
        "消化",
        "转化",
        "异化",
        "绿化",
        "老化",
        "美化",
        "净化",
        "优化",
        "深化",
        "强化",
        "弱化",
        "量化",
        "女性",
        "男性",
        "个性",
        "特性",
        "属性",
        "理性",
        "感性",
        "惯性",
        "弹性",
    }
)
_NOMINAL_AFTER_XING = frozenset("的上了地，,。、；：和与是为在）」』很更最也都不对及强高多低大")
_NOMINAL_AFTER_HUA = frozenset("的了吗着过程，,。、；：是为上中在与和建进阶段")
FOUR_CHAR_RUN = re.compile(r"[\u4e00-\u9fff]{4}(?:[、和与及,，][\u4e00-\u9fff]{4}){2,}")
TRIPLE_PARALLEL = re.compile(
    r"(?:[\u4e00-\u9fff]{1,4}[性化力度感][、和与及]){2,}[\u4e00-\u9fff]{1,4}[性化力度感]"
)
ANCHORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:19|20)\d{2}\s*年?"),
    re.compile(r"\d+(?:\.\d+)?\s*[%％]?"),
    re.compile(r"《[^》\n]{1,60}》"),
    re.compile(r"\[\s*(?:@[\w:.\-]+|\d+(?:\s*[,，\-–]\s*\d+)*)\s*\]"),
    re.compile(r"第\s*\d+\s*页"),
    re.compile(r"10\.\d{4,9}/[^\s，。；]+"),
)

# Cold-start thresholds from design §7. Kept here so tests and the UI agree.
THRESHOLDS: dict[str, float] = {
    "sentence_cv": 0.38,
    "paragraph_cv": 0.30,
    "connective_per_k": 20.0,
    "connective_ttr": 0.55,
    "inflation_per_k": 2.0,
    "pseudo_depth_per_k": 1.0,
    "dash_per_k": 1.5,
    "quote_per_k": 8.0,
    "vague_verb_per_k": 4.0,
    "anchor_per_100": 1.0,
    "de_chain": 4.0,
}


def _alternation(words: tuple[str, ...]) -> re.Pattern[str]:
    ordered = sorted((re.escape(w) for w in words), key=len, reverse=True)
    return re.compile("|".join(ordered))


CONNECTIVE_RE = _alternation(CONNECTIVES)
BOILERPLATE_RE = _alternation(BOILERPLATE)
INFLATION_RE = _alternation(INFLATION)


@dataclass(frozen=True, slots=True)
class Span:
    """A half-open character range with the exact text it covers."""

    start: int
    end: int
    text: str


def visible_len(value: str) -> int:
    """Length in non-whitespace characters."""
    return len(SPACES.sub("", value))


def cjk_len(value: str) -> int:
    """Chinese/Japanese count; this is the density unit."""
    return len(CJK.findall(value))


def density_unit(value: str) -> int:
    """Characters used as density denominator; never zero."""
    return cjk_len(value) or max(1, visible_len(value))


def coefficient_of_variation(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = statistics.fmean(values)
    if mean <= 0:
        return 0.0
    return statistics.pstdev(values) / mean


def _push(spans: list[Span], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end > start:
        spans.append(Span(start, end, text[start:end]))


def paragraph_spans(text: str) -> list[Span]:
    """Markdown-ish paragraphs: blocks separated by a blank line."""
    spans: list[Span] = []
    cursor = 0
    for match in PARA_BREAK.finditer(text):
        _push(spans, text, cursor, match.start())
        cursor = match.end()
    _push(spans, text, cursor, len(text))
    return spans


def is_heading(paragraph: Span) -> bool:
    return bool(HEADING.match(paragraph.text))


def body_paragraphs(text: str) -> list[Span]:
    """Paragraphs that carry prose; headings are layout, not argument."""
    return [p for p in paragraph_spans(text) if not is_heading(p)]


def sentence_spans(paragraph: Span) -> list[Span]:
    """Sentences inside one paragraph, with absolute offsets into the full text."""
    content = paragraph.text
    base = paragraph.start
    spans: list[Span] = []
    cursor = 0
    boundaries = [match.end() for match in SENT_END.finditer(content)]
    if not boundaries or boundaries[-1] < len(content):
        boundaries.append(len(content))
    for boundary in boundaries:
        start = base + cursor
        end = base + boundary
        while start < end and content[start - base].isspace():
            start += 1
        while end > start and content[end - 1 - base].isspace():
            end -= 1
        if end > start:
            spans.append(Span(start, end, content[start - base : end - base]))
        cursor = boundary
    return spans


def anchor_spans(value: str, offset: int = 0) -> list[Span]:
    """Verifiable anchors: years, numbers, 《titles》, citation markers, pages."""
    hits: list[Span] = []
    for pattern in ANCHORS:
        for match in pattern.finditer(value):
            hits.append(Span(offset + match.start(), offset + match.end(), match.group(0)))
    hits.sort(key=lambda span: (span.start, -span.end))
    merged: list[Span] = []
    for hit in hits:
        if merged and hit.start < merged[-1].end:
            continue
        merged.append(hit)
    return merged


def nominalization_hits(value: str) -> list[Span]:
    """`X性` / `X化` nominalizations, skipping lexicalized words like 文化/女性."""
    hits: list[Span] = []
    for match in NOMINAL_SUFFIX.finditer(value):
        index = match.start()
        if index == 0 or not CJK.match(value[index - 1]):
            continue
        tail2 = value[max(0, index - 1) : index + 1]
        tail3 = value[max(0, index - 2) : index + 1]
        if tail2 in NOMINAL_WORD_BLACKLIST or tail3 in NOMINAL_WORD_BLACKLIST:
            continue
        following = value[index + 1] if index + 1 < len(value) else ""
        if following and not following.isspace():
            allowed = _NOMINAL_AFTER_XING if match.group(0) == "性" else _NOMINAL_AFTER_HUA
            if following not in allowed:
                continue
        start = max(0, index - 2)
        while start < index and not CJK.match(value[start]):
            start += 1
        hits.append(Span(start, index + 1, value[start : index + 1]))
    return hits


def _same_length_run(lengths: list[int]) -> int:
    """Longest run of consecutive sentences whose lengths differ by <= 8."""
    if not lengths:
        return 0
    best = run = 1
    for previous, current in zip(lengths, lengths[1:], strict=False):
        if abs(current - previous) <= 8:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def compute(text: str) -> dict[str, float]:
    """Return the paragraph-level metric bag for one text (pure function)."""
    text = text or ""
    paragraphs = body_paragraphs(text)
    sentence_lengths: list[int] = []
    run_best = 0
    de_hits = 0
    max_de = 0
    for paragraph in paragraphs:
        sentences = sentence_spans(paragraph)
        lengths = [visible_len(s.text) for s in sentences]
        sentence_lengths.extend(lengths)
        run_best = max(run_best, _same_length_run(lengths))
        for sentence in sentences:
            count = sentence.text.count("的")
            if count:
                de_hits += 1 if count >= int(THRESHOLDS["de_chain"]) else 0
            max_de = max(max_de, count)

    units = density_unit(text)
    paragraph_lengths = [float(visible_len(p.text)) for p in paragraphs]
    sentences_count = len(sentence_lengths)

    connectives = CONNECTIVE_RE.findall(text)
    connective_density = len(connectives) * 1000.0 / units
    connective_ttr = len(set(connectives)) / len(connectives) if connectives else 0.0

    boilerplate = BOILERPLATE_RE.findall(text)
    inflation = INFLATION_RE.findall(text)
    pseudo = PSEUDO_DEPTH.findall(text)
    vague = VAGUE_VERB.findall(text)
    nominal = nominalization_hits(text)
    anchors = anchor_spans(text)

    four_char_runs = len(FOUR_CHAR_RUN.findall(text)) + len(TRIPLE_PARALLEL.findall(text))
    dash_count = len(DASH.findall(text))
    quote_count = len(QUOTE_PAIR.findall(text))

    return {
        "chars": float(cjk_len(text)),
        "units": float(units),
        "visible_chars": float(visible_len(text)),
        "paragraphs": float(len(paragraphs)),
        "sentences": float(sentences_count),
        "sentence_mean": float(statistics.fmean(sentence_lengths)) if sentence_lengths else 0.0,
        "sentence_cv": coefficient_of_variation([float(n) for n in sentence_lengths]),
        "paragraph_cv": coefficient_of_variation(paragraph_lengths),
        "same_len_run": float(run_best),
        "connectives": float(len(connectives)),
        "connective_per_k": connective_density,
        "connective_ttr": connective_ttr,
        "boilerplate": float(len(boilerplate)),
        "boilerplate_per_k": len(boilerplate) * 1000.0 / units,
        "inflation": float(len(inflation)),
        "inflation_per_k": len(inflation) * 1000.0 / units,
        "pseudo_depth_per_k": len(pseudo) * 1000.0 / units,
        "dash_per_k": dash_count * 1000.0 / units,
        "quote_per_k": quote_count * 1000.0 / units,
        "vague_verb_per_k": len(vague) * 1000.0 / units,
        "nominalization_per_k": len(nominal) * 1000.0 / units,
        "anchor_per_100": len(anchors) * 100.0 / units,
        "max_de": float(max_de),
        "de_chain": float(de_hits),
        "four_char_runs": float(four_char_runs),
    }
