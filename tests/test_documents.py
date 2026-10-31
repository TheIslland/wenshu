from __future__ import annotations


def test_save_and_conflict(client, document):
    doc_id = document["id"]
    first = client.put(
        f"/api/documents/{doc_id}",
        json={"content_md": "## 一、导论\n\n第一段。", "version": document["version"]},
    )
    assert first.status_code == 200
    saved = first.json()
    assert saved["version"] == document["version"] + 1
    assert saved["word_count"] > 0

    stale = client.put(
        f"/api/documents/{doc_id}",
        json={"content_md": "另一个窗口", "version": document["version"]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"


def test_snapshot_and_restore(client, document):
    doc_id = document["id"]
    client.put(
        f"/api/documents/{doc_id}",
        json={"content_md": "原始内容", "version": document["version"]},
    )
    snap = client.post(f"/api/documents/{doc_id}/snapshots", json={"reason": "before edit"}).json()
    assert snap["id"]

    current = client.get(f"/api/documents/{doc_id}").json()
    client.put(
        f"/api/documents/{doc_id}",
        json={"content_md": "改坏了", "version": current["version"]},
    )
    restored = client.post(f"/api/documents/{doc_id}/restore/{snap['id']}").json()
    assert restored["content_md"] == "原始内容"


def test_outline(client, document):
    doc_id = document["id"]
    client.put(
        f"/api/documents/{doc_id}",
        json={
            "content_md": "# 摘要\n\n正文\n\n## 一、导论\n\n### （一）背景\n",
            "version": document["version"],
        },
    )
    outline = client.get(f"/api/documents/{doc_id}/outline").json()
    assert [item["level"] for item in outline] == [1, 2, 3]
    assert outline[1]["title"] == "一、导论"


def test_rename_document(client, document):
    response = client.patch(
        f"/api/documents/{document['id']}", json={"title": "改名后的稿子"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "改名后的稿子"
    assert response.json()["version"] == document["version"]
    assert client.get(f"/api/documents/{document['id']}").json()["title"] == "改名后的稿子"



def test_delete_document(client, document):
    response = client.delete(f"/api/documents/{document['id']}")
    assert response.json()["ok"] is True
    assert client.get(f"/api/documents/{document['id']}").status_code == 404
