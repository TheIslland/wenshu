from __future__ import annotations

import pytest

from wenshu.models import SearchHit
from wenshu.services import search as search_service


@pytest.fixture(autouse=True)
def _clear_search_cache():
    search_service.clear_cache()
    yield
    search_service.clear_cache()


class FakeAdapter:
    label = "Fake Source"

    def __init__(self, hits=None, error=None):
        self.hits = hits or []
        self.error = error
        self.calls: list[dict] = []

    def search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if self.error:
            raise self.error
        return [hit.model_copy(deep=True) for hit in self.hits]


def make_hit(**overrides) -> SearchHit:
    data = {
        "source": "fake",
        "source_id": "F1",
        "title": "偶像与拟像",
        "year": 2021,
        "authors": ["张三"],
    }
    data.update(overrides)
    return SearchHit(**data)


def test_search_endpoint_returns_normalized_results(client, monkeypatch):
    adapter = FakeAdapter([make_hit(), make_hit(title="第二篇", doi="10.1234/two")])
    monkeypatch.setitem(search_service.ADAPTERS, "fake", adapter)

    response = client.post(
        "/api/search",
        json={"query": "拟像", "sources": ["fake"], "limit": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "拟像"
    assert len(body["results"]) == 2
    assert body["results"][0]["source"] == "fake"
    assert body["errors"] == {}
    assert body["took_ms"] >= 0
    assert body["cached"] is False
    assert adapter.calls[0]["limit"] == 10


def test_search_cache_returns_cached_flag(client, monkeypatch):
    adapter = FakeAdapter([make_hit()])
    monkeypatch.setitem(search_service.ADAPTERS, "fake", adapter)
    payload = {"query": "拟像缓存", "sources": ["fake"]}
    first = client.post("/api/search", json=payload)
    assert first.status_code == 200
    calls = len(adapter.calls)
    second = client.post("/api/search", json=payload)
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert len(adapter.calls) == calls


def test_search_unknown_source_is_422(client):
    response = client.post(
        "/api/search", json={"query": "拟像", "sources": ["google_scholar"]}
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert "google_scholar" in error["message"]


def test_search_empty_query_is_422(client):
    response = client.post("/api/search", json={"query": "", "sources": ["openalex"]})
    assert response.status_code == 422


def test_search_one_source_failure_keeps_others(client, monkeypatch):
    good = FakeAdapter([make_hit(title="活下来的结果")])
    broken = FakeAdapter(error=RuntimeError("upstream exploded"))
    monkeypatch.setitem(search_service.ADAPTERS, "fake", good)
    monkeypatch.setitem(search_service.ADAPTERS, "broken", broken)

    response = client.post(
        "/api/search", json={"query": "拟像", "sources": ["fake", "broken"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["results"]] == ["活下来的结果"]
    assert "broken" in body["errors"]
    assert body["errors"]["broken"]


def test_search_nested_filters_are_tolerated(client, monkeypatch):
    adapter = FakeAdapter([make_hit()])
    monkeypatch.setitem(search_service.ADAPTERS, "fake", adapter)
    response = client.post(
        "/api/search",
        json={
            "query": "拟像",
            "sources": ["fake"],
            "filters": {"year_from": 2020, "year_to": 2022, "language": "zh", "limit": 5},
        },
    )
    assert response.status_code == 200
    call = adapter.calls[0]
    assert call["year_from"] == 2020
    assert call["year_to"] == 2022
    assert call["language"] == "zh"
    assert call["limit"] == 5


def test_search_history_records_project_and_filters(client, project, monkeypatch):
    adapter = FakeAdapter([make_hit()])
    monkeypatch.setitem(search_service.ADAPTERS, "fake", adapter)
    response = client.post(
        "/api/search",
        json={
            "query": "历史查询",
            "sources": ["fake"],
            "project_id": project["id"],
            "year_from": 2019,
        },
    )
    assert response.status_code == 200

    history = client.get(f"/api/search/history?project_id={project['id']}")
    assert history.status_code == 200
    items = history.json()
    assert items[0]["query"] == "历史查询"
    assert items[0]["source"] == "fake"
    assert items[0]["filters"]["year_from"] == 2019


def test_search_unknown_project_is_404(client, monkeypatch):
    monkeypatch.setitem(search_service.ADAPTERS, "fake", FakeAdapter([make_hit()]))
    response = client.post(
        "/api/search",
        json={"query": "拟像", "sources": ["fake"], "project_id": 999999},
    )
    assert response.status_code == 404


def test_search_doi_endpoint(client, monkeypatch):
    import wenshu.api.search as api_search

    def fake_import(doi):
        return SearchHit(
            source="doi",
            doi="10.1234/xyz",
            title="按 DOI 查到的文献",
            authors=["张三"],
            year=2020,
        )

    monkeypatch.setattr(api_search, "import_doi", fake_import)
    response = client.post("/api/search/doi", json={"doi": "10.1234/XYZ"})
    assert response.status_code == 200
    body = response.json()
    assert body["doi"] == "10.1234/xyz"
    assert body["title"] == "按 DOI 查到的文献"


def test_search_doi_rejects_garbage(client):
    response = client.post("/api/search/doi", json={"doi": "not-a-doi"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_search_sources_endpoint(client):
    response = client.get("/api/search/sources")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert {"openalex", "crossref", "semantic_scholar", "arxiv", "wanfang"} <= names
