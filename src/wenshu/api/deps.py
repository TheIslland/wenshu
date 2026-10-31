"""Shared FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request

from ..config import RuntimeConfig
from ..db import Database


def get_con(request: Request) -> Iterator[sqlite3.Connection]:
    db: Database = request.app.state.db
    con = db.connect()
    try:
        yield con
    finally:
        con.close()


def get_cfg(request: Request) -> RuntimeConfig:
    return request.app.state.cfg


def get_db(request: Request) -> Database:
    return request.app.state.db
