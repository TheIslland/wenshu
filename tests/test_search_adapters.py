from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from wenshu.errors import ValidationFailed
from wenshu.models import SearchHit
from wenshu.services import search as search_service
from wenshu.services.search import base, dedupe
from wenshu.services.search.arxiv import ArxivAdapter, _build_query
from wenshu.services.search.crossref import CrossrefAdapter
from wenshu.services.search.openalex import OpenAlexAdapter
from wenshu.services.search.semantic_scholar import SemanticScholarAdapter
from wenshu.services.search.zotero import ZoteroClient


@pytest.fixture(autouse=True)
def _clean_search_state(monkeypatch):
    search_service.clear_cache()
    base.configure(mailto="", s2_api_key="")
    monkeypatch.setattr(base.time, "sleep", lambda *_args, **_kwargs: None)
    yield
    search_service.clear_cache()


def make_hit(**overrides) -> SearchHit:
    data = {
        "source": "openalex",
        "source_id": "W1",
        "title": "默认标题",
    }
    data.update(overrides)
    return SearchHit(**data)


def test_normalize_helpers():
    assert base.normalize_doi("https://doi.org/10.1234/ABC.") == "10.1234/abc"
    assert base.normalize_doi("doi: 10.5555/x") == "10.5555/x"
    assert base.normalize_doi("not a doi") is None

    assert base.normalize_title("《偶像与{拟像}》：日本") == "偶像与拟像日本"
    assert base.title_similarity("偶像与拟像研究", "偶像与拟像研究！") == 1.0
    assert base.title_similarity("偶像与拟像研究", "明清小说考据") < 0.3

    assert base.parse_year("2019-05-01") == 2019
    assert base.parse_year({"date-parts": [[2020, 3]]}) == 2020
    assert base.parse_year("forthcoming") is None

    assert base.guess_language("アイドルと擬像") == "ja"
    assert base.guess_language("偶像与拟像") == "zh"
    assert base.guess_language("Idols and simulacra") == "en"
    assert base.normalize_language("zh-CN") == "zh"
    assert base.normalize_language("Japanese") == "ja"

    assert base.normalize_authors("张三; 李四 and 王五") == ["张三", "李四", "王五"]
    assert base.normalize_authors([{"given": "三", "family": "张"}]) == ["三 张"]


def test_clean_text_nfc_and_entities():
    decomposed = "Cafe\u0301 &amp; 研究"
    cleaned = base.clean_text(decomposed)
    assert cleaned == "Caf\u00e9 & 研究"
    assert base.normalize_title(decomposed) == base.normalize_title("Caf\u00e9 & 研究")


def test_openalex_mapping():
    work = {
        "id": "https://openalex.org/W123",
        "doi": "https://doi.org/10.1234/OA",
        "display_name": "偶像与拟像研究",
        "authorships": [
            {"author": {"display_name": "山田太郎"}},
            {"author": {"display_name": "张三"}},
        ],
        "publication_year": 2021,
        "primary_location": {
            "source": {"display_name": "文化研究"},
            "landing_page_url": "https://example.org/landing",
        },
        "biblio": {"volume": "12", "issue": "3", "first_page": "45", "last_page": "67"},
        "type": "article",
        "language": "zh",
        "abstract_inverted_index": {"消费": [0], "社会": [1], "偶像": [2]},
        "cited_by_count": 7,
        "open_access": {"oa_url": "https://example.org/a.pdf", "is_oa": True},
    }
    hit = OpenAlexAdapter()._to_hit(work)
    assert hit is not None
    assert hit.source == "openalex"
    assert hit.source_id == "W123"
    assert hit.doi == "10.1234/oa"
    assert hit.authors == ["山田太郎", "张三"]
    assert hit.year == 2021
    assert hit.venue == "文化研究"
    assert hit.pages == "45-67"
    assert hit.type == "journal-article"
    assert hit.abstract == "消费 社会 偶像"
    assert hit.url == "https://doi.org/10.1234/oa"
    assert hit.pdf_url == "https://example.org/a.pdf"
    assert hit.cited_by == 7


def test_openalex_search_applies_year_and_language_filters(monkeypatch):
    adapter = OpenAlexAdapter()
    zh_2021 = {
        "id": "https://openalex.org/W1",
        "display_name": "中文文献",
        "publication_year": 2021,
        "language": "zh",
    }
    en_2019 = {
        "id": "https://openalex.org/W2",
        "display_name": "An English paper",
        "publication_year": 2019,
        "language": "en",
    }
    monkeypatch.setattr(adapter, "_fetch", lambda *args, **kwargs: [zh_2021, en_2019])
    hits = adapter.search("拟像", year_from=2020, language="zh", limit=10)
    assert [hit.title for hit in hits] == ["中文文献"]


