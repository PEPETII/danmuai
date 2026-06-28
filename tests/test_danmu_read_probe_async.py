"""Tests for BUG-004: DanmuReadService.run_probe is async (no sync synthesize_tts).

Verifies that run_probe validates synchronously and returns immediately, then
submits a _DanmuTtsRunnable to QThreadPool without calling synthesize_tts in
the calling thread. Also covers _on_tts_ready probe bypass and _on_tts_failed
state cleanup.
"""

import threading
from unittest.mock import MagicMock

import pytest

from app.danmu_read_service import DanmuReadService
from app.danmu_tts import ResolvedTtsConfig


def _make_service(qapp):
    """Construct a real DanmuReadService on a minimal DanmuApp shell."""
    from PyQt6.QtCore import QObject

    from main import DanmuApp
    from tests.conftest import bind_minimal_danmu_app
    from tests.fakes import FakeConfig

    app = DanmuApp.__new__(DanmuApp)
    QObject.__init__(app)
    bind_minimal_danmu_app(app)
    config = FakeConfig({"danmu_read_enabled": "0"})
    # FakeConfig lacks get_tts_api_key; provide it returning empty by default
    config.get_tts_api_key = lambda: ""
    object.__setattr__(app, "config", config)
    service = DanmuReadService(app)
    return service


def test_run_probe_returns_immediately_without_sync_synthesize(qapp, monkeypatch):
    """run_probe submits to QThreadPool and returns without calling synthesize_tts."""
    service = _make_service(qapp)
    monkeypatch.setattr(service._playback, "is_busy", lambda: False)

    synthesize_calls = []

    def fake_synthesize(*args, **kwargs):
        synthesize_calls.append(threading.current_thread().name)
        return b"FAKE_WAV"

    monkeypatch.setattr("app.danmu_read_service.synthesize_tts", fake_synthesize)

    captured_runnables = []
    fake_pool = MagicMock()
    fake_pool.start = captured_runnables.append
    monkeypatch.setattr(
        "app.danmu_read_service.QThreadPool.globalInstance", lambda: fake_pool
    )

    resolved = ResolvedTtsConfig(
        provider="mimo",
        endpoint="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5",
        is_custom=False,
        stored_provider="",
        stored_endpoint="",
        stored_model_id="",
    )
    monkeypatch.setattr(
        "app.danmu_read_service.resolve_tts_config", lambda *a, **k: resolved
    )
    monkeypatch.setattr(
        "app.danmu_read_service.normalize_tts_voice", lambda *a, **k: "voice1"
    )

    result = service.run_probe(api_key_override="sk-test")

    assert result["ok"] is True
    assert "试听已提交" in result["message"]
    assert synthesize_calls == []
    assert len(captured_runnables) == 1
    assert service._tts_in_flight is True
    assert service._probe_pending is True


def test_run_probe_no_api_key_returns_synchronously(qapp):
    """run_probe returns failure when no API key is available."""
    service = _make_service(qapp)

    result = service.run_probe()

    assert result["ok"] is False
    assert "API Key" in result["message"]
    assert service._tts_in_flight is False
    assert service._probe_pending is False


def test_run_probe_busy_returns_synchronously(qapp, monkeypatch):
    """run_probe returns failure when playback is busy."""
    service = _make_service(qapp)
    monkeypatch.setattr(service._playback, "is_busy", lambda: True)

    result = service.run_probe(api_key_override="sk-test")

    assert result["ok"] is False
    assert "稍后再试听" in result["message"]
    assert service._tts_in_flight is False
    assert service._probe_pending is False


def test_run_probe_bad_config_returns_synchronously(qapp, monkeypatch):
    """run_probe returns failure when resolve_tts_config raises ValueError."""
    service = _make_service(qapp)
    monkeypatch.setattr(service._playback, "is_busy", lambda: False)

    def raise_bad_config(*args, **kwargs):
        raise ValueError("bad config")

    monkeypatch.setattr(
        "app.danmu_read_service.resolve_tts_config", raise_bad_config
    )

    result = service.run_probe(api_key_override="sk-test")

    assert result["ok"] is False
    assert result["message"] == "bad config"
    assert service._tts_in_flight is False
    assert service._probe_pending is False


def test_on_tts_ready_plays_probe_wav_when_engine_stopped(qapp, monkeypatch):
    """_on_tts_ready plays probe WAV even when engine is stopped."""
    service = _make_service(qapp)
    service._probe_pending = True
    service._tts_in_flight = True
    service._app.engine.running = False

    play_calls = []

    def fake_play(wav):
        play_calls.append(wav)
        return True

    monkeypatch.setattr(service._playback, "play_wav_bytes", fake_play)

    service._on_tts_ready(b"FAKE_WAV")

    assert play_calls == [b"FAKE_WAV"]
    assert service._probe_pending is False
    assert service._tts_in_flight is True


def test_on_tts_ready_drops_tick_wav_when_engine_stopped(qapp, monkeypatch):
    """_on_tts_ready drops non-probe WAV when engine is stopped."""
    service = _make_service(qapp)
    service._probe_pending = False
    service._tts_in_flight = True
    service._app.engine.running = False

    play_calls = []

    def fake_play(wav):
        play_calls.append(wav)
        return True

    monkeypatch.setattr(service._playback, "play_wav_bytes", fake_play)

    service._on_tts_ready(b"FAKE_WAV")

    assert play_calls == []
    assert service._tts_in_flight is False
    assert any(
        "tts_ready dropped" in msg for msg in service._app.logger.warning_messages
    )


def test_on_tts_failed_clears_probe_pending(qapp):
    """_on_tts_failed clears both _tts_in_flight and _probe_pending."""
    service = _make_service(qapp)
    service._probe_pending = True
    service._tts_in_flight = True

    service._on_tts_failed("boom")

    assert service._tts_in_flight is False
    assert service._probe_pending is False
