from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from app.api_probe import probe_connection


def test_probe_connection_missing_key():
    result = probe_connection("https://api.deepseek.com/v1", "", "deepseek-chat", "openai-compatible")
    assert result.ok is False
    assert result.status_code is None
    assert result.error_category == "auth_missing"


def test_probe_local_does_not_network():
    with patch("app.api_probe.httpx.Client") as client_cls:
        result = probe_connection("https://api.example.com/v1", "", "gpt-4o", "openai", stage="local")
    assert result.ok is False
    assert result.error_category == "auth_missing"
    client_cls.assert_not_called()
    assert result.stage == "local"
    assert result.message_key == "custom_model.error_api_key"


def test_probe_local_missing_model_does_not_network():
    with patch("app.api_probe.httpx.Client") as client_cls:
        result = probe_connection("https://api.example.com/v1", "sk-test", "", "openai", stage="local")
    assert result.ok is False
    assert result.error_category == "model_not_found"
    client_cls.assert_not_called()


@patch("app.api_probe.discover_models")
@patch("app.api_probe.httpx.Client")
def test_auth_model_uses_controlled_client_and_marks_visible(mock_client_cls, mock_discover):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = client
    mock_discover.return_value = SimpleNamespace(
        discovery_kind="account_discovery",
        models=(SimpleNamespace(id="gpt-4o"),),
    )
    result = probe_connection("https://api.example.com/v1", "sk-test", "gpt-4o", "openai", stage="auth_model")
    assert result.ok is True
    assert result.capability_updates == {"model_visible": True, "vision": None}
    mock_discover.assert_called_once_with("custom_openai", "sk-test", endpoint="https://api.example.com/v1", http_client=client)
    client.__exit__.assert_called_once()


@patch("app.api_probe.discover_models")
@patch("app.api_probe.httpx.Client")
def test_auth_model_marks_invisible_model_without_leaking_credentials(mock_client_cls, mock_discover):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = client
    mock_discover.return_value = SimpleNamespace(
        discovery_kind="account_discovery",
        models=(SimpleNamespace(id="other-model"),),
    )
    result = probe_connection("https://api.example.com/v1", "sk-secret", "gpt-4o", "openai", stage="auth_model")
    assert result.ok is False
    assert result.error_category == "model_not_found"
    assert result.capability_updates == {"model_visible": False, "vision": None}
    assert "sk-secret" not in result.message
    mock_discover.assert_called_once_with("custom_openai", "sk-secret", endpoint="https://api.example.com/v1", http_client=client)