def test_crossref_mapping():
    item = {
        "DOI": "10.1234/CR",
        "title": ["<jats:title>偶像与拟像</jats:title>"],
        "author": [{"given": "三", "family": "张"}, {"name": "Research Group"}],
        "issued": {"date-parts": [[2020, 5, 1]]},
        "container-title": ["文化研究"],
        "volume": "12",
        "issue": "3",
        "page": "45--67",
        "type": "posted-content",
        "language": "zh",
        "abstract": "<jats:p>消费社会中的偶像。</jats:p>",
        "URL": "https://example.org/cr",
        "is-referenced-by-count": 11,
    }
    hit = CrossrefAdapter()._to_hit(item)
    assert hit is not None
    assert hit.doi == "10.1234/cr"
    assert hit.title == "偶像与拟像"
    assert hit.authors == ["三 张", "Research Group"]
    assert hit.year == 2020
    assert hit.type == "preprint"
    assert hit.abstract == "消费社会中的偶像。"
    assert hit.cited_by == 11


def test_semantic_scholar_mapping():
    raw = {
        "paperId": "abc123",
        "title": "Idols and Simulacra",
        "authors": [{"name": "A. Author"}, {"name": "B. Writer"}],
        "year": 2022,
        "venue": "Journal of Tests",
        "journal": {"volume": "3", "pages": "10-20"},
        "externalIds": {"DOI": "10.1234/S2"},
        "abstract": "An abstract.",
        "url": "https://www.semanticscholar.org/paper/abc123",
        "openAccessPdf": {"url": "https://example.org/s2.pdf"},
        "citationCount": 5,
        "publicationTypes": ["JournalArticle"],
    }
    hit = SemanticScholarAdapter()._to_hit(raw)
    assert hit is not None
    assert hit.source == "semantic_scholar"
    assert hit.source_id == "abc123"
    assert hit.doi == "10.1234/s2"
    assert hit.authors == ["A. Author", "B. Writer"]
    assert hit.volume == "3"
    assert hit.pdf_url == "https://example.org/s2.pdf"


def test_arxiv_mapping_and_query_builder():
    item = SimpleNamespace(
        entry_id="http://arxiv.org/abs/2401.12345v2",
        title="Idols and\nSimulacra",
        authors=[SimpleNamespace(name="A. Author")],
        published=datetime(2024, 1, 1),
        doi=None,
        journal_ref="Some Journal",
        summary="An abstract.",
        pdf_url="https://arxiv.org/pdf/2401.12345v2",
        categories=[SimpleNamespace(category="cs.CL")],
        primary_category=SimpleNamespace(category="cs.CL"),
        comment="12 pages",
    )
    hit = ArxivAdapter()._to_hit(item)
    assert hit is not None
    assert hit.source_id == "2401.12345"
    assert hit.title == "Idols and Simulacra"
    assert hit.type == "preprint"
    assert hit.url.startswith("http://arxiv.org/abs/")
    assert hit.raw["primary_category"] == "cs.CL"
    query = _build_query("拟像", 2020, 2024)
    assert 'all:"拟像"' in query
    assert "submittedDate:[202001010000 TO 202412312359]" in query


def test_dedupe_by_doi_merges_fields():
    first = make_hit(
        source="openalex",
        title="偶像与拟像",
        doi="10.1234/ABC",
        abstract="短",
        cited_by=2,
    )
    second = make_hit(
        source="crossref",
        title="Idols and Simulacra",
        doi="https://doi.org/10.1234/abc",
        abstract="这是一个更长的摘要。",
        venue="文化研究",
        cited_by=9,
        authors=["张三"],
    )
    hits = dedupe.dedupe([first, second])
    assert len(hits) == 1
    assert hits[0].doi == "10.1234/abc"
    assert hits[0].abstract == "这是一个更长的摘要。"
    assert hits[0].venue == "文化研究"
    assert hits[0].cited_by == 9
    assert hits[0].authors == ["张三"]
    assert set(hits[0].raw["merged_sources"]) == {"openalex", "crossref"}


def test_dedupe_by_title_and_year_without_doi():
    first = make_hit(title="《偶像与{拟像}》：日本流行文化研究", year=2021)
    second = make_hit(title="偶像与拟像 日本流行文化研究", year=2021, source="crossref")
    third = make_hit(title="偶像与拟像 日本流行文化研究", year=2019, source="arxiv")
    hits = dedupe.dedupe([first, second, third])
    assert len(hits) == 2


def test_dedupe_keeps_distinct_dois_and_bridges_missing_doi():
    a = make_hit(title="同一篇论文的标题", year=2020, doi="10.1234/a")
    b = make_hit(title="同一篇论文的标题", year=2020, doi="10.1234/b")
    assert len(dedupe.dedupe([a, b])) == 2

    c = make_hit(title="同一篇论文的标题", year=2020, doi=None, source="arxiv")
    merged = dedupe.dedupe([c, a])
    assert len(merged) == 1
    assert merged[0].doi == "10.1234/a"


def test_cjk_japanese_and_braces_roundtrip():
    left = "『アイドル』と{擬像}：日本文化研究"
    right = "『アイドル』と擬像：日本文化研究"
    assert dedupe.titles_match(left, right)
    hit = make_hit(title=left)
    assert hit.title == left
    assert dedupe.dedupe([hit, make_hit(title=right)])[0].title == left


