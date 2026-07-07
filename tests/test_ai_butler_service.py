"""W-AIBUTLER-001 — AI管家 LLM 解析服务测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_butler_service import (
    FORBIDDEN_CONFIG_KEYS,
    _AiButlerWorker,
    _build_context,
    _build_system_prompt,
    _extract_json,
    _normalize_tool_calls,
    _parse_butler_response,
    _stream_llm,
    _try_local_intent,
    _validate_update_config_changes,
    chat,
)
from app.web_api.ai_butler import register_ai_butler_route
from tests.fakes import FakeConfig


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


def test_system_prompt_contains_valid_json_example():
    config = FakeConfig({"danmu_speed": "5"})
    prompt = _build_system_prompt(config)
    assert "{{" not in prompt
    assert '"name":"update_config"' in prompt
    assert "danmu_speed: 5" in prompt


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_fence_multiline():
    raw = "```json\n{\"reply\": \"hi\", \"tool_calls\": []}\n```"
    assert _extract_json(raw) == {"reply": "hi", "tool_calls": []}


def test_try_local_intent_danmu_speed_faster():
    config = FakeConfig({"danmu_speed": "4"})
    result = _try_local_intent("把弹幕速度调快", config)
    assert result is not None
    assert result["tool_calls"]
    assert result["tool_calls"][0]["changes"][0]["key"] == "danmu_speed"
    assert float(result["tool_calls"][0]["changes"][0]["value"]) > 4


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_invalid_json_uses_local_intent(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = "not json at all"
    config = FakeConfig({"danmu_speed": "4", "default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "把弹幕速度调快"}])
    assert result["ok"] is True
    assert result["tool_calls"]
    assert result["tool_calls"][0]["changes"][0]["key"] == "danmu_speed"


def test_extract_json_with_leading_noise():
    raw = '好的，这是结果：\n{"reply": "ok", "tool_calls": []}\n后续说明'
    obj = _extract_json(raw)
    assert obj is not None
    assert obj["reply"] == "ok"


def test_extract_json_empty_returns_none():
    assert _extract_json("") is None
    assert _extract_json("   ") is None


def test_extract_json_invalid_returns_none():
    assert _extract_json("not json at all") is None
    assert _extract_json("{broken") is None


# ---------------------------------------------------------------------------
# _validate_update_config_changes
# ---------------------------------------------------------------------------


def test_validate_changes_accepts_whitelisted_key():
    changes = [{"key": "danmu_speed", "value": "8", "label": "弹幕速度 5→8"}]
    valid, rejected = _validate_update_config_changes(changes)
    assert len(valid) == 1
    assert valid[0]["key"] == "danmu_speed"
    assert valid[0]["value"] == "8"
    assert rejected == []


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "api_key",
        "mic_api_key",
        "use_thinking",
        "persona_model_bindings",
        "region_x",
        "region_y",
        "region_w",
        "region_h",
        "default_model_id",
    ],
)
def test_validate_changes_rejects_forbidden_keys(forbidden_key):
    changes = [{"key": forbidden_key, "value": "x", "label": ""}]
    valid, rejected = _validate_update_config_changes(changes)
    assert valid == []
    assert len(rejected) == 1
    assert forbidden_key in rejected[0]


def test_validate_changes_rejects_non_whitelisted_key():
    changes = [{"key": "nonexistent_key", "value": "x", "label": ""}]
    valid, rejected = _validate_update_config_changes(changes)
    assert valid == []
    assert "nonexistent_key" in rejected[0]


def test_validate_changes_rejects_missing_value():
    changes = [{"key": "danmu_speed", "label": "x"}]
    valid, rejected = _validate_update_config_changes(changes)
    assert valid == []
    assert "danmu_speed" in rejected[0]


def test_validate_changes_partial_batch():
    changes = [
        {"key": "danmu_speed", "value": "8", "label": ""},
        {"key": "api_key", "value": "sk-xxx", "label": ""},
    ]
    valid, rejected = _validate_update_config_changes(changes)
    assert len(valid) == 1
    assert valid[0]["key"] == "danmu_speed"
    assert len(rejected) == 1


# ---------------------------------------------------------------------------
# _normalize_tool_calls
# ---------------------------------------------------------------------------


def test_normalize_update_config_always_requires_confirm():
    calls = [{
        "name": "update_config",
        "changes": [{"key": "danmu_speed", "value": "8", "label": ""}],
        "require_confirm": False,
    }]
    out, rejected = _normalize_tool_calls(calls)
    assert len(out) == 1
    assert out[0]["name"] == "update_config"
    assert out[0]["require_confirm"] is True
    assert rejected == []


def test_normalize_update_config_label_uses_config_current_value():
    config = FakeConfig({"danmu_lines": "10"})
    calls = [{
        "name": "update_config",
        "changes": [{"key": "danmu_lines", "value": "20", "label": "弹幕行数: 12 → 20"}],
    }]
    out, _ = _normalize_tool_calls(calls, config)
    assert out[0]["changes"][0]["label"] == "弹幕行数: 10 → 20"


def test_normalize_font_size_requires_confirm():
    calls = [{
        "name": "update_config",
        "changes": [{"key": "font_size", "value": "18", "label": "字体 24→18"}],
    }]
    out, _ = _normalize_tool_calls(calls)
    assert out[0]["require_confirm"] is True


def test_normalize_set_console_theme():
    calls = [{
        "name": "set_console_theme",
        "theme": "light",
        "label": "切换浅色",
    }]
    out, rejected = _normalize_tool_calls(calls)
    assert len(out) == 1
    assert out[0]["name"] == "set_console_theme"
    assert out[0]["theme"] == "light"
    assert out[0]["require_confirm"] is True
    assert rejected == []


def test_normalize_set_console_theme_label_from_config():
    config = FakeConfig({"console_theme": "dark"})
    calls = [{"name": "set_console_theme", "theme": "light"}]
    out, _ = _normalize_tool_calls(calls, config)
    assert out[0]["label"] == "控制台主题: 深色 → 浅色"


def test_normalize_set_console_theme_normalizes_invalid():
    calls = [{"name": "set_console_theme", "theme": "sepia"}]
    out, _ = _normalize_tool_calls(calls)
    assert out[0]["theme"] == "dark"


def test_normalize_set_console_theme_light_passthrough():
    calls = [{"name": "set_console_theme", "theme": "light"}]
    out, _ = _normalize_tool_calls(calls)
    assert out[0]["theme"] == "light"


def test_validate_changes_rejects_theme_key():
    changes = [{"key": "theme", "value": "light", "label": ""}]
    valid, rejected = _validate_update_config_changes(changes)
    assert valid == []
    assert "theme" in rejected[0]


def test_normalize_update_config_confirm_level_inferred():
    """api_mode 等敏感项恒为确认级。"""
    calls = [{
        "name": "update_config",
        "changes": [{"key": "api_mode", "value": "openai", "label": ""}],
        "require_confirm": False,
    }]
    out, _ = _normalize_tool_calls(calls)
    assert out[0]["require_confirm"] is True


def test_normalize_set_default_model():
    calls = [{
        "name": "set_default_model",
        "index": 1,
        "model_id": "mimo-v2.5",
        "label": "切到 mimo",
    }]
    out, rejected = _normalize_tool_calls(calls)
    assert len(out) == 1
    assert out[0]["index"] == 1
    assert out[0]["require_confirm"] is True
    assert rejected == []


def test_normalize_set_default_model_invalid_index():
    calls = [{"name": "set_default_model", "index": -1, "label": ""}]
    out, rejected = _normalize_tool_calls(calls)
    assert out == []
    assert len(rejected) == 1


def test_normalize_unknown_tool_rejected():
    calls = [{"name": "delete_model", "id": "x"}]
    out, rejected = _normalize_tool_calls(calls)
    assert out == []
    assert "delete_model" in rejected[0]


def test_normalize_update_config_missing_changes():
    calls = [{"name": "update_config", "require_confirm": False}]
    out, rejected = _normalize_tool_calls(calls)
    assert out == []
    assert len(rejected) == 1


# ---------------------------------------------------------------------------
# _parse_butler_response
# ---------------------------------------------------------------------------


def test_parse_valid_response_with_tool_calls():
    raw = '{"reply": "好的，我来调快弹幕速度", "tool_calls": [{"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"5→8"}],"require_confirm":false}]}'
    result = _parse_butler_response(raw)
    assert result["reply"] == "好的，我来调快弹幕速度"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "update_config"


def test_parse_valid_response_no_tool_calls():
    raw = '{"reply": "请在设置页修改 API Key", "tool_calls": []}'
    result = _parse_butler_response(raw)
    assert result["reply"] == "请在设置页修改 API Key"
    assert result["tool_calls"] == []


def test_parse_invalid_json_degrades():
    result = _parse_butler_response("not json")
    assert "换个说法" in result["reply"]
    assert result["tool_calls"] == []


def test_parse_missing_reply_defaults():
    raw = '{"tool_calls": []}'
    result = _parse_butler_response(raw)
    assert result["reply"] == "好的。"
    assert result["tool_calls"] == []


def test_parse_rejected_items_appended_to_reply():
    raw = '{"reply": "ok", "tool_calls": [{"name":"update_config","changes":[{"key":"api_key","value":"x","label":""}]}]}'
    result = _parse_butler_response(raw)
    assert "api_key" in result["reply"]
    assert result["tool_calls"] == []


# ---------------------------------------------------------------------------
# _build_context
# ---------------------------------------------------------------------------


def test_build_context_uses_defaults_when_value_missing():
    config = FakeConfig({})
    ctx = _build_context(config)
    assert "danmu_lines: 20" in ctx


def test_build_context_includes_config_values():
    config = FakeConfig({
        "api_mode": "openai",
        "danmu_speed": "5",
        "screen_index": "0",
        "font_size": "24",
    })
    ctx = _build_context(config)
    assert "api_mode: openai" in ctx
    assert "danmu_speed: 5" in ctx
    assert "font_size: 24" in ctx
    assert "console_theme" in ctx
    assert "default_model_id" in ctx


def test_build_context_does_not_leak_api_key():
    config = FakeConfig({
        "_api_key": "sk-secret-xxx",
        "api_mode": "openai",
    })
    ctx = _build_context(config)
    assert "sk-secret-xxx" not in ctx
    assert "api_key" not in ctx.lower().replace("api_mode", "").replace("mic_api_key", "") or "sk-secret" not in ctx


def test_build_context_lists_custom_models_with_index():
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    config.set_custom_models([
        {"default_model_id": "doubao-seed", "name": "豆包", "mode": "doubao", "apiKey": "sk-a"},
        {"default_model_id": "mimo-v2.5", "name": "小米", "mode": "openai", "apiKey": "sk-b"},
    ])
    ctx = _build_context(config)
    assert "index=0" in ctx
    assert "index=1" in ctx
    assert "当前使用" in ctx
    assert "sk-a" not in ctx
    assert "sk-b" not in ctx


def test_build_context_empty_models():
    config = FakeConfig({})
    ctx = _build_context(config)
    assert "无模型档案" in ctx


# ---------------------------------------------------------------------------
# chat() 主入口
# ---------------------------------------------------------------------------


def _cred_tuple():
    return ("https://api.test.com/v1", "sk-xxx", "mimo-v2.5", "openai")


@patch("app.application.ai_butler_service.stream_openai")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_stream_llm_openai_path_injects_thinking_disabled(mock_cred, mock_stream):
    mock_cred.return_value = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "sk-xxx",
        "qwen-plus",
        "openai",
    )
    mock_stream.return_value = ('{"reply": "ok", "tool_calls": []}', 0, 0)
    worker = _AiButlerWorker(FakeConfig({"default_model_id": "qwen-plus"}))
    _stream_llm(worker, "sys", [{"role": "user", "content": "hi"}])
    data = mock_stream.call_args[0][4]
    assert data.get("enable_thinking") is False
    assert "thinking" not in data


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_returns_parsed_tool_calls(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = (
        '{"reply": "好的", "tool_calls": [{"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"5→8"}],"require_confirm":false}]}'
    )
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "把弹幕速度调快"}])
    assert result["ok"] is True
    assert result["reply"] == "好的"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["changes"][0]["key"] == "danmu_speed"


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_invalid_json_degrades(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = "not json at all"
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "随便说点啥"}])
    assert result["ok"] is True
    assert "换个说法" in result["reply"]
    assert result["tool_calls"] == []


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_timeout_returns_error(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.side_effect = httpx.TimeoutException("timed out")
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "hi"}])
    assert result["ok"] is False
    assert result["error"] == "timeout"


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_http_error_returns_error(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    response = httpx.Response(status_code=401, request=httpx.Request("POST", "https://x"))
    mock_stream.side_effect = httpx.HTTPStatusError("err", request=response.request, response=response)
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "hi"}])
    assert result["ok"] is False
    assert result["error"] == "http_401"


def test_chat_missing_credentials_returns_error():
    with patch("app.application.ai_butler_service.resolve_request_credentials", return_value=None):
        config = FakeConfig({})
        result = chat(config, [{"role": "user", "content": "hi"}])
    assert result["ok"] is False
    assert "error" in result


def test_chat_empty_messages_returns_error():
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [])
    assert result["ok"] is False
    assert result["error"] == "empty_messages"


def test_chat_none_config_returns_error():
    result = chat(None, [{"role": "user", "content": "hi"}])
    assert result["ok"] is False
    assert result["error"] == "model_not_configured"


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_rejects_api_key_in_tool_calls(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = (
        '{"reply": "好的", "tool_calls": [{"name":"update_config","changes":[{"key":"api_key","value":"sk-xxx","label":""}],"require_confirm":true}]}'
    )
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "改 API Key"}])
    assert result["ok"] is True
    assert result["tool_calls"] == []
    assert "api_key" in result["reply"]


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_multi_tool_calls(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = (
        '{"reply": "好的，我来同时调速度和透明度", "tool_calls": ['
        '{"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":""},{"key":"opacity","value":"90","label":""}],"require_confirm":false}'
        ']}'
    )
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "调快弹幕并提高透明度"}])
    assert result["ok"] is True
    assert len(result["tool_calls"]) == 1
    assert len(result["tool_calls"][0]["changes"]) == 2


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_truncates_long_history(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = '{"reply": "ok", "tool_calls": []}'
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    long_messages = [{"role": "user", "content": f"msg {i}"} for i in range(100)]
    result = chat(config, long_messages)
    assert result["ok"] is True
    # _sanitize_messages 内部裁剪，_stream_llm 收到的 messages ≤ 40
    args = mock_stream.call_args
    worker, system_pt, messages = args[0][0], args[0][1], args[0][2]
    assert len(messages) <= 40


# ---------------------------------------------------------------------------
# 路由测试
# ---------------------------------------------------------------------------


def _build_app():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig({"default_model_id": "mimo-v2.5"})
    return app, bridge


def test_route_chat_requires_messages():
    app, bridge = _build_app()
    register_ai_butler_route(app, bridge, lambda _auth: None)
    client = TestClient(app)
    res = client.post("/api/ai-butler/chat", json={"messages": []})
    assert res.status_code == 400


def test_route_chat_returns_butler_response():
    app, bridge = _build_app()
    with patch("app.web_api.ai_butler.butler_chat", return_value={
        "ok": True,
        "reply": "好的",
        "tool_calls": [{"name": "update_config", "changes": [], "require_confirm": False}],
    }):
        register_ai_butler_route(app, bridge, lambda _auth: None)
        client = TestClient(app)
        res = client.post(
            "/api/ai-butler/chat",
            json={"messages": [{"role": "user", "content": "把弹幕速度调快"}]},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["reply"] == "好的"


def test_route_chat_passes_model_id_field():
    """model_id 字段被接受（W-001 暂忽略，但字段不能报错）。"""
    app, bridge = _build_app()
    with patch("app.web_api.ai_butler.butler_chat", return_value={
        "ok": True, "reply": "hi", "tool_calls": []
    }):
        register_ai_butler_route(app, bridge, lambda _auth: None)
        client = TestClient(app)
        res = client.post(
            "/api/ai-butler/chat",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "model_id": "mimo-v2.5",
            },
        )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# FORBIDDEN_CONFIG_KEYS 完整性
# ---------------------------------------------------------------------------


def test_forbidden_keys_cover_sensitive_fields():
    for key in ("api_key", "mic_api_key", "use_thinking", "region_x", "region_y"):
        assert key in FORBIDDEN_CONFIG_KEYS
