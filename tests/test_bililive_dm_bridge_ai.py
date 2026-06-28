"""W-BILILIVE-DM-PLUGIN-BRIDGE-003 — bililive_dm 旁路真实 AI 生成测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.application import bililive_dm_bridge_service as bridge_service
from app.web_api.bililive_dm_bridge import BililiveDmBridgeRequest


def _fake_config(**values):
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default="": values.get(key, default)
    cfg.get_float.side_effect = lambda key, default=0.0: float(values.get(key, default))
    cfg.get_int.side_effect = lambda key, default=0: int(values.get(key, default))
    cfg.get_default_model_id.return_value = values.get("default_model_id", "")
    cfg.get_api_key.return_value = values.get("api_key", "")
    cfg.get_custom_models.return_value = values.get("custom_models", [])
    return cfg


def test_parse_bridge_text_splits_lines_and_strips_bullets():
    items = bridge_service._parse_bridge_text("谢谢支持\n- 哈哈哈\n• 第二条")
    assert items == ["谢谢支持", "哈哈哈", "第二条"]


def test_parse_bridge_text_truncates_long_line():
    long = "a" * 80
    items = bridge_service._parse_bridge_text(long)
    assert len(items) == 1
    assert len(items[0]) == bridge_service._MAX_ITEM_CHARS
    assert items[0].endswith("…")


def test_parse_bridge_text_caps_at_max_items():
    raw = "\n".join(f"line{i}" for i in range(10))
    items = bridge_service._parse_bridge_text(raw)
    assert len(items) == bridge_service._MAX_ITEMS


def test_generate_ai_replies_empty_text():
    result = bridge_service.generate_ai_replies(_fake_config(), BililiveDmBridgeRequest(text="  "))
    assert result.ok is False
    assert result.error == "empty_text"


def test_generate_ai_replies_config_none():
    result = bridge_service.generate_ai_replies(
        None,
        BililiveDmBridgeRequest(text="hello"),
    )
    assert result.ok is False
    assert result.error == "model_not_configured"


@patch("app.application.bililive_dm_bridge_service.resolve_request_credentials", return_value=None)
def test_generate_ai_replies_missing_credentials(mock_resolve):
    config = _fake_config()
    result = bridge_service.generate_ai_replies(
        config,
        BililiveDmBridgeRequest(text="hello", user_name="alice"),
    )
    assert result.ok is False
    assert result.error
    mock_resolve.assert_called_once()


@patch("app.application.bililive_dm_bridge_service._stream_ai_reply", return_value="")
def test_generate_ai_replies_empty_response(mock_stream):
    config = _fake_config(
        api_endpoint="https://api.example.com/v1",
        api_key="sk-test",
        model="m",
        api_mode="openai",
    )
    with patch(
        "app.application.bililive_dm_bridge_service.resolve_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "m", "openai"),
    ):
        result = bridge_service.generate_ai_replies(
            config,
            BililiveDmBridgeRequest(text="hello"),
        )
    assert result.ok is False
    assert result.error == "empty_response"
    mock_stream.assert_called_once()


@patch("app.application.bililive_dm_bridge_service._parse_bridge_text", return_value=[])
@patch(
    "app.application.bililive_dm_bridge_service._stream_ai_reply",
    return_value="AI said something",
)
def test_generate_ai_replies_empty_after_parse(mock_stream, mock_parse):
    config = _fake_config()
    with patch(
        "app.application.bililive_dm_bridge_service.resolve_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "m", "openai"),
    ):
        result = bridge_service.generate_ai_replies(
            config,
            BililiveDmBridgeRequest(text="hello"),
        )
    assert result.ok is False
    assert result.error == "empty_after_parse"


@patch(
    "app.application.bililive_dm_bridge_service._stream_ai_reply",
    return_value="谢谢\n哈哈",
)
def test_generate_ai_replies_happy_path(mock_stream):
    config = _fake_config()
    with patch(
        "app.application.bililive_dm_bridge_service.resolve_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "m", "openai"),
    ):
        result = bridge_service.generate_ai_replies(
            config,
            BililiveDmBridgeRequest(text="不错", user_name="甲"),
        )
    assert result.ok is True
    assert result.items == ["谢谢", "哈哈"]
    mock_stream.assert_called_once()


@patch(
    "app.application.bililive_dm_bridge_service._stream_ai_reply",
    side_effect=httpx.TimeoutException("timed out"),
)
def test_generate_ai_replies_timeout(mock_stream):
    config = _fake_config()
    with patch(
        "app.application.bililive_dm_bridge_service.resolve_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "m", "openai"),
    ):
        result = bridge_service.generate_ai_replies(
            config,
            BililiveDmBridgeRequest(text="hello"),
        )
    assert result.ok is False
    assert result.error == "timeout"


@patch(
    "app.application.bililive_dm_bridge_service._stream_ai_reply",
    side_effect=httpx.HTTPStatusError(
        "401",
        request=MagicMock(),
        response=MagicMock(status_code=401),
    ),
)
def test_generate_ai_replies_http_error(mock_stream):
    config = _fake_config()
    with patch(
        "app.application.bililive_dm_bridge_service.resolve_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "m", "openai"),
    ):
        result = bridge_service.generate_ai_replies(
            config,
            BililiveDmBridgeRequest(text="hello"),
        )
    assert result.ok is False
    assert result.error == "http_401"


@patch(
    "app.application.bililive_dm_bridge_service._stream_ai_reply",
    side_effect=RuntimeError("unexpected"),
)
def test_generate_ai_replies_internal_error(mock_stream):
    config = _fake_config()
    with patch(
        "app.application.bililive_dm_bridge_service.resolve_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "m", "openai"),
    ):
        result = bridge_service.generate_ai_replies(
            config,
            BililiveDmBridgeRequest(text="hello"),
        )
    assert result.ok is False
    assert result.error == "internal_error:RuntimeError"


def test_make_user_prompt_truncates_long_comment():
    prompt = bridge_service._make_user_prompt(
        BililiveDmBridgeRequest(user_name="bob", text="x" * 300),
    )
    assert "观众 bob 说：" in prompt
    assert len(prompt) <= len("观众 bob 说：") + bridge_service._MAX_USER_TEXT_CHARS


@patch("app.application.bililive_dm_bridge_service.stream_openai", return_value=("line1", 1, 2))
@patch("app.application.bililive_dm_bridge_service.resolve_api_transport", return_value="openai")
def test_stream_ai_reply_openai_path(mock_transport, mock_stream):
    worker = bridge_service._BridgeStreamWorker(_fake_config())
    with patch.object(worker, "_resolve_request_credentials") as mock_cred:
        mock_cred.return_value = ("https://api.example.com/v1", "k", "m", "openai")
        text = bridge_service._stream_ai_reply(worker, "sys", "user")
    assert text == "line1"
    mock_stream.assert_called_once()


@patch("app.application.bililive_dm_bridge_service.stream_doubao", return_value=("dm1", 1, 2, ""))
@patch("app.application.bililive_dm_bridge_service.resolve_api_transport", return_value="doubao")
def test_stream_ai_reply_doubao_path(mock_transport, mock_stream):
    worker = bridge_service._BridgeStreamWorker(_fake_config())
    with patch.object(worker, "_resolve_request_credentials") as mock_cred:
        mock_cred.return_value = ("https://ark.example.com/api/v3", "k", "m", "doubao")
        text = bridge_service._stream_ai_reply(worker, "sys", "user")
    assert text == "dm1"
    mock_stream.assert_called_once()
