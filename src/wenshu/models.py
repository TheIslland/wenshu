"""Pydantic models shared by API and services."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Project(Base):
    id: int
    name: str
    field: str = ""
    question: str = ""
    description: str = ""
    status: str = "active"
    created_at: str
    updated_at: str


class ProjectCreate(Base):
    name: str = Field(min_length=1, max_length=200)
    field: str = ""
    question: str = ""
    description: str = ""


class ProjectPatch(Base):
    name: str | None = None
    field: str | None = None
    question: str | None = None
    description: str | None = None
    status: str | None = None


class Document(Base):
    id: int
    project_id: int
    title: str
    kind: str = "paper"
    content_md: str = ""
    word_count: int = 0
    version: int = 1
    created_at: str
    updated_at: str


class DocumentCreate(Base):
    title: str = Field(min_length=1, max_length=300)
    kind: str = "paper"
    content_md: str = ""


class DocumentSave(Base):
    content_md: str
    version: int


class DocumentPatch(Base):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    kind: str | None = None


class Snapshot(Base):
    id: int
    document_id: int
    reason: str = ""
    created_at: str


class SearchHit(Base):
    source: str
    source_id: str = ""
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    type: str = "journal-article"
    language: str = ""
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""
    cited_by: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class Ref(Base):
    id: int
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    type: str = "journal-article"
    language: str = ""
    abstract: str = ""
    url: str = ""
    source: str = ""
    source_id: str = ""
    bibkey: str = ""
    tags: list[str] = Field(default_factory=list)
    note: str = ""
    status: str = "inbox"
    pdf_path: str | None = None
    has_fulltext: bool = False
    created_at: str = ""
    updated_at: str = ""


class RefPatch(Base):
    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    url: str | None = None
    type: str | None = None
    language: str | None = None
    abstract: str | None = None
    note: str | None = None
    tags: list[str] | None = None
    status: str | None = None
    bibkey: str | None = None


class ImportResult(Base):
    imported: int = 0
    skipped: int = 0
    refs: list[Ref] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class StyleFinding(Base):
    rule_id: str
    name: str
    severity: Literal["info", "warn", "high"] = "warn"
    start: int = 0
    end: int = 0
    text: str = ""
    message: str = ""
    suggestion: str = ""
    auto_fixable: bool = False
    weight: float = 0.0


class StyleReport(Base):
    score: float = 0
    level: Literal["low", "medium", "high"] = "low"
    metrics: dict[str, float] = Field(default_factory=dict)
    findings: list[StyleFinding] = Field(default_factory=list)
    summary: str = ""
    baseline_used: bool = False
    llm_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class DiffOp(Base):
    op: Literal["equal", "insert", "delete"]
    text: str


class RewriteResult(Base):
    original: str
    revised: str
    diff: list[DiffOp] = Field(default_factory=list)
    ops: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    mode: str = ""


class MethodRow(Base):
    id: int | None = None
    project_id: int | None = None
    ref_id: int | None = None
    method: str = ""
    data: str = ""
    sample: str = ""
    theory: str = ""
    finding: str = ""
    limitation: str = ""
    evidence: list[str] = Field(default_factory=list)
    updated_at: str = ""


class TaskItem(Base):
    id: int
    project_id: int
    stage: str = "todo"
    title: str
    status: str = "todo"
    due: str | None = None
    notes: str = ""
    sort: int = 0
    created_at: str = ""
    updated_at: str = ""


class CitationCheck(Base):
    ref_id: int
    status: Literal["verified", "mismatch", "not_found", "no_doi", "error"]
    detail: dict[str, Any] = Field(default_factory=dict)


class DirectionCard(Base):
    id: int | None = None
    question: str
    gap: str = ""
    materials: str = ""
    method: str = ""
    risk: str = ""
    difficulty: str = ""
    novelty: str = ""
    evidence_refs: list[int] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)


class DirectionResult(Base):
    stats: dict[str, Any] = Field(default_factory=dict)
    cards: list[DirectionCard] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SearchResponse(Base):
    query: str
    results: list[SearchHit] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    cached: bool = False
    took_ms: int = 0
