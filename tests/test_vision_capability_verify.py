"""W-REVIEW-20260820-VISION-CAPABILITY-VERIFY-001: end-to-end vision capability vs image payload.

Deterministic offline tests from capability_resolver → plan_http_request → adapter body.
Documents current behavior: caps.vision=False does not strip image_data_uri (unlike mic audio).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from app.ai_client import AiWorker
from app.ai_client_requests import request_openai
from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.adapters.responses import ResponsesAdapter
from app.providers.capability_resolver import resolve_capabilities
from app.providers.request_planner import GenerationRequest, plan_http_request

from tests.fakes import ai_client_fake_config

FAKE_IMAGE_URI = "data:image/jpeg;base64,FAKEVISION"
FAKE_USER_TEXT = "describe scene"


def _image_part_types(body: dict) -> list[str]:
    """Collect vision-related part types from planned OpenAI chat or Responses body."""
    if "messages" in body:
        content = body["messages"][-1]["content"]
        if isinstance(content, str):
            return ["text_only"] if content else []
        return [part.get("type", "") for part in content]
    if "input" in body:
        content = body["input"][0]["content"]
        return [part.get("type", "") for part in content]
    return []


def _body_contains_image(body: dict, image_uri: str = FAKE_IMAGE_URI) -> bool:
    types = _image_part_types(body)
    if "image_url" in types or "input_image" in types:
        return True
    if "messages" in body:
        content = body["messages"][-1]["content"]
        if isinstance(content, str):
            return image_uri in content
    return False


@pytest.mark.parametrize(
    ("label", "model_id", "endpoint", "api_mode", "provider_id"),
    [
        (
            "custom_openai_unknown",
            "user-custom-model",
            "https://custom.example.com/v1",
            "openai-compatible",
            "custom_openai",
        ),
        (
            "custom_doubao_unknown",
            "my-doubao-model",
            "https://custom-doubao.example.com/api/v3",
            "doubao",
            "custom_doubao",
        ),
        (
            "dashscope_unknown_catalog",
            "future-model",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai-compatible",
            "dashscope",
        ),
    ],
)
def test_unknown_or_non_vision_models_resolve_conservative_vision_false(
    label, model_id, endpoint, api_mode, provider_id,
):
  caps = resolve_capabilities(
      model_id, endpoint, api_mode, provider_id=provider_id,
  )
  assert caps.vision is False, label


@pytest.mark.parametrize(
    ("label", "model_id", "endpoint", "api_mode", "provider_id"),
    [
        (
            "custom_openai_unknown",
            "user-custom-model",
            "https://custom.example.com/v1",
            "openai-compatible",
            "custom_openai",
        ),
        (
            "custom_doubao_unknown",
            "my-doubao-model",
            "https://custom-doubao.example.com/api/v3",
            "doubao",
            "custom_doubao",
        ),
        (
            "dashscope_unknown_catalog",
            "future-model",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai-compatible",
            "dashscope",
        ),
    ],
)
def test_vision_false_still_leaks_image_in_planned_body_current_behavior(
    label, model_id, endpoint, api_mode, provider_id,
):
    """Current defect: planner/adapters ignore caps.vision; image is not stripped."""
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id=model_id,
            endpoint=endpoint,
            api_key="fixture-key",
            api_mode=api_mode,
            provider_id=provider_id,
            user_text=FAKE_USER_TEXT,
            image_data_uri=FAKE_IMAGE_URI,
            stream=True,
        )
    )
    assert planned.applied_capabilities is not None
    assert planned.applied_capabilities.vision is False, label
    assert "vision_stripped" not in planned.warnings, label
    assert _body_contains_image(planned.json_body), label


@pytest.mark.parametrize(
    ("label", "model_id", "endpoint", "api_mode", "provider_id", "expected_image_types"),
    [
        (
            "mimo_catalog_vision",
            "mimo-v2.5",
            "https://api.xiaomimimo.com/v1",
            "openai-compatible",
            "mimo",
            ["image_url", "text"],
        ),
        (
            "qwen_catalog_vision",
            "qwen3-vl-flash",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai-compatible",
            "dashscope",
            ["text", "image_url"],
        ),
    ],
)
def test_vision_supported_models_keep_image_payload_contract(
    label, model_id, endpoint, api_mode, provider_id, expected_image_types,
):
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id=model_id,
            endpoint=endpoint,
            api_key="fixture-key",
            api_mode=api_mode,
            provider_id=provider_id,
            user_text=FAKE_USER_TEXT,
            image_data_uri=FAKE_IMAGE_URI,
            stream=True,
        )
    )
    assert planned.applied_capabilities is not None
    assert planned.applied_capabilities.vision is True, label
    assert _image_part_types(planned.json_body) == expected_image_types, label


def test_supports_vision_override_enables_caps_and_image_for_custom_openai():
    planned = plan_http_request(
        GenerationRequest(
            purpose="visual_danmu",
            model_id="user-custom",
            endpoint="https://custom.example.com/v1",
            api_key="fixture-key",
            api_mode="openai-compatible",
            provider_id="custom_openai",
            user_text=FAKE_USER_TEXT,
            image_data_uri=FAKE_IMAGE_URI,
            supports_vision_override=True,
            stream=True,
        )
    )
    assert planned.applied_capabilities is not None
    assert planned.applied_capabilities.vision is True
    assert _body_contains_image(planned.json_body)
    assert _image_part_types(planned.json_body) == ["text", "image_url"]


def test_default_openai_adapter_builds_image_without_caps_gate():
    """Adapter layer does not consult caps.vision before embedding image_url."""
    adapter = DefaultOpenAIAdapter()
    parts = adapter.build_vision_user_content(FAKE_USER_TEXT, FAKE_IMAGE_URI)
    types = [p["type"] for p in parts]
    assert types == ["text", "image_url"]
    assert parts[1]["image_url"]["url"] == FAKE_IMAGE_URI


def test_responses_adapter_builds_input_image_for_custom_doubao_unknown():
    from app.providers.capabilities import get_capabilities

    adapter = ResponsesAdapter()
    caps = get_capabilities("custom_doubao")
    req = GenerationRequest(
        purpose="visual_danmu",
        model_id="unknown-doubao",
        endpoint="https://custom-doubao.example.com/api/v3",
        api_key="k",
        api_mode="doubao",
        provider_id="custom_doubao",
        user_text=FAKE_USER_TEXT,
        image_data_uri=FAKE_IMAGE_URI,
        stream=True,
        api_family="openai_responses",
    )
    body = adapter.build_body(req, caps, [])
    content = body["input"][0]["content"]
    assert [p["type"] for p in content] == ["input_image", "input_text"]
    assert content[0]["image_url"] == FAKE_IMAGE_URI


def test_request_openai_leaks_image_for_unknown_custom_model_via_ai_client():
    worker = AiWorker(
        ai_client_fake_config(
            data={
                "default_model_id": "custom-text-only",
                "api_mode": "openai-compatible",
                "api_endpoint": "https://custom.example.com/v1",
                "model": "custom-text-only",
            },
            api_key="sk-test",
            custom_models=[
                {
                    "name": "Custom Text",
                    "default_model_id": "custom-text-only",
                    "modelId": "custom-text-only",
                    "endpoint": "https://custom.example.com/v1",
                    "apiKey": "sk-test",
                    "mode": "openai-compatible",
                }
            ],
        )
    )
    resolved = (
        "https://custom.example.com/v1",
        "sk-test",
        "custom-text-only",
        "openai-compatible",
    )
    captured: dict = {}

    def fake_stream(_worker, _client, _url, _headers, data, **_kwargs):
        captured["data"] = data
        return ("ok", 1, 1)

    with patch("app.ai_client_requests.stream_openai", side_effect=fake_stream):
        request_openai(
            worker,
            FAKE_IMAGE_URI,
            "sys",
            FAKE_USER_TEXT,
            "p1",
            1,
            1,
            1.0,
            0,
            resolved=resolved,
            emit=False,
        )

    assert _body_contains_image(captured["data"])
    worker.close()
