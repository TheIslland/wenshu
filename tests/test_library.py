from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from wenshu.errors import Conflict, ValidationFailed
from wenshu.models import SearchHit
from wenshu.services import library

RIS_TEXT = """TY  - JOUR
TI  - 日本偶像与拟像
AU  - 山田太郎
PY  - 2019
JO  - 文化研究
DO  - 10.1234/RIS.1
ER  -

TY  - BOOK
TI  - 消费社会
AU  - 鲍德里亚
PY  - 1970
PB  - 南京大学出版社
ER  -
"""

ZOTERO_ITEMS = [
    {
        "key": "Z1",
        "data": {
            "key": "Z1",
            "itemType": "journalArticle",
            "title": "Zotero 导入的文献",
            "creators": [{"creatorType": "author", "firstName": "三", "lastName": "张"}],
            "date": "2018",
            "publicationTitle": "文化研究",
            "DOI": "10.1234/ZOTERO",
        },
    },
    {"key": "Z2", "data": {"key": "Z2", "itemType": "attachment", "title": "PDF"}},
]


@pytest.fixture()
def con(app):
    connection = app.state.db.connect()
    try:
        yield connection
    finally:
        connection.close()


def make_hit(**overrides) -> SearchHit:
    data = {
        "source": "openalex",
        "source_id": "W1",
        "title": "偶像与拟像研究",
        "year": 2021,
        "authors": ["张三"],
    }
    data.update(overrides)
    return SearchHit(**data)


def make_pdf(text: str = "Hello Wenshu", *, title: str = "Test Paper") -> bytes:
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Title (" + title.encode("latin-1") + b") >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_upsert_ref_deduplicates_by_doi_and_merges(con):
    first = make_hit(
        doi="https://doi.org/10.1234/ABC",
        abstract="短摘要",
        source="openalex",
    )
    second = make_hit(
        source="crossref",
        doi="10.1234/abc",
        title="Idols and Simulacra",
        venue="文化研究",
        abstract="这是一个更长更完整的摘要。",
        authors=["张三", "李四"],
        language="zh",
    )
    ref_id = library.upsert_ref(con, first, None)
    second_id = library.upsert_ref(con, second, None)
    assert ref_id == second_id
    stored = library.get_ref(con, ref_id)
    assert stored["doi"] == "10.1234/abc"
    assert stored["title"] == "偶像与拟像研究"
    assert stored["authors"] == ["张三", "李四"]
    assert stored["venue"] == "文化研究"
    assert stored["abstract"] == "这是一个更长更完整的摘要。"
    assert stored["source"] == "openalex"
    assert con.execute("SELECT COUNT(*) FROM refs").fetchone()[0] == 1


def test_upsert_ref_deduplicates_title_and_year_without_doi(con):
    first_id = library.upsert_ref(con, make_hit(title="《偶像与{拟像}》：日本研究", year=2021))
    second_id = library.upsert_ref(con, make_hit(title="偶像与拟像 日本研究", year=2021))
    third_id = library.upsert_ref(
        con, make_hit(title="偶像与拟像 日本研究", year=2019, source="crossref")
    )
    assert first_id == second_id
    assert third_id != first_id


def test_upsert_ref_keeps_distinct_dois(con):
    first = library.upsert_ref(con, make_hit(doi="10.1234/a"))
    second = library.upsert_ref(con, make_hit(doi="10.1234/b"))
    assert first != second


def test_upsert_ref_links_project_and_relevance(con, project):
    ref_id = library.upsert_ref(con, make_hit(), project["id"], relevance=0.8)
    refs = library.list_refs(con, project_id=project["id"])
    assert [ref["id"] for ref in refs] == [ref_id]
    assert refs[0]["relevance"] == pytest.approx(0.8)
    # Linking twice must not duplicate the project row.
    library.upsert_ref(con, make_hit(), project["id"], relevance=0.2)
    count = con.execute(
        "SELECT COUNT(*) FROM project_refs WHERE project_id=?", (project["id"],)
    ).fetchone()[0]
    assert count == 1


