"""Crossref adapter (habanero), including DOI lookups."""

from __future__ import annotations

from typing import Any

from habanero import Crossref

from ...models import SearchHit
from .base import (
    SEARCH_TIMEOUT,
    USER_AGENT,
    SearchAdapter,
    clean_text,
    normalize_authors,
    normalize_doi,
    option,
    parse_year,
)

_SELECT = [
    "DOI",
    "title",
    "author",
    "issued",
    "published-print",
    "published-online",
    "container-title",
    "volume",
    "issue",
    "page",
    "type",
    "language",
    "abstract",
    "URL",
    "is-referenced-by-count",
]

_TYPE_MAP = {
    "posted-content": "preprint",
    "dissertation": "thesis",
    "monograph": "book",
    "edited-book": "book",
    "reference-book": "book",
    "standard": "document",
    "component": "document",
    "peer-review": "document",
}


def _client() -> Crossref:
    mailto = option("mailto") or None
    return Crossref(
        mailto=mailto,
        timeout=int(SEARCH_TIMEOUT),
        ua_string=f"{USER_AGENT} (mailto:{mailto})" if mailto else USER_AGENT,
    )


def _map_type(value: Any) -> str:
    text = clean_text(value) or "journal-article"
    return _TYPE_MAP.get(text, text)


def _message(response: Any) -> dict[str, Any] | None:
    if isinstance(response, dict):
        message = response.get("message")
        if isinstance(message, dict):
            return message
    return None


class CrossrefAdapter(SearchAdapter):
    name = "crossref"
    label = "Crossref"

    def _fetch(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        language: str | None,
    ) -> list[Any]:
        filters: dict[str, str] = {}
        if year_from:
            filters["from-pub-date"] = f"{year_from}-01-01"
        if year_to:
            filters["until-pub-date"] = f"{year_to}-12-31"
        client = _client()
        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "sort": "relevance",
            "select": _SELECT,
        }
        if filters:
            params["filter"] = filters
        response = client.works(**params)
        message = _message(response)
        items = (message or {}).get("items") or []
        return [item for item in items if isinstance(item, dict)]

    def _to_hit(self, item: Any) -> SearchHit | None:
        work = item if isinstance(item, dict) else {}
        titles = work.get("title") or []
        title = clean_text(titles[0]) if isinstance(titles, list) and titles else clean_text(titles)
        if not title:
            return None
        doi = normalize_doi(work.get("DOI"))
        containers = work.get("container-title") or []
        venue = (
            clean_text(containers[0])
            if isinstance(containers, list) and containers
            else clean_text(containers)
        )
        issued = work.get("issued") or work.get("published-print") or work.get("published-online")
        return SearchHit(
            source=self.name,
            source_id=doi or "",
            doi=doi,
            title=title,
            authors=normalize_authors(work.get("author") or []),
            year=parse_year(issued),
            venue=venue,
            volume=clean_text(work.get("volume") or ""),
            issue=clean_text(work.get("issue") or ""),
            pages=clean_text(work.get("page") or "").replace("--", "-"),
            type=_map_type(work.get("type")),
            language=clean_text(work.get("language") or ""),
            abstract=clean_text(work.get("abstract") or ""),
            url=clean_text(work.get("URL") or "")
            or (f"https://doi.org/{doi}" if doi else ""),
            cited_by=int(work.get("is-referenced-by-count") or 0),
            raw={
                "publisher": clean_text(work.get("publisher") or ""),
                "subject": work.get("subject") or [],
            },
        )


def fetch_doi_work(doi: str) -> dict[str, Any] | None:
    """Fetch one Crossref work by DOI (used by the importer)."""
    response = _client().works(ids=doi)
    return _message(response)
