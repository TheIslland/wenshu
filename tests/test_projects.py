from __future__ import annotations


def test_create_project_creates_default_document(client):
    response = client.post("/api/projects", json={"name": "日本偶像", "field": "文化研究"})
    assert response.status_code == 200
    project = response.json()
    assert project["name"] == "日本偶像"
    docs = client.get(f"/api/projects/{project['id']}/documents").json()
    assert len(docs) == 1
    assert docs[0]["title"] == "日本偶像"


def test_project_crud(client):
    project = client.post("/api/projects", json={"name": "A"}).json()
    listed = client.get("/api/projects").json()
    assert any(p["id"] == project["id"] for p in listed)

    patched = client.patch(
        f"/api/projects/{project['id']}",
        json={"question": "符号如何获得身体？", "status": "active"},
    ).json()
    assert patched["question"] == "符号如何获得身体？"

    deleted = client.delete(f"/api/projects/{project['id']}")
    assert deleted.json()["ok"] is True
    assert client.get(f"/api/projects/{project['id']}").status_code == 404


def test_missing_project_404(client):
    response = client.get("/api/projects/9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
