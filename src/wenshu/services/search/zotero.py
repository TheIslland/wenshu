"""Zotero 7 local API (read-only).

The local API is opt-in in Zotero 7 (Settings -> Advanced). When it is closed we
must return a human sentence instead of letting a connection error become a 500.
"""

from __future__ import annotations

from typing import Any

import httpx

from ...models import SearchHit
from .base import (
    ZOTERO_TIMEOUT,
    SourceError,
    clean_text,
    http_get_json,
    new_http_client,
    normalize_authors,
    normalize_doi,
    parse_year,
)

ZOTERO_BASE = "http://127.0.0.1:23119/api/users/0"
ZOTERO_OFF_MESSAGE = (
    "没检测到 Zotero 本地接口。请打开 Zotero 7，在「设置 → 高级」里启用本地 API"
    "（默认端口 23119），然后重试。"
)

_TYPE_MAP = {
    "journalArticle": "journal-article",
    "book": "book",
    "bookSection": "book-chapter",
    "conferencePaper": "proceedings-article",
    "thesis": "thesis",
    "report": "report",
    "manuscript": "manuscript",
    "webpage": "webpage",
    "preprint": "preprint",
    "newspaperArticle": "newspaper-article",
    "magazineArticle": "magazine-article",
    "blogPost": "webpage",
    "document": "document",
}

_VENUE_KEYS = (
    "publicationTitle",
    "bookTitle",
    "proceedingsTitle",
    "conferenceName",
    "university",
    "publisher",
    "websiteTitle",
)


class ZoteroClient:
    def __init__(self, base_url: str = ZOTERO_BASE, *, timeout: float = ZOTERO_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # -- status ---------------------------------------------------------
    def status(self) -> dict[str, Any]:
        try:
            with new_http_client(timeout=self.timeout) as client:
                http_get_json(
                    client,
                    f"{self.base_url}/items",
                    params={"limit": 1, "format": "json"},
                )
        except httpx.TransportError:
            return {"running": False, "message": ZOTERO_OFF_MESSAGE, "base_url": self.base_url}
        except httpx.HTTPStatusError as exc:
            return {
                "running": False,
                "message": (
                    f"Zotero 本地接口返回 {exc.response.status_code}。请确认已在 Zotero 7 的"
                    "「设置 → 高级」中启用本地 API。"
                ),
                "base_url": self.base_url,
            }
        except ValueError:
            return {
                "running": True,
                "message": "Zotero 本地接口有响应，但返回的不是 JSON。",
                "base_url": self.base_url,
            }
        return {"running": True, "message": "Zotero 本地接口可用。", "base_url": self.base_url}

    # -- import ---------------------------------------------------------
    def fetch_items(self, *, limit: int = 100) -> list[SearchHit]:
        capped = max(1, min(int(limit or 100), 100))
        try:
            with new_http_client(timeout=self.timeout) as client:
                payload = http_get_json(
                    client,
                    f"{self.base_url}/items",
                    params={"limit": capped, "format": "json"},
                )
        except httpx.TransportError as exc:
            raise SourceError("zotero", ZOTERO_OFF_MESSAGE) from exc
        except httpx.HTTPStatusError as exc:
            raise SourceError(
                "zotero",
                f"Zotero 本地接口返回 {exc.response.status_code}，无法读取文献库。",
            ) from exc
        except ValueError as exc:
            raise SourceError("zotero", "Zotero 本地接口返回的数据不是合法 JSON。") from exc

        hits: list[SearchHit] = []
        for item in payload if isinstance(payload, list) else []:
            hit = self._to_hit(item)
            if hit is not None:
                hits.append(hit)
            if len(hits) >= capped:
                break
        return hits

    def _to_hit(self, item: Any) -> SearchHit | None:
        if not isinstance(item, dict):
            return None
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        if not isinstance(data, dict):
            return None
        item_type = clean_text(data.get("itemType") or "")
        if item_type in {"attachment", "note", "annotation"}:
            return None
        title = clean_text(data.get("title") or "")
        if not title:
            return None
        venue = ""
        for key in _VENUE_KEYS:
            venue = clean_text(data.get(key) or "")
            if venue:
                break
        creators = data.get("creators") or []
        tags = [
            clean_text(tag.get("tag") or "")
            for tag in (data.get("tags") or [])
            if isinstance(tag, dict) and clean_text(tag.get("tag") or "")
        ]
        return SearchHit(
            source="zotero",
            source_id=clean_text(data.get("key") or item.get("key") or ""),
            doi=normalize_doi(data.get("DOI")),
            title=title,
            authors=normalize_authors(creators),
            year=parse_year(data.get("date")),
            venue=venue,
            volume=clean_text(data.get("volume") or ""),
            issue=clean_text(data.get("issue") or ""),
            pages=clean_text(data.get("pages") or "").replace("--", "-"),
            type=_TYPE_MAP.get(item_type, item_type.lower() or "journal-article"),
            language=clean_text(data.get("language") or ""),
            abstract=clean_text(data.get("abstractNote") or ""),
            url=clean_text(data.get("url") or ""),
            raw={"itemType": item_type, "tags": tags},
        )


def default_client() -> ZoteroClient:
    return ZoteroClient()
