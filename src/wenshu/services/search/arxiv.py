"""arXiv adapter (official `arxiv` client, Atom parsing included)."""

from __future__ import annotations

import re
from typing import Any

import arxiv

from ...models import SearchHit
from .base import (
    SearchAdapter,
    clean_text,
    new_requests_session,
    normalize_doi,
    parse_year,
)

_ARXIV_ID_RE = re.compile(r"abs/([^/?#]+)")
_VERSION_RE = re.compile(r"v\d+$")


def _build_query(query: str, year_from: int | None, year_to: int | None) -> str:
    safe = re.sub(r'["\\]', " ", query).strip()
    parts = [f'all:"{safe}"']
    if year_from or year_to:
        start = f"{(year_from or 1900):04d}01010000"
        end = f"{(year_to or 2199):04d}12312359"
        parts.append(f"submittedDate:[{start} TO {end}]")
    return " AND ".join(parts)


def _arxiv_id(entry_id: Any) -> str:
    text = clean_text(entry_id)
    match = _ARXIV_ID_RE.search(text)
    if not match:
        return text
    return _VERSION_RE.sub("", match.group(1))


class ArxivAdapter(SearchAdapter):
    name = "arxiv"
    label = "arXiv"

    def _fetch(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        language: str | None,
    ) -> list[Any]:
        search = arxiv.Search(
            query=_build_query(query, year_from, year_to),
            max_results=max(1, min(limit, 100)),
            sort_by=arxiv.SortCriterion.Relevance,
        )
        client = arxiv.Client(page_size=max(1, min(limit, 100)), delay_seconds=0, num_retries=0)
        # arxiv.Client creates its own requests session without a timeout.
        client._session = new_requests_session(retries=0)
        return list(client.results(search))

    def _to_hit(self, item: Any) -> SearchHit | None:
        title = clean_text(getattr(item, "title", ""))
        if not title:
            return None
        entry_id = clean_text(getattr(item, "entry_id", ""))
        authors = [
            clean_text(getattr(author, "name", ""))
            for author in (getattr(item, "authors", None) or [])
            if clean_text(getattr(author, "name", ""))
        ]
        published = getattr(item, "published", None)
        categories = [
            clean_text(getattr(category, "category", ""))
            for category in (getattr(item, "categories", None) or [])
            if clean_text(getattr(category, "category", ""))
        ]
        primary = getattr(item, "primary_category", None)
        doi = normalize_doi(getattr(item, "doi", None))
        return SearchHit(
            source=self.name,
            source_id=_arxiv_id(entry_id),
            doi=doi,
            title=title,
            authors=authors,
            year=parse_year(published),
            venue=clean_text(getattr(item, "journal_ref", "") or "arXiv"),
            type="preprint",
            language="",
            abstract=clean_text(getattr(item, "summary", "")),
            url=entry_id or (f"https://arxiv.org/abs/{_arxiv_id(entry_id)}" if entry_id else ""),
            pdf_url=clean_text(getattr(item, "pdf_url", "")),
            cited_by=0,
            raw={
                "arxiv_id": _arxiv_id(entry_id),
                "categories": categories,
                "primary_category": clean_text(getattr(primary, "category", "")),
                "comment": clean_text(getattr(item, "comment", "")),
            },
        )
