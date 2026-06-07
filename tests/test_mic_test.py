import struct
import time
from unittest.mock import MagicMock

import pytest
from app.mic_test import clamp_test_duration, capture_mic_sample, pcm_metrics, run_mic_test
from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_clamp_test_duration():
    assert clamp_test_duration(0.5) == 2.0
    assert clamp_test_duration(3) == 3.0
    assert clamp_test_duration(99) == 8.0


def test_pcm_metrics_silent():
    pcm = struct.pack("<100h", *([0] * 100))
    rms, peak = pcm_metrics(pcm)
    assert rms == 0
    assert peak == 0


def test_pcm_metrics_nonzero():
    pcm = struct.pack("<4h", 1000, -2000, 500, 0)
    rms, peak = pcm_metrics(pcm)
    assert peak == 2000
    assert rms > 0


def test_run_mic_test_unavailable(monkeypatch):
    monkeypatch.setattr("app.mic_test.MicCaptureService.is_available", staticmethod(lambda: False))
    svc = MagicMock()
    result = run_mic_test(svc, keep_running=False)
    assert result.ok is False
    assert result.error == "sounddevice_unavailable"


def test_capture_mic_sample_does_not_block_main_thread(qapp, monkeypatch):
    monkeypatch.setattr("app.mic_test.MicCaptureService.is_available", staticmethod(lambda: True))

    timer_fired = {"value": False}

    def on_timeout():
        timer_fired["value"] = True

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(on_timeout)
    timer.start(50)

    svc = MagicMock()
    svc.is_running.return_value = True
    svc.snapshot_pcm.return_value = struct.pack("<100h", *([1000] * 100))

    _, result = capture_mic_sample(svc, duration_sec=2.0, keep_running=True)

    assert timer_fired["value"] is True
    assert result.pcm_bytes > 0
    timer.stop()
