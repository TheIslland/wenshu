from __future__ import annotations


def test_health_is_public(anon_client):
    response = anon_client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "wenshu"
    assert data["demo"] is True
    assert data["fts_tokenizer"] in {"trigram", "unicode61", None}


def test_health_counts(client, project):
    data = client.get("/api/health").json()
    assert data["counts"]["projects"] == 1
    assert data["counts"]["documents"] == 1
