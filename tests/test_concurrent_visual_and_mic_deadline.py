"""W-AI-DEADLINE-RACE-001: per-request deadline must not share AiWorker instance attrs."""

from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import MagicMock

import httpx
import pytest

from app.ai_client import AiWorker
from app.ai_client_requests import request_openai, stream_openai

from tests.fakes import ai_client_fake_config


def _infinite_sse_stream():
    @contextmanager
    def fake_stream(*_args, **_kwargs):
        class Resp:
            def raise_for_status(self):
                return None

            def iter_lines(self):
                while True:
                    yield 'data: {"choices":[{"delta":{}}]}'

        yield Resp()

    return fake_stream


def test_stream_openai_uses_explicit_deadline_not_worker_attr():
    worker = AiWorker(ai_client_fake_config())
    worker._request_deadline_at = None

    client = MagicMock()
    client.stream.side_effect = _infinite_sse_stream()
    expired = time.monotonic() - 1.0

    with pytest.raises(httpx.TimeoutException, match="request wall clock exceeded"):
        stream_openai(
            worker,
            client,
            "https://api.example/v1/chat/completions",
            {},
            {},
            endpoint="https://api.example/v1",
            deadline_at=expired,
        )
    worker.close()


def test_stream_openai_explicit_deadline_not_overridden_by_worker_attr():
    """Mic-style worker attr clear must not extend visual stream wall clock."""
    worker = AiWorker(ai_client_fake_config())
    worker._request_deadline_at = time.monotonic() + 3600.0

    client = MagicMock()
    client.stream.side_effect = _infinite_sse_stream()
    expired = time.monotonic() - 1.0

    with pytest.raises(httpx.TimeoutException, match="request wall clock exceeded"):
        stream_openai(
            worker,
            client,
            "https://api.example/v1/chat/completions",
            {},
            {},
            endpoint="https://api.example/v1",
            deadline_at=expired,
        )
    worker.close()


def test_request_openai_retry_wall_clock_uses_explicit_deadline():
    worker = MagicMock()
    worker._request_deadline_at = time.monotonic() + 3600.0
    worker._resolve_request_credentials.return_value = (
        "https://api.example/v1",
        "key",
        "model",
        "openai-compatible",
    )
    worker.config.get_float.return_value = 0.8
    worker.config.get_int.return_value = 512
    worker._deliver_outcome.return_value = None

    request_openai(
        worker,
        "data:image/jpeg;base64,abc",
        "sys",
        "user",
        "p1",
        1,
        2,
        0.0,
        0,
        deadline_at=time.monotonic() - 1.0,
    )

    worker._stream_openai.assert_not_called()
    worker._deliver_outcome.assert_called_once()
    assert worker._deliver_outcome.call_args.kwargs["signal_name"] == "error"
