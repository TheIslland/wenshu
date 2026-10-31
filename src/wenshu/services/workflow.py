"""Research workflow: templates, task CRUD, export gate and weekly report."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..db import json_load
from ..errors import NotFound, ValidationFailed
from ..models import TaskItem, now_iso

TASK_STATUSES = ("todo", "doing", "done")

TASK_TEMPLATES: dict[str, dict[str, Any]] = {
    "proposal": {
        "label": "开题",
        "tasks": [
            ("选题", "确定研究问题与问题卡", 0, "依赖：研究方向探索；把问题卡拆成可执行任务。"),
            ("文献", "完成文献检索与入库", 3, "检索结果去重后入库，标注阅读状态。"),
            ("文献", "撰写文献综述初稿", 10, "依赖：完成文献检索与入库。"),
            ("方法", "确定研究方法与材料", 14, "方法矩阵可辅助比较；缺材料标「待检索」。"),
            ("写作", "完成开题报告初稿", 21, "按章节组织，逐段挂证据。"),
            ("核引", "核引与格式检查", 25, "依赖：完成开题报告初稿；未核引必须清零。"),
        ],
    },
    "paper": {
        "label": "论文",
        "tasks": [
            ("写作", "搭建章节大纲", 0, "从问题卡与综述地图收束论证线。"),
            ("写作", "完成各章初稿", 14, "先证据后表达，不写没有材料支撑的判断。"),
            ("修订", "全文风格体检与修订", 21, "高风险段落逐段处理，不做整篇一键重写。"),
            ("修订", "段落调整与证据补齐", 25, "压缩/扩写/重排/补论证，gaps 清零。"),
            ("核引", "核引与参考文献整理", 28, "所有 DOI 核验；无 DOI 文献进人工清单。"),
            ("交付", "导出 DOCX 并定稿", 30, "导出前跑门禁，确认未核引清单。"),
        ],
    },
    "submission": {
        "label": "投稿",
        "tasks": [
            ("投稿", "选定目标期刊", 0, "核对期刊范围、字数与引用格式要求。"),
            ("投稿", "按期刊要求调整格式", 3, "参考文献样式、图表编号、匿名化。"),
            ("投稿", "撰写投稿信", 5, "说明贡献、材料与伦理声明。"),
            ("投稿", "提交投稿系统", 6, "保存投稿确认与稿件编号。"),
            ("投稿", "跟踪审稿与返修", 30, "记录审稿意见与逐条回应。"),
        ],
    },
}

TEMPLATE_ALIASES = {
    "开题": "proposal",
    "开题报告": "proposal",
    "proposal": "proposal",
    "research-proposal": "proposal",
    "论文": "paper",
    "论文写作": "paper",
    "paper": "paper",
    "thesis": "paper",
    "投稿": "submission",
    "submission": "submission",
    "submit": "submission",
}


def _task(con: sqlite3.Connection, task_id: int) -> TaskItem:
    row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise NotFound("任务不存在。")
    return TaskItem(**dict(row))


def _project_exists(con: sqlite3.Connection, project_id: int) -> None:
    if not con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise NotFound("项目不存在。")


def list_tasks(
    con: sqlite3.Connection,
    project_id: int,
    *,
    status: str | None = None,
    stage: str | None = None,
) -> list[TaskItem]:
    _project_exists(con, project_id)
    sql = "SELECT * FROM tasks WHERE project_id=?"
    params: list[Any] = [project_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    if stage:
        sql += " AND stage=?"
        params.append(stage)
    sql += " ORDER BY sort, id"
    return [TaskItem(**dict(row)) for row in con.execute(sql, params).fetchall()]


def create_task(
    con: sqlite3.Connection,
    project_id: int,
    title: str,
    *,
    stage: str = "todo",
    status: str = "todo",
    due: str | None = None,
    notes: str = "",
    sort: int | None = None,
) -> TaskItem:
    _project_exists(con, project_id)
    title = (title or "").strip()
    if not title:
        raise ValidationFailed("任务标题不能为空。")
    if status not in TASK_STATUSES:
        raise ValidationFailed(f"任务状态必须是 {', '.join(TASK_STATUSES)}。")
    if sort is None:
        row = con.execute(
            "SELECT COALESCE(MAX(sort), 0) AS top FROM tasks WHERE project_id=?", (project_id,)
        ).fetchone()
        sort = int(row["top"] or 0) + 1
    now = now_iso()
    cur = con.execute(
        "INSERT INTO tasks(project_id, stage, title, status, due, notes, sort, created_at, "
        "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (project_id, stage.strip() or "todo", title, status, due, notes.strip(), sort, now, now),
    )
    con.commit()
    return _task(con, int(cur.lastrowid or 0))


def update_task(con: sqlite3.Connection, task_id: int, changes: dict[str, Any]) -> TaskItem:
    _task(con, task_id)
    allowed = {"title", "stage", "status", "due", "notes", "sort"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationFailed(f"不支持修改字段：{', '.join(sorted(unknown))}")
    fields = [key for key in allowed if key in changes and changes[key] is not None]
    if not fields:
        return _task(con, task_id)
    if "status" in changes and changes["status"] not in TASK_STATUSES:
        raise ValidationFailed(f"任务状态必须是 {', '.join(TASK_STATUSES)}。")
    if "title" in changes and not str(changes["title"]).strip():
        raise ValidationFailed("任务标题不能为空。")
    values: list[Any] = []
    for key in fields:
        value = changes[key]
        if key in {"title", "stage", "notes"}:
            value = str(value).strip()
        elif key == "sort":
            value = int(value)
        values.append(value)
    values.append(now_iso())
    values.append(task_id)
    con.execute(
        f"UPDATE tasks SET {', '.join(f'{key}=?' for key in fields)}, updated_at=? WHERE id=?",
        values,
    )
    con.commit()
    return _task(con, task_id)


def delete_task(con: sqlite3.Connection, task_id: int) -> dict[str, bool]:
    _task(con, task_id)
    con.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    con.commit()
    return {"ok": True}


def _parse_start_date(start_date: str | None) -> date:
    if not start_date:
        return datetime.now(UTC).date()
    try:
        return date.fromisoformat(start_date.strip()[:10])
    except ValueError as exc:
        raise ValidationFailed("start_date 必须是 YYYY-MM-DD 格式。") from exc


def apply_template(
    con: sqlite3.Connection,
    project_id: int,
    template: str = "proposal",
    *,
    start_date: str | None = None,
) -> list[TaskItem]:
    """Create the tasks of a built-in workflow template; existing titles are skipped."""
    _project_exists(con, project_id)
    key = TEMPLATE_ALIASES.get((template or "proposal").strip().lower())
    if key is None:
        raise ValidationFailed(
            f"未知流程模板：{template}", detail={"available": sorted(TASK_TEMPLATES)}
        )
    base = _parse_start_date(start_date)
    existing = {
        str(row["title"]).strip()
        for row in con.execute("SELECT title FROM tasks WHERE project_id=?", (project_id,))
    }
    row = con.execute(
        "SELECT COALESCE(MAX(sort), 0) AS top FROM tasks WHERE project_id=?", (project_id,)
    ).fetchone()
    sort = int(row["top"] or 0) + 1
    now = now_iso()
    created: list[int] = []
    for stage, title, offset, notes in TASK_TEMPLATES[key]["tasks"]:
        if title in existing:
            continue
        due = (base + timedelta(days=int(offset))).isoformat()
        cur = con.execute(
            "INSERT INTO tasks(project_id, stage, title, status, due, notes, sort, created_at, "
            "updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (project_id, stage, title, "todo", due, notes, sort, now, now),
        )
        created.append(int(cur.lastrowid or 0))
        sort += 1
    con.commit()
    return [_task(con, task_id) for task_id in created]


def gate(con: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    """Export gate: unverified citations, high-risk style runs, unresolved gaps."""
    _project_exists(con, project_id)
    blockers: list[dict[str, Any]] = []

    refs = con.execute(
        "SELECT r.id, r.title FROM refs r JOIN project_refs pr ON pr.ref_id=r.id "
        "WHERE pr.project_id=? ORDER BY r.id",
        (project_id,),
    ).fetchall()
    checks = {
        int(row["ref_id"]): str(row["status"])
        for row in con.execute(
            "SELECT c.ref_id, c.status FROM citation_checks c JOIN ("
            "SELECT ref_id, MAX(id) AS mid FROM citation_checks GROUP BY ref_id"
            ") latest ON latest.mid=c.id"
        ).fetchall()
    }
    for ref in refs:
        ref_id = int(ref["id"])
        status = checks.get(ref_id, "unchecked")
        if status == "verified":
            continue
        blockers.append(
            {
                "type": "citation",
                "ref_id": ref_id,
                "title": ref["title"],
                "status": status,
                "message": "文献尚未核验或核验未通过。",
            }
        )

    latest_runs: dict[Any, sqlite3.Row] = {}
    for row in con.execute(
        "SELECT * FROM style_runs WHERE project_id=? ORDER BY id DESC", (project_id,)
    ).fetchall():
        latest_runs.setdefault(row["document_id"], row)
    for document_id, row in latest_runs.items():
        if str(row["level"]) == "high":
            blockers.append(
                {
                    "type": "style",
                    "document_id": document_id,
                    "run_id": int(row["id"]),
                    "score": float(row["score"]),
                    "message": "最近一次风格体检为高风险，尚未见复检记录。",
                }
            )

    for row in con.execute(
        "SELECT * FROM rewrites WHERE project_id=? AND status='proposed' ORDER BY id DESC",
        (project_id,),
    ).fetchall():
        gaps = json_load(row["gaps"], [])
        if gaps:
            blockers.append(
                {
                    "type": "gap",
                    "rewrite_id": int(row["id"]),
                    "document_id": row["document_id"],
                    "gaps": gaps,
                    "message": "还有未解决的证据缺口。",
                }
            )

    counts = {
        "refs": len(refs),
        "unverified": sum(1 for item in blockers if item["type"] == "citation"),
        "high_risk": sum(1 for item in blockers if item["type"] == "style"),
        "open_gaps": sum(1 for item in blockers if item["type"] == "gap"),
    }
    return {
        "ok": not blockers,
        "blockers": blockers,
        "counts": counts,
        "checked_at": now_iso(),
    }


def weekly_report(con: sqlite3.Connection, project_id: int) -> dict[str, Any]:
    """One-click Markdown weekly report: done this week, plan for next week."""
    _project_exists(con, project_id)
    today = datetime.now(UTC).date()
    week_start = today - timedelta(days=today.weekday())
    next_week = week_start + timedelta(days=7)
    horizon = next_week + timedelta(days=6)
    tasks = [TaskItem(**dict(row)) for row in con.execute(
        "SELECT * FROM tasks WHERE project_id=? ORDER BY sort, id", (project_id,)
    ).fetchall()]
    done = [
        task
        for task in tasks
        if task.status == "done" and str(task.updated_at)[:10] >= week_start.isoformat()
    ]
    planned = [
        task
        for task in tasks
        if task.status != "done"
        and (task.due is None or str(task.due)[:10] <= horizon.isoformat())
    ]
    added_refs = con.execute(
        "SELECT COUNT(*) FROM project_refs WHERE project_id=? AND added_at >= ?",
        (project_id, week_start.isoformat()),
    ).fetchone()[0]
    blockers = gate(con, project_id)["blockers"]

    lines = [f"# 本周研究周报（{week_start.isoformat()} 至 {today.isoformat()}）", ""]
    lines.append("## 本周完成")
    if done:
        lines.extend(f"- [{task.stage}] {task.title}" for task in done)
    else:
        lines.append("- 暂无标记为完成的任务。")
    lines.append("")
    lines.append("## 下周计划")
    if planned:
        for task in planned[:10]:
            due = f"，截止 {task.due}" if task.due else ""
            lines.append(f"- [{task.stage}] {task.title}{due}")
    else:
        lines.append("- 暂无待办任务。")
    lines.append("")
    lines.append("## 本周新增文献")
    lines.append(f"- 新增 {int(added_refs)} 篇。")
    lines.append("")
    lines.append("## 未解决门禁")
    if blockers:
        lines.extend(f"- {item['type']}：{item['message']}" for item in blockers)
    else:
        lines.append("- 无，可以导出。")
    return {"markdown": "\n".join(lines) + "\n"}


def gate_summary(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "门禁通过"
    counts: dict[str, int] = {}
    for item in blockers:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    labels = {"citation": "未核引", "style": "高风险段", "gap": "未解决 gaps"}
    return "；".join(f"{labels.get(key, key)} {value} 项" for key, value in counts.items())


def dump_gate(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)
