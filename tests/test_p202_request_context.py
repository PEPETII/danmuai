"""P2-02：冻结 resolved request context 的确定性验收。"""

from __future__ import annotations

import json
import threading
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from app.ai_client_requests import request_doubao, request_openai
from app.ai_client_support import resolve_visual_request_context
from app.providers.request_context import ResolvedRequestContext
from app.providers.request_planner import GenerationRequest, plan_http_request


class _Config:
    def __init__(self, profiles: list[dict]):
        self.profiles = profiles
        self.values = {
            "active_model_profile_id": "profile-a",
            "max_tokens": "9999",
            "temperature": "1.8",
            "use_thinking": "1",
        }

    def get_custom_models(self):
        return self.profiles

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_int(self, key, default=0):
        return int(self.values.get(key, default))

    def get_float(self, key, default=0.0):
        return float(self.values.get(key, default))


def _profile(
    *,
    profile_id: str,
    endpoint: str,
    mode: str,
    provider: str,
    api_key: str,
    max_tokens: int,
    temperature: float,
) -> dict:
    return {
        "profile_id": profile_id,
        "name": profile_id,
        "model_ids": ["shared-model"],
        "default_model_id": "shared-model",
        "endpoint": endpoint,
        "mode": mode,
        "provider": provider,
        "apiKey": api_key,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "thinking_effort": "off",
        "supportsMic": False,
    }


def _config() -> _Config:
    return _Config(
        [
            _profile(
                profile_id="profile-a",
                endpoint="https://ark.cn-beijing.volces.com/api/v3",
                mode="doubao",
                provider="custom_doubao",
                api_key="sk-profile-a",
                max_tokens=700,
                temperature=0.2,
            ),
            _profile(
                profile_id="profile-b",
                endpoint="https://api.openai.com/v1",
                mode="openai-compatible",
                provider="custom_openai",
                api_key="sk-profile-b",
                max_tokens=900,
                temperature=0.7,
            ),
        ]
    )


def _context(config: _Config, persona_id: str) -> ResolvedRequestContext:
    context = resolve_visual_request_context(config, persona_id)
    assert context is not None
    return context


def _generation_request(context: ResolvedRequestContext) -> GenerationRequest:
    return GenerationRequest(
        purpose="visual_danmu",
        model_id=context.model_id,
        endpoint=context.endpoint,
        api_key=context.api_key,
        api_mode=context.api_mode,
        user_text="describe",
        image_data_uri="data:image/jpeg;base64,abc",
        stream=True,
        request_context=context,
    )


def test_persona_ids_resolve_to_the_same_global_profile_and_hide_credentials():
    config = _config()
    context_a = _context(config, "persona-a")
    context_b = _context(config, "persona-b")

    assert context_a.profile_id == "profile-a"
    assert context_b.profile_id == "profile-a"
    assert context_a.model_id == context_b.model_id == "shared-model"
    assert context_a.provider_id == "custom_doubao"
    assert context_b.provider_id == "custom_doubao"
    assert context_a.api_key == "sk-profile-a"
    assert context_b.api_key == "sk-profile-a"

    public = context_a.public_projection()
    assert public.profile_id == "profile-a"
    assert not hasattr(public, "api_key")
    assert "sk-profile-a" not in repr(public)
    with pytest.raises(FrozenInstanceError):
        context_a.max_tokens = 1


def test_legacy_persona_binding_does_not_change_global_resolution():
    config = _config()
    config.values["persona_model_bindings"] = json.dumps({"persona-a": "profile-b"})
    context = _context(config, "persona-a")
    assert context.profile_id == "profile-a"
    assert context.api_key == "sk-profile-a"


def test_profile_max_tokens_reach_both_final_payload_shapes():
    config = _config()
    context_a = _context(config, "persona-a")
    config.values["active_model_profile_id"] = "profile-b"
    context_b = _context(config, "persona-b")

    planned_a = plan_http_request(_generation_request(context_a))
    planned_b = plan_http_request(_generation_request(context_b))

    assert planned_a.json_body["max_output_tokens"] == 700
    assert planned_b.json_body["max_tokens"] == 900
    assert planned_a.json_body["temperature"] == 0.2
    assert planned_b.json_body["temperature"] == 0.7


def test_provider_paths_use_frozen_context_after_config_changes():
    config = _config()
    context_a = _context(config, "persona-a")
    config.values["active_model_profile_id"] = "profile-b"
    context_b = _context(config, "persona-b")

    config.profiles[0]["max_tokens"] = 1800
    config.profiles[0]["temperature"] = 1.9
    config.profiles[0]["apiKey"] = "sk-changed"
    config.values["max_tokens"] = "1"
    config.values["temperature"] = "0.01"

    planned_a = plan_http_request(_generation_request(context_a))
    planned_b = plan_http_request(_generation_request(context_b))
    assert planned_a.json_body["max_output_tokens"] == 700
    assert planned_a.json_body["temperature"] == 0.2
    assert planned_a.headers["Authorization"] == "Bearer sk-profile-a"
    assert planned_b.json_body["max_tokens"] == 900
    assert planned_b.json_body["temperature"] == 0.7

    class _RejectConfig:
        def __getattr__(self, name):
            raise AssertionError(f"provider path re-read config via {name}")

    class _Worker:
        _stopping = threading.Event()
        config = _RejectConfig()

        def _get_http_client(self):
            return object()

        def _deliver_outcome(self, **kwargs):
            return kwargs

    worker = _Worker()
    captured: dict[str, dict] = {}

    def capture_doubao(_worker, _client, _url, _headers, data, **_kwargs):
        captured["doubao"] = data
        return "ok", 0, 0, ""

    def capture_openai(_worker, _client, _url, _headers, data, **_kwargs):
        captured["openai"] = data
        return "ok", 0, 0

    with patch("app.ai_client_requests.stream_doubao", side_effect=capture_doubao):
        request_doubao(
            worker,
            "data:image/jpeg;base64,abc",
            "sys",
            "user",
            "persona-a",
            1,
            1,
            1.0,
            0,
            request_context=context_a,
            emit=False,
        )
    with patch("app.ai_client_requests.stream_openai", side_effect=capture_openai):
        request_openai(
            worker,
            "data:image/jpeg;base64,abc",
            "sys",
            "user",
            "persona-b",
            1,
            1,
            1.0,
            0,
            request_context=context_b,
            emit=False,
        )

    assert captured["doubao"]["max_output_tokens"] == 700
    assert captured["doubao"]["temperature"] == 0.2
    assert captured["openai"]["max_tokens"] == 900
    assert captured["openai"]["temperature"] == 0.7
