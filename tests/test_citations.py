from __future__ import annotations

import json

import httpx
import pytest
import respx

from wenshu.services import citations

NOW = "2026-01-01T00:00:00+00:00"

CROSSREF_URL = "https://api.crossref.org/works/"
OPENALEX_URL = "https://api.openalex.org/works/"


@pytest.fixture()
def con(app):
    connection = app.state.db.connect()
    yield connection
    connection.close()


def seed_ref(
    con,
    project_id: int,
    *,
    title: str,
    year: int | None = 2020,
    authors: tuple[str, ...] = ("Smith, John",),
    doi: str | None = "10.1234/abc",
) -> int:
    cur = con.execute(
        "INSERT INTO refs(doi, title, authors, year, venue, type, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            doi,
            title,
            json.dumps(list(authors), ensure_ascii=False),
            year,
            "Journal of Examples",
            "journal-article",
            NOW,
            NOW,
        ),
    )
    ref_id = int(cur.lastrowid or 0)
    con.execute(
        "INSERT INTO project_refs(project_id, ref_id, added_at) VALUES(?,?,?)",
        (project_id, ref_id, NOW),
    )
    con.commit()
    return ref_id


def crossref_payload(title: str, year: int, family: str = "Smith", given: str = "John"):
    return {
        "message": {
            "title": [title],
            "author": [{"family": family, "given": given}],
            "issued": {"date-parts": [[year]]},
            "DOI": "10.1234/abc",
            "container-title": ["Journal of Examples"],
        }
    }


def openalex_payload(title: str, year: int, name: str = "John Smith"):
    return {
        "title": title,
        "publication_year": year,
        "authorships": [{"author": {"display_name": name}}],
        "doi": "https://doi.org/10.1234/abc",
        "type": "article",
    }


@respx.mock
def test_verify_verified_via_crossref(con, project):
    ref_id = seed_ref(con, project["id"], title="A Study of Fan Culture")
    respx.get(url__startswith=CROSSREF_URL).mock(
        return_value=httpx.Response(200, json=crossref_payload("A Study of Fan Culture", 2020))
    )
    with httpx.Client() as http_client:
        results = citations.verify(con, [ref_id], client=http_client)
    assert results[0]["status"] == "verified"
    assert results[0]["detail"]["source"] == "crossref"
    stored = con.execute("SELECT * FROM citation_checks WHERE ref_id=?", (ref_id,)).fetchone()
    assert stored is not None
    assert stored["status"] == "verified"


@respx.mock
def test_verify_mismatch(con, project):
    ref_id = seed_ref(con, project["id"], title="A Study of Fan Culture")
    respx.get(url__startswith=CROSSREF_URL).mock(
        return_value=httpx.Response(
            200, json=crossref_payload("A Completely Different Title", 1999)
        )
    )
    with httpx.Client() as http_client:
        results = citations.verify(con, [ref_id], client=http_client)
    result = results[0]
    assert result["status"] == "mismatch"
    fields = {issue["field"] for issue in result["detail"]["issues"]}
    assert {"title", "year"} <= fields


@respx.mock
def test_verify_not_found(con, project):
    ref_id = seed_ref(con, project["id"], title="Missing Work")
    respx.get(url__startswith=CROSSREF_URL).mock(return_value=httpx.Response(404))
    respx.get(url__startswith=OPENALEX_URL).mock(return_value=httpx.Response(404))
    with httpx.Client() as http_client:
        results = citations.verify(con, [ref_id], client=http_client)
    assert results[0]["status"] == "not_found"
    assert results[0]["detail"]["tried"] == ["crossref", "openalex"]


@respx.mock
def test_verify_openalex_fallback(con, project):
    ref_id = seed_ref(con, project["id"], title="A Study of Fan Culture")
    respx.get(url__startswith=CROSSREF_URL).mock(return_value=httpx.Response(404))
    respx.get(url__startswith=OPENALEX_URL).mock(
        return_value=httpx.Response(200, json=openalex_payload("A Study of Fan Culture", 2020))
    )
    with httpx.Client() as http_client:
        results = citations.verify(con, [ref_id], client=http_client)
    assert results[0]["status"] == "verified"
    assert results[0]["detail"]["source"] == "openalex"


