"""Shared search contracts: 15s transport, retry-once, normalization helpers.

Every adapter implements `search(...)` on top of `_fetch(...)`/`_to_hit(...)`.
Transport limits live here so no source can hang the whole search:

* 15s wall-clock timeout on every external call;
* one retry for 429/5xx (and connection/timeout errors);
* per-source errors are raised, never swallowed silently.
"""

from __future__ import annotations

import html
import re
import time
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

import httpx
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ...models import SearchHit

T = TypeVar("T")

SEARCH_TIMEOUT = 15.0
ZOTERO_TIMEOUT = 5.0
RETRY_STATUS = (429, 500, 502, 503, 504)
RETRY_DELAY_S = 0.15
MAX_LIMIT = 100
USER_AGENT = "Wenshu/0.1 (local-first research workbench)"

SOURCE_LABELS: dict[str, str] = {
    "openalex": "OpenAlex",
    "crossref": "Crossref",
    "semantic_scholar": "Semantic Scholar",
    "arxiv": "arXiv",
    "wanfang": "万方",
    "zotero": "Zotero",
    "doi": "DOI 查询",
}

# Politeness settings (mailto / S2 key) are process-wide because adapters are
# module-level singletons. The API refreshes them from the settings table before
# each search; they are read-only while the parallel requests run.
_OPTIONS: dict[str, str] = {"mailto": "", "s2_api_key": ""}


def configure(*, mailto: str | None = None, s2_api_key: str | None = None) -> None:
    """Update politeness settings. `None` keeps the current value."""
    if mailto is not None:
        _OPTIONS["mailto"] = mailto.strip()
    if s2_api_key is not None:
        _OPTIONS["s2_api_key"] = s2_api_key.strip()


def option(key: str, default: str = "") -> str:
    return _OPTIONS.get(key, default)


class SourceError(Exception):
    """A source-specific failure with a message ready for the UI."""

    def __init__(self, source: str, message: str):
        super().__init__(message)
        self.source = source
        self.message = message


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


# ---------------------------------------------------------------------------
# Transport helpers


class _TimeoutSession(requests.Session):
    """requests.Session whose default timeout can never be forgotten."""

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", SEARCH_TIMEOUT)
        return super().request(method, url, **kwargs)


def new_requests_session(*, retries: int = 0) -> requests.Session:
    """A requests session with the 15s timeout (and optional urllib3 retries)."""
    session = _TimeoutSession()
    retry = Retry(
        total=retries,
        status_forcelist=list(RETRY_STATUS),
        allowed_methods={"GET"},
        backoff_factor=0.2,
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def new_http_client(*, timeout: float = SEARCH_TIMEOUT) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


def http_get_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET JSON with one retry for 429/5xx."""

    def do() -> Any:
        response = client.get(url, params=params, headers=headers)
        if response.status_code in RETRY_STATUS:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code}", request=response.request, response=response
            )
        response.raise_for_status()
        return response.json()

    return retry_once(do)


def status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status extraction across httpx/requests/habanero/arXiv."""
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    match = re.search(r"\b(429|5\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


def is_retryable(exc: BaseException) -> bool:
    status = status_of(exc)
    if status is not None:
        return status in RETRY_STATUS
    if type(exc).__name__ in {"InternalServerErrorException", "GatewayTimeoutException"}:
        return True
    return isinstance(
        exc,
        (ConnectionError, TimeoutError, httpx.TransportError, httpx.TimeoutException),
    )


def retry_once(
    fn: Callable[[], T],
    *,
    retries: int = 1,
    delay: float = RETRY_DELAY_S,
    retryable: Callable[[BaseException], bool] = is_retryable,
) -> T:
    """Call `fn`, retrying once by default on 429/5xx/connection errors."""
    last: BaseException | None = None
    attempts = retries + 1
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            last = exc
            if attempt >= retries or not retryable(exc):
                raise
            time.sleep(delay * (attempt + 1))
    assert last is not None  # pragma: no cover - loop always returns/raises
    raise last


def human_error(source: str, exc: BaseException) -> str:
    """Turn any source failure into a short Chinese sentence for the UI."""
    label = source_label(source)
    if isinstance(exc, SourceError):
        return exc.message
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return f"{label} 在 15 秒内没有响应，已跳过这一源。"
    status = status_of(exc)
    if status == 429:
        return f"{label} 返回 429（请求过多），请过一会儿再试。"
    if status == 404:
        return f"{label} 没有找到对应的记录。"
    if status is not None and status >= 500:
        return f"{label} 返回 {status}（服务端错误），已跳过这一源。"
    if isinstance(exc, (httpx.ConnectError, requests.exceptions.ConnectionError)):
        return f"连不上 {label}，请检查网络或稍后再试。"
    return f"{label} 检索失败：{exc}"


# ---------------------------------------------------------------------------
# Normalization


def clamp_limit(limit: int | None) -> int:
    try:
        value = int(limit or 20)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, MAX_LIMIT))


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_LATIN_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")


