from __future__ import annotations

import io
import json

import pytest
from docx import Document as DocxDocument
from docx.oxml.ns import qn

from wenshu.errors import ValidationFailed
from wenshu.services import exporters

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture()
def con(app):
    connection = app.state.db.connect()
    yield connection
    connection.close()


def seed_ref(con, project_id: int, **overrides) -> int:
    data = {
        "doi": "10.1234/abc",
        "title": "消费文化与后现代主义",
        "authors": ["费瑟斯通"],
        "year": 2000,
        "venue": "译林出版社",
        "type": "book",
        "bibkey": "fei2000",
    }
    data.update(overrides)
    cur = con.execute(
        "INSERT INTO refs(doi, title, authors, year, venue, type, bibkey, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            data["doi"],
            data["title"],
            json.dumps(data["authors"], ensure_ascii=False),
            data["year"],
            data["venue"],
            data["type"],
            data["bibkey"],
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


REF = {
    "id": 1,
    "doi": "10.1234/abc",
    "title": "消费文化与后现代主义",
    "authors": ["费瑟斯通"],
    "year": 2000,
    "venue": "译林出版社",
    "type": "book",
    "bibkey": "fei2000",
    "citation_status": "no_doi",
}

PROJECT = {"id": 1, "name": "测试项目"}
DOCUMENT = {"id": 1, "title": "我的论文", "content_md": "## 导论\n\n消费文化研究[@fei2000]。"}


def test_markdown_export_resolves_citations_and_lists_unverified():
    text = exporters.markdown(PROJECT, DOCUMENT, [REF])
    assert text.startswith("# 我的论文")
    assert "## 导论" in text
    assert "消费文化研究[1]。" in text
    assert "## 参考文献" in text
    assert "消费文化与后现代主义" in text
    assert "## 未核引清单" in text
    assert "无 DOI" in text


def test_markdown_unknown_citation_key_raises():
    with pytest.raises(ValidationFailed):
        exporters.markdown(PROJECT, DOCUMENT, [])


def test_markdown_verified_reference_omits_unverified_section():
    verified = {**REF, "citation_status": "verified"}
    text = exporters.markdown(PROJECT, DOCUMENT, [verified])
    assert "未核引清单" not in text


def test_bibtex_export():
    text = exporters.bibtex([REF])
    assert "@book{fei2000," in text
    assert "author = {费瑟斯通}" in text
    assert "title = {{消费文化与后现代主义}}" in text
    assert "publisher = {译林出版社}" in text
    assert "year = {2000}" in text


def test_ris_export():
    text = exporters.ris([REF])
    assert "TY  - BOOK" in text
    assert "AU  - 费瑟斯通" in text
    assert "TI  - 消费文化与后现代主义" in text
    assert "ER  - " in text


def test_docx_structure_and_chinese_fonts():
    data = exporters.docx(PROJECT, DOCUMENT, [REF])
    assert data[:2] == b"PK"

    doc = DocxDocument(io.BytesIO(data))
    texts = [paragraph.text for paragraph in doc.paragraphs]
    assert "我的论文" in texts
    assert "导论" in texts
    assert "参考文献" in texts
    assert "未核引清单" in texts

    normal = doc.styles["Normal"]
    assert normal.font.size.pt == 12
    assert normal.element.rPr.rFonts.get(qn("w:eastAsia")) == "宋体"
    assert normal.element.rPr.rFonts.get(qn("w:ascii")) == "Times New Roman"

    headings = [p for p in doc.paragraphs if p.style.name == "Heading 2"]
    assert any(p.text == "导论" for p in headings)
    body = next(p for p in doc.paragraphs if p.text == "消费文化研究[1]。")
    assert body.paragraph_format.line_spacing == 1.5


def test_docx_unknown_key_raises():
    with pytest.raises(ValidationFailed):
        exporters.docx(PROJECT, {**DOCUMENT, "content_md": "坏引用[@missing]"}, [])


def test_export_api_docx_and_markdown(client, con, project, document):
    doc_id = int(document["id"])
    con.execute(
        "UPDATE documents SET content_md=? WHERE id=?",
        ("# 一、导论\n\n消费文化研究[@fei2000]。", doc_id),
    )
    con.commit()
    ref_id = seed_ref(con, project["id"])
    con.execute(
        "INSERT INTO citation_checks(ref_id, status, detail, checked_at) VALUES(?,?,?,?)",
        (ref_id, "verified", "{}", NOW),
    )
    con.commit()

    docx_response = client.post(
        "/api/export/docx", json={"project_id": project["id"], "style": "gbt7714"}
    )
    assert docx_response.status_code == 200, docx_response.text
    assert docx_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    reopened = DocxDocument(io.BytesIO(docx_response.content))
    assert any(paragraph.text == "一、导论" for paragraph in reopened.paragraphs)
    assert not any(paragraph.text == "未核引清单" for paragraph in reopened.paragraphs)

    md_response = client.post(
        "/api/export/md", json={"document_id": doc_id, "style": "gbt7714"}
    )
    assert md_response.status_code == 200, md_response.text
    assert "## 参考文献" in md_response.text
    assert "消费文化研究[1]。" in md_response.text

    bib_response = client.post("/api/export/bibtex", json={"project_id": project["id"]})
    assert bib_response.status_code == 200
    assert "@book{fei2000," in bib_response.text

    ris_response = client.post("/api/export/ris", json={"project_id": project["id"]})
    assert ris_response.status_code == 200
    assert "TY  - BOOK" in ris_response.text

    bad = client.post("/api/export/pdf", json={"project_id": project["id"]})
    assert bad.status_code == 422
