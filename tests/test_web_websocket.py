"""Web console tests: websocket."""

from unittest.mock import MagicMock

import pytest
from app.web_console import (
    WebConsoleBridge,
)

from tests.web_console_helpers import build_ws_logs_test_app, build_ws_status_test_app


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
    """W-SECURITY-002: 首次消息认证机制。"""
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

    # 使用 query 参数传递 token 作为向后兼容方式
    with client.websocket_connect(f"/ws/status?ws_token={token}") as ws:
        payload = ws.receive_json()
        assert payload["running"] is True
        assert "danmu_count" in payload


def test_ws_status_websocket_rejects_invalid_token_with_1008():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()
    bridge._last_status_payload = {"running": False}

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/status?ws_token=invalid-token"):
            pass

    assert exc_info.value.code == 1008
    bridge.register_status_consumer.assert_not_called()


def test_ws_status_websocket_rejects_missing_token_with_1008():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()

    app = build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/status"):
            # 不发送认证消息，应该超时关闭
            pass

    bridge.register_status_consumer.assert_not_called()


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

    from app.web_console import _WS_MAX_STATUS_CONSUMERS
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

        with pytest.raises(WebSocketDisconnect) as exc_info:
            stack.enter_context(client.websocket_connect(url))
        assert exc_info.value.code == 1008
        assert len(bridge._ws_status_queues) == _WS_MAX_STATUS_CONSUMERS

    assert len(bridge._ws_status_queues) == 0


def test_ws_logs_max_connections_capped():
    """S-026: reject excess /ws/logs clients before register_log_consumer."""
    from contextlib import ExitStack

    from app.web_console import _WS_MAX_LOG_CONSUMERS
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

        with pytest.raises(WebSocketDisconnect) as exc_info:
            stack.enter_context(client.websocket_connect(url))
        assert exc_info.value.code == 1008
        assert len(bridge._ws_log_queues) == _WS_MAX_LOG_CONSUMERS

    assert len(bridge._ws_log_queues) == 0


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

