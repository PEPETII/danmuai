import ipaddress
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from app.api_probe import parse_business_reply_items, probe_connection
from app.providers.request_planner import GenerationRequest, plan_http_request

_PROBE_IMAGE = "data:image/png;base64,probe"


def test_openai_compatible_vision_probe_body_contract():
    planned = plan_http_request(
        GenerationRequest(
            purpose="connection_probe",
            model_id="qwen3-vl-flash",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-test",
            api_mode="openai-compatible",
            user_text="probe text",
            image_data_uri=_PROBE_IMAGE,
            max_output_tokens=1,
            stream=False,
            force_thinking_off=True,
            supports_vision_override=True,
        )
    )

    payload = planned.json_body
    assert planned.api_family == "openai_chat_completions"
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "probe text"},
        {"type": "image_url", "image_url": {"url": _PROBE_IMAGE}},
    ]
    assert payload["max_tokens"] == 1
    assert payload["enable_thinking"] is False


def test_text_probe_body_contract_remains_plain_text():
    planned = plan_http_request(
        GenerationRequest(
            purpose="connection_probe",
            model_id="qwen3-vl-flash",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-test",
            api_mode="openai-compatible",
            user_text="probe text",
            max_output_tokens=1,
            stream=False,
            force_thinking_off=True,
        )
    )

    payload = planned.json_body
    assert payload["messages"][0]["content"] == "probe text"
    assert isinstance(payload["messages"][0]["content"], str)
    assert payload["max_tokens"] == 1
    assert payload["enable_thinking"] is False


def test_mimo_vision_probe_body_contract_keeps_image_before_text():
    planned = plan_http_request(
        GenerationRequest(
            purpose="connection_probe",
            model_id="mimo-v2.5",
            endpoint="https://api.xiaomimimo.com/v1",
            api_key="sk-test",
            api_mode="openai-compatible",
            user_text="probe text",
            image_data_uri=_PROBE_IMAGE,
            max_output_tokens=1,
            stream=False,
            force_thinking_off=True,
            supports_vision_override=True,
        )
    )

    payload = planned.json_body
    assert planned.api_family == "openai_chat_completions"
    assert payload["messages"][0]["content"] == [
        {"type": "image_url", "image_url": {"url": _PROBE_IMAGE}},
        {"type": "text", "text": "probe text"},
    ]
    assert payload["max_completion_tokens"] == 1
    assert payload["thinking"] == {"type": "disabled"}


def test_doubao_responses_vision_probe_body_contract_does_not_fallback():
    planned = plan_http_request(
        GenerationRequest(
            purpose="connection_probe",
            model_id="doubao-seed-1-6-vision-250815",
            endpoint="https://ark.cn-beijing.volces.com/api/v3",
            api_key="sk-test",
            api_mode="doubao",
            user_text="probe text",
            image_data_uri=_PROBE_IMAGE,
            max_output_tokens=1,
            stream=False,
            force_thinking_off=True,
            supports_vision_override=True,
        )
    )

    payload = planned.json_body
    assert planned.api_family == "openai_responses"
    assert "messages" not in payload
    assert payload["input"][0]["content"] == [
        {"type": "input_image", "image_url": _PROBE_IMAGE},
        {"type": "input_text", "text": "probe text"},
    ]
    assert payload["max_output_tokens"] == 1
    assert payload["thinking"] == {"type": "disabled"}


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


# ---------------------------------------------------------------------------
# W-AUDIT-PROBE-SECRET-001：出站目标策略、重定向与日志脱敏
# ---------------------------------------------------------------------------

_VIRTUAL_KEY = "sk-virtual-probe-key-0001"


def test_probe_rejects_private_network_target_without_request():
    with patch("app.api_probe.httpx.Client") as client_cls:
        result = probe_connection(
            "https://192.168.1.10/v1", _VIRTUAL_KEY, "gpt-4o", "openai"
        )
    assert result.ok is False
    assert result.error_category == "outbound_target_blocked"
    assert result.message_key == "custom_model.error_target_blocked"
    client_cls.assert_not_called()


def test_probe_rejects_link_local_and_cloud_metadata_targets():
    for endpoint in (
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/v1",
        "http://[fd00:ec2::254]/v1",
        "http://[fe80::1]/v1",
        "http://10.0.0.5/v1",
        "http://172.16.9.9/v1",
    ):
        with patch("app.api_probe.httpx.Client") as client_cls:
            result = probe_connection(endpoint, _VIRTUAL_KEY, "gpt-4o", "openai")
        assert result.ok is False, endpoint
        assert result.error_category == "outbound_target_blocked", endpoint
        client_cls.assert_not_called()


