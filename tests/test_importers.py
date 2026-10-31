from __future__ import annotations

import pytest
from habanero.exceptions import RequestError

from wenshu.errors import NotFound, ValidationFailed
from wenshu.services import importers

RIS_TEXT = """TY  - JOUR
TI  - 日本偶像与{拟像}
AU  - 山田太郎
AU  - 铃木花子
PY  - 2019
JO  - 文化研究
VL  - 12
IS  - 3
SP  - 45
EP  - 67
DO  - 10.1234/RIS.2019
AB  - 摘要{花括号}与「引号」测试
LA  - ja
ER  -

TY  - BOOK
TI  - 消费社会
AU  - 鲍德里亚
PY  - 1970
PB  - 南京大学出版社
ER  -
"""

BIBTEX_TEXT = """
@article{zhang2021,
  title = {中国偶像与{拟像}},
  author = {张三 and 李四},
  year = {2021},
  journal = {文化研究},
  volume = {12},
  number = {3},
  pages = {45--67},
  doi = {10.1234/BIB.2021},
  abstract = {摘要 with {braces}},
  language = {zh},
}
"""

CROSSREF_WORK = {
    "DOI": "10.1234/XYZ",
    "title": ["<jats:title>偶像与拟像</jats:title>"],
    "author": [{"given": "三", "family": "张"}],
    "issued": {"date-parts": [[2020]]},
    "container-title": ["文化研究"],
    "type": "journal-article",
    "abstract": "<jats:p>消费社会中的偶像。</jats:p>",
    "URL": "https://doi.org/10.1234/xyz",
}


def test_import_ris_chinese_japanese_and_braces():
    hits = importers.import_ris(RIS_TEXT)
    assert len(hits) == 2
    first, second = hits
    assert first.source == "ris"
    assert first.title == "日本偶像与{拟像}"
    assert first.authors == ["山田太郎", "铃木花子"]
    assert first.year == 2019
    assert first.venue == "文化研究"
    assert first.volume == "12"
    assert first.issue == "3"
    assert first.pages == "45-67"
    assert first.doi == "10.1234/ris.2019"
    assert first.language == "ja"
    assert "{花括号}" in first.abstract
    assert second.title == "消费社会"
    assert second.type == "book"


def test_import_ris_empty_returns_empty():
    assert importers.import_ris("   ") == []


def test_import_bibtex_unbraces_and_normalizes():
    hits = importers.import_bibtex(BIBTEX_TEXT)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.source == "bibtex"
    assert hit.title == "中国偶像与拟像"
    assert hit.authors == ["张三", "李四"]
    assert hit.year == 2021
    assert hit.venue == "文化研究"
    assert hit.issue == "3"
    assert hit.pages == "45-67"
    assert hit.doi == "10.1234/bib.2021"
    assert hit.abstract == "摘要 with braces"
    assert hit.raw["bibkey"] == "zhang2021"


def test_import_bibtex_rejects_garbage():
    with pytest.raises(ValidationFailed):
        importers.import_bibtex("this is not bibtex at all")


def test_import_ris_nfc_roundtrip():
    text = "TY  - JOUR\nTI  - Cafe\u0301 研究\nAU  - 张三\nPY  - 2020\nER  -\n"
    hits = importers.import_ris(text)
    assert hits[0].title == "Caf\u00e9 研究"


def test_import_doi_uses_crossref_and_normalizes(monkeypatch):
    captured = {}

    def fake_lookup(doi):
        captured["doi"] = doi
        return CROSSREF_WORK

    monkeypatch.setattr(importers, "_lookup_crossref", fake_lookup)
    hit = importers.import_doi("https://doi.org/10.1234/XYZ")
    assert captured["doi"] == "10.1234/xyz"
    assert hit.source == "doi"
    assert hit.doi == "10.1234/xyz"
    assert hit.title == "偶像与拟像"
    assert hit.authors == ["三 张"]
    assert hit.year == 2020
    assert hit.abstract == "消费社会中的偶像。"


def test_import_doi_not_found(monkeypatch):
    def fake_lookup(_doi):
        raise RequestError(404, "Resource not found.")

    monkeypatch.setattr(importers, "_lookup_crossref", fake_lookup)
    with pytest.raises(NotFound):
        importers.import_doi("10.1234/missing")


def test_import_doi_rejects_invalid_format():
    with pytest.raises(ValidationFailed):
        importers.import_doi("not-a-doi")


def test_import_doi_upstream_failure_is_friendly(monkeypatch):
    def fake_lookup(_doi):
        raise ConnectionError("network down")

    monkeypatch.setattr(importers, "_lookup_crossref", fake_lookup)
    with pytest.raises(Exception) as excinfo:
        importers.import_doi("10.1234/boom")
    assert "DOI" in str(excinfo.value) or "连不上" in str(excinfo.value)
