"""API tests for /api/style/* (TestClient, demo FakeLLM, no network)."""

from __future__ import annotations

AI_SAMPLE = (
    "首先，值得注意的是，在当代文化研究的语境中，偶像文化的兴起标志着青年亚文化的重要转向。"
    "其次，这种转向深刻地体现了媒介环境与消费逻辑之间的复杂性、多元性和互动性。"
    "再次，粉丝的实践活动呈现出一种结构性的、整体性的文化逻辑。"
    "最后，这种逻辑在平台资本与情感劳动的互动中获得了新的形态。"
    "综上所述，上述分析表明，所谓的“情感劳动”与“平台资本”已经构成一种新的“文化机制”，"
    "这一机制不是审美问题，而是社会结构问题——由此可见，我们应当以整体性的视角对其深入分析，"
    "作出更加系统化的回应。"
)


def test_analyze_returns_style_report(client):
    response = client.post("/api/style/analyze", json={"text": AI_SAMPLE, "use_llm": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["score"] >= 60
    assert body["level"] == "high"
    assert body["findings"]
    assert body["metrics"]
    assert "风格风险" in body["summary"]
    assert "AI 概率" not in response.text
    assert "ai_probability" not in response.text
    assert any("未接入 LLM" in warning for warning in body["warnings"])
    finding = body["findings"][0]
    assert 0 <= finding["start"] < finding["end"] <= len(AI_SAMPLE)
    assert AI_SAMPLE[finding["start"] : finding["end"]] == finding["text"]


def test_analyze_empty_text_is_not_an_error(client):
    response = client.post("/api/style/analyze", json={"text": "", "use_llm": False})
    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 0
    assert body["findings"] == []


def test_analyze_in_demo_mode_labels_semantic_review_as_placeholder(client):
    response = client.post("/api/style/analyze", json={"text": AI_SAMPLE})
    assert response.status_code == 200
    body = response.json()
    assert body["llm_used"] is True
    assert any("演示模式" in warning for warning in body["warnings"])


def test_analyze_can_load_document_text(client, project):
    document = client.post(
        f"/api/projects/{project['id']}/documents",
        json={"title": "风格测试文档", "content_md": AI_SAMPLE},
    ).json()
    response = client.post(
        "/api/style/analyze",
        json={"text": "", "document_id": document["id"], "use_llm": False},
    )
    assert response.status_code == 200
    assert response.json()["findings"]


def test_analyze_missing_document_is_404(client):
    response = client.post(
        "/api/style/analyze", json={"text": "", "document_id": 999999, "use_llm": False}
    )
    assert response.status_code == 404


def test_fix_returns_revised_applied_and_diff(client):
    response = client.post("/api/style/fix", json={"text": AI_SAMPLE})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"revised", "applied", "diff", "warnings"}
    assert body["applied"]
    assert "首先" not in body["revised"]
    assert all(item["op"] in {"equal", "insert", "delete"} for item in body["diff"])
    assert "".join(op["text"] for op in body["diff"] if op["op"] != "delete") == body["revised"]


def test_fix_accepts_findings_from_analyze(client):
    analysis = client.post(
        "/api/style/analyze", json={"text": AI_SAMPLE, "use_llm": False}
    ).json()
    response = client.post(
        "/api/style/fix", json={"text": AI_SAMPLE, "findings": analysis["findings"]}
    )
    assert response.status_code == 200
    assert response.json()["applied"]


def test_fix_rejects_broken_findings(client):
    response = client.post(
        "/api/style/fix", json={"text": "一段文字。", "findings": [{"rule_id": "boilerplate"}]}
    )
    assert response.status_code == 422


def test_rewrite_falls_back_to_safe_fixes_without_llm(client):
    response = client.post(
        "/api/style/rewrite",
        json={"text": AI_SAMPLE, "mode": "academic", "use_llm": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"original", "revised", "diff", "ops", "gaps", "warnings", "mode"}
    assert "首先" not in body["revised"]
    assert body["warnings"]
    assert "没有配置 LLM" in body["warnings"][0]


def test_rewrite_empty_text_is_422(client):
    response = client.post("/api/style/rewrite", json={"text": "  "})
    assert response.status_code == 422
    assert "文本为空" in response.json()["error"]["message"]


def test_rewrite_unknown_mode_is_422(client):
    response = client.post("/api/style/rewrite", json={"text": AI_SAMPLE, "mode": "vibes"})
    assert response.status_code == 422
    assert "改写模式" in response.json()["error"]["message"]


def test_baseline_endpoint(client):
    response = client.post(
        "/api/style/baseline",
        json={"texts": ["第一段本人文本。", "第二段本人文本。", "第三段本人文本。"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["samples"] == 3
    assert body["metrics"]["sentence_cv"]["mean"] >= 0
    assert body["warnings"] == []


def test_baseline_endpoint_needs_texts(client):
    response = client.post("/api/style/baseline", json={"texts": []})
    assert response.status_code == 422
    assert "基线" in response.json()["error"]["message"]


def test_style_endpoints_require_token(anon_client):
    response = anon_client.post("/api/style/analyze", json={"text": "文字。"})
    assert response.status_code == 401


def test_llm_calls_are_written_to_ai_logs(client, app):
    client.post("/api/style/rewrite", json={"text": AI_SAMPLE, "mode": "concise"})
    rows = app.state.db.query("SELECT task, ok FROM ai_logs WHERE task='style_rewrite'")
    assert rows
    assert all(row["ok"] == 1 for row in rows)


def test_rule_only_path_writes_no_ai_log(client, app):
    client.post("/api/style/rewrite", json={"text": AI_SAMPLE, "use_llm": False})
    rows = app.state.db.query("SELECT task FROM ai_logs WHERE task='style_rewrite'")
    assert rows == []