def test_verify_no_doi(con, project):
    ref_id = seed_ref(con, project["id"], title="No DOI Work", doi=None)
    with respx.mock(assert_all_called=False) as mock:
        results = citations.verify(con, [ref_id])
        assert mock.calls == []
    assert results[0]["status"] == "no_doi"


def test_empty_selection_makes_no_request(con):
    assert citations.verify(con, []) == []
    assert citations.latest_checks(con, []) == []


@respx.mock
def test_verify_error(con, project):
    ref_id = seed_ref(con, project["id"], title="Network Down")
    respx.get(url__startswith=CROSSREF_URL).mock(side_effect=httpx.ConnectError("boom"))
    respx.get(url__startswith=OPENALEX_URL).mock(side_effect=httpx.ConnectError("boom"))
    with httpx.Client() as http_client:
        results = citations.verify(con, [ref_id], client=http_client)
    assert results[0]["status"] == "error"
    assert results[0]["detail"]["reason"]


@respx.mock
def test_verify_batch(con, project):
    no_doi = seed_ref(con, project["id"], title="No DOI", doi=None)
    with_doi = seed_ref(con, project["id"], title="Has DOI", doi="10.1234/xyz")
    respx.get(url__startswith=CROSSREF_URL).mock(return_value=httpx.Response(404))
    respx.get(url__startswith=OPENALEX_URL).mock(return_value=httpx.Response(404))
    results = citations.verify(con, [no_doi, with_doi])
    assert [item["ref_id"] for item in results] == [no_doi, with_doi]
    assert results[0]["status"] == "no_doi"
    assert results[1]["status"] == "not_found"


GOLDEN_REFS = [
    {
        "id": 1,
        "authors": ["费瑟斯通"],
        "title": "消费文化与后现代主义",
        "type": "book",
        "venue": "译林出版社",
        "year": 2000,
    },
    {
        "id": 2,
        "authors": ["Smith, John", "Doe, Ann"],
        "title": "A Study of Things",
        "type": "journal-article",
        "venue": "Journal of Examples",
        "year": 2020,
        "volume": "12",
        "issue": "3",
        "pages": "45-67",
    },
]

GOLDEN_GB = (
    "[1] 费瑟斯通. 消费文化与后现代主义[M]. 译林出版社, 2000.\n"
    "[2] SMITH J, DOE A. A Study of Things[J]. Journal of Examples, 2020, 12(3): 45-67."
)


def test_gbt7714_builtin_golden(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("citeproc unavailable")

    monkeypatch.setattr(citations, "_render_citeproc", boom)
    report = citations.format_refs_report(GOLDEN_REFS, "gbt7714")
    assert report["engine"] == "builtin"
    assert report["text"] == GOLDEN_GB
    assert report["warnings"]
    assert citations.format_refs(GOLDEN_REFS) == GOLDEN_GB


def test_format_refs_uses_citeproc_when_available():
    report = citations.format_refs_report(GOLDEN_REFS, "gbt7714")
    assert report["text"]
    assert "消费文化与后现代主义" in report["text"]
    assert "[1]" in report["text"]
    assert report["engine"] in {"citeproc", "builtin"}

    apa = citations.format_refs_report(GOLDEN_REFS, "apa")
    assert "smith" in apa["text"].lower()


def test_format_unknown_style_warns():
    report = citations.format_refs_report(GOLDEN_REFS, "not-a-style")
    assert report["warnings"]
    assert "消费文化与后现代主义" in report["text"]


def test_citations_api_format(client, con, project):
    seed_ref(con, project["id"], title="A Study of Fan Culture")
    response = client.get(
        "/api/citations/format",
        params={"project_id": project["id"], "style": "gbt7714"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert "A Study of Fan Culture" in body["text"]
    assert isinstance(body["warnings"], list)
