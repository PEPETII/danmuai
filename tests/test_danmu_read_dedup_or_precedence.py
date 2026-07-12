"""Tests for dedup logic in DanmuReadService._on_tick.

Verifies that when all candidates equal _last_text, _on_tick returns early
instead of falling back to the full list. Also verifies partial duplication
only picks from non-duplicate candidates.
"""

from unittest.mock import MagicMock

import pytest

from app.danmu_read_service import DanmuReadService
from app.tts_providers import ResolvedTtsConfig


def _make_service(qapp):
    """Construct a real DanmuReadService on a minimal DanmuApp shell."""
    from PyQt6.QtCore import QObject

    from main import DanmuApp
    from tests.conftest import bind_minimal_danmu_app
    from tests.fakes import FakeConfig

    app = DanmuApp.__new__(DanmuApp)
    QObject.__init__(app)
    bind_minimal_danmu_app(app)
    config = FakeConfig({"danmu_read_enabled": "1"})
    config.get_tts_api_key = lambda: "sk-test"
    object.__setattr__(app, "config", config)
    app.engine.running = True
    service = DanmuReadService(app)
    return service


def test_on_tick_all_duplicates_returns_early(qapp, monkeypatch):
    """When every visible text equals _last_text, _on_tick returns without picking."""
    service = _make_service(qapp)
    service._last_text = "same"
    monkeypatch.setattr(service._playback, "is_busy", lambda: False)
    monkeypatch.setattr(
        service._app.engine, "visible_display_texts", lambda: ["same", "same", "same"], raising=False
    )

    service._on_tick()

    assert service._last_text == "same"
    assert service._tts_in_flight is False


def test_on_tick_partial_duplicates_chooses_non_duplicate(qapp, monkeypatch):
    """When some texts duplicate _last_text, only non-duplicates are eligible."""
    service = _make_service(qapp)
    service._last_text = "old"
    monkeypatch.setattr(service._playback, "is_busy", lambda: False)
    monkeypatch.setattr(
        service._app.engine, "visible_display_texts", lambda: ["old", "new1", "new2"], raising=False
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

    captured_runnables = []
    fake_pool = MagicMock()
    fake_pool.start = captured_runnables.append
    monkeypatch.setattr(
        "app.danmu_read_service.QThreadPool.globalInstance", lambda: fake_pool
    )

    service._on_tick()

    assert service._tts_in_flight is True
    assert service._last_text in ("new1", "new2")
    assert service._last_text != "old"
    assert len(captured_runnables) == 1