def clean_text(value: Any) -> str:
    """NFC, unescape entities, drop tags, collapse whitespace. Never None."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value if item)
    text = html.unescape(str(value).replace("\x00", " "))
    text = _TAG_RE.sub(" ", text)
    text = unicodedata.normalize("NFC", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_doi(value: Any) -> str | None:
    """Return a bare lowercase DOI, or None when the value is not a DOI."""
    if not value:
        return None
    text = str(value).strip()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text, flags=re.I)
    match = re.search(r"10\.\d{4,9}/\S+", text, flags=re.I)
    if not match:
        return None
    doi = html.unescape(match.group(0)).strip()
    doi = doi.rstrip(".,;:)]}\"'")
    return doi.lower() or None


def normalize_title(title: Any) -> str:
    """Comparison key: NFKC, lowercase, no punctuation/space/braces."""
    text = clean_text(title)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"^(?:the|a|an)\s+", "", text)
    text = re.sub(r"[{}]", "", text)
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE)


def title_tokens(title: Any) -> set[str]:
    """Character bigrams for CJK, word tokens otherwise; used for Jaccard."""
    text = unicodedata.normalize("NFKC", clean_text(title)).lower()
    text = re.sub(r"[{}]", "", text)
    if _CJK_RE.search(text) or _KANA_RE.search(text):
        chars = list(_CJK_RE.findall(text)) + list(_KANA_RE.findall(text))
        if len(chars) < 2:
            return set(chars)
        return {chars[index] + chars[index + 1] for index in range(len(chars) - 1)}
    return set(_LATIN_WORD_RE.findall(text))


def title_similarity(left: Any, right: Any) -> float:
    left_tokens = title_tokens(left)
    right_tokens = title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b")


def parse_year(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1500 <= value <= 2199 else None
    if isinstance(value, (list, tuple)):
        for item in value:
            year = parse_year(item)
            if year:
                return year
        return None
    if isinstance(value, dict):
        for key in ("year", "date-parts", "date_parts", "value", "date"):
            if key in value:
                year = parse_year(value[key])
                if year:
                    return year
        return None
    match = _YEAR_RE.search(str(value))
    return int(match.group(1)) if match else None


_LANGUAGE_ALIASES = {
    "zh": "zh",
    "zho": "zh",
    "chi": "zh",
    "cn": "zh",
    "chinese": "zh",
    "中文": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-hant": "zh",
    "en": "en",
    "eng": "en",
    "english": "en",
    "英文": "en",
    "ja": "ja",
    "jpn": "ja",
    "jp": "ja",
    "japanese": "ja",
    "日文": "ja",
    "日语": "ja",
    "ko": "ko",
    "kor": "ko",
    "korean": "ko",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "fr": "fr",
    "de": "de",
}


def normalize_language(value: Any) -> str:
    if not value:
        return ""
    return _LANGUAGE_ALIASES.get(str(value).strip().lower(), "")


def guess_language(*texts: Any) -> str:
    text = " ".join(clean_text(item) for item in texts if item)
    if _KANA_RE.search(text):
        return "ja"
    if _HANGUL_RE.search(text):
        return "ko"
    if _CJK_RE.search(text):
        return "zh"
    if _CYRILLIC_RE.search(text):
        return "ru"
    if _LATIN_WORD_RE.search(text):
        return "en"
    return ""


def normalize_authors(value: Any) -> list[str]:
    """Normalize str/list/dict author shapes into a clean ordered list."""
    if value is None:
        return []
    raw: list[Any]
    if isinstance(value, str):
        raw = re.split(r"\s*(?:;|；|\band\b|、|&)\s*", value)
    elif isinstance(value, dict):
        raw = [value]
    elif isinstance(value, Iterable):
        raw = list(value)
    else:
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = ""
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = clean_text(item.get("name") or item.get("literal") or "")
            if not name:
                family = clean_text(item.get("family") or item.get("lastName") or "")
                given = clean_text(item.get("given") or item.get("firstName") or "")
                name = f"{given} {family}".strip() if given else family
            if not name:
                parts = [clean_text(item.get(key) or "") for key in ("given", "family")]
                name = " ".join(part for part in parts if part)
        if not name:
            continue
        name = re.sub(r"\s+", " ", name).strip(" ,;")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        result.append(name)
        if len(result) >= 50:
            break
    return result


def pages_from(first: Any, last: Any) -> str:
    start = clean_text(first)
    end = clean_text(last)
    if start and end and start != end:
        return f"{start}-{end}"
    return start or end


# ---------------------------------------------------------------------------
# Adapter contract


def accept_hit(
    hit: SearchHit,
    *,
    year_from: int | None,
    year_to: int | None,
    language: str | None,
) -> bool:
    """Client-side guard for sources that ignore or partially honor filters."""
    if hit.year is not None:
        if year_from is not None and hit.year < year_from:
            return False
        if year_to is not None and hit.year > year_to:
            return False
    target = normalize_language(language)
    if target:
        actual = normalize_language(hit.language) or guess_language(hit.title, hit.abstract)
        if actual and actual != target:
            return False
    return True


class SearchAdapter(ABC):
    """One literature source. `search` is the only method callers use."""

    name = ""
    label = ""

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        language: str | None = None,
    ) -> list[SearchHit]:
        text = clean_text(query)
        if not text:
            return []
        capped = clamp_limit(limit)
        raw = retry_once(
            lambda: self._fetch(
                text,
                limit=capped,
                year_from=year_from,
                year_to=year_to,
                language=language,
            )
        )
        hits: list[SearchHit] = []
        for item in raw:
            try:
                hit = self._to_hit(item)
            except Exception:  # noqa: BLE001 - one bad record must not kill the source
                continue
            if hit is None:
                continue
            hit.title = clean_text(hit.title)
            if not hit.title:
                continue
            if not hit.source:
                hit.source = self.name
            if not hit.language:
                hit.language = guess_language(hit.title, hit.abstract)
            if not accept_hit(hit, year_from=year_from, year_to=year_to, language=language):
                continue
            hits.append(hit)
            if len(hits) >= capped:
                break
        return hits

    @abstractmethod
    def _fetch(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        language: str | None,
    ) -> list[Any]:
        """Fetch raw records (network/IO lives here, timeout enforced)."""

    @abstractmethod
    def _to_hit(self, item: Any) -> SearchHit | None:
        """Map one raw record into a SearchHit; return None to skip."""
