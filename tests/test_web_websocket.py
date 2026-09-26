"""Web console tests: websocket."""

from unittest.mock import MagicMock

import pytest
from app.web_console import (
    WebConsoleBridge,
)
from app.web_console_ws import _WS_MAX_AUTH_TOKEN_LENGTH

from tests.web_console_helpers import build_ws_logs_test_app, build_ws_status_test_app

_WS_ENDPOINT_CASES = (
    ("/ws/status", "register_status_consumer", "unregister_status_consumer"),
    ("/ws/logs", "register_log_consumer", "unregister_log_consumer"),
    ("/ws/mic-logs", "register_mic_log_consumer", "unregister_mic_log_consumer"),
    ("/ws/panel", "register_panel_consumer", "unregister_panel_consumer"),
)

_INVALID_FIRST_FRAME_TOKENS = (
    pytest.param(None, id="null"),
    pytest.param({"nested": "object"}, id="object"),
    pytest.param(["array"], id="array"),
    pytest.param(123, id="number"),
    pytest.param(True, id="bool"),
    pytest.param("x" * (_WS_MAX_AUTH_TOKEN_LENGTH + 1), id="overlong-string"),
    pytest.param("wrong-token", id="wrong-string"),
)


def test_ws_status_websocket_accepts_valid_token_and_sends_status():
    """Regression: FastAPI @app.websocket must not be the only registration path."""
    from fastapi.testclient import TestClient

    token = "ws-test-token-valid"
    bridge = MagicMock()
    bridge._last_status_payload = {
        "running": True,
        "danmu_count": 2,
        "queue_count": 0,
        "display_count": 1,
    }

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with client.websocket_connect(f"/ws/status?ws_token={token}") as ws:
        payload = ws.receive_json()
        assert payload["running"] is True
        assert "danmu_count" in payload

    bridge.register_status_consumer.assert_called_once()
    bridge.unregister_status_consumer.assert_called_once()
    bridge.status_refresh_requested.emit.assert_called_once()


def test_ws_status_websocket_accepts_first_message_auth():
    """W-SECURITY-002: 连接后首条消息认证（无 query ws_token）。"""
    from fastapi.testclient import TestClient

    token = "ws-test-token-valid"
    bridge = MagicMock()
    bridge._last_status_payload = {
        "running": True,
        "danmu_count": 2,
        "queue_count": 0,
        "display_count": 1,
    }

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with client.websocket_connect("/ws/status") as ws:
        ws.send_json({"type": "auth", "token": token})
        auth = ws.receive_json()
        assert auth == {"type": "auth", "ok": True}
        payload = ws.receive_json()
        assert payload["running"] is True
        assert "danmu_count" in payload

    bridge.register_status_consumer.assert_called_once()
    bridge.unregister_status_consumer.assert_called_once()


def test_ws_status_websocket_rejects_invalid_token_with_1008():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()
    bridge._last_status_payload = {"running": False}

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with client.websocket_connect("/ws/status?ws_token=invalid-token") as ws:
        resp = ws.receive_json()
        assert resp == {"type": "auth", "ok": False, "error": "认证失败"}
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == 1008
        assert exc_info.value.reason == "认证失败"

    bridge.register_status_consumer.assert_not_called()


@pytest.mark.parametrize(
    ("path", "register_name", "unregister_name"), _WS_ENDPOINT_CASES
)
@pytest.mark.parametrize("auth_token", _INVALID_FIRST_FRAME_TOKENS)
def test_ws_all_endpoints_reject_invalid_first_frame_token_types(
    path, register_name, unregister_name, auth_token, caplog
):
    """P2-11: every WS auth gate rejects non-string/overlong tokens uniformly."""
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    expected_token = "ws-test-token-valid"
    bridge = MagicMock()
    bridge._last_status_payload = {"running": False}
    app = build_ws_status_test_app(bridge, expected_token)
    client = TestClient(app)

    with caplog.at_level("DEBUG", logger="app.web_console_ws"):
        with client.websocket_connect(path) as ws:
            ws.send_json({"type": "auth", "token": auth_token})
            response = ws.receive_json()
            assert response == {"type": "auth", "ok": False, "error": "认证失败"}
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()

    assert exc_info.value.code == 1008
    assert exc_info.value.reason == "认证失败"
    getattr(bridge, register_name).assert_not_called()
    getattr(bridge, unregister_name).assert_not_called()
    if isinstance(auth_token, str):
        assert auth_token not in repr(response)
        assert auth_token not in exc_info.value.reason
        assert auth_token not in caplog.text


def test_ws_auth_failure_closes_when_failure_frame_send_times_out(monkeypatch):
    """P2-11: a failed auth response must still attempt the 1008 close."""
    import asyncio

    from app.web_console_ws import _authenticate_websocket

    class _WebSocket:
        query_params = {}

        def __init__(self):
            self.closed = []

        async def receive_json(self):
            return {"type": "auth", "token": "wrong-token"}

        async def close(self, *, code, reason):
            self.closed.append((code, reason))

    async def _failed_send(*_args, **_kwargs):
        return False

    monkeypatch.setattr("app.web_console_ws._send_json_with_timeout", _failed_send)
    websocket = _WebSocket()
    assert asyncio.run(_authenticate_websocket(websocket, "expected-token")) is False
    assert websocket.closed == [(1008, "认证失败")]


