"""AI 管家：patch 白名单、解析兜底与路由。"""

from unittest.mock import MagicMock, patch

import pytest
from app.config_store import ConfigStore
from app.web_api import ai_butler
from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def config_with_api(workspace_tmp):
    config = ConfigStore(db_path=workspace_tmp / "butler.db")
    config.set_batch(
        {
            "api_endpoint": "https://api.example.com/v1",
            "api_mode": "openai",
            "model": "test-model",
            "danmu_speed": "2",
            "opacity": "100",
        }
    )
    config.set_api_key("sk-test-key")
    return config


def test_sanitize_patch_discards_forbidden_keys(config_with_api):
    patch, reasons, discarded = ai_butler.sanitize_patch(
        {
            "danmu_speed": "1.5",
            "api_key": "evil",
            "hotkey": "Ctrl+X",
        },
        {"danmu_speed": "调慢弹幕"},
        config_with_api,
    )
    assert "danmu_speed" in patch
    assert patch["danmu_speed"] == "1.5"
    assert "api_key" not in patch
    assert "hotkey" not in patch
    assert "api_key" in discarded
    assert "hotkey" in discarded
    assert reasons.get("danmu_speed") == "调慢弹幕"


def test_sanitize_patch_clamps_opacity(config_with_api):
    patch, _, discarded = ai_butler.sanitize_patch(
        {"opacity": "999"},
        {},
        config_with_api,
    )
    assert patch["opacity"] == "100"
    assert discarded == []


def test_ensure_api_configured_missing_key(config_with_api):
    config_with_api.set_api_key("")
    with pytest.raises(ValueError, match="助手设置"):
        ai_butler.ensure_api_configured(config_with_api)


def test_build_system_prompt_includes_faq(config_with_api):
    prompt = ai_butler.build_system_prompt(config_with_api)
    assert "DeepSeek" in prompt
    assert "视觉" in prompt
    assert "火山方舟" in prompt or "doubao" in prompt
    assert "provider_model_mismatch" in prompt
    assert "test-model" in prompt


def test_build_product_knowledge_lists_presets(config_with_api):
    text = ai_butler.build_product_knowledge(config_with_api)
    assert "硅基流动" in text
    assert "没有 DeepSeek 官方预设" in text or "不含 DeepSeek" in text


def test_parse_faq_style_response():
    raw = '{"reply":"助手设置没有 DeepSeek 预设，需使用视觉模型。","patch":{},"reasons":{},"needs_confirmation":false}'
    result = ai_butler.parse_butler_response(raw)
    assert "DeepSeek" in result.reply
    assert result.patch == {}
    assert result.needs_confirmation is False


def test_parse_butler_response_non_json():
    result = ai_butler.parse_butler_response("这只是普通说明文字。")
    assert "普通说明" in result.reply
    assert result.patch == {}
    assert result.needs_confirmation is False


def test_parse_butler_response_markdown_json_block():
    raw = """说明如下：
```json
{"reply":"好的","patch":{"danmu_speed":"1.2"},"reasons":{"danmu_speed":"更慢"},"needs_confirmation":true}
```"""
    result = ai_butler.parse_butler_response(raw)
    assert result.reply == "好的"
    assert result.patch["danmu_speed"] == "1.2"
    assert result.needs_confirmation is True


def test_chat_does_not_write_config(config_with_api):
    app_mock = MagicMock()
    app_mock.config = config_with_api
    original_batch = config_with_api.set_batch

    with patch.object(config_with_api, "set_batch", wraps=original_batch) as batch_mock:
        with patch(
            "app.web_api.ai_butler._call_provider",
            return_value='{"reply":"已调慢","patch":{"danmu_speed":"1.5"},"reasons":{"danmu_speed":"慢一点"},"needs_confirmation":true}',
        ):
            out = ai_butler.chat(app_mock, "帮我把弹幕调慢一点")
    batch_mock.assert_not_called()
    assert out["patch"]["danmu_speed"] == "1.5"
    assert out["current_values"]["danmu_speed"] == "2"


def test_ai_butler_route_missing_api_key(workspace_tmp):
    fastapi_app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "route_butler.db")
    config.set("model", "m")
    bridge.danmu_app = MagicMock()
    bridge.danmu_app.config = config

    register_web_routes(fastapi_app, bridge, lambda _auth=None: None)
    client = TestClient(fastapi_app)
    res = client.post(
        "/api/ai-butler/chat",
        headers={"Authorization": "Bearer test"},
        json={"message": "你好"},
    )
    assert res.status_code == 400
    assert "助手设置" in res.json()["detail"]


def test_ai_butler_route_mock_chat(workspace_tmp, config_with_api):
    fastapi_app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app = MagicMock()
    bridge.danmu_app.config = config_with_api

    register_web_routes(fastapi_app, bridge, lambda _auth=None: None)
    client = TestClient(fastapi_app)

    with patch(
        "app.web_api.ai_butler.chat",
        return_value={
            "reply": "可以调慢",
            "patch": {"danmu_speed": "1.2"},
            "reasons": {"danmu_speed": "降低速度"},
            "needs_confirmation": True,
            "current_values": {"danmu_speed": "2"},
            "discarded_fields": [],
        },
    ):
        res = client.post(
            "/api/ai-butler/chat",
            headers={"Authorization": "Bearer test"},
            json={"message": "调慢弹幕", "history": []},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["patch"]["danmu_speed"] == "1.2"
    assert data["needs_confirmation"] is True
