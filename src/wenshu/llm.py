"""OpenAI-compatible LLM client, settings, and a deterministic fake for tests/demo."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import RuntimeConfig
from .errors import LLMError, LLMNotConfigured, UpstreamError

T = TypeVar("T", bound=BaseModel)

PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "moonshot": {
        "label": "Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "ollama": {
        "label": "Ollama 本地",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
    },
    "custom": {"label": "自定义", "base_url": "", "model": ""},
}

SETTING_KEYS = ("llm.provider", "llm.base_url", "llm.model", "llm.api_key")


@dataclass(slots=True)
class LLMSettings:
    provider: str = "deepseek"
    base_url: str = PRESETS["deepseek"]["base_url"]
    model: str = PRESETS["deepseek"]["model"]
    api_key: str = ""
    timeout_s: int = 90

    @property
    def configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.base_url)
        return bool(self.api_key and self.base_url and self.model)

    @property
    def key_hint(self) -> str:
        if not self.api_key:
            return ""
        return "…" + self.api_key[-4:] if len(self.api_key) > 4 else "已设置"


def _env(name: str) -> str | None:
    import os

    value = os.environ.get(name)
    return value if value else None


def load_settings(con: sqlite3.Connection | None = None) -> LLMSettings:
    values: dict[str, str] = {}
    if con is not None:
        try:
            for row in con.execute("SELECT key, value FROM settings"):
                values[row["key"]] = row["value"]
        except sqlite3.OperationalError:
            pass

    provider = _env("WENSHU_LLM_PROVIDER") or values.get("llm.provider") or "deepseek"
    preset = PRESETS.get(provider, PRESETS["custom"])
    base_url = _env("WENSHU_LLM_BASE_URL") or values.get("llm.base_url") or preset["base_url"]
    model = _env("WENSHU_LLM_MODEL") or values.get("llm.model") or preset["model"]
    api_key = _env("WENSHU_LLM_API_KEY") or values.get("llm.api_key") or ""
    return LLMSettings(
        provider=provider,
        base_url=base_url.strip(),
        model=model.strip(),
        api_key=api_key.strip(),
    )


def save_settings(
    con: sqlite3.Connection,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    clear_key: bool = False,
) -> LLMSettings:
    updates: dict[str, str] = {}
    if provider is not None:
        updates["llm.provider"] = provider
        preset = PRESETS.get(provider)
        if preset:
            if base_url is None:
                updates["llm.base_url"] = preset["base_url"]
            if model is None:
                updates["llm.model"] = preset["model"]
    if base_url is not None:
        updates["llm.base_url"] = base_url.strip()
    if model is not None:
        updates["llm.model"] = model.strip()
    if clear_key:
        updates["llm.api_key"] = ""
    elif api_key is not None and api_key.strip():
        updates["llm.api_key"] = api_key.strip()
    for key, value in updates.items():
        con.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    con.commit()
    return load_settings(con)


def public_settings(con: sqlite3.Connection | None) -> dict[str, Any]:
    settings = load_settings(con)
    mailto = ""
    s2_key = ""
    if con is not None:
        rows = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings")}
        mailto = rows.get("search.mailto", "")
        s2_key = rows.get("search.s2_api_key", "")
    return {
        "llm": {
            "provider": settings.provider,
            "base_url": settings.base_url,
            "model": settings.model,
            "configured": settings.configured,
            "has_key": bool(settings.api_key),
            "key_hint": settings.key_hint,
        },
        "search": {
            "mailto": mailto,
            "has_s2_key": bool(s2_key),
        },
        "presets": PRESETS,
    }


def save_search_settings(
    con: sqlite3.Connection, *, mailto: str | None = None, s2_api_key: str | None = None
) -> None:
    if mailto is not None:
        con.execute(
            "INSERT INTO settings(key, value) VALUES('search.mailto', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (mailto.strip(),),
        )
    if s2_api_key is not None and s2_api_key.strip():
        con.execute(
            "INSERT INTO settings(key, value) VALUES('search.s2_api_key', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (s2_api_key.strip(),),
        )
    con.commit()


class LLMClient:
    def __init__(self, settings: LLMSettings):
        self.settings = settings
        self.last_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}

    @property
    def provider(self) -> str:
        return self.settings.provider

    @property
    def model(self) -> str:
        return self.settings.model

    def _endpoint(self) -> str:
        base = self.settings.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 2000,
        temperature: float = 0.3,
    ) -> str:
        if not self.settings.configured:
            raise LLMNotConfigured("还没有配置 LLM。请到设置页填写 API key，或使用演示模式。")
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        started = time.monotonic()
        try:
            with httpx.Client(timeout=self.settings.timeout_s) as client:
                response = client.post(self._endpoint(), json=payload, headers=headers)
                if response.status_code == 400 and json_mode:
                    payload.pop("response_format", None)
                    response = client.post(self._endpoint(), json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise LLMError(f"连不上 LLM 服务：{exc}") from exc
        if response.status_code >= 400:
            snippet = response.text[:400]
            raise UpstreamError(
                f"LLM 返回 {response.status_code}",
                detail=snippet,
                code="llm_upstream_error",
            )
        try:
            data = response.json()
            message = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise UpstreamError("LLM 响应格式不符合 OpenAI 兼容协议", detail=response.text[:400]) from exc
        if isinstance(message, list):
            message = "".join(part.get("text", "") for part in message if isinstance(part, dict))
        usage = data.get("usage") or {}
        self.last_usage = {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "ms": int((time.monotonic() - started) * 1000),
        }
        return str(message)

    def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        *,
        retries: int = 1,
        max_tokens: int = 2500,
    ) -> T:
        attempt = 0
        current = list(messages)
        last_error: Exception | None = None
        while attempt <= retries:
            raw = self.chat(current, json_mode=True, max_tokens=max_tokens)
            try:
                return schema.model_validate_json(extract_json(raw))
            except (ValidationError, ValueError) as exc:
                last_error = exc
                current = list(messages) + [
                    {"role": "assistant", "content": raw[:4000]},
                    {
                        "role": "user",
                        "content": "上面的 JSON 不合法。只输出符合约定的 JSON 对象，不要解释、不要 Markdown 代码块。",
                    },
                ]
                attempt += 1
        raise LLMError("LLM 没有返回合法 JSON，已回退到规则结果。", detail=str(last_error))


class FakeLLM:
    """Deterministic stand-in. `responses` maps a substring of the prompt to raw text."""

    provider = "fake"
    model = "fake"
    last_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def __init__(self, responses: dict[str, str] | None = None):
        self.responses = responses or {}

    def chat(self, messages: list[dict[str, str]], **_: Any) -> str:
        prompt = "\n".join(str(m.get("content", "")) for m in messages)
        for needle, response in self.responses.items():
            if needle in prompt:
                return response
        return "{}"

    def chat_json(
        self,
        messages: list[dict[str, str]],
        schema: type[T],
        *,
        retries: int = 1,
        max_tokens: int = 2500,
    ) -> T:
        raw = self.chat(messages)
        try:
            return schema.model_validate_json(extract_json(raw))
        except (ValidationError, ValueError) as exc:
            raise LLMError("演示模式没有为这个任务准备结果。", detail=str(exc)) from exc


def build_llm(con: sqlite3.Connection | None, cfg: RuntimeConfig) -> LLMClient | FakeLLM | None:
    if cfg.demo:
        return demo_llm()
    settings = load_settings(con)
    if not settings.configured:
        return None
    return LLMClient(settings)


def demo_llm() -> FakeLLM:
    """Responses used by `--demo`. New tasks can be added here without touching services."""

    return FakeLLM(
        {
            "TASK:STYLE_REWRITE": json.dumps(
                {
                    "revised": "",
                    "ops": [],
                    "gaps": [],
                    "warnings": ["演示模式：请配置 LLM 以获得真实改写。"],
                },
                ensure_ascii=False,
            ),
            "TASK:POLISH": json.dumps(
                {
                    "revised": "",
                    "ops": [],
                    "gaps": [],
                    "warnings": ["演示模式：请配置 LLM 以获得真实润色。"],
                },
                ensure_ascii=False,
            ),
            "TASK:PARAGRAPH": json.dumps(
                {
                    "revised": "",
                    "ops": [],
                    "gaps": [],
                    "warnings": ["演示模式：请配置 LLM 以获得真实调段。"],
                },
                ensure_ascii=False,
            ),
            "TASK:METHOD": json.dumps({"rows": [], "skipped": [], "warnings": ["演示模式"]}),
            "TASK:DIRECTION": json.dumps({"cards": [], "warnings": ["演示模式"]}),
        }
    )


_JSON_START = re.compile(r"[\[{]")


def extract_json(raw: str) -> str:
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = _JSON_START.search(text)
    if not start:
        raise ValueError("no JSON object found")
    opening = text[start.start()]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start.start(), len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return text[start.start() : index + 1]
    raise ValueError("unbalanced JSON")


def log_ai_call(
    con: sqlite3.Connection,
    *,
    task: str,
    llm: Any,
    project_id: int | None = None,
    ok: bool = True,
    error: str = "",
) -> None:
    usage = getattr(llm, "last_usage", {}) or {}
    try:
        con.execute(
            "INSERT INTO ai_logs(project_id, task, provider, model, ms, prompt_tokens, "
            "completion_tokens, ok, error, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                project_id,
                task,
                getattr(llm, "provider", ""),
                getattr(llm, "model", ""),
                int(usage.get("ms") or 0),
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
                1 if ok else 0,
                error[:500],
                __import__("wenshu.models", fromlist=["now_iso"]).now_iso(),
            ),
        )
        con.commit()
    except sqlite3.Error:
        pass


def load_prompt(name: str) -> str:
    from pathlib import Path

    path = Path(__file__).parent / "prompts" / name
    return path.read_text(encoding="utf-8")
