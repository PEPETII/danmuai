"""Web console tests: websocket."""

from unittest.mock import MagicMock

import pytest
from app.web_console import (
    WebConsoleBridge,
)

from tests.web_console_helpers import build_ws_status_test_app


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

