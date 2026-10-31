"""Method extraction, matrix and yearly trends.

Rule dictionaries provide a deterministic baseline; an optional LLM may add
fields, but every LLM claim must ship an evidence sentence that is verifiably
present in the source text. Fields without evidence are marked ``未抽取``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

from pydantic import BaseModel, Field

from ..db import json_load
from ..errors import NotFound, ValidationFailed
from ..llm import load_prompt
from ..models import now_iso

NO_EVIDENCE = "未抽取"
METHOD_FIELDS = ("method", "data", "sample", "theory", "finding", "limitation")

METHOD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "文本分析": ("文本分析", "文本细读", "细读", "close reading", "textual analysis"),
    "内容分析": ("内容分析", "内容分析法", "编码表", "编码方案", "类目构建", "content analysis"),
    "话语分析": ("话语分析", "批评话语分析", "话语实践", "discourse analysis"),
    "民族志": ("民族志", "田野调查", "参与观察", "田野工作", "ethnography"),
    "深度访谈": ("深度访谈", "半结构访谈", "半结构化访谈", "焦点小组", "访谈法", "interviews"),
    "问卷": ("问卷", "量表", "抽样调查", "问卷调查", "questionnaire", "survey"),
    "个案研究": ("个案研究", "个案分析", "案例研究", "单案例", "多案例", "case study"),
    "比较研究": ("比较研究", "比较分析", "跨文化比较", "comparative"),
    "实验": ("实验法", "控制组", "实验组", "随机分组", "experiment"),
    "计算方法": ("计算传播", "自然语言处理", "机器学习", "主题模型", "社会网络分析", "大数据"),
    "混合方法": ("混合方法", "混合研究", "mixed methods"),
    "文献研究": ("文献研究", "文献综述", "系统综述", "元分析", "知识图谱", "meta-analysis"),
}

DATA_SOURCES: tuple[str, ...] = (
    "问卷",
    "访谈",
    "田野",
    "档案",
    "报纸",
    "微博",
    "微信",
    "豆瓣",
    "B站",
    "哔哩哔哩",
    "抖音",
    "快手",
    "小红书",
    "知乎",
    "平台数据",
    "语料库",
    "数据集",
    "公开数据",
    "评论",
    "帖子",
    "弹幕",
    "视频",
    "弹幕",
    "票房",
    "收视",
    "文献",
)

THEORY_TERMS: tuple[str, ...] = (
    "理论",
    "符号学",
    "结构主义",
    "后现代",
    "后结构",
    "拟像",
    "景观社会",
    "场域",
    "文化资本",
    "编码/解码",
    "议程设置",
    "使用与满足",
    "框架理论",
    "涵化理论",
    "第三人效果",
    "媒介化",
    "可供性",
    "情感结构",
    "接合理论",
    "亚文化",
    "迷群",
    "参与式文化",
    "身份认同",
    "集体记忆",
    "空间生产",
    "凝视",
    "表演性",
    "物质性",
    "行动者网络",
)

FINDING_MARKERS: tuple[str, ...] = (
    "研究发现",
    "研究表明",
    "本文发现",
    "研究显示",
    "结果显示",
    "数据表明",
    "结论",
    "揭示",
    "表明",
    "显示",
    "认为",
)

LIMITATION_MARKERS: tuple[str, ...] = (
    "局限",
    "不足",
    "未来研究",
    "有待",
    "尚需",
    "未能",
    "样本量小",
    "样本较小",
    "仅以",
    "尚缺乏",
)

_SAMPLE_PATTERNS = (
    re.compile(r"\d{1,6}\s*(?:名|位|人|份|个|篇|条|组)\s*(?:受访者|样本|用户|粉丝|学生|家长|帖子|视频|文章)?"),
    re.compile(r"样本(?:量)?\s*(?:为|是|共|：|:)?\s*\d{1,6}"),
    re.compile(r"\bN\s*=\s*\d{1,6}", re.I),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])|\n+|(?<=\.)\s+")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part and part.strip()]


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _source_segments(ref: dict[str, Any]) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for source, key in (
        ("title", "title"),
        ("abstract", "abstract"),
        ("note", "note"),
        ("fulltext", "fulltext"),
    ):
        value = str(ref.get(key) or "").strip()
        if value:
            if key == "fulltext":
                value = value[:8000]
            segments.append((source, value))
    return segments


def _ref_text(segments: list[tuple[str, str]]) -> str:
    return "\n".join(value for _, value in segments)


def _pick(
    sentences: list[tuple[str, str]], keywords: tuple[str, ...]
) -> tuple[str, str] | None:
    lowered = [(sentence, source, sentence.lower()) for sentence, source in sentences]
    for keyword in keywords:
        needle = keyword.lower()
        for sentence, source, low in lowered:
            if needle in low:
                return sentence, source
    return None


def _detect_methods(text: str) -> list[str]:
    low = text.lower()
    found = []
    for name, keywords in METHOD_KEYWORDS.items():
        if any(keyword.lower() in low for keyword in keywords):
            found.append(name)
    return found


def _detect_sample(sentences: list[tuple[str, str]]) -> tuple[str, str] | None:
    for sentence, source in sentences:
        for pattern in _SAMPLE_PATTERNS:
            if pattern.search(sentence):
                return sentence, source
    return _pick(sentences, ("样本", "受访者", "被试"))


def _rule_extract(ref: dict[str, Any]) -> dict[str, Any]:
    segments = _source_segments(ref)
    text = _ref_text(segments)
    sentences = [(s, source) for source, block in segments for s in _sentences(block)]

    methods = _detect_methods(text)
    row: dict[str, Any] = {
        "ref_id": int(ref["id"]),
        "method": "、".join(methods[:2]) if methods else NO_EVIDENCE,
        "data": NO_EVIDENCE,
        "sample": NO_EVIDENCE,
        "theory": NO_EVIDENCE,
        "finding": NO_EVIDENCE,
        "limitation": NO_EVIDENCE,
        "evidence": [],
    }

    def apply(field: str, hit: tuple[str, str] | None, value: str | None = None) -> None:
        if not hit:
            return
        quote, source = hit
        row[field] = (value or quote)[:300]
        row["evidence"].append(
            {"field": field, "quote": quote[:500], "source": source, "by": "rule"}
        )

    if methods:
        method_hit = None
        for name in methods:
            method_hit = _pick(sentences, METHOD_KEYWORDS[name])
            if method_hit:
                break
        apply("method", method_hit, row["method"])

    apply("data", _pick(sentences, DATA_SOURCES))
    apply("sample", _detect_sample(sentences))
    apply("theory", _pick(sentences, THEORY_TERMS))

    finding = _pick(sentences, FINDING_MARKERS)
    if finding and any(marker in finding[0] for marker in LIMITATION_MARKERS):
        finding = None
    apply("finding", finding)
    apply("limitation", _pick(sentences, LIMITATION_MARKERS))

    return row


class _LLMEvidence(BaseModel):
    field: str = ""
    quote: str = ""


class _LLMRow(BaseModel):
    ref_id: int
    method: str = ""
    data: str = ""
    sample: str = ""
    theory: str = ""
    finding: str = ""
    limitation: str = ""
    evidence: list[_LLMEvidence] = Field(default_factory=list)


class _LLMResult(BaseModel):
    rows: list[_LLMRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _project_refs(
    con: sqlite3.Connection, project_id: int, ref_ids: list[int] | None
) -> list[dict[str, Any]]:
    if not con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise NotFound("项目不存在。")
    sql = (
        "SELECT r.* FROM refs r JOIN project_refs pr ON pr.ref_id=r.id "
        "WHERE pr.project_id=?"
    )
    params: list[Any] = [project_id]
    if ref_ids is not None:
        if not ref_ids:
            return []
        placeholders = ",".join("?" for _ in ref_ids)
        sql += f" AND r.id IN ({placeholders})"
        params.extend(int(rid) for rid in ref_ids)
    sql += " ORDER BY r.year IS NULL, r.year DESC, r.id"
    return [dict(row) for row in con.execute(sql, params).fetchall()]


def _llm_enrich(
    refs: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    llm: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    by_id = {row["ref_id"]: row for row in rows}
    by_text: dict[int, str] = {}
    payload = []
    for ref in refs:
        text = _ref_text(_source_segments(ref))
        by_text[int(ref["id"])] = _norm_ws(text)
        payload.append(
            {
                "ref_id": int(ref["id"]),
                "title": ref.get("title", ""),
                "text": text[:6000],
            }
        )
    system = load_prompt("method_extract.md")
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps({"refs": payload}, ensure_ascii=False),
        },
    ]
    try:
        result = llm.chat_json(messages, _LLMResult)
    except Exception as exc:  # noqa: BLE001 - surfaced as a degraded-mode warning
        return rows, [f"LLM 抽取失败，已回退规则结果：{exc}"]

    warnings.extend(result.warnings)
    for llm_row in result.rows:
        row = by_id.get(int(llm_row.ref_id))
        if row is None:
            warnings.append(f"LLM 返回了项目之外的文献 ID {llm_row.ref_id}，已忽略。")
            continue
        text = by_text.get(int(llm_row.ref_id), "")
        quotes = {
            item.field: _norm_ws(item.quote)
            for item in llm_row.evidence
            if item.field and _norm_ws(item.quote)
        }
        for field in METHOD_FIELDS:
            value = str(getattr(llm_row, field) or "").strip()
            if not value or value == NO_EVIDENCE:
                continue
            quote = quotes.get(field)
            if not quote or quote not in text:
                warnings.append(
                    f"文献 {llm_row.ref_id} 的 {field} 缺少可核验证据句，已忽略该字段。"
                )
                continue
            if row[field] != NO_EVIDENCE:
                continue
            row[field] = value[:300]
            row["evidence"].append(
                {"field": field, "quote": quote[:500], "source": "llm", "by": "llm"}
            )
    return rows, warnings


def _save_rows(
    con: sqlite3.Connection, project_id: int, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    now = now_iso()
    ref_ids = [row["ref_id"] for row in rows]
    if ref_ids:
        placeholders = ",".join("?" for _ in ref_ids)
        con.execute(
            f"DELETE FROM method_rows WHERE project_id=? AND ref_id IN ({placeholders})",
            [project_id, *ref_ids],
        )
    saved: list[dict[str, Any]] = []
    for row in rows:
        cur = con.execute(
            "INSERT INTO method_rows(project_id, ref_id, method, data, sample, theory, "
            "finding, limitation, evidence, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                row["ref_id"],
                row["method"],
                row["data"],
                row["sample"],
                row["theory"],
                row["finding"],
                row["limitation"],
                json.dumps(row["evidence"], ensure_ascii=False),
                now,
            ),
        )
        saved.append({**row, "id": int(cur.lastrowid or 0), "project_id": project_id})
    con.commit()
    return saved


def extract(
    con: sqlite3.Connection,
    project_id: int,
    ref_ids: list[int] | None = None,
    llm: Any = None,
) -> dict[str, Any]:
    """Extract method rows for project references (rules first, LLM second)."""
    refs = _project_refs(con, project_id, ref_ids)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []
    for ref in refs:
        segments = _source_segments(ref)
        if not _ref_text(segments).strip():
            skipped.append(
                {"ref_id": int(ref["id"]), "reason": "没有摘要、笔记或全文，无法抽取。"}
            )
            continue
        rows.append(_rule_extract(ref))
    if llm is not None and rows:
        rows, llm_warnings = _llm_enrich(refs, rows, llm)
        warnings.extend(llm_warnings)
    elif llm is None:
        warnings.append("未配置 LLM，仅使用规则词典命中；未命中的字段标为「未抽取」。")

    saved = _save_rows(con, project_id, rows)
    return {
        "rows": saved,
        "extracted": len(saved),
        "skipped": skipped,
        "warnings": warnings,
        "llm_used": llm is not None,
    }


def _load_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["evidence"] = json_load(data.get("evidence"), [])
    data["ref_authors"] = json_load(data.get("ref_authors"), [])
    return data


MATRIX_SQL = """
SELECT mr.id, mr.project_id, mr.ref_id, mr.method, mr.data, mr.sample, mr.theory,
       mr.finding, mr.limitation, mr.evidence, mr.updated_at,
       r.title AS ref_title, r.year AS ref_year, r.authors AS ref_authors,
       r.venue AS ref_venue, r.doi AS ref_doi
