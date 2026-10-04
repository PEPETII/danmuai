"""海外模型连通性审计的离线契约。

这些测试只检查目录枚举、请求规划和错误分类，不访问真实 provider，
避免把网络、账号额度或区域权限状态固化进测试结果。
"""

from __future__ import annotations

import httpx
import pytest
from app.api_probe import _classify_exception
from app.providers.endpoint_resolver import join_api_path
from app.providers.platform_registry import (
    list_model_definitions_for_provider,
    list_provider_definitions,
)
from app.providers.request_planner import GenerationRequest, plan_http_request

# No-credential overseas Provider/Catalog Contract Test: this module validates
# offline request plans and error classification without contacting providers.


def _international_model_cases():
    cases = []
    for provider in list_provider_definitions():
        if provider.region != "international" or not provider.endpoint.default_url:
            continue
        for model in list_model_definitions_for_provider(provider.id):
            cases.append((provider.id, model.id, provider.endpoint.default_url, provider.endpoint.api_mode))
    return tuple(cases)


@pytest.mark.parametrize(
    "provider_id,model_id,endpoint,api_mode",
    _international_model_cases(),
)
def test_international_catalog_models_have_safe_offline_visual_plans(
    provider_id, model_id, endpoint, api_mode
):
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id=model_id,
            endpoint=endpoint,
            api_key="audit-contract-key",
            api_mode=api_mode,
            provider_id=provider_id,
            system_text="system contract",
            user_text="user contract",
            image_data_uri="data:image/png;base64,AAAA",
            max_output_tokens=64,
            temperature=0.0,
            stream=True,
            stream_options={"include_usage": True},
        )
    )

    assert planned.provider_id == provider_id
    assert planned.model_id == model_id
    assert planned.url == join_api_path(endpoint, planned.api_family)
    assert planned.json_body["model"] == model_id
    assert planned.json_body["stream"] is True
    assert "audit-contract-key" not in repr(planned.json_body)
    assert "audit-contract-key" not in planned.url
    if planned.api_family == "openai_chat_completions":
        assert planned.json_body["messages"][-1]["content"]
        assert any(
            part.get("type") == "image_url"
            for part in planned.json_body["messages"][-1]["content"]
        )


def test_international_catalog_matrix_has_expected_scope():
    providers = {
        provider.id: provider
        for provider in list_provider_definitions()
        if provider.region == "international"
    }
    assert len(providers) == 11
    assert providers["custom_openai"].endpoint.default_url == ""
    assert "mimo" not in providers
    assert any(provider.id == "mimo" and provider.region == "global" for provider in list_provider_definitions())
    expected_cases = sum(
        len(list_model_definitions_for_provider(provider.id))
        for provider in providers.values()
        if provider.endpoint.default_url
    )
    assert len(_international_model_cases()) == expected_cases


@pytest.mark.parametrize(
    ("provider_id", "model_id", "endpoint"),
    (
        ("openai", "gpt-6-astra", "https://api.openai.com/v1"),
        (
            "google_gemini",
            "gemini-3.8-flash",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
    ),
)
def test_openai_and_gemini_request_snapshots(provider_id, model_id, endpoint):
    text = plan_http_request(
        GenerationRequest(
            purpose="connection_probe",
            model_id=model_id,
            endpoint=endpoint,
            api_key="snapshot-key",
            api_mode="openai-compatible",
            provider_id=provider_id,
            user_text="ping",
            max_output_tokens=1,
            stream=False,
            force_thinking_off=True,
        )
    )
    assert text.api_family == "openai_chat_completions"
    assert text.url == endpoint + "/chat/completions"
    max_field = "max_completion_tokens" if provider_id == "openai" else "max_tokens"
    assert text.json_body == {
        max_field: 1,
        "messages": [{"role": "user", "content": "ping"}],
        "model": model_id,
        "stream": False,
    }

    vision = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id=model_id,
            endpoint=endpoint,
            api_key="snapshot-key",
            api_mode="openai-compatible",
            provider_id=provider_id,
            system_text="system",
            user_text="user",
            image_data_uri="data:image/png;base64,AAAA",
            max_output_tokens=64,
            temperature=0.0,
            stream=True,
            force_thinking_off=True,
        )
    )
    assert vision.url == endpoint + "/chat/completions"
    assert vision.json_body == {
        max_field: 64,
        "messages": [
            {"role": "system", "content": "system"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "user"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            },
        ],
        "model": model_id,
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": 0.0,
    }


@pytest.mark.parametrize(
    ("status_code", "expected"),
    (
        (400, "invalid_content_part"),
        (401, "auth_invalid"),
        (402, "quota_exhausted"),
        (403, "permission_denied"),
        (404, "model_not_found"),
        (408, "timeout"),
        (413, "unsupported_modality"),
        (415, "unsupported_modality"),
        (422, "unsupported_parameter"),
        (429, "rate_limited"),
        (500, "provider_unavailable"),
        (503, "provider_unavailable"),
    ),
)
def test_probe_http_error_classification_is_distinct(status_code, expected):
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, headers={"x-request-id": "audit-request"})
    result = _classify_exception(
        httpx.HTTPStatusError("opaque provider error", request=request, response=response),
        stage="text",
    )
    assert result.error_category == expected
    assert result.status_code == status_code
    assert result.request_id == "audit-request"
    assert "opaque provider error" not in result.message


def test_probe_region_hint_overrides_generic_permission_category():
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(
        403,
        request=request,
        content=b'{"error":"model is not available in this region"}',
    )
    result = _classify_exception(
        httpx.HTTPStatusError("opaque provider error", request=request, response=response),
        stage="text",
    )
    assert result.error_category == "model_not_available_in_region"


@pytest.mark.parametrize(
    ("exception", "expected"),
    (
        (httpx.ConnectTimeout("connect timeout"), "timeout"),
        (httpx.ReadTimeout("read timeout"), "timeout"),
        (httpx.ConnectError("connection failed"), "provider_unavailable"),
    ),
)
def test_probe_network_exception_classification(exception, expected):
    result = _classify_exception(exception, stage="text")
    assert result.error_category == expected

