import json
import threading
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
from app.ai_client import (
    DANMU_MIN_OUTPUT_TOKENS,
    DANMU_MIN_OUTPUT_TOKENS_THINKING,
    AiWorker,
    build_openai_vision_user_content,
    format_http_status_error,
    format_openai_http_error,
    is_mimo_endpoint,
    openai_compatible_request_extensions,
    parse_stream_usage,
    resolve_danmu_max_output_tokens,
    sanitize_provider_error_snippet,
)
from app.translations import tr


class FakeConfig:
    def __init__(self, **overrides):
        self._data = {
            "api_endpoint": "https://global.example.com/v1",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
        }
        self._api_key = "sk-global-key"
        self._default_model_id = ""
        self._custom_models = []
        self._data.update(overrides.get("data", {}))
        self._api_key = overrides.get("api_key", self._api_key)
        self._default_model_id = overrides.get("default_model_id", self._default_model_id)
        self._custom_models = overrides.get("custom_models", self._custom_models)

    def get(self, key, default=""):
        return self._data.get(key, default)

    def get_int(self, key, default=0):
        val = self._data.get(key)
        if val is None:
            return default
        return int(val)

    def get_float(self, key, default=0.0):
        return default

    def get_api_key(self):
        return self._api_key

    def get_mic_api_key(self):
        return self._data.get("_mic_api_key", "")

    def get_default_model_id(self):
        return self._default_model_id

    def get_custom_models(self):
        return self._custom_models


def test_parse_stream_usage_openai_fields():
    assert parse_stream_usage({"prompt_tokens": 100, "completion_tokens": 50}) == (100, 50)


def test_parse_stream_usage_dashscope_fields():
    assert parse_stream_usage({"input_tokens": 80, "output_tokens": 20}) == (80, 20)


