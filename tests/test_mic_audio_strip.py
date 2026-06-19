"""W-TEST-COVER-006: mic audio stripped when visual model lacks audio support."""

from __future__ import annotations

from unittest.mock import patch

from app.ai_client import AiWorker
from app.ai_client_requests import request_openai

from tests.fakes import FakeConfig


def test_request_openai_strips_mic_audio_and_logs_when_unsupported():
    worker = AiWorker(
        FakeConfig(
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

    def fake_stream(_client, _url, _headers, data, **_kwargs):
        captured["data"] = data
        return ("ok", 1, 1)

    with patch("app.ai_client_requests.model_supports_mic_audio", return_value=False):
        with patch.object(worker, "_stream_openai", side_effect=fake_stream):
            with patch("app.ai_client_requests.logger") as mock_log:
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
                mock_log.info.assert_called()
                assert "mic audio stripped" in mock_log.info.call_args[0][0]
    user_content = captured["data"]["messages"][1]["content"]
    if isinstance(user_content, list):
        types = {part.get("type") for part in user_content}
        assert "input_audio" not in types
    worker.close()
