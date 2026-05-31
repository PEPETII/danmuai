"""Tests for app.startup_trace."""

from __future__ import annotations

from unittest.mock import patch

from app import startup_trace
from app.startup_trace import log_startup, mark_app_start, web_console_ready_timeout


def test_mark_app_start_and_log_startup_monotonic_ms():
    startup_trace._ORIGIN = None
    mark_app_start()
    log_startup("phase.a")
    log_startup("phase.b", ok=True)
    assert startup_trace._ORIGIN is not None
    assert startup_trace._elapsed_ms() >= 0.0


def test_web_console_ready_timeout_dev():
    with patch("app.startup_trace.is_frozen", return_value=False):
        assert web_console_ready_timeout() == 12.0


def test_web_console_ready_timeout_frozen():
    with patch("app.startup_trace.is_frozen", return_value=True):
        assert web_console_ready_timeout() == 10.0


def test_log_startup_writes_file_when_trace_env(tmp_path, monkeypatch):
    startup_trace._ORIGIN = None
    mark_app_start()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("DANMU_STARTUP_TRACE", "1")
    with patch("app.startup_trace.is_frozen", return_value=False):
        log_startup("test.phase", flag=1)

    log_file = tmp_path / "DanmuAI" / "startup.log"
    assert log_file.is_file()
    text = log_file.read_text(encoding="utf-8")
    assert "test.phase" in text
    assert "flag=1" in text


def test_log_startup_frozen_uses_append_frozen_log(monkeypatch):
    startup_trace._ORIGIN = None
    mark_app_start()
    calls: list[str] = []

    def _capture(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr("app.startup_trace.append_frozen_log", _capture)
    with patch("app.startup_trace.is_frozen", return_value=True):
        log_startup("frozen.phase")

    assert len(calls) == 1
    assert "frozen.phase" in calls[0]
