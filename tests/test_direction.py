from __future__ import annotations

import json

import pytest

from wenshu.llm import FakeLLM
from wenshu.services import direction

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture()
def con(app):
    connection = app.state.db.connect()
    yield connection
    connection.close()


def seed_ref(con, project_id, *, title: str, abstract: str = "", year: int = 2022) -> int:
    cur = con.execute(
        "INSERT INTO refs(title, authors, year, venue, type, abstract, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            title,
            json.dumps(["李四"], ensure_ascii=False),
            year,
            "文化研究",
            "journal-article",
            abstract,
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


def test_explore_without_llm_uses_local_evidence(con, project):
    first = seed_ref(
        con,
        project["id"],
        title="粉丝文化中的参与式实践",
        abstract="研究粉丝社群的参与式文化。",
        year=2021,
    )
    second = seed_ref(
        con,
        project["id"],
        title="粉丝文化与平台算法",
        abstract="讨论平台算法对粉丝文化的影响。",
        year=2023,
    )

    result = direction.explore(con, "粉丝文化", llm=None, project_id=project["id"])

    assert 3 <= len(result["cards"]) <= 5
    assert result["stats"]["total"] == 2
    assert result["stats"]["by_year"] == [
        {"year": 2021, "count": 1},
        {"year": 2023, "count": 1},
    ]
    evidence_ids = {item["ref_id"] for item in result["evidence_refs"]}
    assert {first, second} <= evidence_ids
    for card in result["cards"]:
        assert set(card["evidence_refs"]) <= {first, second}
        assert card["evidence_notes"]
        assert "待检索" not in card["question"]
    saved = con.execute(
        "SELECT COUNT(*) FROM direction_cards WHERE project_id=?", (project["id"],)
    ).fetchone()[0]
    assert saved == len(result["cards"])


def test_explore_without_evidence_marks_pending(con, project):
    result = direction.explore(con, "完全没有的冷门主题", llm=None)
    assert 3 <= len(result["cards"]) <= 5
    for card in result["cards"]:
        assert card["evidence_refs"] == []
        assert card["evidence_notes"] == [direction.NO_EVIDENCE]
        assert card["materials"] == direction.NO_EVIDENCE
    assert result["stats"]["total"] == 0
    assert any("待检索" in warning for warning in result["warnings"])


def test_llm_cannot_cite_unknown_reference(con, project):
    ref_id = seed_ref(con, project["id"], title="粉丝文化研究综述")
    llm = FakeLLM(
        {
            "TASK:DIRECTION": json.dumps(
                {
                    "cards": [
                        {
                            "question": "粉丝文化如何被平台机制重塑？",
                            "gap": "既有研究忽略平台机制。",
                            "materials": "访谈材料",
                            "method": "深度访谈",
                            "risk": "样本偏差",
                            "difficulty": "中",
                            "novelty": "中高",
                            "evidence_refs": [ref_id, 99999],
                        }
                    ],
                    "warnings": [],
                },
                ensure_ascii=False,
            )
        }
    )

    result = direction.explore(
        con, "粉丝文化", llm=llm, project_id=project["id"], years=50
    )

    assert result["llm_used"] is True
    assert 3 <= len(result["cards"]) <= 5
    assert result["cards"][0]["evidence_refs"] == [ref_id]
    assert any("99999" in warning for warning in result["warnings"])


def test_direction_api(client, con, project):
    seed_ref(con, project["id"], title="粉丝文化中的参与式实践")
    response = client.post(
        "/api/direction/explore",
        json={"topic": "粉丝文化", "project_id": project["id"], "years": 20},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert 3 <= len(body["cards"]) <= 5
    assert body["stats"]["total"] == 1
    assert body["llm_used"] is True  # demo FakeLLM
    for card in body["cards"]:
        for key in (
            "question",
            "gap",
            "materials",
            "method",
            "risk",
            "difficulty",
            "novelty",
            "evidence_refs",
            "evidence_notes",
        ):
            assert key in card
