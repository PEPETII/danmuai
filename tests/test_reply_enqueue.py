"""Main flow tests: reply enqueue, lifecycle, and persona."""

import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, normalize_danmu_display_text
from app.lifetime_stats import STATS_LIFETIME_RUNTIME_SEC, LifetimeStats
from app.overlay import DanmuOverlay
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from app.session_run_log import SessionRunLog
from main import DanmuApp, show_startup_notice_if_needed

from tests.conftest import (
    bind_minimal_danmu_app,
    make_app_for_start_without_api_key,
    make_minimal_danmu_app,
)
from tests.fakes import DedupFakeEngine, FakeConfig, FakeLogger, FakeSessionRunLog, FakeTimer


def test_normal_mode_enqueues_full_batch_without_prepend_replacement():
    app = make_minimal_danmu_app()
    app.config = FakeConfig({
        "danmu_display_mode": "normal",
        "normal_reply_count": "3",
        "reply_queue_max_items": "0",
    })
    app._sync_reply_batch_config()
    app.reply_buffer.set_max_items(app._queue_capacity())

    def enqueue_batch(items: list[str], batch_id: int):
        app._batch_id = batch_id
        app._enqueue_reply_batch(
            "p1",
            1,
            batch_id,
            time.monotonic(),
            0,
            items,
        )

    enqueue_batch(["a", "b"], 1)
    enqueue_batch(["c", "d"], 2)
    assert app.reply_buffer.size() == 4
    popped = [app.reply_buffer.pop().content for _ in range(4)]
    assert popped == ["a", "b", "c", "d"]


def test_normal_mode_consumes_all_non_duplicate_items():
    app = make_minimal_danmu_app()
    app.config = FakeConfig(
        {
            "danmu_display_mode": "normal",
            "drop_stale": "0",
        }
    )
    app._sync_reply_batch_config()
    app.engine = DedupFakeEngine("dup")
    app.engine.running = True
    now = time.monotonic()
    for idx, text in enumerate(["ok1", "dup", "ok2"]):
        app.reply_buffer.push(
            QueuedReply(
                "p1",
                1,
                idx,
                text,
                screenshot_id=1,
                captured_at=now,
                scene_generation=0,
            )
        )
    for _ in range(3):
        app._consume_reply_queue()
    assert [c[0] for c in app.engine.calls] == ["ok1", "ok2"]
    assert len(app.history_writer.calls) == 2


def test_duplicate_loss_topup_only_triggers_once_per_request(monkeypatch):
    app = make_minimal_danmu_app()
    app.config = FakeConfig(
        {
            "danmu_display_mode": "normal",
            "drop_stale": "0",
            "danmu_pool_use_custom": "1",
        }
    )
    app._sync_reply_batch_config()
    app.engine = DedupFakeEngine("dup")
    app.engine.running = True
    now = time.monotonic()
    for idx in range(2):
        app.reply_buffer.push(
            QueuedReply(
                "p1",
                1,
                idx,
                "dup",
                screenshot_id=1,
                captured_at=now,
                scene_generation=0,
                request_id="req-1",
            )
        )

    calls: list[int] = []
    original = app._maybe_duplicate_loss_topup

    def counting_topup(queued, stats):
        calls.append(int(stats["duplicate_loss_total"]))
        return original(queued, stats)

    app._maybe_duplicate_loss_topup = counting_topup
    app._consume_reply_queue()
    app._consume_reply_queue()

    assert calls == [1, 2]


def test_history_enqueue_matches_display_truncation():
    """BUG-015: history row content matches on-screen truncation."""
    app = make_minimal_danmu_app()
    app.config = FakeConfig({"danmu_max_chars": "8", "drop_stale": "0"})
    app.engine.running = True
    raw = "一二三四五六七八九十"
    expected = normalize_danmu_display_text(raw, app.config)
    now = time.monotonic()
    app.reply_buffer.push(
        QueuedReply(
            "p1",
            1,
            0,
            raw,
            screenshot_id=1,
            captured_at=now,
            scene_generation=0,
        )
    )
    app._consume_reply_queue()
    assert len(app.history_writer.calls) == 1
    assert app.history_writer.calls[0][0] == expected
    assert app.history_writer.calls[0][0] != raw


