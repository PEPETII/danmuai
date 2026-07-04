"""global_exception_hook / threading_exception_hook 软化行为测试（H2）。"""

from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.main_launch import (
    global_exception_hook,
    register_unhandled_exception_notifier,
    threading_exception_hook,
)


@pytest.fixture(autouse=True)
def _reset_notifier():
    register_unhandled_exception_notifier(None)
    yield
    register_unhandled_exception_notifier(None)


def _call_hook(exc: BaseException) -> None:
    exc_type = type(exc)
    global_exception_hook(exc_type, exc, exc.__traceback__)


def test_keyboard_interrupt_passes_through():
    with patch.object(sys, "exit") as mock_exit:
        _call_hook(KeyboardInterrupt())
    mock_exit.assert_not_called()


def test_system_exit_passes_through():
    with patch.object(sys, "exit") as mock_exit:
        _call_hook(SystemExit(0))
    mock_exit.assert_not_called()


def test_qt_deleted_runtime_error_ignored():
    notifier = MagicMock()
    register_unhandled_exception_notifier(notifier)
    with patch.object(sys, "exit") as mock_exit:
        _call_hook(RuntimeError("wrapped C/C++ object of type QWidget has been deleted"))
    mock_exit.assert_not_called()
    notifier.assert_not_called()


def test_memory_error_exits():
    with patch.object(sys, "exit") as mock_exit:
        _call_hook(MemoryError("out of memory"))
    mock_exit.assert_called_once_with(1)


def test_recoverable_exception_with_notifier_does_not_exit():
    notifier = MagicMock()
    register_unhandled_exception_notifier(notifier)
    with patch.object(sys, "exit") as mock_exit:
        _call_hook(RuntimeError("transient failure"))
    mock_exit.assert_not_called()
    notifier.assert_called_once()


def test_recoverable_exception_without_notifier_exits():
    with patch.object(sys, "exit") as mock_exit:
        _call_hook(RuntimeError("startup failure"))
    mock_exit.assert_called_once_with(1)


def _make_thread_hook_args(exc: BaseException) -> threading.ExceptHookArgs:
    return threading.ExceptHookArgs(
        (type(exc), exc, exc.__traceback__, threading.current_thread())
    )


def test_threading_hook_does_not_exit_without_notifier():
    with patch.object(sys, "exit") as mock_exit:
        threading_exception_hook(_make_thread_hook_args(RuntimeError("background failure")))
    mock_exit.assert_not_called()


def test_threading_hook_notifies_when_registered():
    notifier = MagicMock()
    register_unhandled_exception_notifier(notifier)
    with patch.object(sys, "exit") as mock_exit:
        threading_exception_hook(_make_thread_hook_args(RuntimeError("background failure")))
    mock_exit.assert_not_called()
    notifier.assert_called_once()


def test_threading_hook_single_shots_when_qapp_on_different_thread():
    notifier = MagicMock()
    register_unhandled_exception_notifier(notifier)
    mock_qapp = MagicMock()
    mock_qapp.thread.return_value = object()
    with patch.object(sys, "exit") as mock_exit:
        with patch("app.main_launch.QApplication.instance", return_value=mock_qapp):
            with patch("app.main_launch.QThread.currentThread", return_value=object()):
                with patch("app.main_launch.QTimer.singleShot") as mock_single_shot:
                    threading_exception_hook(
                        _make_thread_hook_args(RuntimeError("background failure"))
                    )
    mock_exit.assert_not_called()
    mock_single_shot.assert_called_once()
    assert mock_single_shot.call_args[0][1] is notifier
    notifier.assert_not_called()


def test_threading_memory_error_does_not_exit():
    notifier = MagicMock()
    register_unhandled_exception_notifier(notifier)
    with patch.object(sys, "exit") as mock_exit:
        with patch("app.main_launch.QTimer.singleShot"):
            threading_exception_hook(_make_thread_hook_args(MemoryError("thread oom")))
    mock_exit.assert_not_called()


def test_unhandled_exception_writes_frozen_log_when_frozen(monkeypatch):
    calls: list[str] = []

    def _capture(msg: str) -> None:
        calls.append(msg)

    monkeypatch.setattr("app.main_launch.append_frozen_log", _capture)
    with patch.object(sys, "exit"):
        _call_hook(RuntimeError("startup failure"))
    assert len(calls) == 1
    assert "UNHANDLED EXCEPTION" in calls[0]
    assert "startup failure" in calls[0]
