"""Shared helpers for web console pytest modules (T008)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from app.web_console import WebConsoleBridge, save_config_via_bridge


def make_status_app():
    app = MagicMock()
    app.build_status_snapshot.return_value = {
        "running": False,
        "danmu_count": 0,
        "queue_count": 0,
        "display_count": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "runtime_sec": 0.0,
        "error_message": "",
        "is_error": False,
        "live_analyzing": False,
        "live_local_fallback": False,
        "live_delay_sec": 0.0,
        "live_message": "",
        "persona_names": [],
        "screen_index": 0,
        "has_api_key": True,
        "dedup_profile": None,
        "lifetime_danmu_count": 0,
        "lifetime_runtime_sec": 0.0,
        "lifetime_total_tokens": 0,
        "lifetime_input_tokens": 0,
        "lifetime_output_tokens": 0,
        "session_runs": [
            {
                "started_at": 1000.0,
                "ended_at": 1060.0,
                "model": "gpt-test",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "danmu_count": 2,
            }
        ],
    }
    return app


def pump_qt_until(qt_app, *, invoke_worker=None, extra_thread=None) -> None:
    """Process Qt events until QThread worker and optional threading.Thread finish."""
    while True:
        running_invoke = invoke_worker is not None and invoke_worker.isRunning()
        running_extra = extra_thread is not None and extra_thread.is_alive()
        if not running_invoke and not running_extra:
            break
        qt_app.processEvents()
        if invoke_worker is not None:
            invoke_worker.wait(50)
        if extra_thread is not None:
            extra_thread.join(0.05)


def build_ws_status_test_app(bridge, token: str):
    """Mirror WebConsoleServer WebSocketRoute registration for /ws/status."""
    from app.web_console_ws import register_websocket_routes
    from fastapi import FastAPI, WebSocketDisconnect
    from starlette.routing import WebSocketRoute

    app = FastAPI()
    register_websocket_routes(app, bridge, token, WebSocketRoute, WebSocketDisconnect)
    return app


def build_ws_logs_test_app(bridge, token: str):
    """Mirror WebConsoleServer WebSocketRoute registration for /ws/logs."""
    from app.web_console_ws import register_websocket_routes
    from fastapi import FastAPI, WebSocketDisconnect
    from starlette.routing import WebSocketRoute

    app = FastAPI()
    register_websocket_routes(app, bridge, token, WebSocketRoute, WebSocketDisconnect)
    return app


__all__ = [
    "build_ws_logs_test_app",
    "build_ws_status_test_app",
    "make_status_app",
    "pump_qt_until",
    "save_config_via_bridge",
    "WebConsoleBridge",
]
