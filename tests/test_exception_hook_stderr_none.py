"""BUG-003: global_exception_hook must not crash when stderr=None and SanitizedLogger fails."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from app.main_launch import global_exception_hook, register_unhandled_exception_notifier


@pytest.fixture(autouse=True)
def _reset_notifier():
    register_unhandled_exception_notifier(None)
    yield
    register_unhandled_exception_notifier(None)


def _call_hook(exc: BaseException) -> None:
    exc_type = type(exc)
    global_exception_hook(exc_type, exc, exc.__traceback__)


def test_global_exception_hook_survives_stderr_none_when_logger_fails(monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)

    class BrokenLogger:
        def error(self, _message: str) -> None:
            raise RuntimeError("logger unavailable")

    monkeypatch.setattr("app.main_launch.SanitizedLogger", BrokenLogger)

    with patch.object(sys, "exit") as mock_exit:
        _call_hook(RuntimeError("frozen startup failure"))

    mock_exit.assert_called_once_with(1)


def test_global_exception_hook_fallback_writes_frozen_log_when_logger_fails(monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)

    class BrokenLogger:
        def error(self, _message: str) -> None:
            raise RuntimeError("logger unavailable")

    monkeypatch.setattr("app.main_launch.SanitizedLogger", BrokenLogger)

    calls: list[str] = []

    def _capture(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr("app.main_launch.append_frozen_log", _capture)

    with patch.object(sys, "exit"):
        _call_hook(RuntimeError("frozen startup failure"))

    assert any("FATAL:" in msg for msg in calls)
    assert any("UNHANDLED EXCEPTION" in msg for msg in calls)
    assert any("frozen startup failure" in msg for msg in calls)


def test_global_exception_hook_skips_print_when_stderr_none(monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)

    class BrokenLogger:
        def error(self, _message: str) -> None:
            raise RuntimeError("logger unavailable")

    monkeypatch.setattr("app.main_launch.SanitizedLogger", BrokenLogger)
    print_mock = MagicMock()
    monkeypatch.setattr("builtins.print", print_mock)

    with patch.object(sys, "exit"):
        _call_hook(RuntimeError("no stderr path"))

    print_mock.assert_not_called()
