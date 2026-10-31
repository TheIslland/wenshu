"""Cross-module integration: demo data through analysis, direction and export."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wenshu.app import create_app
from wenshu.config import RuntimeConfig
from wenshu.demo import DEMO_PROJECT, seed_demo

TOKEN = "integration-token"


@pytest.fixture()
def demo(tmp_path):
    cfg = RuntimeConfig(data_dir=tmp_path, token=TOKEN, demo=True)
    app = create_app(cfg)
    assert seed_demo(app.state.db) is True
    with TestClient(app) as client:
        client.headers.update({"X-Wenshu-Token": TOKEN})
        yield client


def test_health_and_project(demo):
    health = demo.get("/api/health").json()
    assert health["demo"] is True
    assert health["counts"]["projects"] == 1
    projects = demo.get("/api/projects").json()
    assert projects[0]["name"] == DEMO_PROJECT["name"]


def test_style_analysis_on_document(demo):
    report = demo.post("/api/style/analyze", json={"document_id": 1}).json()
    assert report["score"] > 0
    assert report["level"] in {"low", "medium", "high"}
    assert report["findings"]
    assert "ai_probability" not in report
    for finding in report["findings"]:
        assert finding["rule_id"]
        assert finding["start"] <= finding["end"]
        assert finding["text"]


def test_safe_fix_removes_boilerplate(demo):
    text = (
        "首先，短视频提供了可见性。其次，它重塑了关系。"
        "最后，它影响了生产。综上所述，意义重大。"
    )
    result = demo.post("/api/style/fix", json={"text": text}).json()
    assert result["applied"]
    assert "首先" not in result["revised"]
    assert "综上所述" not in result["revised"]


def test_direction_falls_back_to_project_library(demo):
    result = demo.post(
        "/api/direction/explore",
        json={"topic": DEMO_PROJECT["name"], "project_id": 1},
    ).json()
    assert result["stats"]["total"] >= 5
    assert 3 <= len(result["cards"]) <= 5
    assert any("已改用项目全部" in warning for warning in result["warnings"])


def test_workflow_gate_blocks_unverified_citations(demo):
    gate = demo.get("/api/workflow/gate?project_id=1").json()
    assert gate["ok"] is False
    assert any(blocker["type"] == "citation" for blocker in gate["blockers"])


def test_export_markdown_and_docx(demo):
    markdown = demo.post("/api/export/markdown", json={"project_id": 1})
    assert markdown.status_code == 200
    assert "论文初稿" in markdown.text
    assert "参考文献" in markdown.text

    docx = demo.post("/api/export/docx", json={"project_id": 1})
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"


def test_citation_format_gbt(demo):
    response = demo.get("/api/citations/format?project_id=1&style=gbt7714").json()
    assert response["text"]
    assert "[1]" in response["text"]
    assert response["warnings"] == []