@patch("app.api_probe.discover_models")
@patch("app.api_probe.httpx.Client")
def test_auth_model_maps_discovery_failures_without_warning_leak(mock_client_cls, mock_discover):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = client
    expected = {
        401: "auth_invalid", 403: "permission_denied", 404: "model_not_found",
        402: "quota_exhausted", 429: "rate_limited", 503: "provider_unavailable",
    }
    for status_code, category in expected.items():
        mock_discover.return_value = SimpleNamespace(
            discovery_kind="fallback_http_error",
            models=(SimpleNamespace(id="gpt-4o"),),
            status="fallback_http_error",
            warnings=(f"http_status:{status_code}", "secret-key=do-not-return"),
        )
        result = probe_connection("https://api.example.com/v1", "sk-secret", "gpt-4o", "openai", stage="auth_model")
        assert result.error_category == category
        assert result.status_code == status_code
        assert "do-not-return" not in result.message
    mock_discover.return_value = SimpleNamespace(
        discovery_kind="fallback_request_error",
        models=(),
        status="fallback_request_error",
        warnings=("request_error:ReadTimeout", "secret-body=do-not-return"),
    )
    result = probe_connection("https://api.example.com/v1", "sk-secret", "gpt-4o", "openai", stage="auth_model")
    assert result.error_category == "provider_unavailable"
    assert result.status_code is None
    assert "do-not-return" not in result.message


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_probe_explicit_stages_use_safe_fixtures(mock_client_cls, mock_stream):
    response = MagicMock(status_code=200)
    response.raise_for_status = MagicMock()
    response.headers = {"x-request-id": "safe-request-1"}
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = response
    mock_client_cls.return_value = mock_client
    mock_stream.return_value = SimpleNamespace(text="stream ok", input_tokens=2, output_tokens=1, reasoning_only=False)
    for stage in ("text", "vision", "audio", "stream"):
        result = probe_connection("https://api.example.com/v1", "sk-test", "gpt-4o", "openai", stage=stage)
        assert result.ok is True
        assert result.stage == stage
        if stage == "text":
            assert result.capability_updates == {"text_input": True}
        elif stage == "vision":
            assert result.capability_updates == {"vision": True, "image_input": True}
        elif stage == "audio":
            assert result.capability_updates == {"mic_audio": True, "audio_input": True}
        else:
            assert result.capability_updates["stream"] is True
        if stage != "stream":
            assert result.request_id == "safe-request-1"
    bodies = [call.kwargs["json"] for call in mock_client.post.call_args_list]
    assert all("sk-test" not in repr(body) for body in bodies)


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_stream_probe_projects_usage_and_reasoning_without_network(mock_client_cls, mock_stream):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = client
    mock_stream.return_value = SimpleNamespace(text="", input_tokens=12, output_tokens=3, reasoning_only=True)
    result = probe_connection("https://api.example.com/v1", "sk-test", "gpt-4o", "openai", stage="stream")
    assert result.ok is True
    assert result.capability_updates == {"stream": True, "input_tokens": 12, "output_tokens": 3}
    assert "reasoning_only" in result.warnings
    mock_stream.assert_called_once()


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_stream_probe_classifies_empty_content(mock_client_cls, mock_stream):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = client
    mock_stream.return_value = SimpleNamespace(text="", input_tokens=0, output_tokens=0, reasoning_only=False)
    result = probe_connection("https://api.example.com/v1", "sk-test", "gpt-4o", "openai", stage="stream")
    assert result.ok is False
    assert result.error_category == "empty_output"
    assert "empty_stream_content" in result.warnings


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_stream_parser_error_is_not_empty_output(mock_client_cls, mock_stream):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    mock_client_cls.return_value = client
    mock_stream.return_value = SimpleNamespace(text="", error="provider details must stay private", input_tokens=0, output_tokens=0, reasoning_only=False)
    result = probe_connection("https://api.example.com/v1", "sk-test", "gpt-4o", "openai", stage="stream")
    assert result.error_category == "malformed_stream"
    assert result.capability_updates["stream"] is True
    assert "provider details" not in result.message


@patch("app.api_probe.httpx.Client")
def test_probe_http_categories_and_request_id_are_safe(mock_client_cls):
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(429, request=request, headers={"x-request-id": "r-1"})
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = httpx.HTTPStatusError("secret body", request=request, response=response)
    mock_client_cls.return_value = mock_client
    result = probe_connection("https://api.example.com/v1", "sk-secret", "gpt-4o", "openai")
    assert result.error_category == "rate_limited"
    assert result.status_code == 429
    assert result.request_id == "r-1"
    assert "secret body" not in result.message


@patch("app.api_probe.httpx.Client")
def test_probe_classifies_region_model_error_without_body(mock_client_cls):
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(
        403,
        request=request,
        content=b'{"error":"model is not available in this region","api_key":"do-not-leak"}',
    )
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = httpx.HTTPStatusError("provider body", request=request, response=response)
    mock_client_cls.return_value = mock_client
    result = probe_connection("https://api.example.com/v1", "sk-secret", "gpt-4o", "openai")
    assert result.error_category == "model_not_available_in_region"
    assert "do-not-leak" not in result.message
    assert "provider body" not in result.message


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