def test_list_refs_filters_q_status_tag_and_fulltext(con):
    first = library.upsert_ref(con, make_hit(title="偶像与拟像", abstract="消费社会"))
    second = library.upsert_ref(con, make_hit(title="明清小说考据", year=2018))
    library.patch_ref(con, first, {"status": "read", "tags": ["理论"]})
    con.execute(
        "UPDATE refs SET fulltext=? WHERE id=?", ("偶像生产与消费社会的合谋", first)
    )
    con.commit()

    assert [ref["id"] for ref in library.list_refs(con, status="read")] == [first]
    assert [ref["id"] for ref in library.list_refs(con, tag="理论")] == [first]
    assert [ref["id"] for ref in library.list_refs(con, q="偶像")] == [first]
    fulltext_hits = library.list_refs(con, q="消费社会")
    assert {ref["id"] for ref in fulltext_hits} == {first}
    assert {ref["id"] for ref in library.list_refs(con)} == {first, second}


def test_list_refs_rejects_unknown_status(con):
    with pytest.raises(ValidationFailed):
        library.list_refs(con, status="finished")


def test_patch_ref_roundtrip_and_conflicts(con):
    first = library.upsert_ref(con, make_hit(doi="10.1234/first"))
    second = library.upsert_ref(con, make_hit(doi="10.1234/second", title="第二篇文献"))
    updated = library.patch_ref(
        con, second, {"status": "reading", "tags": ["方法"], "authors": ["李四"]}
    )
    assert updated["status"] == "reading"
    assert updated["tags"] == ["方法"]
    assert updated["authors"] == ["李四"]

    with pytest.raises(ValidationFailed):
        library.patch_ref(con, second, {"status": "unknown"})
    with pytest.raises(ValidationFailed):
        library.patch_ref(con, second, {"doi": "bad doi"})
    with pytest.raises(Conflict):
        library.patch_ref(con, second, {"doi": "10.1234/FIRST"})
    assert library.get_ref(con, first)["doi"] == "10.1234/first"


