"""TTS 播放生命周期：正常完成、停止、输出错误与 shutdown 清理。"""

from __future__ import annotations

import io
import threading
import time
import wave

from app.danmu_read_service import DanmuReadService
from app.danmu_tts_playback import DanmuTtsPlayback

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def _fake_wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"\x00\x00" * 240)
    return buf.getvalue()


def _make_read_service(qapp, *, engine_running: bool = True) -> DanmuReadService:
    from main import DanmuApp
    from PyQt6.QtCore import QObject

    app = DanmuApp.__new__(DanmuApp)
    QObject.__init__(app)
    bind_minimal_danmu_app(app)
    config = FakeConfig({"danmu_read_enabled": "0"})
    config.get_tts_api_key = lambda: ""
    object.__setattr__(app, "config", config)
    app.engine.running = engine_running
    return DanmuReadService(app)


def _wait_for_event(event: threading.Event, timeout: float = 5.0) -> None:
    assert event.wait(timeout=timeout)


def test_playback_success_emits_finished_only(qapp, monkeypatch):
    playback = DanmuTtsPlayback()
    finished: list[int] = []
    failed: list[int] = []
    stopped: list[int] = []
    playback.playback_finished.connect(finished.append)
    playback.playback_failed.connect(failed.append)
    playback.playback_stopped.connect(stopped.append)

    monkeypatch.setattr("app.danmu_tts_playback.sd.play", lambda *a, **k: None)
    monkeypatch.setattr("app.danmu_tts_playback.sd.wait", lambda: None)

    playback_id = playback.play_wav_bytes(_fake_wav_bytes())
    assert playback_id > 0
    deadline = time.time() + 5.0
    while time.time() < deadline and not finished:
        qapp.processEvents()
        time.sleep(0.01)

    assert finished == [playback_id]
    assert failed == []
    assert stopped == []


def test_playback_output_error_emits_failed_not_finished(qapp, monkeypatch):
    playback = DanmuTtsPlayback()
    finished: list[int] = []
    failed: list[int] = []
    stopped: list[int] = []
    playback.playback_finished.connect(finished.append)
    playback.playback_failed.connect(failed.append)
    playback.playback_stopped.connect(stopped.append)

    def _raise_oserror(*_args, **_kwargs):
        raise OSError("audio device unavailable")

    monkeypatch.setattr("app.danmu_tts_playback.sd.play", _raise_oserror)

    playback_id = playback.play_wav_bytes(_fake_wav_bytes())
    assert playback_id > 0
    deadline = time.time() + 5.0
    while time.time() < deadline and not failed:
        qapp.processEvents()
        time.sleep(0.01)

    assert failed == [playback_id]
    assert finished == []
    assert stopped == []
    assert not playback.is_busy()


def test_playback_stop_emits_stopped_not_finished(qapp, monkeypatch):
    playback = DanmuTtsPlayback()
    finished: list[int] = []
    failed: list[int] = []
    stopped: list[int] = []
    playback.playback_finished.connect(finished.append)
    playback.playback_failed.connect(failed.append)
    playback.playback_stopped.connect(stopped.append)

    worker_started = threading.Event()
    worker_block = threading.Event()

    def _blocking_play(*_args, **_kwargs):
        worker_started.set()
        worker_block.wait(timeout=5.0)

    monkeypatch.setattr("app.danmu_tts_playback.sd.play", _blocking_play)
    monkeypatch.setattr("app.danmu_tts_playback.sd.wait", lambda: worker_block.wait(timeout=5.0))

    playback_id = playback.play_wav_bytes(_fake_wav_bytes())
    assert playback_id > 0
    _wait_for_event(worker_started)
    playback.stop()
    worker_block.set()

    deadline = time.time() + 5.0
    while time.time() < deadline and not stopped:
        qapp.processEvents()
        time.sleep(0.01)

    assert stopped == [playback_id]
    assert finished == []
    assert failed == []
    assert not playback.is_busy()


def test_playback_stop_is_idempotent(qapp, monkeypatch):
    playback = DanmuTtsPlayback()
    monkeypatch.setattr("app.danmu_tts_playback.sd.stop", lambda: None)
    playback.stop()
    playback.stop()
    assert not playback.is_busy()


def test_shutdown_stops_active_playback_and_clears_in_flight(qapp, monkeypatch):
    service = _make_read_service(qapp)
    worker_started = threading.Event()
    worker_block = threading.Event()

    def _blocking_play(*_args, **_kwargs):
        worker_started.set()
        worker_block.wait(timeout=5.0)

    monkeypatch.setattr("app.danmu_tts_playback.sd.play", _blocking_play)
    monkeypatch.setattr(
        "app.danmu_tts_playback.sd.wait",
        lambda: worker_block.wait(timeout=5.0),
    )

    service._tts_in_flight = True
    service._on_tts_ready(_fake_wav_bytes())
    assert service._playback.is_busy()
    assert service._tts_in_flight
    _wait_for_event(worker_started)

    service.shutdown()
    assert not service._playback.is_busy()
    assert not service._tts_in_flight
    assert service._shutdown

    worker_block.set()
    deadline = time.time() + 5.0
    while time.time() < deadline and service._playback.is_busy():
        qapp.processEvents()
        time.sleep(0.01)


def test_on_engine_stopped_stops_active_playback(qapp, monkeypatch):
    service = _make_read_service(qapp)
    worker_started = threading.Event()
    worker_block = threading.Event()

    def _blocking_play(*_args, **_kwargs):
        worker_started.set()
        worker_block.wait(timeout=5.0)

    monkeypatch.setattr("app.danmu_tts_playback.sd.play", _blocking_play)
    monkeypatch.setattr(
        "app.danmu_tts_playback.sd.wait",
        lambda: worker_block.wait(timeout=5.0),
    )

    service._tts_in_flight = True
    service._on_tts_ready(_fake_wav_bytes())
    _wait_for_event(worker_started)
    service.on_engine_stopped()

    assert not service._playback.is_busy()
    assert not service._tts_in_flight
    worker_block.set()


def test_read_service_shutdown_is_idempotent(qapp):
    service = _make_read_service(qapp)
    service.shutdown()
    service.shutdown()
    assert service._shutdown
    assert not service._tts_in_flight


def test_playback_failed_clears_read_service_in_flight(qapp, monkeypatch):
    service = _make_read_service(qapp)

    def _raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("output stream closed")

    monkeypatch.setattr("app.danmu_tts_playback.sd.play", _raise_runtime_error)

    service._tts_in_flight = True
    service._on_tts_ready(_fake_wav_bytes())
    assert service._playback.is_busy()

    deadline = time.time() + 5.0
    while time.time() < deadline and service._tts_in_flight:
        qapp.processEvents()
        time.sleep(0.01)

    assert not service._tts_in_flight
