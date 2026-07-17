"""W-AIBUTLER-CHAT-ONLY-001 — AI管家纯对话服务测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ai_butler_service import (
    _AiButlerWorker,
    _build_context,
    _build_system_prompt,
    _extract_json,
    _parse_butler_response,
    _stream_llm,
    chat,
)
from app.web_api.ai_butler import register_ai_butler_route
from tests.fakes import FakeConfig


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


def test_system_prompt_is_chat_only_no_tools():
    config = FakeConfig({"danmu_speed": "5"})
    prompt = _build_system_prompt(config)
    assert "AI管家" in prompt or "对话助手" in prompt
    assert "update_config" not in prompt
    assert "set_default_model" not in prompt
    assert "set_console_theme" not in prompt
    assert "tool_calls" not in prompt
    assert "danmu_speed: 5" in prompt
    assert "禁止" in prompt or "不能" in prompt


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_markdown_fence_multiline():
    raw = "```json\n{\"reply\": \"hi\", \"tool_calls\": []}\n```"
    assert _extract_json(raw) == {"reply": "hi", "tool_calls": []}


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
# _parse_butler_response（纯对话）
# ---------------------------------------------------------------------------


def test_parse_plain_text_reply():
    result = _parse_butler_response("弹幕速度可以在弹幕设置里改哦")
    assert result["reply"] == "弹幕速度可以在弹幕设置里改哦"
    assert result["tool_calls"] == []


def test_parse_legacy_json_extracts_reply_drops_tools():
    raw = (
        '{"reply": "好的，我来调快弹幕速度", "tool_calls": '
        '[{"name":"update_config","changes":[{"key":"danmu_speed","value":"8","label":"5→8"}],'
        '"require_confirm":false}]}'
    )
    result = _parse_butler_response(raw)
    assert result["reply"] == "好的，我来调快弹幕速度"
    assert result["tool_calls"] == []


def test_parse_legacy_json_empty_tool_calls():
    raw = '{"reply": "请在设置页修改 API Key", "tool_calls": []}'
    result = _parse_butler_response(raw)
    assert result["reply"] == "请在设置页修改 API Key"
    assert result["tool_calls"] == []


def test_parse_empty_degrades():
    result = _parse_butler_response("")
    assert "换个说法" in result["reply"] or "catch" in result["reply"].lower()
    assert result["tool_calls"] == []


def test_parse_legacy_json_missing_reply_degrades():
    raw = '{"tool_calls": [{"name":"update_config","changes":[]}]}'
    result = _parse_butler_response(raw)
    assert result["tool_calls"] == []
    assert result["reply"]


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
    mock_stream.return_value = ("你好，我是 AI 管家", 0, 0)
    worker = _AiButlerWorker(FakeConfig({"default_model_id": "qwen-plus"}))
    _stream_llm(worker, "sys", [{"role": "user", "content": "hi"}])
    data = mock_stream.call_args[0][4]
    assert data.get("enable_thinking") is False
    assert "thinking" not in data
    assert data.get("response_format") is None


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_returns_plain_reply_empty_tool_calls(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = "弹幕速度请到弹幕设置页调整，我无法代改。"
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "把弹幕速度调快"}])
    assert result["ok"] is True
    assert "弹幕" in result["reply"]
    assert result["tool_calls"] == []


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_legacy_json_tools_stripped(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = (
        '{"reply": "好的", "tool_calls": [{"name":"update_config","changes":'
        '[{"key":"danmu_speed","value":"8","label":"5→8"}],"require_confirm":false}]}'
    )
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "把弹幕速度调快"}])
    assert result["ok"] is True
    assert result["reply"] == "好的"
    assert result["tool_calls"] == []


@patch("app.application.ai_butler_service._stream_llm")
@patch("app.application.ai_butler_service.resolve_request_credentials")
def test_chat_plain_non_json_is_reply(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = "not json at all, just a friendly reply"
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    result = chat(config, [{"role": "user", "content": "随便说点啥"}])
    assert result["ok"] is True
    assert result["reply"] == "not json at all, just a friendly reply"
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
def test_chat_truncates_long_history(mock_cred, mock_stream):
    mock_cred.return_value = _cred_tuple()
    mock_stream.return_value = "ok"
    config = FakeConfig({"default_model_id": "mimo-v2.5"})
    long_messages = [{"role": "user", "content": f"msg {i}"} for i in range(100)]
    result = chat(config, long_messages)
    assert result["ok"] is True
    args = mock_stream.call_args
    messages = args[0][2]
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
        "reply": "好的，请问还有什么想了解的？",
        "tool_calls": [],
    }):
        register_ai_butler_route(app, bridge, lambda _auth: None)
        client = TestClient(app)
        res = client.post(
            "/api/ai-butler/chat",
            json={"messages": [{"role": "user", "content": "你好"}]},
        )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["reply"]
    assert body["tool_calls"] == []


def test_route_chat_passes_model_id_field():
    """model_id 字段被接受（服务层暂忽略，但字段不能报错）。"""
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