def test_api_import_doi(client, project, monkeypatch):
    import wenshu.api.library as api_library

    monkeypatch.setattr(
        api_library.importers,
        "import_doi",
        lambda _doi: make_hit(doi="10.1234/IMPORT", title="导入的 DOI 文献"),
    )
    response = client.post(
        "/api/refs/import",
        json={"project_id": project["id"], "kind": "doi", "payload": "10.1234/import"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1
    assert body["refs"][0]["title"] == "导入的 DOI 文献"
    assert body["refs"][0]["status"] == "inbox"

    listing = client.get(f"/api/refs?project_id={project['id']}")
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)
    assert listing.json()[0]["authors"] == ["张三"]


def test_api_import_hits_dedupes(client, project):
    hit = make_hit(doi="10.1234/BATCH").model_dump()
    response = client.post(
        "/api/refs/import",
        json={
            "project_id": project["id"],
            "kind": "hits",
            "hits": [hit, {**hit, "source": "crossref"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 1


def test_api_import_ris(client, project):
    response = client.post(
        "/api/refs/import",
        json={"project_id": project["id"], "kind": "ris", "payload": RIS_TEXT},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 2
    assert {ref["title"] for ref in body["refs"]} == {"日本偶像与拟像", "消费社会"}


def test_api_import_bibtex_preserves_bibkey(client, project):
    bibtex = (
        "@article{zhang2021,\n"
        "  title = {中国偶像与拟像},\n"
        "  author = {张三},\n"
        "  year = {2021},\n"
        "  journal = {文化研究},\n"
        "}\n"
    )
    response = client.post(
        "/api/refs/import",
        json={"project_id": project["id"], "kind": "bibtex", "payload": bibtex},
    )
    assert response.status_code == 200, response.text
    assert response.json()["refs"][0]["bibkey"] == "zhang2021"


def test_api_import_unknown_kind(client):
    response = client.post("/api/refs/import", json={"kind": "cnki"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_api_attach_pdf_and_search_fulltext(client, project, cfg):
    created = client.post(
        f"/api/refs?project_id={project['id']}",
        json=make_hit(title="待补 PDF", doi=None).model_dump(),
    )
    assert created.status_code == 200, created.text
    ref_id = created.json()["id"]
    response = client.post(
        f"/api/refs/{ref_id}/attach",
        files={"file": ("paper.pdf", make_pdf(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_fulltext"] is True
    assert body["fulltext_chars"] > 0
    assert body["pdf_path"].endswith(".pdf")
    saved = cfg.attachments_dir / Path(body["pdf_path"]).name
    assert saved.exists()

    text = client.get(f"/api/refs/{ref_id}/text?q=Wenshu")
    assert text.status_code == 200
    payload = text.json()
    assert payload["chars"] > 0
    assert payload["matches"]
    assert "Wenshu" in payload["matches"][0]["snippet"]


def test_api_attach_corrupt_pdf_is_422(client, project):
    created = client.post(f"/api/refs?project_id={project['id']}", json=make_hit().model_dump())
    ref_id = created.json()["id"]
    response = client.post(
        f"/api/refs/{ref_id}/attach",
        files={"file": ("broken.pdf", b"%PDF-1.4 broken", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "pdf_unreadable"


def test_api_import_pdf_file(client, project):
    response = client.post(
        "/api/refs/import/file",
        data={"project_id": str(project["id"])},
        files={"file": ("论文草稿.pdf", make_pdf(title="PDF Import"), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1
    assert body["refs"][0]["title"] == "PDF Import"
    assert body["refs"][0]["has_fulltext"] is True


def test_api_get_ref_text_without_fulltext(client, project):
    created = client.post(f"/api/refs?project_id={project['id']}", json=make_hit().model_dump())
    ref_id = created.json()["id"]
    response = client.get(f"/api/refs/{ref_id}/text")
    assert response.status_code == 200
    payload = response.json()
    assert payload["chars"] == 0
    assert payload["matches"] == []


def test_zotero_status_when_down(client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith="http://127.0.0.1:23119/").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        response = client.get("/api/zotero/status")
    assert response.status_code == 200
    body = response.json()
    assert body["running"] is False
    assert "Zotero" in body["message"]


def test_zotero_import_when_down_returns_human_error(client, project):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith="http://127.0.0.1:23119/").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        response = client.post(
            "/api/zotero/import", json={"project_id": project["id"], "limit": 10}
        )
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "upstream_error"
    assert "Zotero" in body["error"]["message"]


def test_zotero_import_success(client, project):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__startswith="http://127.0.0.1:23119/").mock(
            return_value=httpx.Response(200, json=ZOTERO_ITEMS)
        )
        response = client.post(
            "/api/zotero/import", json={"project_id": project["id"], "limit": 10}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["imported"] == 1
    assert body["refs"][0]["title"] == "Zotero 导入的文献"
    assert body["refs"][0]["doi"] == "10.1234/zotero"


def test_import_zip_roundtrip(client, project):
    # A Unicode attachment name and a CJK title must survive the whole round trip.
    title = "『アイドル』と擬像：中文标题"
    response = client.post(
        "/api/refs/import",
        json={
            "project_id": project["id"],
            "kind": "hits",
            "hits": [
                {
                    "source": "import",
                    "title": title,
                    "authors": ["山田太郎"],
                    "abstract": "摘要{保持}",
                    "year": 2020,
                }
            ],
        },
    )
    assert response.status_code == 200
    ref_id = response.json()["refs"][0]["id"]
    fetched = client.get(f"/api/refs/{ref_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == title
    assert fetched.json()["abstract"] == "摘要{保持}"
