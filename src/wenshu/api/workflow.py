"""Research workflow API: tasks, templates, gate and weekly report."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..services import workflow as service
from .deps import get_con

router = APIRouter(prefix="/api", tags=["workflow"])


class TaskCreate(BaseModel):
    project_id: int
    title: str
    stage: str = "todo"
    status: str = "todo"
    due: str | None = None
    notes: str = ""
    sort: int | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    stage: str | None = None
    status: str | None = None
    due: str | None = None
    notes: str | None = None
    sort: int | None = None


class TemplatePayload(BaseModel):
    project_id: int
    template: str = "proposal"
    start_date: str | None = None


@router.get("/tasks")
def list_tasks(
    project_id: int,
    status: str | None = None,
    stage: str | None = None,
    con: sqlite3.Connection = Depends(get_con),
) -> list[dict]:
    tasks = service.list_tasks(con, project_id, status=status, stage=stage)
    return [task.model_dump() for task in tasks]


@router.post("/tasks")
def create_task(payload: TaskCreate, con: sqlite3.Connection = Depends(get_con)) -> dict:
    task = service.create_task(
        con,
        payload.project_id,
        payload.title,
        stage=payload.stage,
        status=payload.status,
        due=payload.due,
        notes=payload.notes,
        sort=payload.sort,
    )
    return task.model_dump()


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int, payload: TaskPatch, con: sqlite3.Connection = Depends(get_con)
) -> dict:
    task = service.update_task(con, task_id, payload.model_dump(exclude_unset=True))
    return task.model_dump()


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, con: sqlite3.Connection = Depends(get_con)) -> dict:
    return service.delete_task(con, task_id)


@router.post("/workflow/template")
def apply_template(
    payload: TemplatePayload, con: sqlite3.Connection = Depends(get_con)
) -> list[dict]:
    tasks = service.apply_template(
        con, payload.project_id, payload.template, start_date=payload.start_date
    )
    return [task.model_dump() for task in tasks]


@router.get("/workflow/gate")
def gate(project_id: int, con: sqlite3.Connection = Depends(get_con)) -> dict:
    return service.gate(con, project_id)


@router.get("/workflow/weekly")
def weekly(project_id: int, con: sqlite3.Connection = Depends(get_con)) -> dict:
    return service.weekly_report(con, project_id)