def test_request_openai_enables_stream_usage_option():
    worker = AiWorker(
        FakeConfig(
            data={
                "api_mode": "openai-compatible",
                "api_endpoint": "https://api.siliconflow.cn/v1",
            }
        )
    )
    captured: dict = {}

    def capture(_http_client, _url, _headers, data, **kwargs):
        captured["data"] = data
        return ("ok", 1, 1)

    with patch.object(worker, "_stream_openai", side_effect=capture):
        with patch.object(worker, "_emit_safe"):
            worker._request_openai("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)

    assert captured["data"]["stream_options"] == {"include_usage": True}
    assert "thinking" not in captured["data"]
    worker.close()


def test_request_openai_includes_thinking_for_mimo():
    worker = AiWorker(
        FakeConfig(
            data={
                "api_mode": "openai-compatible",
                "api_endpoint": "https://api.xiaomimimo.com/v1",
            }
        )
    )
    captured: dict = {}

    def capture(_http_client, _url, _headers, data, **kwargs):
        captured["data"] = data
        return ("ok", 1, 1)

    with patch.object(worker, "_stream_openai", side_effect=capture):
        with patch.object(worker, "_emit_safe"):
            worker._request_openai("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)

    data = captured["data"]
    assert data["thinking"] == {"type": "disabled"}
    # MiMo caps.thinking_param → 更大输出下限（PR #10 与空响应缓解）
    assert data["max_completion_tokens"] == DANMU_MIN_OUTPUT_TOKENS_THINKING
    assert "max_tokens" not in data
    assert "stream_options" not in data
    user_content = data["messages"][1]["content"]
    assert user_content[0]["type"] == "image_url"
    assert user_content[1]["type"] == "text"
    worker.close()


def test_openai_compatible_request_extensions_siliconflow_omits_thinking():
    assert openai_compatible_request_extensions("https://api.siliconflow.cn/v1") == {}


def test_openai_compatible_request_extensions_mimo_includes_max_completion_tokens():
    ext = openai_compatible_request_extensions(
        "https://api.xiaomimimo.com/v1",
        max_tokens=512,
    )
    assert ext["thinking"] == {"type": "disabled"}
    assert ext["max_completion_tokens"] == 512


def test_build_openai_vision_user_content_mimo_image_first():
    parts = build_openai_vision_user_content(
        "https://api.xiaomimimo.com/v1",
        "hello",
        "data:image/jpeg;base64,abc",
    )
    assert parts[0]["type"] == "image_url"
    assert parts[1]["type"] == "text"


def test_build_openai_vision_user_content_other_text_first():
    parts = build_openai_vision_user_content(
        "https://api.siliconflow.cn/v1",
        "hello",
        "data:image/jpeg;base64,abc",
    )
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"


def test_is_mimo_endpoint():
    assert is_mimo_endpoint("https://api.xiaomimimo.com/v1")
    assert not is_mimo_endpoint("https://api.siliconflow.cn/v1")


def test_sanitize_provider_error_snippet_redacts_api_key():
    raw = "x" * 50 + " sk-abc1234567890abcdef1234567890abcdef " + "y" * 300
    snippet = sanitize_provider_error_snippet(raw, max_len=200)
    assert "sk-abc1234567890abcdef1234567890abcdef" not in snippet
    assert "sk-****" in snippet
    assert snippet.endswith("…")


def test_format_http_status_error_uses_truncated_message_instead_of_hidden():
    long_msg = (
        "error detail sk-abc1234567890abcdef1234567890abcdef "
        + ("x" * 300)
    )
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(400, request=request, json={"message": long_msg})
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    text = format_http_status_error(exc)
    assert "HTTP 400" in text
    assert tr("ai.error_http_hidden").format(status_code=400) not in text
    assert "sk-abc1234567890abcdef1234567890abcdef" not in text
    assert "sk-****" in text


def test_format_http_status_error_hidden_when_body_empty():
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(500, request=request, content=b"")
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    assert format_http_status_error(exc) == tr("ai.error_http_hidden").format(status_code=500)


def test_format_openai_http_error_maps_siliconflow_model_missing_code():
    request = httpx.Request("POST", "https://api.siliconflow.cn/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"code": 20012, "message": "Model does not exist. Please check it carefully."},
    )
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    assert format_openai_http_error(exc) == tr("ai.error_model_not_found")


def test_request_routes_ark_endpoint_to_doubao_when_api_mode_openai():
    worker = AiWorker(
        FakeConfig(
            data={
                "api_mode": "openai",
                "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            }
        )
    )
    with patch.object(worker, "_request_doubao") as mock_doubao:
        with patch.object(worker, "_request_openai") as mock_openai:
            worker._request("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
    mock_doubao.assert_called_once()
    mock_openai.assert_not_called()
    worker.close()


def test_stream_openai_ignores_reasoning_content():
    worker = AiWorker(FakeConfig())

    @contextmanager
    def fake_stream(*_args, **_kwargs):
        chunk = {"choices": [{"delta": {"reasoning_content": "内部推理不应作为弹幕"}}]}
        lines = [f"data: {json.dumps(chunk)}", "data: [DONE]"]

        class Resp:
            def raise_for_status(self):
                return None

            def iter_lines(self):
                return iter(lines)

        yield Resp()

    client = MagicMock()
    client.stream.side_effect = fake_stream
    text, in_tok, out_tok = worker._stream_openai(
        client,
        "https://api.xiaomimimo.com/v1/chat/completions",
        {},
        {},
        endpoint="https://api.xiaomimimo.com/v1",
    )
    assert text == ""
    assert in_tok == 0 and out_tok == 0
    worker.close()


def test_stream_openai_logs_mimo_reasoning_only(caplog):
    import logging

    worker = AiWorker(FakeConfig())

    @contextmanager
    def fake_stream(*_args, **_kwargs):
        chunk = {"choices": [{"delta": {"reasoning_content": "only reasoning"}}]}
        lines = [f"data: {json.dumps(chunk)}", "data: [DONE]"]

        class Resp:
            def raise_for_status(self):
                return None

            def iter_lines(self):
                return iter(lines)

        yield Resp()

    client = MagicMock()
    client.stream.side_effect = fake_stream
    with caplog.at_level(logging.WARNING):
        worker._stream_openai(
            client,
            "https://api.xiaomimimo.com/v1/chat/completions",
            {},
            {},
            endpoint="https://api.xiaomimimo.com/v1",
        )
    assert any(
        "只有 reasoning_content 没有 content" in r.message for r in caplog.records
    )
    worker.close()


def test_resolve_danmu_max_output_tokens_applies_floor():
    assert resolve_danmu_max_output_tokens(50) == DANMU_MIN_OUTPUT_TOKENS
    assert resolve_danmu_max_output_tokens(200) == DANMU_MIN_OUTPUT_TOKENS
    assert resolve_danmu_max_output_tokens(800) == 800
    assert resolve_danmu_max_output_tokens(0) == DANMU_MIN_OUTPUT_TOKENS


def test_resolve_danmu_max_output_tokens_thinking_floor():
    assert resolve_danmu_max_output_tokens(200, use_thinking=True) == DANMU_MIN_OUTPUT_TOKENS_THINKING
    assert resolve_danmu_max_output_tokens(1500, use_thinking=True) == 1500


def test_request_doubao_sends_effective_max_output_tokens():
    worker = AiWorker(FakeConfig(data={"max_tokens": "200", "use_thinking": "0"}))
    with patch.object(worker, "_stream_doubao", return_value=("test", 100, 50, "")) as mock_stream:
        with patch.object(worker, "_emit_safe"):
            worker._request_doubao("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
    payload = mock_stream.call_args[0][3]
    assert payload["max_output_tokens"] == DANMU_MIN_OUTPUT_TOKENS
    worker.close()


def test_request_doubao_includes_input_audio_when_provided():
    worker = AiWorker(FakeConfig())
    audio = "data:audio/wav;base64,QUJD"
    with patch.object(worker, "_stream_doubao", return_value=("test", 100, 50, "")) as mock_stream:
        with patch.object(worker, "_emit_safe"):
            worker._request_doubao(
                "data:image/jpeg;base64,abc",
                "sys",
                "user",
                "p1",
                1,
                1,
                1.0,
                0,
                audio_data_uri=audio,
            )
    payload = mock_stream.call_args[0][3]
    content = payload["input"][0]["content"]
    assert any(part.get("type") == "input_audio" and part.get("audio_url") == audio for part in content)
    worker.close()


def test_request_openai_mimo_includes_input_audio_when_provided():
    worker = AiWorker(
        FakeConfig(
            data={
                "api_endpoint": "https://api.xiaomimimo.com/v1",
                "api_mode": "openai-compatible",
                "model": "mimo-v2.5",
            }
        )
    )
    audio = "data:audio/wav;base64,QUJD"
    with patch.object(worker, "_stream_openai", return_value=("test", 100, 50)) as mock_stream:
        with patch.object(worker, "_emit_safe"):
            worker._request_openai(
                "data:image/jpeg;base64,abc",
                "sys",
                "user",
                "p1",
                1,
                1,
                1.0,
                0,
                audio_data_uri=audio,
            )
    payload = mock_stream.call_args[0][3]
    content = payload["messages"][1]["content"]
    assert any(
        part.get("type") == "input_audio" and part.get("input_audio", {}).get("data") == audio
        for part in content
    )
    worker.close()


def test_request_doubao_always_disables_thinking():
    worker = AiWorker(FakeConfig(data={"max_tokens": "200", "use_thinking": "1"}))
    with patch.object(worker, "_stream_doubao", return_value=("test", 100, 50, "")) as mock_stream:
        with patch.object(worker, "_emit_safe"):
            worker._request_doubao("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
    payload = mock_stream.call_args[0][3]
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_output_tokens"] == DANMU_MIN_OUTPUT_TOKENS
    worker.close()


def test_get_http_client_returns_same_instance_per_thread():
    worker = AiWorker(FakeConfig())
    client1 = worker._get_http_client()
    client2 = worker._get_http_client()
    assert client1 is client2
    worker.close()


def test_close_cleans_up_client():
    worker = AiWorker(FakeConfig())
    client = worker._get_http_client()
    assert client is not None
    worker.close()
    assert worker._thread_local.client is None


def test_close_is_safe_when_no_client():
    worker = AiWorker(FakeConfig())
    worker.close()
    assert not hasattr(worker._thread_local, 'client') or worker._thread_local.client is None


def test_request_doubao_uses_thread_local_client():
    worker = AiWorker(FakeConfig())
    with patch.object(worker, '_stream_doubao', return_value=("test", 100, 50, "")) as mock_stream:
        with patch.object(worker, '_emit_safe') as mock_emit:
            worker._request_doubao("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
            mock_stream.assert_called_once()
            http_client = mock_stream.call_args[0][0]
            assert http_client is worker._get_http_client()
    worker.close()


def test_request_openai_uses_thread_local_client():
    worker = AiWorker(FakeConfig())
    with patch.object(worker, '_stream_openai', return_value=("test", 100, 50)) as mock_stream:
        with patch.object(worker, '_emit_safe') as mock_emit:
            worker._request_openai("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
            mock_stream.assert_called_once()
            http_client = mock_stream.call_args[0][0]
            assert http_client is worker._get_http_client()
    worker.close()


def test_request_doubao_rebuilds_client_on_exception():
    worker = AiWorker(FakeConfig())
    first_client = worker._get_http_client()

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("connection broken")
        return ("recovered", 100, 50, "")

    with patch.object(worker, '_stream_doubao', side_effect=side_effect):
        with patch.object(worker, '_emit_safe'):
            worker._request_doubao("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)

    new_client = worker._get_http_client()
    assert new_client is not first_client
    assert call_count == 2
    worker.close()


def test_request_openai_rebuilds_client_on_exception():
    worker = AiWorker(FakeConfig())
    first_client = worker._get_http_client()

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("connection broken")
        return ("recovered", 100, 50)

    with patch.object(worker, '_stream_openai', side_effect=side_effect):
        with patch.object(worker, '_emit_safe'):
            worker._request_openai("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)

    new_client = worker._get_http_client()
    assert new_client is not first_client
    assert call_count == 2
    worker.close()


def test_resolve_credentials_uses_custom_model_without_global_fallback():
    worker = AiWorker(
        FakeConfig(
            default_model_id="deepseek-chat",
            custom_models=[
                {
                    "name": "DeepSeek",
                    "modelId": "deepseek-chat",
                    "endpoint": "https://api.deepseek.com/v1",
                    "apiKey": "sk-custom-only",
                    "mode": "openai-compatible",
                }
            ],
        )
    )
    endpoint, api_key, model_id, api_mode = worker._resolve_request_credentials()
    assert endpoint == "https://api.deepseek.com/v1"
    assert api_key == "sk-custom-only"
    assert model_id == "deepseek-chat"
    assert api_mode == "openai-compatible"
    worker.close()


def test_resolve_credentials_empty_global_endpoint_returns_none():
    worker = AiWorker(
        FakeConfig(
            data={
                "api_endpoint": "",
                "api_mode": "doubao",
                "model": "doubao-seed-1-6-flash-250828",
            },
            api_key="sk-test",
        )
    )
    assert worker._resolve_request_credentials() is None
    worker.close()


def test_resolve_credentials_incomplete_custom_model_returns_none():
    worker = AiWorker(
        FakeConfig(
            default_model_id="partial-model",
            custom_models=[
                {
                    "name": "Partial",
                    "modelId": "partial-model",
                    "endpoint": "",
                    "apiKey": "",
                    "mode": "openai-compatible",
                }
            ],
        )
    )
    assert worker._resolve_request_credentials() is None
    worker.close()


def test_request_openai_emits_incomplete_for_partial_custom_model():
    worker = AiWorker(
        FakeConfig(
            default_model_id="partial-model",
            custom_models=[
                {
                    "name": "Partial",
                    "modelId": "partial-model",
                    "endpoint": "https://api.deepseek.com/v1",
                    "apiKey": "",
                    "mode": "openai-compatible",
                }
            ],
        )
    )
    with patch.object(worker, "_emit_safe") as mock_emit:
        worker._request_openai("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][1]  # non-empty error message
    worker.close()


def test_request_doubao_resolves_credentials_once():
    worker = AiWorker(FakeConfig(data={"api_mode": "doubao"}))
    resolved = ("https://global.example.com/v1", "sk-global-key", "doubao-seed-1-6-flash-250828", "doubao")
    with patch.object(worker, "_resolve_request_credentials", return_value=resolved) as mock_resolve:
        with patch.object(worker, "_request_doubao") as mock_doubao:
            worker._request("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
    mock_resolve.assert_called_once()
    mock_doubao.assert_called_once()
    assert mock_doubao.call_args.kwargs["resolved"] == resolved
    worker.close()


def test_request_openai_resolves_credentials_once():
    worker = AiWorker(FakeConfig(data={"api_mode": "openai"}))
    resolved = ("https://global.example.com/v1", "sk-global-key", "gpt-4o", "openai")
    with patch.object(worker, "_resolve_request_credentials", return_value=resolved) as mock_resolve:
        with patch.object(worker, "_request_openai") as mock_openai:
            worker._request("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
    mock_resolve.assert_called_once()
    mock_openai.assert_called_once()
    assert mock_openai.call_args.kwargs["resolved"] == resolved
    worker.close()


def test_request_with_audio_uses_mic_credentials():
    worker = AiWorker(
        FakeConfig(
            data={
                "api_mode": "doubao",
                "model": "doubao-seed-1-6-flash-250828",
                "mic_use_visual_model": "0",
                "mic_model": "doubao-seed-2-0-mini-260428",
                "mic_api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
                "mic_api_mode": "doubao",
                "_mic_api_key": "sk-mic",
            },
        )
    )
    visual = ("https://ark.cn-beijing.volces.com/api/v3", "sk-visual", "doubao-seed-1-6-flash-250828", "doubao")
    mic = ("https://ark.cn-beijing.volces.com/api/v3", "sk-mic", "doubao-seed-2-0-mini-260428", "doubao")
    with patch.object(worker, "_resolve_request_credentials", return_value=visual) as mock_visual:
        with patch.object(worker, "resolve_mic_request_credentials", return_value=mic) as mock_mic:
            with patch.object(worker, "_request_doubao") as mock_doubao:
                worker._request(
                    "data:image/jpeg;base64,abc",
                    "sys",
                    "user",
                    "p1",
                    1,
                    1,
                    1.0,
                    0,
                    audio_data_uri="data:audio/wav;base64,abc",
                )
    mock_visual.assert_not_called()
    mock_mic.assert_called_once()
    mock_doubao.assert_called_once()
    assert mock_doubao.call_args.kwargs["resolved"] == mic
    worker.close()


def test_request_doubao_direct_call_resolves_when_resolved_none():
    worker = AiWorker(FakeConfig())
    resolved = ("https://global.example.com/v1", "sk-global-key", "doubao-seed-1-6-flash-250828", "doubao")
    with patch.object(worker, "_resolve_request_credentials", return_value=resolved) as mock_resolve:
        with patch.object(worker, "_stream_doubao", return_value=("test", 100, 50, "")):
            with patch.object(worker, "_emit_safe"):
                worker._request_doubao("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
    mock_resolve.assert_called_once()
    worker.close()


def test_request_openai_direct_call_resolves_when_resolved_none():
    worker = AiWorker(FakeConfig(data={"api_mode": "openai"}))
    resolved = ("https://global.example.com/v1", "sk-global-key", "gpt-4o", "openai")
    with patch.object(worker, "_resolve_request_credentials", return_value=resolved) as mock_resolve:
        with patch.object(worker, "_stream_openai", return_value=("test", 100, 50, "")):
            with patch.object(worker, "_emit_safe"):
                worker._request_openai("data:image/jpeg;base64,abc", "sys", "user", "p1", 1, 1, 1.0, 0)
    mock_resolve.assert_called_once()
    worker.close()


def test_different_threads_get_different_clients():
    worker = AiWorker(FakeConfig())
    results = {}

    def get_client(name):
        results[name] = worker._get_http_client()

    t1 = threading.Thread(target=get_client, args=("t1",))
    t2 = threading.Thread(target=get_client, args=("t2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["t1"] is not results["t2"]
    worker.close()
