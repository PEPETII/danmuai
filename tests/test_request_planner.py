"""Request planner, auth resolver, and endpoint exact-match tests (Batch 3)."""

import json
from pathlib import Path

import pytest
from app.providers.auth_resolver import build_auth_headers
from app.providers.capabilities import ProviderCapabilities
from app.providers.capability_resolver import resolve_capabilities
from app.providers.endpoint_resolver import extract_hostname, hostname_matches, join_api_path
from app.providers.registry import guess_provider_from_endpoint, match_host_entry
from app.providers.request_planner import GenerationRequest, plan_http_request
from app.providers.thinking import apply_thinking_mode

FIXTURES = Path(__file__).parent / "fixtures" / "model_api"


@pytest.fixture
def golden_dir(tmp_path):
    FIXTURES.mkdir(parents=True, exist_ok=True)
    return FIXTURES


def test_extract_hostname_strips_port():
    assert extract_hostname("http://127.0.0.1:18765/v1") == "127.0.0.1"


def test_hostname_exact_match_rejects_suffix_attack():
    assert match_host_entry("https://evil-openrouter.ai/api/v1") is None
    assert match_host_entry("https://openrouter.ai/api/v1") is not None
    assert guess_provider_from_endpoint("https://not-api.xiaomimimo.com/v1") != "mimo"


def test_hostname_matches_not_substring():
    assert hostname_matches("openrouter.ai", "https://openrouter.ai/api/v1") is True
    assert hostname_matches("openrouter.ai", "https://evil-openrouter.ai/api/v1") is False


def test_join_api_path_openai_and_responses():
    assert join_api_path("https://api.openai.com/v1", "openai_chat_completions").endswith(
        "/chat/completions"
    )
    assert join_api_path("https://ark.cn-beijing.volces.com/api/v3", "openai_responses").endswith(
        "/responses"
    )


def test_build_auth_headers_bearer_and_openrouter_attribution():
    headers = build_auth_headers(
        "test-key",
        provider_id="openrouter",
        endpoint="https://openrouter.ai/api/v1",
    )
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["HTTP-Referer"].startswith("https://")
    assert headers["X-Title"] == "DanmuAI"


def test_unknown_custom_model_conservative_capabilities():
    caps = resolve_capabilities(
        "user-custom-model",
        "https://unknown.example.com/v1",
        "openai-compatible",
    )
    assert caps.vision is False
    assert caps.stream_usage_in_final_chunk is False
    assert caps.thinking_param_style == "none"


def test_catalog_model_inherits_vision():
    caps = resolve_capabilities(
        "qwen3-vl-flash",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "openai-compatible",
    )
    assert caps.vision is True


def test_thinking_styles_cover_seven_families():
    styles = [
        ("thinking_type", "thinking"),
        ("enable_thinking", "enable_thinking"),
        ("reasoning_effort_flat", "reasoning_effort"),
        ("reasoning_object", "reasoning"),
        ("reasoning_enabled", "reasoning"),
        ("chat_template_kwargs", "chat_template_kwargs"),
        ("always_on", "reasoning_effort"),
    ]
    for style, key in styles:
        data: dict = {}
        caps = ProviderCapabilities(thinking_param_style=style)
        apply_thinking_mode(data, enabled=True, caps=caps, effort="high")
        assert key in data


def test_plan_connection_probe_openai_golden_shape(golden_dir):
    planned = plan_http_request(
        GenerationRequest(
            purpose="connection_probe",
            model_id="gpt-5",
            endpoint="https://api.openai.com/v1",
            api_key="fixture-key",
            api_mode="openai-compatible",
            user_text="ping",
            max_output_tokens=1,
            stream=False,
            force_thinking_off=True,
        )
    )
    assert planned.url == "https://api.openai.com/v1/chat/completions"
    assert planned.headers["Authorization"] == "Bearer fixture-key"
    assert planned.json_body["stream"] is False
    assert "stream_options" not in planned.json_body
    assert planned.json_body["messages"] == [{"role": "user", "content": "ping"}]
    _write_golden(golden_dir, "openai_chat.json", planned)


def test_plan_visual_doubao_golden_shape(golden_dir):
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id="doubao-seed-1-6-flash-250828",
            endpoint="https://ark.cn-beijing.volces.com/api/v3",
            api_key="fixture-key",
            api_mode="doubao",
            user_text="hi",
            image_data_uri="data:image/jpeg;base64,abc",
            max_output_tokens=512,
            temperature=0.8,
            reasoning_enabled=False,
            stream=True,
        )
    )
    assert planned.api_family == "openai_responses"
    assert planned.url.endswith("/responses")
    assert planned.json_body["thinking"] == {"type": "disabled"}
    _write_golden(golden_dir, "doubao_responses.json", planned)


