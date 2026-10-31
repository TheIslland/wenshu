"""Health and capability probe."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import VERSION, RuntimeConfig
from ..db import Database

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    cfg: RuntimeConfig = request.app.state.cfg
    db: Database = request.app.state.db
    con = db.connect()
    try:
        counts = {
            "projects": con.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            "documents": con.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "refs": con.execute("SELECT COUNT(*) FROM refs").fetchone()[0],
        }
        from ..llm import load_settings

        llm = load_settings(con)
    finally:
        con.close()
    return {
        "app": "wenshu",
        "version": VERSION,
        "demo": cfg.demo,
        "data_dir": str(cfg.data_dir),
        "llm_configured": bool(cfg.demo or llm.configured),
        "llm_provider": "demo" if cfg.demo else llm.provider,
        "llm_model": "demo" if cfg.demo else llm.model,
        "fts_tokenizer": db.fts_tokenizer,
        "counts": counts,
    }
