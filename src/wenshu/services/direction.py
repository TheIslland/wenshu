"""Research-direction exploration: local-library statistics + evidence-bound cards.

Hard rule: cards may only cite references that actually exist in the local
library or were passed in from a search result. Everything else is ``待检索``.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ..errors import NotFound, ValidationFailed
from ..llm import load_prompt
from ..models import now_iso

NO_EVIDENCE = "待检索"

_TEMPLATE_CARDS: tuple[dict[str, str], ...] = (
    {
        "question": "{topic}在近年的具体实践中呈现出哪些新的形态与差异？",
        "gap": "既有研究多停留在宏观描述，缺少对不同平台、群体或时期具体形态的比较。",
        "materials": "待检索",
        "method": "比较研究；内容分析",
        "risk": "材料可及性与样本代表性可能限制结论。",
        "difficulty": "中",
        "novelty": "中",
    },
    {
        "question": "哪些机制解释了{topic}的生成、扩散与接受？",
        "gap": "现有解释常把结构条件与行动者实践分开讨论，机制链条不完整。",
        "materials": "待检索",
        "method": "深度访谈；过程追踪",
        "risk": "机制推断容易滑向无法证伪的功能解释。",
        "difficulty": "高",
        "novelty": "中高",
    },
    {
        "question": "不同群体对{topic}的理解与使用存在怎样的差异？",
        "gap": "多数研究以单一群体为样本，跨群体比较与接受史证据不足。",
        "materials": "待检索",
        "method": "问卷；深度访谈；比较研究",
        "risk": "群体划分与抽样偏差需要提前说明。",
        "difficulty": "中",
        "novelty": "中",
    },
    {
        "question": "{topic}的概念与研究方法如何被学科史塑造，又如何反过来改变研究对象？",
        "gap": "概念史梳理常与当代经验研究脱节，缺少方法反思。",
        "materials": "待检索",
        "method": "文献研究；话语分析",
        "risk": "史料范围过宽，容易变成综述而不是问题。",
        "difficulty": "中高",
        "novelty": "中高",
    },
)


class _LLMCard(BaseModel):
    question: str
    gap: str = ""
    materials: str = ""
    method: str = ""
    risk: str = ""
    difficulty: str = ""
    novelty: str = ""
    evidence_refs: list[int] = Field(default_factory=list)


class _LLMResult(BaseModel):
    cards: list[_LLMCard] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _ref_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        for key in ("authors", "tags"):
            if isinstance(data.get(key), str):
                try:
                    data[key] = json.loads(data[key])
                except ValueError:
                    data[key] = []
        result.append(data)
    return result


def _query_refs(
    con: sqlite3.Connection,
    topic: str,
    project_id: int | None,
    years: int,
    language: str | None,
) -> list[dict[str, Any]]:
    sql = "SELECT r.* FROM refs r"
    params: list[Any] = []
    where: list[str] = []
    if project_id is not None:
        if not con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise NotFound("项目不存在。")
        sql += " JOIN project_refs pr ON pr.ref_id=r.id"
        where.append("pr.project_id=?")
        params.append(project_id)
    needle = topic.strip()
    if needle:
        where.append(
            "(r.title LIKE ? OR r.abstract LIKE ? OR r.note LIKE ? OR r.fulltext LIKE ? "
            "OR r.tags LIKE ?)"
        )
        pattern = f"%{needle}%"
        params.extend([pattern] * 5)
    if language:
        where.append("r.language LIKE ?")
        params.append(f"%{language.strip()}%")
    if years:
        current_year = datetime.now(UTC).year
        where.append("(r.year IS NULL OR r.year >= ?)")
        params.append(current_year - max(int(years), 1) + 1)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.year IS NULL, r.year DESC, r.id LIMIT 80"
    return _ref_dicts(con.execute(sql, params).fetchall())


def _stats(
    refs: list[dict[str, Any]], topic: str, project_id: int | None
) -> dict[str, Any]:
    years = [int(ref["year"]) for ref in refs if ref.get("year")]
    by_year = Counter(years)
    venues = Counter(
        str(ref["venue"]).strip() for ref in refs if str(ref.get("venue") or "").strip()
    )
    authors: Counter[str] = Counter()
    for ref in refs:
        names = ref.get("authors")
        if isinstance(names, str):
            try:
                names = json.loads(names)
            except ValueError:
                names = []
        for name in names or []:
            name = str(name).strip()
            if name:
                authors[name] += 1
    return {
        "topic": topic,
        "scope": "project" if project_id is not None else "library",
        "total": len(refs),
        "with_abstract": sum(1 for ref in refs if str(ref.get("abstract") or "").strip()),
        "year_range": [min(years), max(years)] if years else [],
        "by_year": [{"year": year, "count": count} for year, count in sorted(by_year.items())],
        "top_venues": [{"venue": name, "count": count} for name, count in venues.most_common(5)],
        "top_authors": [{"author": name, "count": count} for name, count in authors.most_common(5)],
    }


def _evidence_entry(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "ref_id": int(ref["id"]),
        "title": ref.get("title", ""),
        "authors": ref.get("authors", []),
        "year": ref.get("year"),
        "venue": ref.get("venue", ""),
        "doi": ref.get("doi"),
    }


def _note_for(ref: dict[str, Any]) -> str:
    year = ref.get("year")
    venue = str(ref.get("venue") or "").strip()
    suffix = f"（{venue}, {year}）" if venue and year else (f"（{year}）" if year else "")
    return f"文献 {ref['id']}：{ref.get('title', '')}{suffix}"


def _clean(value: Any, fallback: str = NO_EVIDENCE) -> str:
    text = str(value or "").strip()
    return text or fallback


def _template_cards(
    topic: str, refs: list[dict[str, Any]], warnings: list[str]
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    evidence_ids = [int(ref["id"]) for ref in refs[:3]]
    notes = [_note_for(ref) for ref in refs[:2]] or [NO_EVIDENCE]
    for template in _TEMPLATE_CARDS:
        card = {key: value.format(topic=topic) for key, value in template.items()}
        cards.append(
            {
                "id": None,
                "question": card["question"],
                "gap": card["gap"],
                "materials": card["materials"],
                "method": card["method"],
                "risk": card["risk"],
                "difficulty": card["difficulty"],
                "novelty": card["novelty"],
                "evidence_refs": evidence_ids,
                "evidence_notes": notes,
            }
        )
    if not refs:
        warnings.append("本地库没有匹配文献，所有问题卡的支撑文献均标为「待检索」。")
    return cards


def _llm_cards(
    topic: str,
    refs: list[dict[str, Any]],
    llm: Any,
    warnings: list[str],
) -> list[dict[str, Any]] | None:
    allowed = {int(ref["id"]): ref for ref in refs}
    payload = {
        "topic": topic,
        "refs": [
            {
                "ref_id": int(ref["id"]),
                "title": ref.get("title", ""),
                "year": ref.get("year"),
                "authors": ref.get("authors", []),
                "venue": ref.get("venue", ""),
                "abstract": str(ref.get("abstract") or "")[:1200],
            }
            for ref in refs[:30]
        ],
    }
    messages = [
        {"role": "system", "content": load_prompt("direction.md")},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        result = llm.chat_json(messages, _LLMResult)
    except Exception as exc:  # noqa: BLE001 - degrade to templates
        warnings.append(f"LLM 研究方向生成失败，已回退内置问题卡模板：{exc}")
        return None

    warnings.extend(result.warnings)
    cards: list[dict[str, Any]] = []
    for raw in result.cards[:5]:
        question = _clean(raw.question, "")
        if not question:
            continue
        kept_ids: list[int] = []
        for ref_id in raw.evidence_refs:
            if int(ref_id) in allowed:
                kept_ids.append(int(ref_id))
            else:
                warnings.append(f"问题卡引用了不在本地库/检索结果中的文献 {ref_id}，已剔除。")
        notes = [_note_for(allowed[ref_id]) for ref_id in kept_ids] or [NO_EVIDENCE]
        cards.append(
            {
                "id": None,
                "question": question,
                "gap": _clean(raw.gap),
                "materials": _clean(raw.materials),
                "method": _clean(raw.method),
                "risk": _clean(raw.risk),
                "difficulty": _clean(raw.difficulty),
                "novelty": _clean(raw.novelty),
                "evidence_refs": kept_ids,
                "evidence_notes": notes,
            }
        )
    return cards


def _save_cards(
    con: sqlite3.Connection, project_id: int, topic: str, cards: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    con.execute(
        "DELETE FROM direction_cards WHERE project_id=? AND topic=?", (project_id, topic)
    )
    saved: list[dict[str, Any]] = []
    now = now_iso()
    for card in cards:
        cur = con.execute(
            "INSERT INTO direction_cards(project_id, topic, question, gap, materials, method, "
            "risk, difficulty, novelty, evidence, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                topic,
                card["question"],
                card["gap"],
                card["materials"],
                card["method"],
                card["risk"],
                card["difficulty"],
                card["novelty"],
                json.dumps(
                    {
                        "ref_ids": card["evidence_refs"],
                        "notes": card["evidence_notes"],
                    },
                    ensure_ascii=False,
                ),
                now,
            ),
        )
        saved.append({**card, "id": int(cur.lastrowid or 0)})
    con.commit()
    return saved


def explore(
    con: sqlite3.Connection,
    topic: str,
    *,
    llm: Any = None,
    project_id: int | None = None,
    years: int = 10,
    language: str | None = None,
    hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build 3–5 research-question cards from local evidence."""
    topic = (topic or "").strip()
    if not topic:
        raise ValidationFailed("请先填写研究主题/关键词。")
    warnings: list[str] = []
    refs = _query_refs(con, topic, project_id, years, language)
    stats = _stats(refs, topic, project_id)

    cards = _llm_cards(topic, refs, llm, warnings) if llm is not None else None
    if cards is None:
        if llm is None:
            warnings.append("未配置 LLM，使用内置问题模板（现象/机制/比较/接受史）。")
        cards = _template_cards(topic, refs, warnings)
    else:
        if len(cards) < 3:
            warnings.append("LLM 生成的问题卡不足 3 张，已用内置模板补足。")
            for card in _template_cards(topic, refs, warnings):
                if len(cards) >= 3:
                    break
                if any(card["question"] == item["question"] for item in cards):
                    continue
                cards.append(card)
        if len(cards) > 5:
            cards = cards[:5]

    evidence_refs = [_evidence_entry(ref) for ref in refs[:20]]
    for hit in (hits or [])[:20]:
        if isinstance(hit, dict):
            evidence_refs.append(
                {
                    "ref_id": hit.get("ref_id") or hit.get("id"),
                    "title": hit.get("title", ""),
                    "authors": hit.get("authors", []),
                    "year": hit.get("year"),
                    "venue": hit.get("venue", ""),
                    "doi": hit.get("doi"),
                    "source": hit.get("source", "search"),
                }
            )
    if project_id is not None:
        cards = _save_cards(con, project_id, topic, cards)

    return {
        "stats": stats,
        "cards": cards,
        "evidence_refs": evidence_refs,
        "warnings": warnings,
        "llm_used": llm is not None,
    }
