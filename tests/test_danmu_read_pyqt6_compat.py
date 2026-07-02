"""PyQt6 兼容性回归测试：验证 _service_alive / _emit_tts_ready / _emit_tts_failed
在 PyQt6（sip 绑定）环境下正确工作，不依赖 PySide6 的 shiboken6。
"""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication


class _FakeService(QObject):
    _tts_ready = pyqtSignal(bytes)
    _tts_failed = pyqtSignal(str)
    _shutdown = False


class _FakeServiceShutdown(QObject):
    _tts_ready = pyqtSignal(bytes)
    _tts_failed = pyqtSignal(str)
    _shutdown = True


# --------------------------------------------------------------------------- #
# _service_alive
# --------------------------------------------------------------------------- #


def test_service_alive_sip_not_deleted():
    from app.danmu_read_service import _service_alive

    with patch("PyQt6.sip.isdeleted", return_value=False):
        assert _service_alive(_FakeService()) is True  # type: ignore[arg-type]


def test_service_alive_sip_deleted():
    from app.danmu_read_service import _service_alive

    with patch("PyQt6.sip.isdeleted", return_value=True):
        assert _service_alive(_FakeService()) is False  # type: ignore[arg-type]


def test_service_alive_none():
    from app.danmu_read_service import _service_alive

    assert _service_alive(None) is False


def test_service_alive_shutdown():
    from app.danmu_read_service import _service_alive

    assert _service_alive(_FakeServiceShutdown()) is False  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# _emit_tts_ready / _emit_tts_failed
# --------------------------------------------------------------------------- #


def test_emit_tts_ready_emits_when_alive():
    QApplication.instance() or QApplication([])
    from app.danmu_read_service import _emit_tts_ready

    service = _FakeService()
    received: list[bytes] = []
    service._tts_ready.connect(received.append)

    with patch("PyQt6.sip.isdeleted", return_value=False):
        _emit_tts_ready(service, b"wav_data")

    assert received == [b"wav_data"]


def test_emit_tts_ready_silenced_when_deleted():
    QApplication.instance() or QApplication([])
    from app.danmu_read_service import _emit_tts_ready

    service = _FakeService()
    received: list[bytes] = []
    service._tts_ready.connect(received.append)

    with patch("PyQt6.sip.isdeleted", return_value=True):
        _emit_tts_ready(service, b"wav_data")

    assert received == []


def test_emit_tts_failed_emits_when_alive():
    QApplication.instance() or QApplication([])
    from app.danmu_read_service import _emit_tts_failed

    service = _FakeService()
    received: list[str] = []
    service._tts_failed.connect(received.append)

    with patch("PyQt6.sip.isdeleted", return_value=False):
        _emit_tts_failed(service, "error message")

    assert received == ["error message"]


def test_emit_tts_failed_silenced_when_deleted():
    QApplication.instance() or QApplication([])
    from app.danmu_read_service import _emit_tts_failed

    service = _FakeService()
    received: list[str] = []
    service._tts_failed.connect(received.append)

    with patch("PyQt6.sip.isdeleted", return_value=True):
        _emit_tts_failed(service, "error message")

    assert received == []
