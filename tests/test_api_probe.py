from unittest.mock import MagicMock, patch

import httpx
from app.api_probe import probe_connection


def test_probe_connection_missing_key():
    result = probe_connection("https://api.deepseek.com/v1", "", "deepseek-chat", "openai-compatible")
    assert result.ok is False
    assert result.status_code is None


@patch("app.api_probe.httpx.Client")
def test_probe_openai_success(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    result = probe_connection(
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-chat",
        "openai-compatible",
    )
    assert result.ok is True
    assert result.status_code == 200


@patch("app.api_probe.httpx.Client")
def test_probe_openai_auth_failure(mock_client_cls):
    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = httpx.Response(401, request=request)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = httpx.HTTPStatusError("auth", request=request, response=response)
    mock_client_cls.return_value = mock_client

    result = probe_connection(
        "https://api.deepseek.com/v1",
        "bad-key",
        "deepseek-chat",
        "openai",
    )
    assert result.ok is False
    assert result.status_code == 401


@patch("app.api_probe.httpx.Client")
def test_probe_dashscope_request_omits_stream_options(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    result = probe_connection(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "sk-test",
        "qwen3-vl-flash",
        "openai-compatible",
    )
    assert result.ok is True
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload.get("stream") is False
    assert "stream_options" not in payload


@patch("app.api_probe.httpx.Client")
def test_probe_openai_connect_error_user_friendly(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")
    mock_client_cls.return_value = mock_client

    result = probe_connection(
        "https://api.example.com/v1",
        "sk-test",
        "gpt-4o",
        "openai-compatible",
    )
    assert result.ok is False
    assert "Connection refused" not in result.message
    assert "连接" in result.message or "connect" in result.message.lower()


@patch("app.api_probe.httpx.Client")
def test_probe_openai_adds_openrouter_headers(mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    probe_connection(
        "https://openrouter.ai/api/v1",
        "sk-test",
        "openai/gpt-4o",
        "openai-compatible",
    )
    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers.get("HTTP-Referer")
    assert headers.get("X-Title") == "DanmuAI"


@patch("app.api_probe.httpx.Client")
def test_probe_minimax_adds_reasoning_split(mock_client_cls):
    """MiniMax probe request must include reasoning_split: true (W-PR-INTAKE-020)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    probe_connection(
        "https://api.minimax.chat/v1",
        "sk-test",
        "MiniMax-Text-01",
        "openai-compatible",
    )
    payload = mock_client.post.call_args.kwargs["json"]
    assert payload.get("reasoning_split") is True


@patch("app.api_probe.httpx.Client")
def test_probe_non_minimax_omits_reasoning_split(mock_client_cls):
    """Non-MiniMax probe must NOT include reasoning_split (W-PR-INTAKE-020)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value = mock_client

    probe_connection(
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-chat",
        "openai-compatible",
    )
    payload = mock_client.post.call_args.kwargs["json"]
    assert "reasoning_split" not in payload