def test_inject_test_danmu_batch_reuses_history_truncation_path():
    app = make_minimal_danmu_app()
    app.config = FakeConfig({"danmu_max_chars": "8", "drop_stale": "0"})
    raw = "一二三四五六七八九十"
    expected = normalize_danmu_display_text(raw, app.config)

    result = app.inject_test_danmu_batch([raw], persona_id="验收")

    assert result["ok"] is True
    assert result["queued"] == 1
    assert result["expected_texts"] == [expected]
    assert result["visible_texts"] == []
    assert result["active_texts"] == []
    assert app.reply_buffer.is_empty()
    assert len(app.history_writer.calls) == 1
    assert app.history_writer.calls[0][0] == expected
    assert app.history_writer.calls[0][0] != raw


def test_inject_test_danmu_batch_rejects_empty_items():
    app = make_minimal_danmu_app()

    with pytest.raises(ValueError, match="请至少提供一条弹幕"):
        app.inject_test_danmu_batch(["", "   "])


def test_show_startup_notice_on_first_run(monkeypatch):
    from unittest.mock import MagicMock

    from PyQt6.QtWidgets import QMessageBox

    notice = "未找到配置文件，已创建默认配置，请先检查 API Key 等基础设置。"
    config = MagicMock()
    config.get_startup_notice.return_value = notice
    logger = FakeLogger()
    dialog_calls = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: dialog_calls.append(args),
    )

    assert show_startup_notice_if_needed(config, logger) is True
    assert len(dialog_calls) == 1
    assert dialog_calls[0][2] == notice
    assert any(notice in msg for msg in logger.info_messages)


def test_init_normalizes_legacy_realtime_display_mode_config(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "legacy_mode.db")
    store.set("danmu_display_mode", "realtime")
    store._normalize_legacy_display_mode()
    assert store.get("danmu_display_mode") == "normal"


def test_config_change_updates_overlay_font(workspace_tmp, qapp):
    """BUG-007: font_size change via _on_config_changed must refresh overlay font immediately."""
    del qapp
    store = ConfigStore(db_path=workspace_tmp / "font_overlay.db")
    store.set("font_size", "24")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "4")

    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    overlay = DanmuOverlay(store, engine)
    engine.overlay = overlay

    app = DanmuApp.__new__(DanmuApp)
    app.config = store
    app.engine = engine
    app.overlay = overlay
    app.web_runtime_state = WebRuntimeState(
        cached_danmu_lines=4,
        cached_layout_mode=store.get("layout_mode", "fullscreen"),
    )
    app.screenshot_timer = FakeTimer()
    app.reply_buffer = AIReplyFIFOBuffer(max_items=8)
    app.hotkey = Mock()
    app._sync_mic_service = lambda: None
    app._sync_reply_batch_config = DanmuApp._sync_reply_batch_config.__get__(app, DanmuApp)
    app._normal_recognition_interval_ms = DanmuApp._normal_recognition_interval_ms.__get__(
        app, DanmuApp
    )
    app._queue_capacity = DanmuApp._queue_capacity.__get__(app, DanmuApp)
    app._ensure_web_runtime_state = DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp)
    app._on_config_changed = DanmuApp._on_config_changed.__get__(app, DanmuApp)

    assert overlay.font.pointSize() == 24

    store.set("font_size", "36")
    app._on_config_changed()

    assert overlay.font.pointSize() == 36


