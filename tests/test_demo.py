from __future__ import annotations

from fastapi.testclient import TestClient

from wenshu.app import create_app
from wenshu.config import RuntimeConfig
from wenshu.demo import DEMO_REFS, seed_demo


def test_seed_demo_creates_project(tmp_path):
    cfg = RuntimeConfig(data_dir=tmp_path, token="t", demo=True)
    app = create_app(cfg)
    assert seed_demo(app.state.db) is True
    con = app.state.db.connect()
    try:
        assert con.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM refs").fetchone()[0] == len(DEMO_REFS)
        assert con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 5
        assert con.execute("SELECT COUNT(*) FROM method_rows").fetchone()[0] == 3
    finally:
        con.close()
    assert seed_demo(app.state.db) is False


def test_demo_project_visible(tmp_path):
    cfg = RuntimeConfig(data_dir=tmp_path, token="t", demo=True)
    app = create_app(cfg)
    seed_demo(app.state.db)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "县城屏幕" in response.text
        health = client.get("/api/health").json()
        assert health["demo"] is True
        assert health["counts"]["projects"] == 1
