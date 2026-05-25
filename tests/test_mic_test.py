import struct
from unittest.mock import MagicMock

from app.mic_test import clamp_test_duration, pcm_metrics, run_mic_test


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