def test_ws_status_websocket_rejects_missing_token_with_1008():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with client.websocket_connect("/ws/status") as ws:
        assert ws.receive_json() == {"type": "auth", "ok": False, "error": "认证超时"}
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == 1008
        assert exc_info.value.reason == "认证超时"

    bridge.register_status_consumer.assert_not_called()


def test_ws_status_unauthenticated_closes_within_timeout_without_consumer():
    """BUG-015: unauthenticated /ws/status closes within auth timeout and never registers consumer."""
    import time

    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    started = time.monotonic()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/status"):
            pass
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    bridge.register_status_consumer.assert_not_called()


def test_ws_logs_unauthenticated_closes_within_timeout_without_consumer():
    """BUG-015: unauthenticated /ws/logs closes within auth timeout and never registers consumer."""
    import time

    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()

    app = build_ws_logs_test_app(bridge, token)
    client = TestClient(app)

    started = time.monotonic()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/logs"):
            pass
    elapsed = time.monotonic() - started

    assert elapsed < 2.0
    bridge.register_log_consumer.assert_not_called()


def test_ws_status_client_can_reconnect_after_disconnect():
    from fastapi.testclient import TestClient

    token = "ws-reconnect-token"
    danmu_app = MagicMock()
    danmu_app.logger = MagicMock()
    bridge = WebConsoleBridge(danmu_app)
    bridge._last_status_payload = {"running": False, "danmu_count": 0, "queue_count": 0, "display_count": 0}
    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)
    url = f"/ws/status?ws_token={token}"

    with client.websocket_connect(url) as ws:
        first = ws.receive_json()
        assert first["running"] is False
    with client.websocket_connect(url) as ws:
        second = ws.receive_json()
        assert second["running"] is False
    assert len(bridge._ws_status_queues) == 0


def test_ws_status_max_connections_capped():
    """BUG-038: reject excess /ws/status clients before register_status_consumer."""
    from contextlib import ExitStack

    from app.web_console_ws import _WS_MAX_STATUS_CONSUMERS
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-max-conn"
    danmu_app = MagicMock()
    danmu_app.logger = MagicMock()
    bridge = WebConsoleBridge(danmu_app)
    bridge._last_status_payload = {
        "running": False,
        "danmu_count": 0,
        "queue_count": 0,
        "display_count": 0,
    }

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)
    url = f"/ws/status?ws_token={token}"

    with ExitStack() as stack:
        for _ in range(_WS_MAX_STATUS_CONSUMERS):
            ws = stack.enter_context(client.websocket_connect(url))
            ws.receive_json()
        assert len(bridge._ws_status_queues) == _WS_MAX_STATUS_CONSUMERS

        extra = stack.enter_context(client.websocket_connect(url))
        with pytest.raises(WebSocketDisconnect):
            extra.receive_json()
        assert len(bridge._ws_status_queues) == _WS_MAX_STATUS_CONSUMERS

    assert len(bridge._ws_status_queues) == 0


def test_ws_logs_max_connections_capped():
    """S-026: reject excess /ws/logs clients before register_log_consumer."""
    from contextlib import ExitStack

    from app.web_console_ws import _WS_MAX_LOG_CONSUMERS
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-logs-max"
    danmu_app = MagicMock()
    danmu_app.logger = MagicMock()
    bridge = WebConsoleBridge(danmu_app)

    app = build_ws_logs_test_app(bridge, token)
    client = TestClient(app)
    url = f"/ws/logs?ws_token={token}"

    with ExitStack() as stack:
        for _ in range(_WS_MAX_LOG_CONSUMERS):
            stack.enter_context(client.websocket_connect(url))
        assert len(bridge._ws_log_queues) == _WS_MAX_LOG_CONSUMERS

        extra = stack.enter_context(client.websocket_connect(url))
        with pytest.raises(WebSocketDisconnect):
            extra.receive_json()
        assert len(bridge._ws_log_queues) == _WS_MAX_LOG_CONSUMERS

    assert len(bridge._ws_log_queues) == 0


def test_ws_logs_dotted_token_replay_is_sanitized():
    from app.logger import SanitizedLogger
    from fastapi.testclient import TestClient

    from tests.web_console_helpers import make_status_app

    token = "ws-test-token-sanitized-log"
    jwt = "fakeHead.fakePayload123456.fakeSignature789012"
    danmu_app = make_status_app()
    danmu_app.logger = SanitizedLogger()
    bridge = WebConsoleBridge(danmu_app)
    danmu_app.logger.error(f"provider Authorization: Bearer {jwt}")

    app = build_ws_logs_test_app(bridge, token)
    client = TestClient(app)
    with client.websocket_connect(f"/ws/logs?ws_token={token}") as ws:
        payload = ws.receive_json()

    assert payload["level"] == "ERROR"
    for part in jwt.split("."):
        assert part not in payload["message"]
    assert "Authorization: Bearer" in payload["message"]


def test_send_json_with_timeout_returns_false_on_slow_client():
    """P-35: slow send_json disconnects via timeout helper."""
    import asyncio

    from app.web_console_ws import _send_json_with_timeout

    class _SlowWebSocket:
        async def send_json(self, _item):
            await asyncio.sleep(5.0)

    async def _run() -> None:
        ok = await _send_json_with_timeout(_SlowWebSocket(), {"x": 1}, timeout_sec=0.05)
        assert ok is False

    asyncio.run(_run())