FROM method_rows mr
LEFT JOIN refs r ON r.id = mr.ref_id
WHERE mr.project_id = ?
ORDER BY r.year IS NULL, r.year DESC, mr.id
"""


def matrix(
    con: sqlite3.Connection,
    project_id: int,
    *,
    client: Any = None,
    topic: str | None = None,
    years: int = 10,
) -> dict[str, Any]:
    """Return editable method rows, local trends, method trends and conflicts."""
    if not con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise NotFound("项目不存在。")
    rows = [_load_row(row) for row in con.execute(MATRIX_SQL, (project_id,)).fetchall()]

    trend_rows = con.execute(
        "SELECT r.year AS year, COUNT(*) AS count FROM refs r "
        "JOIN project_refs pr ON pr.ref_id=r.id "
        "WHERE pr.project_id=? AND r.year IS NOT NULL "
        "GROUP BY r.year ORDER BY r.year",
        (project_id,),
    ).fetchall()
    trend = [{"year": int(row["year"]), "count": int(row["count"])} for row in trend_rows]

    method_counts: Counter[tuple[int, str]] = Counter()
    for row in rows:
        if not row.get("ref_year") or not row.get("method"):
            continue
        for name in re.split(r"[、；;,，/]", row["method"]):
            name = name.strip()
            if name and name != NO_EVIDENCE:
                method_counts[(int(row["ref_year"]), name)] += 1
    method_trend = [
        {"year": year, "method": method, "count": count}
        for (year, method), count in sorted(method_counts.items())
    ]

    warnings: list[str] = []
    openalex_trend: list[dict[str, int]] = []
    if client is not None:
        query = (topic or "").strip()
        if not query:
            project = con.execute(
                "SELECT name, field, question FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            query = " ".join(
                str(project[key] or "").strip() for key in ("question", "field", "name")
            ).strip()
        try:
            mailto_row = con.execute(
                "SELECT value FROM settings WHERE key='search.mailto'"
            ).fetchone()
            mailto = str(mailto_row["value"]).strip() if mailto_row else None
            openalex_trend = openalex_year_counts(
                query, client=client, years=years, mailto=mailto
            )
        except Exception as exc:  # noqa: BLE001 - external trend is advisory only
            warnings.append(f"OpenAlex 年度趋势获取失败，仅显示本地库年份：{exc}")

    return {
        "rows": rows,
        "trend": trend,
        "method_trend": method_trend,
        "conflicts": _conflicts(rows),
        "openalex_trend": openalex_trend,
        "warnings": warnings,
    }


def _norm_for_compare(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def _conflicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        authors = row.get("ref_authors") or []
        author = str(authors[0]).strip() if authors else ""
        sample = str(row.get("sample") or "").strip()
        finding = str(row.get("finding") or "").strip()
        if not author or not sample or sample == NO_EVIDENCE or not finding:
            continue
        if finding == NO_EVIDENCE:
            continue
        groups[(_norm_for_compare(author), _norm_for_compare(sample))].append(row)

    conflicts: list[dict[str, Any]] = []
    for (_author_key, _sample_key), group in groups.items():
        if len(group) < 2:
            continue
        findings = [str(item.get("finding") or "").strip() for item in group]
        distinct: list[str] = []
        for finding in findings:
            if not any(
                SequenceMatcher(None, _norm_for_compare(finding), _norm_for_compare(other)).ratio()
                >= 0.9
                for other in distinct
            ):
                distinct.append(finding)
        if len(distinct) < 2:
            continue
        conflicts.append(
            {
                "author": group[0].get("ref_authors", [""])[0],
                "sample": group[0].get("sample", ""),
                "ref_ids": [item.get("ref_id") for item in group],
                "findings": findings,
                "message": "同一作者/样本的研究出现不同结论，请人工核对。",
            }
        )
    return conflicts


def update_row(
    con: sqlite3.Connection, row_id: int, changes: dict[str, Any]
) -> dict[str, Any]:
    """Edit one matrix cell. Empty strings are allowed; unknown keys are rejected."""
    current = con.execute("SELECT * FROM method_rows WHERE id=?", (row_id,)).fetchone()
    if not current:
        raise NotFound("方法矩阵行不存在。")
    fields = [key for key in METHOD_FIELDS if key in changes and changes[key] is not None]
    unknown = set(changes) - set(METHOD_FIELDS)
    if unknown:
        raise ValidationFailed(f"不支持编辑字段：{', '.join(sorted(unknown))}")
    if not fields:
        return _load_row(current)
    values = [str(changes[key])[:500] for key in fields]
    values.append(now_iso())
    values.append(row_id)
    con.execute(
        f"UPDATE method_rows SET {', '.join(f'{key}=?' for key in fields)}, "
        "updated_at=? WHERE id=?",
        values,
    )
    con.commit()
    updated = con.execute(MATRIX_SQL.replace("WHERE mr.project_id = ?", "WHERE mr.id = ?"), (row_id,)).fetchone()
    if updated is None:
        updated = con.execute("SELECT * FROM method_rows WHERE id=?", (row_id,)).fetchone()
    return _load_row(updated) if updated is not None else {}


OPENALEX_WORKS = "https://api.openalex.org/works"


def openalex_year_counts(
    query: str,
    *,
    client: Any,
    years: int = 10,
    mailto: str | None = None,
) -> list[dict[str, int]]:
    """Fetch yearly publication counts from OpenAlex (caller supplies HTTP client)."""
    current_year = datetime.now(UTC).year
    params: dict[str, Any] = {
        "search": query,
        "group_by": "publication_year",
        "per-page": 200,
    }
    if mailto:
        params["mailto"] = mailto
    response = client.get(OPENALEX_WORKS, params=params)
    response.raise_for_status()
    data = response.json()
    counts: list[dict[str, int]] = []
    for group in data.get("group_by") or []:
        try:
            year = int(group.get("key"))
        except (TypeError, ValueError):
            continue
        if year < current_year - max(int(years), 1) + 1:
            continue
        counts.append({"year": year, "count": int(group.get("count") or 0)})
    return sorted(counts, key=lambda item: item["year"])