def test_probe_rejects_hostname_resolving_to_private_address(monkeypatch):
    monkeypatch.setattr(
        "app.api_probe._resolve_probe_host_ips",
        lambda host: [ipaddress.ip_address("10.1.2.3")],
    )
    with patch("app.api_probe.httpx.Client") as client_cls:
        result = probe_connection(
            "https://dns-rebind.example.test/v1", _VIRTUAL_KEY, "gpt-4o", "openai"
        )
    assert result.ok is False
    assert result.error_category == "outbound_target_blocked"
    client_cls.assert_not_called()


def test_probe_allows_explicit_loopback_compat_service():
    """明确保存/输入的 loopback 兼容服务仍有一条可测试的合法路径。"""
    mock_resp = MagicMock(status_code=200)
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    with patch("app.api_probe.httpx.Client") as client_cls:
        client_cls.return_value = mock_client
        result = probe_connection(
            "http://127.0.0.1:8123/v1", _VIRTUAL_KEY, "local-model", "openai"
        )
    assert result.ok is True
    assert client_cls.call_count == 1
    headers = mock_client.post.call_args.kwargs["headers"]
    assert headers.get("Authorization") == f"Bearer {_VIRTUAL_KEY}"


def test_probe_local_stage_skips_outbound_target_policy():
    """local 阶段不发起网络请求，不受出站策略影响（保持既有语义）。"""
    with patch("app.api_probe.httpx.Client") as client_cls:
        result = probe_connection(
            "https://192.168.1.10/v1", _VIRTUAL_KEY, "gpt-4o", "openai", stage="local"
        )
    client_cls.assert_not_called()
    assert result.error_category != "outbound_target_blocked"


def test_probe_disables_redirects_explicitly():
    mock_resp = MagicMock(status_code=200)
    mock_resp.raise_for_status = MagicMock()
    with patch("app.api_probe.httpx.Client") as client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        client_cls.return_value = mock_client
        probe_connection("https://api.example.com/v1", _VIRTUAL_KEY, "gpt-4o", "openai")
    assert client_cls.call_args.kwargs["follow_redirects"] is False


def test_probe_does_not_follow_cross_origin_redirect(monkeypatch):
    """跨 origin 重定向不携带原 Authorization：只发一跳并归类为拒绝。"""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization", "")))
        return httpx.Response(
            302, headers={"Location": "https://evil.example.net/v1/chat/completions"}
        )

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.Client

    def factory(*args, **kwargs):
        assert kwargs.get("follow_redirects") is False
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    result = probe_connection(
        "https://api.example.com/v1", _VIRTUAL_KEY, "gpt-4o", "openai"
    )
    assert result.ok is False
    assert result.error_category == "outbound_redirect_blocked"
    assert len(seen) == 1
    assert seen[0][0].startswith("https://api.example.com/v1")
    assert seen[0][1] == f"Bearer {_VIRTUAL_KEY}"
    assert all("evil.example.net" not in url for url, _ in seen)


def test_probe_result_and_logs_never_expose_key(caplog):
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(401, request=request)
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.side_effect = httpx.HTTPStatusError(
        f"bad key {_VIRTUAL_KEY}", request=request, response=response
    )
    with caplog.at_level("DEBUG"):
        with patch("app.api_probe.httpx.Client") as client_cls:
            client_cls.return_value = mock_client
            result = probe_connection(
                "https://api.example.com/v1", _VIRTUAL_KEY, "gpt-4o", "openai"
            )
    assert result.ok is False
    assert result.error_category == "auth_invalid"
    assert _VIRTUAL_KEY not in json.dumps(result.to_dict(), default=str)
    assert _VIRTUAL_KEY not in caplog.text


# ---------------------------------------------------------------------------
# W-AUDIT-PROBE-PARITY-001：正式视觉流式 + 正式业务解析阶段
# ---------------------------------------------------------------------------

_VISION_KEY = "sk-virtual-vision-key-0001"
_VISION_PROFILE_PARAMS = {"temperature": 0.5, "thinking_effort": "off", "max_tokens": 640}


