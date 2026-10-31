"""Semantic Scholar adapter (official `semanticscholar` client)."""

from __future__ import annotations

from typing import Any

from semanticscholar import SemanticScholar

from ...models import SearchHit
from .base import (
    SEARCH_TIMEOUT,
    SearchAdapter,
    clean_text,
    normalize_doi,
    option,
    pages_from,
    parse_year,
)

_FIELDS = [
    "title",
    "authors",
    "year",
    "publicationDate",
    "venue",
    "publicationVenue",
    "journal",
    "abstract",
    "externalIds",
    "url",
    "openAccessPdf",
    "citationCount",
    "publicationTypes",
]


def _year_arg(year_from: int | None, year_to: int | None) -> str | None:
    if year_from and year_to:
        return f"{year_from}-{year_to}"
    if year_from:
        return f"{year_from}-"
    if year_to:
        return f"-{year_to}"
    return None


def _raw(item: Any) -> dict[str, Any]:
    raw = getattr(item, "raw_data", None)
    if isinstance(raw, dict):
        return raw
    return item if isinstance(item, dict) else {}


class SemanticScholarAdapter(SearchAdapter):
    name = "semantic_scholar"
    label = "Semantic Scholar"

    def _fetch(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        language: str | None,
    ) -> list[Any]:
        client = SemanticScholar(
            timeout=int(SEARCH_TIMEOUT),
            api_key=option("s2_api_key") or None,
            retry=False,
        )
        year = _year_arg(year_from, year_to)
        results = client.search_paper(
            query,
            limit=max(1, min(limit, 100)),
            fields=_FIELDS,
            year=year,
        )
        return list(results or [])

    def _to_hit(self, item: Any) -> SearchHit | None:
        work = _raw(item)
        title = clean_text(work.get("title") or "")
        if not title:
            return None
        external = work.get("externalIds") or {}
        doi = normalize_doi(external.get("DOI") if isinstance(external, dict) else None)
        journal = work.get("journal") or {}
        venue = clean_text(work.get("venue") or (work.get("publicationVenue") or {}).get("name") or "")
        open_pdf = work.get("openAccessPdf") or {}
        source_id = clean_text(work.get("paperId") or "")
        publication_types = work.get("publicationTypes") or []
        hit_type = "journal-article"
        if isinstance(publication_types, list) and publication_types:
            if "JournalArticle" in publication_types:
                hit_type = "journal-article"
            elif "Conference" in publication_types:
                hit_type = "proceedings-article"
            elif "Review" in publication_types:
                hit_type = "journal-article"
        return SearchHit(
            source=self.name,
            source_id=source_id,
            doi=doi,
            title=title,
            authors=[
                clean_text(author.get("name") or "")
                for author in (work.get("authors") or [])
                if isinstance(author, dict) and clean_text(author.get("name") or "")
            ],
            year=parse_year(work.get("year") or work.get("publicationDate")),
            venue=venue,
            volume=clean_text((journal or {}).get("volume") or ""),
            pages=pages_from((journal or {}).get("pages"), ""),
            type=hit_type,
            language="",
            abstract=clean_text(work.get("abstract") or ""),
            url=clean_text(work.get("url") or ""),
            pdf_url=clean_text((open_pdf or {}).get("url") or ""),
            cited_by=int(work.get("citationCount") or 0),
            raw={
                "paperId": source_id,
                "publicationTypes": publication_types,
                "fieldsOfStudy": work.get("fieldsOfStudy") or [],
            },
        )
