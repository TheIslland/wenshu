from __future__ import annotations


def test_api_requires_token(anon_client):
    response = anon_client.get("/api/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_wrong_token_rejected(anon_client):
    response = anon_client.get("/api/projects", headers={"X-Wenshu-Token": "nope"})
    assert response.status_code == 401


def test_bearer_token_accepted(anon_client):
    response = anon_client.get("/api/projects", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200


def test_cross_origin_write_rejected(client):
    response = client.post(
        "/api/projects",
        json={"name": "evil"},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "bad_origin"


def test_same_origin_write_allowed(client):
    response = client.post(
        "/api/projects",
        json={"name": "ok"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200


def test_bad_host_rejected(anon_client):
    response = anon_client.get(
        "/api/projects",
        headers={"Host": "evil.example", "X-Wenshu-Token": "test-token"},
    )
    assert response.status_code == 403