def test_parse_business_reply_items_reuses_formal_contract():
    """业务解析直接复用正式回复信封/规范化合同，且不注入弹幕池补齐。"""
    assert parse_business_reply_items('{"comments": ["第一条", "第二条"]}') == ["第一条", "第二条"]
    assert parse_business_reply_items('["a", "b"]') == ["a", "b"]
    # 纯占位内容被正式 normalize 过滤 → 空（不能靠池补齐伪造成功）
    assert parse_business_reply_items('{"comments": ["comment 1", ":"]}') == []
    assert parse_business_reply_items("") == []
    assert parse_business_reply_items("[]") == []


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_vision_stream_stage_uses_formal_visual_payload(mock_client_cls, mock_stream):
    """vision_stream 复用正式视觉 payload：图片 + system/user + stream + 档案参数。"""
    mock_stream.return_value = SimpleNamespace(
        text='{"comments": ["ok"]}', input_tokens=3, output_tokens=4,
        reasoning_only=False, error="", stream_completed=True,
    )
    result = probe_connection(
        "https://api.example.com/v1", _VISION_KEY, "gpt-4o", "openai",
        stage="vision_stream", profile_params=dict(_VISION_PROFILE_PARAMS),
    )
    assert result.ok is True
    assert result.stage == "vision_stream"
    assert result.capability_updates["stream"] is True
    assert result.stages[0]["stage"] == "vision_stream"
    args, kwargs = mock_stream.call_args
    body = args[3]
    messages = body["messages"]
    assert messages[0]["role"] == "system" and messages[0]["content"]
    user_parts = messages[-1]["content"]
    assert [part["type"] for part in user_parts] == ["text", "image_url"]
    assert user_parts[1]["image_url"]["url"].startswith("data:image/")
    assert body["stream"] is True
    assert body["temperature"] == 0.5
    assert body.get("max_tokens", body.get("max_completion_tokens")) == 640
    assert kwargs.get("endpoint") == "https://api.example.com/v1/chat/completions"
    assert args[1] == "https://api.example.com/v1/chat/completions"
    assert _VISION_KEY not in json.dumps(body)


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_business_parse_stage_fails_on_filtered_items(mock_client_cls, mock_stream):
    """合法 SSE 但候选全被过滤 → business_parse 失败并分类明确。"""
    mock_stream.return_value = SimpleNamespace(
        text='{"comments": ["comment 1"]}', input_tokens=1, output_tokens=1,
        reasoning_only=False, error="", stream_completed=True,
    )
    result = probe_connection(
        "https://api.example.com/v1", _VISION_KEY, "gpt-4o", "openai",
        stage="business_parse", profile_params=dict(_VISION_PROFILE_PARAMS),
    )
    assert result.ok is False
    assert result.stage == "business_parse"
    assert result.error_category == "empty_output"
    assert "empty_business_items" in result.warnings
    assert result.complete is False
    assert [item["stage"] for item in result.stages] == ["vision_stream", "business_parse"]


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_business_parse_stage_passes_on_legal_stream(mock_client_cls, mock_stream):
    mock_stream.return_value = SimpleNamespace(
        text='{"comments": ["有效弹幕"]}', input_tokens=1, output_tokens=1,
        reasoning_only=False, error="", stream_completed=True,
    )
    result = probe_connection(
        "https://api.example.com/v1", _VISION_KEY, "gpt-4o", "openai",
        stage="business_parse", profile_params=dict(_VISION_PROFILE_PARAMS),
    )
    assert result.ok is True
    assert result.complete is True
    assert [item["status"] for item in result.stages] == ["passed", "passed"]


@patch("app.api_probe.stream_openai_chat")
@patch("app.api_probe.httpx.Client")
def test_reasoning_only_never_reports_vision_stage_failure_but_blocks_business(mock_client_cls, mock_stream):
    """reasoning-only：视觉传输正常（仅 warning），业务解析必须失败。"""
    mock_stream.return_value = SimpleNamespace(
        text="", input_tokens=5, output_tokens=2,
        reasoning_only=True, error="", stream_completed=True,
    )
    result = probe_connection(
        "https://api.example.com/v1", _VISION_KEY, "gpt-4o", "openai",
        stage="business_parse", profile_params=dict(_VISION_PROFILE_PARAMS),
    )
    assert result.ok is False
    assert result.error_category == "empty_output"
    assert result.stages[0]["status"] == "passed"
    assert "reasoning_only" in result.stages[0]["warnings"]
    assert result.stages[1]["stage"] == "business_parse"
