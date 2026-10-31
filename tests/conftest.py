from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wenshu.app import create_app
from wenshu.config import RuntimeConfig

TOKEN = "test-token"


@pytest.fixture()
def cfg(tmp_path):
    return RuntimeConfig(data_dir=tmp_path, port=8765, token=TOKEN, demo=True)


@pytest.fixture()
def app(cfg):
    return create_app(cfg)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        test_client.headers.update({"X-Wenshu-Token": TOKEN})
        yield test_client


@pytest.fixture()
def anon_client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project(client):
    response = client.post("/api/projects", json={"name": "测试项目", "field": "文化研究"})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def document(client, project):
    response = client.get(f"/api/projects/{project['id']}/documents")
    assert response.status_code == 200
    docs = response.json()
    assert docs
    return docs[0]
