"""W-TEST-COVER-013: diagnostics SSE route registration smoke test (no live stream)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.application.diagnostics_hub import DiagnosticsHub
from app.web_api.auth import require_auth
from app.web_api.routes import register_diagnostics_sse_route
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

VALID_SSE_TOKEN = "test-token"


def _make_sse_app(check_token):
    app = FastAPI()
    hub = DiagnosticsHub()
    hub.set_loop(asyncio.new_event_loop())
    bridge = SimpleNamespace(
        danmu_app=SimpleNamespace(
            build_diagnostic_snapshot=MagicMock(
                return_value={"scheduler": {}, "timing": {}, "runtime_state": {}, "diagnosis": {}}
            )
        ),
        invoke_on_main=lambda fn: fn(),
        publish_diagnostic_snapshot=lambda: None,
    )
    register_diagnostics_sse_route(app, hub, bridge, check_token)
    return app, hub


def _strict_check_token(authorization: str | None = None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    if authorization.removeprefix("Bearer ").strip() != VALID_SSE_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


def test_diagnostics_sse_route_registered_on_app():
    app, hub = _make_sse_app(lambda _authorization=None: None)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert "/api/diagnostics/events" in paths
    hub._loop.close()


def test_diagnostics_sse_events_requires_auth():
    app, hub = _make_sse_app(_strict_check_token)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/diagnostics/events")
    assert response.status_code == 401

    hub._loop.close()


def test_diagnostics_sse_events_rejects_invalid_token():
    app, hub = _make_sse_app(_strict_check_token)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/diagnostics/events",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 403

    hub._loop.close()


def test_diagnostics_sse_events_rejects_query_token():
    app, hub = _make_sse_app(_strict_check_token)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(f"/api/diagnostics/events?token={VALID_SSE_TOKEN}")
    assert response.status_code == 401

    hub._loop.close()


def test_diagnostics_sse_events_accepts_valid_bearer_token():
    """Bearer 鉴权 + 有限 SSE 响应；避免真实无限流阻塞 TestClient。"""
    app = FastAPI()

    @app.get("/api/diagnostics/events")
    @require_auth(_strict_check_token)
    async def diagnostics_events(authorization: str | None = Header(default=None)):
        async def finite_stream():
            yield 'event: hello\ndata: {"event":"hello"}\n\n'

        return StreamingResponse(finite_stream(), media_type="text/event-stream")

    client = TestClient(app, raise_server_exceptions=False)
    with client.stream(
        "GET",
        "/api/diagnostics/events",
        headers={"Authorization": f"Bearer {VALID_SSE_TOKEN}"},
    ) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        lines = list(response.iter_lines())
    assert any(line.startswith("event: hello") for line in lines)
