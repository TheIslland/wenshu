from __future__ import annotations

import json

import pytest

from wenshu.errors import ValidationFailed
from wenshu.services import workflow

NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture()
def con(app):
    connection = app.state.db.connect()
    yield connection
    connection.close()


def seed_ref(con, project_id: int) -> int:
    cur = con.execute(
        "INSERT INTO refs(title, authors, year, venue, type, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("待核文献", json.dumps(["张三"], ensure_ascii=False), 2020, "期刊", "journal-article", NOW, NOW),
    )
    ref_id = int(cur.lastrowid or 0)
    con.execute(
        "INSERT INTO project_refs(project_id, ref_id, added_at) VALUES(?,?,?)",
        (project_id, ref_id, NOW),
    )
    con.commit()
    return ref_id


def add_style_run(con, project_id: int, level: str, score: float = 80) -> int:
    cur = con.execute(
        "INSERT INTO style_runs(project_id, document_id, text_hash, score, level, findings, "
        "baseline, provider, model, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (project_id, None, "hash", score, level, "[]", "{}", "", "", NOW),
    )
    con.commit()
    return int(cur.lastrowid or 0)


def add_rewrite(con, project_id: int, gaps: list[str]) -> int:
    cur = con.execute(
        "INSERT INTO rewrites(project_id, document_id, mode, source_text, result_text, ops, gaps, "
        "provider, model, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            project_id,
            None,
            "expand",
            "原文",
            "改写",
            "[]",
            json.dumps(gaps, ensure_ascii=False),
            "",
            "",
            "proposed",
            NOW,
        ),
    )
    con.commit()
    return int(cur.lastrowid or 0)


def test_apply_template_creates_dated_tasks(con, project):
    tasks = workflow.apply_template(con, project["id"], "proposal", start_date="2026-11-01")
    assert len(tasks) == 6
    assert tasks[0].due == "2026-11-01"
    assert tasks[1].due == "2026-11-04"
    assert all(task.status == "todo" for task in tasks)
    assert [task.sort for task in tasks] == sorted(task.sort for task in tasks)

    again = workflow.apply_template(con, project["id"], "开题", start_date="2026-11-01")
    assert again == []
    assert len(workflow.list_tasks(con, project["id"])) == 6


def test_apply_template_unknown(con, project):
    with pytest.raises(ValidationFailed):
        workflow.apply_template(con, project["id"], "unknown-template")


def test_task_crud(con, project):
    task = workflow.create_task(
        con, project["id"], "写引言", stage="写作", due="2026-11-20", notes="先写问题"
    )
    assert task.id and task.status == "todo"
    assert task.due == "2026-11-20"

    updated = workflow.update_task(con, task.id, {"status": "doing", "notes": "进行中"})
    assert updated.status == "doing"
    assert updated.notes == "进行中"

    with pytest.raises(ValidationFailed):
        workflow.update_task(con, task.id, {"status": "flying"})

    deleted = workflow.delete_task(con, task.id)
    assert deleted["ok"] is True
    assert workflow.list_tasks(con, project["id"]) == []


def test_gate_citation_style_and_gaps(con, project):
    ref_id = seed_ref(con, project["id"])
    gate = workflow.gate(con, project["id"])
    assert gate["ok"] is False
    assert gate["counts"]["unverified"] == 1
    assert gate["blockers"][0]["type"] == "citation"
    assert gate["blockers"][0]["status"] == "unchecked"

    con.execute(
        "INSERT INTO citation_checks(ref_id, status, detail, checked_at) VALUES(?,?,?,?)",
        (ref_id, "verified", "{}", NOW),
    )
    con.commit()
    assert workflow.gate(con, project["id"])["ok"] is True

    add_style_run(con, project["id"], "high")
    gate = workflow.gate(con, project["id"])
    assert gate["ok"] is False
    assert gate["counts"]["high_risk"] == 1
    assert any(item["type"] == "style" for item in gate["blockers"])

    add_style_run(con, project["id"], "low", score=10)
    assert workflow.gate(con, project["id"])["ok"] is True

    add_rewrite(con, project["id"], ["缺少 2024 年后的平台材料"])
    gate = workflow.gate(con, project["id"])
    assert gate["ok"] is False
    assert gate["counts"]["open_gaps"] == 1
    assert any(item["type"] == "gap" for item in gate["blockers"])


def test_weekly_report(con, project):
    done = workflow.create_task(con, project["id"], "完成文献综述")
    workflow.update_task(con, done.id, {"status": "done"})
    workflow.create_task(con, project["id"], "下周写方法", due="2026-11-05")

    report = workflow.weekly_report(con, project["id"])["markdown"]
    assert "本周完成" in report
    assert "完成文献综述" in report
    assert "下周计划" in report
    assert "下周写方法" in report
    assert "未解决门禁" in report


def test_workflow_api(client, project):
    template = client.post(
        "/api/workflow/template",
        json={"project_id": project["id"], "template": "paper", "start_date": "2026-11-01"},
    )
    assert template.status_code == 200, template.text
    assert len(template.json()) == 6

    tasks = client.get("/api/tasks", params={"project_id": project["id"]})
    assert tasks.status_code == 200
    assert len(tasks.json()) == 6
    task_id = tasks.json()[0]["id"]

    patched = client.patch(f"/api/tasks/{task_id}", json={"status": "doing"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "doing"

    created = client.post(
        "/api/tasks",
        json={"project_id": project["id"], "title": "补一条任务", "stage": "写作"},
    )
    assert created.status_code == 200
    new_id = created.json()["id"]

    deleted = client.delete(f"/api/tasks/{new_id}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    gate = client.get("/api/workflow/gate", params={"project_id": project["id"]})
    assert gate.status_code == 200
    assert gate.json()["ok"] is True

    weekly = client.get("/api/workflow/weekly", params={"project_id": project["id"]})
    assert weekly.status_code == 200
    assert "下周计划" in weekly.json()["markdown"]