def test_start_seeds_visibility_counts(workspace_tmp, monkeypatch):
    """BUG-003: after start + on-screen danmu, visible display_count must not stay 0."""
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda _a, _b: 50.0)
    monkeypatch.setattr("app.danmu_engine.random.choices", lambda population, **_kw: population[:1])

    store = ConfigStore(db_path=workspace_tmp / "bug003.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")

    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    engine.start()

    item = engine.add_text("hello", persona="p1")
    assert item is not None
    item.x = 100.0
    engine._refresh_item_visibility(item)

    assert engine.visible_display_count() > 0

    app = SimpleNamespace(
        engine=engine,
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: engine.visible_display_count(),
        stats_state=StatsState(danmu_count=0, start_time=time.monotonic()),
        web_runtime_state=WebRuntimeState(),
        personae=SimpleNamespace(get_active=lambda: []),
        config=store,
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
        _region_selection_state="idle",
    )
    status = DanmuApp.build_status_snapshot(app)
    assert status["display_count"] > 0


def test_startup_notice_skipped_when_not_first_run(monkeypatch):
    from unittest.mock import MagicMock

    from PyQt6.QtWidgets import QMessageBox

    config = MagicMock()
    config.get_startup_notice.return_value = ""
    logger = FakeLogger()
    dialog_calls = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: dialog_calls.append(args),
    )

    assert show_startup_notice_if_needed(config, logger) is False
    assert dialog_calls == []
    assert logger.info_messages == []


def test_init_language_uses_seeded_config_not_system_locale(tmp_path, monkeypatch):
    from app.config_defaults import DEFAULT_LANGUAGE, config_value_with_default
    from app.translations import Translator

    monkeypatch.setattr(Translator, "detect_system_language", lambda: "en")

    store = ConfigStore(db_path=tmp_path / "config.db")
    assert store.get("language") == DEFAULT_LANGUAGE

    resolved = Translator.resolve_language(
        config_value_with_default(store, "language")
    )
    assert resolved == DEFAULT_LANGUAGE

    store.close()


def test_start_without_api_key_does_not_start(monkeypatch):
    """BUG-009: start() must not start engine or timers when API key is missing."""
    app, engine_start_called, screenshot_timer, _tray = make_app_for_start_without_api_key(
        monkeypatch
    )
    DanmuApp.start(app)
    assert engine_start_called == []
    assert app.engine.running is False
    assert screenshot_timer.started == 0


def test_start_without_api_key_surfaces_ui_feedback(monkeypatch):
    """BUG-009: missing API key must set web error state and show tray hint."""
    from app.ai_client_requests import format_credential_error

    app, _engine_start_called, _screenshot_timer, tray = make_app_for_start_without_api_key(
        monkeypatch
    )
    DanmuApp.start(app)
    msg = format_credential_error(app.config)
    assert app.web_runtime_state.error_message == msg
    assert app.web_runtime_state.is_error is True
    tray.show_api_key_missing_hint.assert_called_once()


def test_start_without_api_key_updates_tray_state(monkeypatch):
    """BUG-022: missing API key must sync tray to stopped state."""
    app, _engine_start_called, _screenshot_timer, tray = make_app_for_start_without_api_key(
        monkeypatch
    )
    DanmuApp.start(app)
    tray.update_state.assert_called_once_with(running=False)


def _custom_model_only_config() -> FakeConfig:
    cfg = FakeConfig(
        {
            "api_endpoint": "",
            "default_model_id": "mimo-v2.5",
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "MiMo",
                "default_model_id": "mimo-v2.5",
                "modelId": "mimo-v2.5",
                "endpoint": "https://api.xiaomimimo.com/v1",
                "apiKey": "sk-mimo",
                "mode": "openai",
            }
        ]
    )
    return cfg


