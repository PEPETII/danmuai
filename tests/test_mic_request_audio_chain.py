"""W-MIC-AUDIO-NO-EFFECT-001: PCM → WAV → request body audio part → mock reply."""

from __future__ import annotations

import struct
from unittest.mock import patch

from app.ai_client import AiWorker
from app.ai_client_requests import request_doubao, request_openai
from app.mic_encode import pcm_to_wav_data_uri
from app.providers.request_planner import GenerationRequest, plan_http_request

from tests.fakes import ai_client_fake_config


def _sample_pcm(num_frames: int = 1600) -> bytes:
    return struct.pack(f"<{num_frames}h", *([100] * num_frames))


def test_pcm_to_wav_data_uri_round_trip():
    pcm = _sample_pcm()
    uri = pcm_to_wav_data_uri(pcm)
    assert uri is not None
    assert uri.startswith("data:audio/wav;base64,")


def test_request_openai_preserves_audio_for_declared_custom_model():
    worker = AiWorker(
        ai_client_fake_config(
            data={
                "default_model_id": "or-audio",
                "api_mode": "openai-compatible",
                "api_endpoint": "https://openrouter.ai/api/v1",
                "model": "or-audio",
                "mic_use_visual_model": "1",
            },
            api_key="sk-test",
            custom_models=[
                {
                    "name": "OR Audio",
                    "default_model_id": "or-audio",
                    "modelId": "or-audio",
                    "endpoint": "https://openrouter.ai/api/v1",
                    "apiKey": "sk-test",
                    "mode": "openai-compatible",
                    "supportsMic": True,
                }
            ],
        )
    )
    resolved = (
        "https://openrouter.ai/api/v1",
        "sk-test",
        "or-audio",
        "openai-compatible",
    )
    pcm = _sample_pcm()
    audio_uri = pcm_to_wav_data_uri(pcm)
    captured: dict = {}

    def fake_stream(_worker, _client, _url, _headers, data, **_kwargs):
        captured["data"] = data
        return ("ok", 1, 1)

    with patch("app.ai_client_requests.stream_openai", side_effect=fake_stream):
        result = request_openai(
            worker,
            "data:image/jpeg;base64,abc",
            "sys",
            "user",
            "p1",
            1,
            1,
            1.0,
            0,
            audio_data_uri=audio_uri,
            resolved=resolved,
            emit=False,
        )

    assert result is not None
    assert result.signal == "finished"
    user_content = captured["data"]["messages"][1]["content"]
    types = {part.get("type") for part in user_content}
    assert "input_audio" in types
    worker.close()


def test_request_openai_strips_audio_for_undeclared_gpt4o():
    worker = AiWorker(
        ai_client_fake_config(
            data={
                "api_mode": "openai",
                "api_endpoint": "https://api.openai.com/v1",
                "model": "gpt-4o",
            },
            api_key="sk-test",
        )
    )
    resolved = ("https://api.openai.com/v1", "sk-test", "gpt-4o", "openai")
    captured: dict = {}

    def fake_stream(_worker, _client, _url, _headers, data, **_kwargs):
        captured["data"] = data
        return ("ok", 1, 1)

    with patch("app.ai_client_requests.stream_openai", side_effect=fake_stream):
        request_openai(
            worker,
            "data:image/jpeg;base64,abc",
            "sys",
            "user",
            "p1",
            1,
            1,
            1.0,
            0,
            audio_data_uri="data:audio/wav;base64,xyz",
            resolved=resolved,
            emit=False,
        )

    user_content = captured["data"]["messages"][1]["content"]
    types = {part.get("type") for part in user_content}
    assert "input_audio" not in types
    worker.close()


def test_request_doubao_preserves_audio_for_seed_model():
    worker = AiWorker(
        ai_client_fake_config(
            data={
                "api_mode": "doubao",
                "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
                "model": "doubao-seed-2-0-mini-260428",
            },
            api_key="sk-test",
        )
    )
    resolved = (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-test",
        "doubao-seed-2-0-mini-260428",
        "doubao",
    )
    captured: dict = {}

    def fake_stream(_worker, _client, _url, _headers, data, **_kwargs):
        captured["data"] = data
        return ("ok", 1, 1, None)

    with patch("app.ai_client_requests.stream_doubao", side_effect=fake_stream):
        request_doubao(
            worker,
            "data:image/jpeg;base64,abc",
            "sys",
            "user",
            "p1",
            1,
            1,
            1.0,
            0,
            audio_data_uri="data:audio/wav;base64,xyz",
            resolved=resolved,
            emit=False,
        )

    content = captured["data"]["input"][0]["content"]
    types = {part.get("type") for part in content}
    assert "input_audio" in types
    worker.close()


def test_plan_http_request_honors_supports_mic_declared():
    planned = plan_http_request(
        GenerationRequest(
            purpose="mic_danmu",
            model_id="custom-audio-model",
            endpoint="https://example.com/v1",
            api_key="sk-test",
            api_mode="openai-compatible",
            user_text="hello",
            image_data_uri="data:image/jpeg;base64,abc",
            audio_data_uri="data:audio/wav;base64,xyz",
            supports_mic_declared=True,
        )
    )
    assert "mic_audio_stripped" not in planned.warnings
    user_content = planned.json_body["messages"][-1]["content"]
    types = {part.get("type") for part in user_content}
    assert "input_audio" in types
