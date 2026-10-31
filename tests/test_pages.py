from __future__ import annotations


def test_dashboard(client, project):
    response = client.get("/")
    assert response.status_code == 200
    assert "文枢" in response.text
    assert "测试项目" in response.text


def test_settings_page(client):
    response = client.get("/settings")
    assert response.status_code == 200
    assert "语言模型" in response.text


def test_project_page(client, project):
    response = client.get(f"/p/{project['id']}")
    assert response.status_code == 200
    assert "data-project-id" in response.text
    for tab in ("writing", "library", "search", "style", "methods", "workflow"):
        assert f'data-panel="{tab}"' in response.text


def test_missing_project_page(client):
    response = client.get("/p/9999")
    assert response.status_code == 404


def test_static_assets(client):
    for path in ("/static/css/base.css", "/static/js/api.js", "/static/js/workspace.js"):
        assert client.get(path).status_code == 200
