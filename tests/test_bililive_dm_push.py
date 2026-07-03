"""W-BILILIVE-DM-PLUGIN-PUSH-004 — DanmuAI 主链路 → bililive_dm 主动推送测试。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

import app.bililive_dm_plugin_auth as plugin_auth
from app.bililive_dm_plugin_auth import PLUGIN_SECRET_HEADER
from app.application import bililive_dm_push_service as push_service
from app.application.bililive_dm_contracts import (
    DEFAULT_PUSH_URL,
    PUSH_SOURCE_MAIN,
    BililiveDmPushRequest,
)

from tests.conftest import make_minimal_danmu_app

_TEST_SECRET = "test-secret"


@pytest.fixture(autouse=True)
def _plugin_secret_env(monkeypatch):
    monkeypatch.setenv("DANMU_BILILIVE_DM_PLUGIN_SECRET", _TEST_SECRET)
    monkeypatch.setattr(plugin_auth, "_cached_secret", None)


def test_sanitize_push_items_drops_blank_and_whitespace():
    items = push_service.sanitize_push_items(["  hello  ", "", "   ", "world"])
    assert items == ["hello", "world"]


def test_sanitize_push_items_truncates_long_text():
    long = "a" * 100
    items = push_service.sanitize_push_items([long])
    assert len(items) == 1
    assert len(items[0]) == push_service.MAX_ITEM_CHARS
    assert items[0].endswith("…")


def test_sanitize_push_items_caps_at_max_items():
    items = push_service.sanitize_push_items([f"line{i}" for i in range(10)])
    assert len(items) == push_service.MAX_ITEMS


def test_sanitize_push_items_deduplicates():
    items = push_service.sanitize_push_items(["hi", "hi", "bye"])
    assert items == ["hi", "bye"]


def test_push_request_json_round_trip():
    req = BililiveDmPushRequest(
        source=PUSH_SOURCE_MAIN,
        batch_id=7,
        items=["a", "b"],
        persona="测试",
    )
    data = req.model_dump()
    restored = BililiveDmPushRequest.model_validate(data)
    assert restored.batch_id == 7
    assert restored.items == ["a", "b"]
    assert restored.persona == "测试"


def test_push_batch_empty_items_returns_empty_items_error():
    result = push_service.push_batch_to_bililive_dm(
        BililiveDmPushRequest(batch_id=1, items=["", "   "]),
    )
    assert result.ok is False
    assert result.error == "empty_items"
    assert result.displayed == 0


def test_push_batch_success(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "error": None, "displayed": 2}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, url, json=None, headers=None):
            assert json["source"] == PUSH_SOURCE_MAIN
            assert json["batch_id"] == 3
            assert json["items"] == ["a", "b"]
            assert headers is not None
            assert headers.get(PLUGIN_SECRET_HEADER) == _TEST_SECRET
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = push_service.push_batch_to_bililive_dm(
        BililiveDmPushRequest(batch_id=3, items=["a", "b"]),
        url="http://127.0.0.1:18766/api/plugin/danmuai/push/",
    )
    assert result.ok is True
    assert result.displayed == 2


def test_push_batch_http_error_status(monkeypatch):
    class FakeResponse:
        status_code = 500

        @staticmethod
        def json():
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, url, json=None, headers=None):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = push_service.push_batch_to_bililive_dm(
        BililiveDmPushRequest(batch_id=1, items=["x"]),
    )
    assert result.ok is False
    assert result.error == "http_500"


def test_push_batch_connection_refused(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, url, json=None, headers=None):
            raise httpx.ConnectError("refused", request=MagicMock())

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = push_service.push_batch_to_bililive_dm(
        BililiveDmPushRequest(batch_id=1, items=["x"]),
    )
    assert result.ok is False
    assert result.error == "connection_refused"


def test_push_batch_timeout(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, url, json=None, headers=None):
            raise httpx.TimeoutException("timed out")

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = push_service.push_batch_to_bililive_dm(
        BililiveDmPushRequest(batch_id=1, items=["x"]),
    )
    assert result.ok is False
    assert result.error == "timeout"


def test_schedule_push_batch_disabled(monkeypatch):
    monkeypatch.setenv("DANMU_BILILIVE_DM_PUSH", "0")
    with patch.object(push_service.threading, "Thread") as mock_thread_cls:
        push_service.schedule_push_batch(batch_id=1, items=["hello"])
        mock_thread_cls.assert_not_called()


def test_schedule_push_batch_starts_daemon_thread(monkeypatch):
    monkeypatch.setenv("DANMU_BILILIVE_DM_PUSH", "1")
    started = []

    class FakeThread:
        def __init__(self, target=None, kwargs=None, name=None, daemon=None):
            self._target = target
            self._kwargs = kwargs or {}
            self.daemon = daemon

        def start(self):
            started.append((self._target, self._kwargs))

    monkeypatch.setattr(push_service.threading, "Thread", FakeThread)
    push_service.schedule_push_batch(batch_id=5, items=["a"], persona="p1")
    assert len(started) == 1
    assert started[0][1]["batch_id"] == 5
    assert started[0][1]["items"] == ["a"]


def test_enqueue_ai_batch_schedules_bililive_push():
    app = make_minimal_danmu_app()
    app.config.set("bililive_dm_mode_enabled", "1")
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._batch_id = 2
        app._enqueue_reply_batch(
            "人格A",
            1,
            1,
            time.monotonic(),
            0,
            ["hello", "world"],
        )
        mock_push.assert_called_once()
        kwargs = mock_push.call_args.kwargs
        assert kwargs["batch_id"] == 2
        assert kwargs["persona"] == "人格A"
        assert len(kwargs["items"]) == 2


def test_enqueue_mic_batch_does_not_schedule_push():
    app = make_minimal_danmu_app()
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._enqueue_reply_batch(
            "p1",
            1,
            1,
            time.monotonic(),
            0,
            ["mic line"],
            from_mic_insert=True,
        )
        mock_push.assert_not_called()


def test_enqueue_fallback_batch_does_not_schedule_push():
    app = make_minimal_danmu_app()
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._enqueue_reply_batch(
            "p1",
            1,
            1,
            time.monotonic(),
            0,
            ["fallback"],
            from_local_fallback=True,
        )
        mock_push.assert_not_called()


def test_default_push_url_constant():
    assert DEFAULT_PUSH_URL.endswith("/api/plugin/danmuai/push/")
