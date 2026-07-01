"""Tests for app.mic_capture — start/stop/error behaviour."""

from app.mic_capture import MicCaptureService


def test_mic_capture_start_without_sounddevice_sets_error(monkeypatch):
    """BUG-015: sounddevice 未安装时 start() 返回 False 且 last_error 非空。"""
    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", False)
    cap = MicCaptureService()
    result = cap.start()
    assert result is False
    assert cap.last_error == "sounddevice not installed"
