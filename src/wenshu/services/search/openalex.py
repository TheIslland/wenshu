"""OpenAlex adapter.

pyalex builds the query and decodes the inverted abstract index; transport is
replaced with a 15s requests session because pyalex ships no timeout of its own.
"""

from __future__ import annotations

from typing import Any

import requests
from pyalex import Works, invert_abstract
from pyalex import api as pyalex_api

from ...models import SearchHit
from .base import (
    MAX_LIMIT,
    SearchAdapter,
    clean_text,
    new_requests_session,
    normalize_authors,
    normalize_doi,
    option,
    pages_from,
    parse_year,
)

_SESSION_PATCHED = False


def _install_timeout_session() -> None:
    """Give pyalex a 15s session. Safe to call more than once."""
    global _SESSION_PATCHED
    if _SESSION_PATCHED:
        return

    def factory() -> requests.Session:
        # pyalex calls this for every request; retry is handled by retry_once.
        return new_requests_session(retries=0)

    pyalex_api._get_requests_session = factory
    _SESSION_PATCHED = True


def _openalex_language(language: str | None) -> str:
    mapping = {
        "zh": "zh",
        "中文": "zh",
        "en": "en",
        "英文": "en",
        "ja": "ja",
        "日文": "ja",
        "ko": "ko",
        "ru": "ru",
        "fr": "fr",
        "de": "de",
    }
    return mapping.get((language or "").strip().lower(), "")


def _year_filter(year_from: int | None, year_to: int | None) -> str:
    if year_from and year_to:
        return f"{year_from}-{year_to}"
    if year_from:
        return f">={year_from}"
    if year_to:
        return f"<={year_to}"
    return ""


_TYPE_MAP = {
    "journal-article": "journal-article",
    "article": "journal-article",
    "book": "book",
    "book-chapter": "book-chapter",
    "book-section": "book-chapter",
    "proceedings-article": "proceedings-article",
    "dissertation": "thesis",
    "thesis": "thesis",
    "preprint": "preprint",
    "report": "report",
    "dataset": "dataset",
    "review": "journal-article",
    "editorial": "journal-article",
    "letter": "journal-article",
    "erratum": "journal-article",
    "paratext": "document",
    "other": "document",
}


def _openalex_id(value: Any) -> str:
    text = clean_text(value)
    return text.rsplit("/", 1)[-1] if "/" in text else text


class OpenAlexAdapter(SearchAdapter):
    name = "openalex"
    label = "OpenAlex"

    def _fetch(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        language: str | None,
    ) -> list[Any]:
        _install_timeout_session()
        pyalex_api.config.email = option("mailto") or None
        works = Works().search(query)
        filters: dict[str, Any] = {}
        year_range = _year_filter(year_from, year_to)
        if year_range:
            filters["publication_year"] = year_range
        source_language = _openalex_language(language)
        if source_language:
            filters["language"] = source_language
        if filters:
            works = works.filter(**filters)
        return list(works.get(per_page=max(1, min(limit, MAX_LIMIT))))

    def _to_hit(self, item: Any) -> SearchHit | None:
        work: dict[str, Any] = dict(item) if isinstance(item, dict) else {}
        if not work:
            return None
        title = clean_text(work.get("display_name") or work.get("title") or "")
        if not title:
            return None
        authors = []
        for authorship in work.get("authorships") or []:
            author = (authorship or {}).get("author") or {}
            name = clean_text(author.get("display_name") or author.get("name") or "")
            if name:
                authors.append(name)
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        biblio = work.get("biblio") or {}
        open_access = work.get("open_access") or {}
        abstract = ""
        inverted = work.get("abstract_inverted_index")
        if inverted:
            try:
                abstract = invert_abstract(inverted)
            except (TypeError, ValueError, AttributeError):
                abstract = ""
        doi = normalize_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))
        landing = clean_text(location.get("landing_page_url") or work.get("id") or "")
        return SearchHit(
            source=self.name,
            source_id=_openalex_id(work.get("id")),
            doi=doi,
            title=title,
            authors=normalize_authors(authors),
            year=parse_year(work.get("publication_year") or work.get("publication_date")),
            venue=clean_text(source.get("display_name") or ""),
            volume=clean_text(biblio.get("volume") or ""),
            issue=clean_text(biblio.get("issue") or ""),
            pages=pages_from(biblio.get("first_page"), biblio.get("last_page")),
            type=_TYPE_MAP.get(clean_text(work.get("type")), clean_text(work.get("type")) or "journal-article"),
            language=clean_text(work.get("language") or ""),
            abstract=clean_text(abstract),
            url=f"https://doi.org/{doi}" if doi else landing,
            pdf_url=clean_text(open_access.get("oa_url") or ""),
            cited_by=int(work.get("cited_by_count") or 0),
            raw={
                "openalex_id": _openalex_id(work.get("id")),
                "type": clean_text(work.get("type") or ""),
                "publication_year": work.get("publication_year"),
                "is_oa": bool(work.get("open_access", {}).get("is_oa")),
            },
        )
