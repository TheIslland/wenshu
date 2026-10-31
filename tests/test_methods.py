from __future__ import annotations

import json

import httpx
import pytest
import respx

from wenshu.llm import FakeLLM
from wenshu.services import methods

NOW = "2026-01-01T00:00:00+00:00"


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
    abstract: str = "",
    year: int | None = 2022,
    authors: tuple[str, ...] = ("张三",),
    doi: str | None = None,
    bibkey: str = "",
) -> int:
    cur = con.execute(
        "INSERT INTO refs(doi, title, authors, year, venue, type, abstract, bibkey, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            doi,
            title,
            json.dumps(list(authors), ensure_ascii=False),
            year,
            "测试期刊",
            "journal-article",
            abstract,
            bibkey or f"ref{title[:4]}",
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


def test_rule_extraction_with_evidence(con, project):
    ref_id = seed_ref(
        con,
        project["id"],
        title="粉丝文化中的参与式实践",
        abstract=(
            "本文采用深度访谈与内容分析法，访谈了 24 位粉丝，"
            "基于参与式文化理论，研究发现粉丝通过二次创作协商身份。"
            "研究局限在于样本量较小，未来研究可扩大样本。"
        ),
    )

    result = methods.extract(con, project["id"], [ref_id], None)

    assert result["extracted"] == 1
    row = result["rows"][0]
    assert "内容分析" in row["method"]
    assert "深度访谈" in row["method"]
    assert "24" in row["sample"]
    assert "参与式文化" in row["theory"]
    assert row["finding"] != methods.NO_EVIDENCE
    assert row["limitation"] != methods.NO_EVIDENCE
    assert row["evidence"]
    assert all(item["by"] == "rule" for item in row["evidence"])
    assert any(item["field"] == "method" for item in row["evidence"])

    stored = con.execute("SELECT * FROM method_rows WHERE ref_id=?", (ref_id,)).fetchone()
    assert stored is not None
    assert json.loads(stored["evidence"])


def test_fields_without_evidence_marked(con, project):
    ref_id = seed_ref(con, project["id"], title="平台文化研究", abstract="")
    result = methods.extract(con, project["id"], [ref_id], None)
    row = result["rows"][0]
    for field in ("method", "data", "sample", "theory", "finding", "limitation"):
        assert row[field] == methods.NO_EVIDENCE
    assert result["warnings"]


def test_extract_with_empty_selection_is_noop(con, project):
    seed_ref(con, project["id"], title="平台文化研究", abstract="本文采用内容分析。")
    result = methods.extract(con, project["id"], [], None)
    assert result["rows"] == []
    assert result["extracted"] == 0
    assert con.execute("SELECT COUNT(*) FROM method_rows").fetchone()[0] == 0


def test_llm_fills_only_missing_fields_with_valid_quote(con, project):
    abstract = "平台文化研究。本文使用深度访谈方法，访谈了 12 位用户。"
    ref_id = seed_ref(con, project["id"], title="平台文化研究", abstract=abstract)
    llm = FakeLLM(
        {
            "TASK:METHOD": json.dumps(
                {
                    "rows": [
                        {
                            "ref_id": ref_id,
                            "theory": "参与式文化",
                            "limitation": "样本有限",
                            "evidence": [
                                {
                                    "field": "theory",
                                    "quote": "本文使用深度访谈方法，访谈了 12 位用户。",
                                },
                                {"field": "limitation", "quote": "原文里没有这句话"},
                            ],
                        }
                    ],
                    "warnings": [],
                },
                ensure_ascii=False,
            )
        }
    )

    result = methods.extract(con, project["id"], [ref_id], llm)
    row = result["rows"][0]
    assert row["theory"] == "参与式文化"
    assert row["limitation"] == methods.NO_EVIDENCE
    assert any(
        item["field"] == "theory" and item["by"] == "llm" for item in row["evidence"]
    )
    assert any("缺少可核验证据句" in warning for warning in result["warnings"])


def test_matrix_trend_and_edit(con, project):
    first = seed_ref(
        con,
        project["id"],
        title="2020 年研究",
        abstract="本文采用内容分析法，研究发现平台规则影响创作。",
        year=2020,
    )
    second = seed_ref(
        con,
        project["id"],
        title="2022 年研究",
        abstract="本文采用深度访谈，研究发现粉丝协商身份。",
        year=2022,
    )
    methods.extract(con, project["id"], [first, second], None)

    matrix = methods.matrix(con, project["id"])
    assert len(matrix["rows"]) == 2
    assert matrix["rows"][0]["ref_title"]
    assert matrix["trend"] == [
        {"year": 2020, "count": 1},
        {"year": 2022, "count": 1},
    ]
    assert matrix["method_trend"]
    assert matrix["conflicts"] == []

    row_id = matrix["rows"][0]["id"]
    updated = methods.update_row(con, row_id, {"method": "混合方法"})
    assert updated["method"] == "混合方法"
    assert methods.matrix(con, project["id"])["rows"][0]["method"] == "混合方法"


def test_conflict_detection(con, project):
    first = seed_ref(
        con,
        project["id"],
        title="研究一",
        abstract="本文访谈了 10 位粉丝。研究发现平台强化了圈层边界。",
        authors=("张三",),
        year=2021,
    )
    second = seed_ref(
        con,
        project["id"],
        title="研究二",
        abstract="本文访谈了 10 位粉丝。研究发现平台削弱了圈层边界。",
        authors=("张三",),
        year=2023,
    )
    methods.extract(con, project["id"], [first, second], None)

    matrix = methods.matrix(con, project["id"])
    assert matrix["conflicts"]
    conflict = matrix["conflicts"][0]
    assert set(conflict["ref_ids"]) == {first, second}
    assert len(conflict["findings"]) == 2


def test_methods_api(client, con, project):
    ref_id = seed_ref(
        con,
        project["id"],
        title="平台文化研究",
        abstract="本文采用深度访谈，访谈了 8 位用户。",
    )
    response = client.post(
        "/api/methods/extract",
        json={"project_id": project["id"], "ref_ids": [ref_id]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extracted"] == 1
    assert body["rows"][0]["ref_id"] == ref_id

    matrix = client.get("/api/methods/matrix", params={"project_id": project["id"]})
    assert matrix.status_code == 200
    row_id = matrix.json()["rows"][0]["id"]

    patched = client.patch(f"/api/methods/rows/{row_id}", json={"finding": "人工修订结论"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["finding"] == "人工修订结论"

    rejected = client.patch(f"/api/methods/rows/{row_id}", json={"unknown": "x"})
    assert rejected.status_code == 422


@respx.mock
def test_openalex_year_counts():
    respx.get(url__startswith=methods.OPENALEX_WORKS).mock(
        return_value=httpx.Response(
            200,
            json={
                "group_by": [
                    {"key": "2024", "count": 7},
                    {"key": "2022", "count": 3},
                    {"key": "1990", "count": 1},
                ]
            },
        )
    )
    with httpx.Client() as http_client:
        counts = methods.openalex_year_counts("粉丝文化", client=http_client, years=10)
    assert counts == [{"year": 2022, "count": 3}, {"year": 2024, "count": 7}]


@respx.mock
def test_matrix_api_external_trend(client, con, project):
    seed_ref(con, project["id"], title="粉丝文化研究", abstract="内容分析。", year=2024)
    respx.get(url__startswith=methods.OPENALEX_WORKS).mock(
        return_value=httpx.Response(200, json={"group_by": [{"key": "2024", "count": 9}]})
    )
    response = client.get(
        "/api/methods/matrix", params={"project_id": project["id"], "external": "true"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["openalex_trend"] == [{"year": 2024, "count": 9}]
    assert body["trend"] == [{"year": 2024, "count": 1}]