def test_adapter_retries_once_on_429():
    class RateLimited(Exception):
        status_code = 429

    class OnceFailingAdapter(SearchAdapterHarness):
        attempts = 0

        def _fetch(self, query, **kwargs):
            type(self).attempts += 1
            if type(self).attempts == 1:
                raise RateLimited("429")
            return [{"title": "重试成功"}]

        def _to_hit(self, item):
            return make_hit(title=item["title"], source="retry")

    adapter = OnceFailingAdapter()
    hits = adapter.search("拟像")
    assert [hit.title for hit in hits] == ["重试成功"]
    assert type(adapter).attempts == 2


class SearchAdapterHarness(base.SearchAdapter):
    name = "retry"
    label = "Retry"


def test_adapter_does_not_retry_validation_errors():
    class BadAdapter(SearchAdapterHarness):
        attempts = 0

        def _fetch(self, query, **kwargs):
            type(self).attempts += 1
            raise ValueError("bad query")

        def _to_hit(self, item):
            return None

    with pytest.raises(ValueError):
        BadAdapter().search("x")
    assert BadAdapter.attempts == 1


def test_search_all_parallel_isolates_errors_and_records_history(app):
    db = app.state.db

    class Source:
        def __init__(self, hits=None, error=None):
            self.hits = hits or []
            self.error = error
            self.calls = 0

        def search(self, query, **kwargs):
            self.calls += 1
            if self.error:
                raise self.error
            return list(self.hits)

    good = Source([make_hit(title="共享论文", doi="10.1234/shared", source="alpha")])
    other = Source([make_hit(title="共享论文", doi="10.1234/shared", source="beta")])
    broken = Source(error=ConnectionError("boom"))
    import wenshu.services.search as search_pkg

    search_pkg.ADAPTERS["alpha"] = good
    search_pkg.ADAPTERS["beta"] = other
    search_pkg.ADAPTERS["broken"] = broken
    try:
        meta: dict = {}
        hits, errors = search_pkg.search_all(
            db, "拟像", ["alpha", "beta", "broken"], limit=10, meta=meta
        )
        assert len(hits) == 1
        assert errors["broken"]
        assert "broken" in errors
        rows = db.query("SELECT query, source, count FROM searches ORDER BY id DESC LIMIT 1")
        assert rows[0]["query"] == "拟像"
        assert rows[0]["count"] == 1
        assert meta["cached"] is False

        # Cache hit: adapters are not called again.
        calls_before = good.calls
        meta2: dict = {}
        hits2, _ = search_pkg.search_all(
            db, "拟像", ["alpha", "beta", "broken"], limit=10, meta=meta2
        )
        assert meta2["cached"] is True
        assert good.calls == calls_before
        assert len(hits2) == 1
    finally:
        for name in ("alpha", "beta", "broken"):
            search_pkg.ADAPTERS.pop(name, None)


def test_search_all_rejects_unknown_source(app):
    with pytest.raises(ValidationFailed) as excinfo:
        search_service.search_all(app.state.db, "拟像", ["google_scholar"])
    assert "google_scholar" in str(excinfo.value)


def test_zotero_item_mapping():
    item = {
        "key": "ITEM1",
        "data": {
            "key": "ITEM1",
            "itemType": "journalArticle",
            "title": "日本偶像研究",
            "creators": [
                {"creatorType": "author", "firstName": "太郎", "lastName": "山田"},
                {"creatorType": "author", "name": "研究小组"},
            ],
            "date": "2019-05-01",
            "publicationTitle": "文化研究",
            "volume": "12",
            "issue": "3",
            "pages": "45-67",
            "DOI": "10.1234/ZOT",
            "url": "https://example.org/zot",
            "abstractNote": "摘要",
            "language": "ja",
            "tags": [{"tag": "偶像"}],
        },
    }
    hit = ZoteroClient()._to_hit(item)
    assert hit is not None
    assert hit.source == "zotero"
    assert hit.source_id == "ITEM1"
    assert hit.authors == ["太郎 山田", "研究小组"]
    assert hit.year == 2019
    assert hit.type == "journal-article"
    assert hit.raw["tags"] == ["偶像"]

    attachment = {"key": "A1", "data": {"itemType": "attachment", "title": "PDF"}}
    assert ZoteroClient()._to_hit(attachment) is None

def test_crossref_fetch_does_not_request_unsupported_language(monkeypatch):
    from wenshu.services.search import crossref

    seen = {}

    class FakeClient:
        def works(self, **params):
            seen.update(params)
            return {"message": {"items": []}}

    monkeypatch.setattr(crossref, "_client", lambda: FakeClient())
    adapter = CrossrefAdapter()
    assert adapter._fetch("short video", limit=1, year_from=None, year_to=None, language=None) == []
    assert "language" not in seen["select"]
    assert "publisher" in seen["select"]
