"""Multi-source literature search: fan out, dedupe, record history, cache 24h."""

from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ...db import Database
from ...errors import ValidationFailed
from ...models import SearchHit, now_iso
from .arxiv import ArxivAdapter
from .base import (
    SEARCH_TIMEOUT,
    SearchAdapter,
    clean_text,
    configure,
    human_error,
)
from .crossref import CrossrefAdapter
from .dedupe import dedupe as dedupe_hits
from .openalex import OpenAlexAdapter
from .semantic_scholar import SemanticScholarAdapter
from .wanfang import WanfangAdapter

# Zotero is imported by the API/library flow (read-only import), not keyword search.
ADAPTERS: dict[str, SearchAdapter] = {
    adapter.name: adapter
    for adapter in (
        OpenAlexAdapter(),
        CrossrefAdapter(),
        SemanticScholarAdapter(),
        ArxivAdapter(),
        WanfangAdapter(),
    )
}

DEFAULT_SOURCES: tuple[str, ...] = ("openalex", "crossref")
ALL_SOURCES: tuple[str, ...] = tuple(ADAPTERS)

_CACHE_TTL_S = 24 * 60 * 60
_CACHE: dict[tuple[Any, ...], tuple[float, list[SearchHit], dict[str, str]]] = {}


def clear_cache() -> None:
    _CACHE.clear()


def _cache_key(
    query: str,
    sources: tuple[str, ...],
    limit: int,
    year_from: int | None,
    year_to: int | None,
    language: str | None,
) -> tuple[Any, ...]:
    return (query.casefold(), sources, limit, year_from, year_to, (language or "").lower())


def _resolve_sources(sources: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    requested = [clean_text(name).lower() for name in (sources or []) if clean_text(name)]
    requested = list(dict.fromkeys(requested))
    if not requested:
        return DEFAULT_SOURCES
    unknown = [name for name in requested if name not in ADAPTERS]
    if unknown:
        raise ValidationFailed(
            f"不认识的检索源：{'、'.join(unknown)}。",
            detail={"available": list(ADAPTERS)},
        )
    return tuple(requested)


def _record_search(
    db: Database | None,
    *,
    project_id: int | None,
    sources: tuple[str, ...],
    query: str,
    limit: int,
    year_from: int | None,
    year_to: int | None,
    language: str | None,
    count: int,
) -> None:
    if db is None:
        return
    filters = {
        "limit": limit,
        "year_from": year_from,
        "year_to": year_to,
        "language": language,
    }
    try:
        db.execute(
            "INSERT INTO searches(project_id, source, query, filters, count, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                project_id,
                ",".join(sources),
                query,
                json.dumps(filters, ensure_ascii=False),
                count,
                now_iso(),
            ),
        )
    except sqlite3.Error:
        # History is a convenience; never fail a search because of it.
        pass


def search_all(
    db: Database | None,
    query: str,
    sources: list[str] | tuple[str, ...] | None = None,
    *,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
    language: str | None = None,
    project_id: int | None = None,
    use_cache: bool = True,
    mailto: str | None = None,
    s2_api_key: str | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[list[SearchHit], dict[str, str]]:
    """Search every requested source in parallel; one failure never sinks the rest.

    Returns `(deduped_hits, errors_by_source)`. If `meta` is provided it is
    filled with `cached` and `took_ms` (the API needs those for SearchResponse).
    """
    started = time.monotonic()
    text = clean_text(query)
    if not text:
        return [], {}

    if mailto is not None or s2_api_key is not None:
        configure(mailto=mailto, s2_api_key=s2_api_key)

    resolved = _resolve_sources(sources)
    limit = max(1, min(int(limit or 20), 100))
    key = _cache_key(text, resolved, limit, year_from, year_to, language)

    if use_cache:
        cached = _CACHE.get(key)
        if cached and cached[0] > time.time():
            hits = [hit.model_copy(deep=True) for hit in cached[1]]
            errors = dict(cached[2])
            if meta is not None:
                meta["cached"] = True
                meta["took_ms"] = int((time.monotonic() - started) * 1000)
            return hits, errors

    def run(name: str) -> list[SearchHit]:
        return ADAPTERS[name].search(
            text,
            limit=limit,
            year_from=year_from,
            year_to=year_to,
            language=language,
        )

    by_source: dict[str, list[SearchHit]] = {}
    errors: dict[str, str] = {}
    if len(resolved) == 1:
        name = resolved[0]
        try:
            by_source[name] = run(name)
        except Exception as exc:  # noqa: BLE001 - reported per source
            errors[name] = human_error(name, exc)
    else:
        with ThreadPoolExecutor(
            max_workers=min(4, len(resolved)), thread_name_prefix="wenshu-search"
        ) as pool:
            futures = {pool.submit(run, name): name for name in resolved}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    by_source[name] = future.result(timeout=SEARCH_TIMEOUT + 5)
                except Exception as exc:  # noqa: BLE001 - reported per source
                    errors[name] = human_error(name, exc)

    merged: list[SearchHit] = []
    for name in resolved:
        merged.extend(by_source.get(name, []))
    hits = dedupe_hits(merged)

    if use_cache and (hits or not errors):
        _CACHE[key] = (
            time.time() + _CACHE_TTL_S,
            [hit.model_copy(deep=True) for hit in hits],
            dict(errors),
        )

    _record_search(
        db,
        project_id=project_id,
        sources=resolved,
        query=text,
        limit=limit,
        year_from=year_from,
        year_to=year_to,
        language=language,
        count=len(hits),
    )

    if meta is not None:
        meta["cached"] = False
        meta["took_ms"] = int((time.monotonic() - started) * 1000)
    return hits, errors