def _bind_start_success_stubs(app, monkeypatch) -> None:
    bind_minimal_danmu_app(
        app,
        config=app.config,
        engine=app.engine,
        screenshot_timer=app.screenshot_timer,
        reply_timer=FakeTimer(),
        _live_status_timer=FakeTimer(),
        _pool_topup_timer=FakeTimer(),
        _lifetime_flush_timer=FakeTimer(),
        _topmost_health_timer=FakeTimer(),
        session_run_log=FakeSessionRunLog(),
        ai_worker=MagicMock(),
        tray=app.tray,
    )
    object.__setattr__(
        app,
        "_ensure_stats_state",
        DanmuApp._ensure_stats_state.__get__(app, DanmuApp),
    )
    object.__setattr__(
        app,
        "_get_request_timing_service",
        DanmuApp._get_request_timing_service.__get__(app, DanmuApp),
    )
    object.__setattr__(
        app,
        "_get_request_scheduler",
        DanmuApp._get_request_scheduler.__get__(app, DanmuApp),
    )
    object.__setattr__(app, "_reset_scene_generation_baseline", lambda: None)
    object.__setattr__(app, "_normal_recognition_interval_ms", lambda: 5000)
    object.__setattr__(app, "_queue_capacity", lambda: 8)
    monkeypatch.setattr(DanmuApp, "_on_normal_capture_tick", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_sync_overlay_visibility", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_sync_floating_panel_visibility", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_sync_pet_window_visibility", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_reassert_active_overlay_topmost", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_start_meme_barrage_timers", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_sync_mic_service", lambda self: None)
    object.__setattr__(app, "state_changed", MagicMock())


def test_start_with_custom_model_key_only_no_global_key(monkeypatch):
    """Profile-only credentials must pass start() guard and start the engine."""
    app, engine_start_called, screenshot_timer, _tray = make_app_for_start_without_api_key(
        monkeypatch
    )
    object.__setattr__(app, "config", _custom_model_only_config())
    _bind_start_success_stubs(app, monkeypatch)
    DanmuApp.start(app)
    assert engine_start_called == [True]
    assert app.engine.running is True
    assert screenshot_timer.started == 1


