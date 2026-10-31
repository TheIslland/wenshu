"""Local settings: LLM provider, API key, search politeness."""

from __future__ import annotations

import sqlite3
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import RuntimeConfig
from ..errors import LLMError
from ..llm import (
    FakeLLM,
    build_llm,
    load_settings,
    public_settings,
    save_search_settings,
    save_settings,
)
from .deps import get_cfg, get_con

router = APIRouter(prefix="/api", tags=["settings"])


class LLMPayload(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    clear_key: bool = False


class SearchPayload(BaseModel):
    mailto: str | None = None
    s2_api_key: str | None = None


class SettingsPayload(BaseModel):
    llm: LLMPayload | None = None
    search: SearchPayload | None = None


@router.get("/settings")
def read_settings(
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    data = public_settings(con)
    data["data_dir"] = str(cfg.data_dir)
    data["demo"] = cfg.demo
    return data


@router.put("/settings")
def write_settings(
    payload: SettingsPayload,
    con: sqlite3.Connection = Depends(get_con),
) -> dict:
    if payload.llm is not None:
        save_settings(
            con,
            provider=payload.llm.provider,
            base_url=payload.llm.base_url,
            model=payload.llm.model,
            api_key=payload.llm.api_key,
            clear_key=payload.llm.clear_key,
        )
    if payload.search is not None:
        save_search_settings(
            con, mailto=payload.search.mailto, s2_api_key=payload.search.s2_api_key
        )
    return public_settings(con)


@router.post("/settings/test-llm")
def test_llm(
    con: sqlite3.Connection = Depends(get_con),
    cfg: RuntimeConfig = Depends(get_cfg),
) -> dict:
    llm = build_llm(con, cfg) or FakeLLM()
    started = time.monotonic()
    try:
        text = llm.chat(
            [
                {"role": "system", "content": "只回复两个字：可用"},
                {"role": "user", "content": "连接测试"},
            ],
            max_tokens=8,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        raise LLMError(f"连接失败：{exc}") from exc
    return {
        "ok": True,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "model": load_settings(con).model,
        "reply": text[:50],
    }
