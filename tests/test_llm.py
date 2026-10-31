from __future__ import annotations

import pytest

from wenshu.llm import (
    FakeLLM,
    LLMClient,
    LLMSettings,
    extract_json,
    load_settings,
    public_settings,
    save_settings,
)
from wenshu.models import StyleReport


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_fenced_and_chatty():
    raw = '好的，结果如下：\n```json\n{"a": {"b": "x}y"}}\n```\n完毕'
    assert extract_json(raw) == '{"a": {"b": "x}y"}}'


def test_extract_json_array():
    assert extract_json("说明 [1, 2, {\"a\": 3}] 尾巴") == '[1, 2, {"a": 3}]'


def test_extract_json_rejects_no_json():
    with pytest.raises(ValueError):
        extract_json("没有 JSON")


def test_settings_roundtrip_and_key_hint(app):
    con = app.state.db.connect()
    try:
        saved = save_settings(
            con,
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key="sk-1234567890",
        )
        assert saved.configured is True
        assert saved.key_hint.endswith("7890")
        public = public_settings(con)
        assert public["llm"]["has_key"] is True
        assert "1234567890" not in str(public)
        assert "sk-" not in str(public)
    finally:
        con.close()


def test_env_override(app, monkeypatch):
    con = app.state.db.connect()
    try:
        save_settings(con, provider="deepseek", api_key="db-key")
        monkeypatch.setenv("WENSHU_LLM_API_KEY", "env-key")
        assert load_settings(con).api_key == "env-key"
    finally:
        con.close()


def test_fake_llm_json():
    fake = FakeLLM({"TASK:STYLE": '{"score": 10, "findings": []}'})
    result = fake.chat_json([{"role": "user", "content": "TASK:STYLE ..."}], StyleReport)
    assert result.score == 10
    assert result.level == "low"


def test_client_endpoint_normalisation():
    client = LLMClient(LLMSettings(base_url="https://example.com/v1/", api_key="k"))
    assert client._endpoint() == "https://example.com/v1/chat/completions"
    client = LLMClient(LLMSettings(base_url="https://example.com/v1/chat/completions", api_key="k"))
    assert client._endpoint() == "https://example.com/v1/chat/completions"