def test_start_with_global_key_only_still_works(monkeypatch):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: legacy global API key is no longer a valid credential."""
    app, engine_start_called, screenshot_timer, _tray = make_app_for_start_without_api_key(
        monkeypatch
    )
    object.__setattr__(
        app,
        "config",
        FakeConfig(
            {
                "api_endpoint": "https://api.example.com/v1",
                "api_mode": "openai",
                "model": "gpt-4o",
                "default_model_id": "gpt-4o",
                "_api_key": "sk-global",
            },
        ),
    )
    _bind_start_success_stubs(app, monkeypatch)
    DanmuApp.start(app)
    assert engine_start_called == []
    assert app.engine.running is False
    assert screenshot_timer.started == 0


def test_toggle_without_api_key_delegates_to_start_guard(monkeypatch):
    """BUG-009: hotkey/tray toggle path must surface the same guard as start()."""
    app, engine_start_called, _screenshot_timer, tray = make_app_for_start_without_api_key(
        monkeypatch
    )
    object.__setattr__(app, "toggle", DanmuApp.toggle.__get__(app, DanmuApp))
    DanmuApp.toggle(app)
    assert engine_start_called == []
    assert app.engine.running is False
    assert app.web_runtime_state.is_error is True
    tray.show_api_key_missing_hint.assert_called_once()


def test_stop_flushes_session_runtime_to_lifetime_stats(workspace_tmp):
    """BUG-010: stop path persists session runtime and clears session clock on success."""
    store = ConfigStore(db_path=workspace_tmp / "stop_runtime.db")
    lifetime = LifetimeStats(store)
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=store, lifetime_stats=lifetime)
    object.__setattr__(
        app,
        "_flush_session_runtime_to_lifetime",
        DanmuApp._flush_session_runtime_to_lifetime.__get__(app, DanmuApp),
    )
    object.__setattr__(app, "_ensure_stats_state", DanmuApp._ensure_stats_state.__get__(app, DanmuApp))

    stats = app.stats_state
    stats.start_time = time.monotonic() - 42.0

    DanmuApp._flush_session_runtime_to_lifetime(app)

    assert stats.start_time == 0.0
    persisted = float(store.get(STATS_LIFETIME_RUNTIME_SEC))
    assert persisted >= 40.0
    assert lifetime.snapshot()["lifetime_runtime_sec"] == persisted


def test_flush_session_runtime_keeps_start_time_when_set_batch_fails(workspace_tmp):
    """BUG-010: failed lifetime flush must not clear session clock."""
    store = ConfigStore(db_path=workspace_tmp / "flush_fail.db")
    lifetime = LifetimeStats(store)
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=store, lifetime_stats=lifetime)
    object.__setattr__(
        app,
        "_flush_session_runtime_to_lifetime",
        DanmuApp._flush_session_runtime_to_lifetime.__get__(app, DanmuApp),
    )
    object.__setattr__(app, "_ensure_stats_state", DanmuApp._ensure_stats_state.__get__(app, DanmuApp))

    stats = app.stats_state
    stats.start_time = time.monotonic() - 10.0
    before = stats.start_time

    with patch.object(store, "set_batch", side_effect=sqlite3.OperationalError("locked")):
        with pytest.raises(sqlite3.OperationalError):
            DanmuApp._flush_session_runtime_to_lifetime(app)

    assert stats.start_time == before
    assert store.get(STATS_LIFETIME_RUNTIME_SEC, "") in ("", "0", "0.0")


def _bind_app_for_full_stop(app, *, config, lifetime_stats, session_run_log):
    bind_minimal_danmu_app(
        app,
        config=config,
        lifetime_stats=lifetime_stats,
        session_run_log=session_run_log,
    )
    app.screenshot_timer = FakeTimer()
    app._live_status_timer = FakeTimer()
    app._pool_topup_timer = FakeTimer()
    app.ai_worker = SimpleNamespace(mark_stopping=lambda: None)
    app.overlay = SimpleNamespace(stop_render_loop=lambda: None, hide=lambda: None)
    app.tray = SimpleNamespace(update_state=lambda **kw: None)
    app.state_changed = Mock()
    mic_service = SimpleNamespace(
        is_running=lambda: False,
        sync=lambda **kw: None,
        stop=lambda: None,
        last_error=lambda: "",
    )
    from app.mic_orchestrator import MicOrchestrator

    app._mic_service = mic_service
    app._mic_orchestrator = MicOrchestrator(
        mic_service=mic_service,
        on_utterance_end=lambda: None,
        log_fn=lambda _msg: None,
    )
    app._mic_poll_timer = FakeTimer()
    object.__setattr__(
        app,
        "_flush_session_runtime_to_lifetime",
        DanmuApp._flush_session_runtime_to_lifetime.__get__(app, DanmuApp),
    )
    object.__setattr__(app, "_ensure_stats_state", DanmuApp._ensure_stats_state.__get__(app, DanmuApp))
    object.__setattr__(app, "_sync_mic_service", DanmuApp._sync_mic_service.__get__(app, DanmuApp))
    object.__setattr__(
        app,
        "_get_request_timing_service",
        DanmuApp._get_request_timing_service.__get__(app, DanmuApp),
    )


def test_stop_writes_session_and_lifetime_atomically(workspace_tmp, monkeypatch):
    """BUG-033: stop() persists lifetime runtime before session_run_log.complete()."""
    store = ConfigStore(db_path=workspace_tmp / "atomic_stop.db")
    lifetime = LifetimeStats(store)
    session_log = SessionRunLog(store)
    app = DanmuApp.__new__(DanmuApp)
    _bind_app_for_full_stop(app, config=store, lifetime_stats=lifetime, session_run_log=session_log)

    session_log.begin(started_at=time.time() - 50.0, model="test-model")
    stats = app.stats_state
    stats.start_time = time.monotonic() - 42.0
    stats.danmu_count = 7
    stats.total_input_tokens = 100
    stats.total_output_tokens = 30

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: False)

    DanmuApp.stop(app)

    rows = session_log.list_dicts_newest_first()
    assert len(rows) == 1
    assert rows[0]["danmu_count"] == 7
    assert rows[0]["input_tokens"] == 100
    assert rows[0]["output_tokens"] == 30
    persisted = float(store.get(STATS_LIFETIME_RUNTIME_SEC))
    assert persisted >= 40.0
    assert stats.start_time == 0.0


def test_stop_skips_session_when_lifetime_runtime_flush_fails(workspace_tmp, monkeypatch):
    """BUG-033: failed runtime flush must not leave a session row without lifetime runtime."""
    store = ConfigStore(db_path=workspace_tmp / "atomic_stop_fail.db")
    lifetime = LifetimeStats(store)
    session_log = SessionRunLog(store)
    app = DanmuApp.__new__(DanmuApp)
    _bind_app_for_full_stop(app, config=store, lifetime_stats=lifetime, session_run_log=session_log)

    session_log.begin(started_at=time.time() - 20.0, model="fail-model")
    stats = app.stats_state
    stats.start_time = time.monotonic() - 10.0
    before_start = stats.start_time

    monkeypatch.setattr("main.mic_audio_supported_for_mic_config", lambda _cfg: False)

    with patch.object(store, "set_batch", side_effect=sqlite3.OperationalError("locked")):
        with pytest.raises(sqlite3.OperationalError):
            DanmuApp.stop(app)

    assert session_log.list_dicts_newest_first() == []
    assert stats.start_time == before_start
    assert store.get(STATS_LIFETIME_RUNTIME_SEC, "") in ("", "0", "0.0")


def test_pick_random_skips_deleted_custom_persona(tmp_path):
    from app.personae import PersonaManager, get_reply_contract

    store = ConfigStore(db_path=tmp_path / "persona_pick.db")
    personae = PersonaManager(store)
    contract = get_reply_contract(store)
    personae.save_custom("测试A", contract, "看图发弹幕：")
    personae.set_active(["测试A"])
    personae.delete_custom("测试A")

    assert "测试A" not in personae.get_active()
    assert "测试A" not in personae.list()

    for _ in range(20):
        picked = personae.pick_random()
        assert picked != "测试A"
        system_pt, user_pt = personae.get_prompt(picked)
        assert system_pt
        assert user_pt


def test_delete_custom_prunes_active_personae(tmp_path):
    from app.personae import PersonaManager, get_reply_contract

    store = ConfigStore(db_path=tmp_path / "persona_prune.db")
    personae = PersonaManager(store)
    contract = get_reply_contract(store)
    personae.save_custom("测试A", contract, "看图发弹幕：")
    personae.set_active(["测试A", "高压吐槽型"])
    personae.delete_custom("测试A")

    stored = store.get_json("active_personae", [])
    assert "测试A" not in stored
    assert "高压吐槽型" in stored
    assert "测试A" not in personae.get_active()


def test_quit_stops_pool_topup_timer(monkeypatch):
    """BUG-019: quit() must stop _pool_topup_timer even if stop() does not."""
    import PyQt6.QtCore as qtcore

    fake_pool = MagicMock()
    fake_pool.waitForDone.return_value = True

    class _FakeQThreadPool:
        @staticmethod
        def globalInstance():
            return fake_pool

    monkeypatch.setattr(qtcore, "QThreadPool", _FakeQThreadPool)
    monkeypatch.setattr("main.QApplication.quit", MagicMock())

    pool_timer = FakeTimer()
    pool_timer.active = True
    pool_timer.started = 1

    app = SimpleNamespace(
        logger=MagicMock(),
        stop=MagicMock(),
        hotkey=MagicMock(),
        tray=MagicMock(),
        ai_worker=MagicMock(),
        history_writer=MagicMock(),
        config=MagicMock(),
        overlay=MagicMock(),
        webview_shell=None,
        web_server=MagicMock(),
        stop_web_status_timer=MagicMock(),
        _pool_topup_timer=pool_timer,
        _mic_service=MagicMock(),
    )

    DanmuApp.quit(app)

    app.stop.assert_called_once_with()
    assert not pool_timer.isActive()
    assert pool_timer.stopped >= 1

