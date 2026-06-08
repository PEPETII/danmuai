from __future__ import annotations

from types import SimpleNamespace

from app.application.diagnostic_snapshot import DiagnosticSnapshotBuilder, build_diagnostic_report
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig, FakeEngine, FakeLogger


def make_diagnostic_app(**overrides):
    app = DanmuApp.__new__(DanmuApp)
    defaults = {
        "logger": FakeLogger(),
        "engine": FakeEngine(),
        "config": FakeConfig(),
        "personae": SimpleNamespace(get_active=lambda: []),
    }
    defaults.update(overrides)
    bind_minimal_danmu_app(app, **defaults)
    if not hasattr(app.config, "get_api_key"):
        object.__setattr__(app.config, "get_api_key", lambda: "")

    for name in (
        "get_request_scheduler",
        "get_request_timing_service",
        "_api_schedule_block_reason",
        "_rtt_avg",
        "_smart_cooldown_ms",
        "build_diagnostic_snapshot",
        "build_diagnostic_report",
        "build_status_snapshot",
    ):
        object.__setattr__(app, name, getattr(DanmuApp, name).__get__(app, DanmuApp))

    object.__setattr__(app, "_has_visual_request_in_flight", lambda: False)
    object.__setattr__(app, "_build_live_status_snapshot", lambda: None)
    app.engine.running = False
    return app


def read_sse_lines(client, *, max_lines: int = 8, timeout_sec: float = 5.0, token: str | None = None):
    """Sync TestClient 在无限 SSE 上会阻塞；在线程中读取若干行后 close。"""
    import concurrent.futures

    def _read():
        url = "/api/diagnostics/events"
        if token:
            url += f"?token={token}"
        with client.stream("GET", url) as response:
            status_code = response.status_code
            headers = dict(response.headers)
            lines: list[str] = []
            for line in response.iter_lines():
                lines.append(line)
                if len(lines) >= max_lines:
                    break
            response.close()
            return status_code, headers, lines

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_read).result(timeout=timeout_sec)


__all__ = [
    "DiagnosticSnapshotBuilder",
    "build_diagnostic_report",
    "make_diagnostic_app",
    "read_sse_lines",
]