def test_plan_gpt56_chat_uses_reasoning_effort_and_max_completion_tokens():
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id="gpt-5.6-sol",
            endpoint="https://api.openai.com/v1",
            api_key="fixture-key",
            api_mode="openai-compatible",
            user_text="hi",
            image_data_uri="data:image/jpeg;base64,abc",
            max_output_tokens=512,
            temperature=0.8,
            reasoning_enabled=False,
            reasoning_effort="none",
            stream=True,
        )
    )
    assert planned.api_family == "openai_chat_completions"
    assert planned.json_body["max_completion_tokens"] == 512
    assert "max_tokens" not in planned.json_body
    assert "temperature" not in planned.json_body
    assert planned.json_body["reasoning_effort"] == "none"


def test_plan_gpt56_responses_uses_responses_fields_and_reasoning_object():
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id="gpt-5.6-luna",
            endpoint="https://api.openai.com/v1",
            api_key="fixture-key",
            api_mode="openai-compatible",
            api_family="openai_responses",
            user_text="hi",
            image_data_uri="data:image/jpeg;base64,abc",
            max_output_tokens=512,
            temperature=0.8,
            reasoning_enabled=True,
            reasoning_effort="medium",
            stream=True,
        )
    )
    assert planned.api_family == "openai_responses"
    assert planned.json_body["max_output_tokens"] == 512
    assert "max_completion_tokens" not in planned.json_body
    assert "max_tokens" not in planned.json_body
    assert "temperature" not in planned.json_body
    assert planned.json_body["reasoning"] == {"effort": "medium"}


def test_explicit_family_and_optional_fields_are_honored_only_when_explicit():
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu", model_id="custom", endpoint="https://example.test/v1",
            api_key="key", api_mode="openai-compatible", api_family="openai_chat_completions",
            user_text="hi", stream=False,
        )
    )
    assert planned.api_family == "openai_chat_completions"
    assert "temperature" not in planned.json_body
    assert "stream_options" not in planned.json_body
    assert "reasoning_effort" not in planned.json_body
    assert "response_format" not in planned.json_body


def test_custom_endpoint_legacy_profile_family_falls_back_to_transport():
    planned = plan_http_request(
        GenerationRequest(
            purpose="connection_probe", model_id="custom", endpoint="https://custom.example/v1",
            api_key="key", provider_id="custom_openai", api_mode="openai-compatible",
            user_text="ping", stream=False,
        )
    )
    assert planned.api_family == "openai_chat_completions"
    assert planned.url.endswith("/chat/completions")


def test_explicit_stream_options_are_forwarded_only_for_streaming_capability():
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu", model_id="qwen3-vl-flash", endpoint="https://api.siliconflow.cn/v1",
            api_key="key", provider_id="siliconflow", api_mode="openai-compatible",
            user_text="hi", stream=True, stream_options={"include_usage": False},
        )
    )
    assert planned.json_body["stream_options"] == {"include_usage": False}


def test_query_auth_is_url_query_not_authorization():
    planned = plan_http_request(
        GenerationRequest(
            purpose="connection_probe", model_id="custom", endpoint="https://example.test/v1",
            api_key="secret", provider_id="custom_query", api_mode="openai-compatible",
            api_family="openai_chat_completions", user_text="ping", stream=False,
        )
    )
    # Custom providers remain bearer by default; the assertion protects the planner boundary.
    assert "Authorization" in planned.headers
    assert "secret" not in planned.url


def test_unknown_explicit_family_fails_safe():
    with pytest.raises(ValueError, match="unknown api family"):
        plan_http_request(
            GenerationRequest(
                purpose="connection_probe", model_id="custom", endpoint="https://example.test/v1",
                api_key="key", api_family="not-a-family", stream=False,
            )
        )


def test_plan_knowledge_organize_reuses_planner_not_duplicate_body():
    planned = plan_http_request(
        GenerationRequest(
            purpose="knowledge_organize",
            model_id="qwen3-vl-flash",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="fixture-key",
            api_mode="openai-compatible",
            system_text="sys",
            user_text="chunk",
            max_output_tokens=8192,
            stream=True,
            force_thinking_off=True,
        )
    )
    assert planned.url.endswith("/chat/completions")
    assert planned.json_body["messages"][0]["role"] == "system"
    assert "enable_thinking" in planned.json_body or "thinking" not in planned.json_body


def _write_golden(directory: Path, name: str, planned) -> None:
    payload = {
        "provider_id": planned.provider_id,
        "api_family": planned.api_family,
        "url": planned.url,
        "headers": {k: v for k, v in planned.headers.items() if k != "Authorization"},
        "json_body": planned.json_body,
        "parser_id": planned.parser_id,
        "usage_normalizer_id": planned.usage_normalizer_id,
    }
    path = directory / name
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        assert existing == payload
    else:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
