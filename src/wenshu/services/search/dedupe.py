"""Cross-source de-duplication: DOI first, then normalized title + year.

Merge policy: keep the first record as the base and fill every empty field from
the duplicate; longer author lists / abstracts win; citation counts take the max.
"""

from __future__ import annotations

from typing import Any

from ...models import SearchHit
from .base import clean_text, normalize_doi, normalize_title, title_similarity

# Jaccard threshold from the plan: same year + >= 0.92 means the same work.
TITLE_JACCARD = 0.92
MIN_TITLE_LENGTH = 8


def same_work(left: SearchHit, right: SearchHit) -> bool:
    left_doi = normalize_doi(left.doi)
    right_doi = normalize_doi(right.doi)
    if left_doi and right_doi:
        return left_doi == right_doi
    if left.year is not None and right.year is not None and left.year != right.year:
        return False
    return titles_match(left.title, right.title)


def titles_match(left: Any, right: Any) -> bool:
    left_key = normalize_title(left)
    right_key = normalize_title(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    if min(len(left_key), len(right_key)) < MIN_TITLE_LENGTH:
        return False
    return title_similarity(left, right) >= TITLE_JACCARD


def merge_hits(base: SearchHit, incoming: SearchHit) -> SearchHit:
    merged = base.model_copy(deep=True)
    merged.doi = normalize_doi(merged.doi) or normalize_doi(incoming.doi)
    fill_scalars = (
        "doi",
        "venue",
        "volume",
        "issue",
        "pages",
        "language",
        "url",
        "pdf_url",
        "source_id",
        "type",
    )
    for field in fill_scalars:
        if not getattr(merged, field) and getattr(incoming, field):
            setattr(merged, field, getattr(incoming, field))
    if merged.year is None and incoming.year is not None:
        merged.year = incoming.year
    if not merged.title:
        merged.title = clean_text(incoming.title)
    if len(incoming.abstract or "") > len(merged.abstract or ""):
        merged.abstract = incoming.abstract
    if len(incoming.authors) > len(merged.authors):
        merged.authors = list(incoming.authors)
    merged.cited_by = max(int(merged.cited_by or 0), int(incoming.cited_by or 0))
    merged.raw = _merged_raw(merged, incoming)
    return merged


def _merged_raw(base: SearchHit, incoming: SearchHit) -> dict[str, Any]:
    sources = list(base.raw.get("merged_sources") or [])
    for value in (base.source, incoming.source):
        if value and value not in sources:
            sources.append(value)
    raw = dict(base.raw)
    raw["merged_sources"] = sources
    incoming_sources = list(incoming.raw.get("merged_sources") or [])
    for value in incoming_sources:
        if value not in sources:
            raw["merged_sources"].append(value)
    return raw


def find_duplicate(hits: list[SearchHit], candidate: SearchHit) -> int | None:
    for index, existing in enumerate(hits):
        if same_work(existing, candidate):
            return index
    return None


def dedupe(hits: list[SearchHit]) -> list[SearchHit]:
    """Return one SearchHit per work, preserving first-seen order."""
    kept: list[SearchHit] = []
    for hit in hits:
        if not clean_text(hit.title):
            continue
        index = find_duplicate(kept, hit)
        if index is None:
            copy = hit.model_copy(deep=True)
            copy.doi = normalize_doi(copy.doi)
            kept.append(copy)
        else:
            kept[index] = merge_hits(kept[index], hit)
    return kept
