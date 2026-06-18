"""Danmu deduplication window and similarity fallback tests."""

import time

import app.danmu_engine as danmu_engine_mod
import app.danmu_engine_dedup as danmu_engine_dedup_mod
import pytest
from app.config_store import ConfigStore
from app.danmu_engine import (
    _LEVENSHTEIN_UNAVAILABLE,
    DanmuEngine,
    DanmuItem,
    _get_levenshtein_ratio,
    dedup_profile_enabled,
    normalize_danmu_display_text,
    reset_dedup_profile_for_tests,
    snapshot_dedup_profile,
)
from app.reply_queue import QueuedReply
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeLogger


@pytest.fixture()
def config_store(workspace_tmp):
    db_path = workspace_tmp / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    store.set("dedup_threshold", "0.85")
    return store


@pytest.fixture()
def engine(config_store):
    eng = DanmuEngine(config_store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    return eng


@pytest.fixture()
def dedup_profile_on(monkeypatch):
    monkeypatch.setenv("DANMU_DEDUP_PROFILE", "1")
    reset_dedup_profile_for_tests()
    yield
    monkeypatch.delenv("DANMU_DEDUP_PROFILE", raising=False)
    reset_dedup_profile_for_tests()


def test_clear_dedup_window_allows_repeat_after_scene_change(engine):
    text = "Python项目仓库界面"
    assert engine.add_text(text) is not None
    assert engine.add_text(text) is None

    engine.clear_dedup_window()

    assert engine.add_text(text) is not None


def test_remember_content_caps_recent_window_at_thirty(engine):
    for i in range(35):
        engine._remember_content(f"msg-{i}")
    assert len(engine.recent) == 30
    assert len(engine.recent_exact_set) == 30
    assert "msg-4" not in engine.recent_exact_set
    assert "msg-34" in engine.recent_exact_set


def test_remember_content_keeps_exact_set_in_sync_with_deque(engine):
    for i in range(31):
        engine._remember_content(f"msg-{i}")

    assert len(engine.recent) == 30
    assert engine.recent_exact_set == set(engine.recent)
    assert "msg-0" not in engine.recent_exact_set


def test_evicted_exact_match_not_blocked_after_window(engine):
    for i in range(31):
        engine._remember_content(f"unique-{i}")

    assert "unique-0" not in engine.recent
    assert "unique-0" not in engine.recent_exact_set

    # 仅验证精确窗口：unique-0 与 unique-10 等前缀相近，模糊去重仍可能命中
    engine.config.set("dedup_threshold", "1.0")
    assert engine._is_duplicate("unique-0") is False


def test_exact_duplicate_within_window_blocked(engine):
    engine._remember_content("hello")

    assert engine._is_duplicate("hello") is True


def test_fuzzy_duplicate_within_window_blocked(engine):
    engine._remember_content("hello world")

    assert engine._is_duplicate("hello wurld") is True


def test_remember_content_keeps_set_when_duplicate_still_in_deque(engine):
    for i in range(28):
        engine._remember_content(f"pad-{i}")
    engine._remember_content("dup")
    engine._remember_content("tail-a")
    engine._remember_content("tail-b")
    engine._remember_content("dup")

    assert engine.recent.count("dup") >= 1
    assert "dup" in engine.recent_exact_set
    assert engine.recent_exact_set == set(engine.recent)


def test_dedup_threshold_one_skips_similarity(engine, monkeypatch):
    engine.config.set("dedup_threshold", "1.0")
    engine._remember_content("alpha")
    calls = []
    monkeypatch.setattr(
        DanmuEngine,
        "_similarity",
        staticmethod(lambda a, b: calls.append((a, b)) or 1.0),
    )

    assert engine._is_duplicate("alphb") is False
    assert calls == []


def test_similarity_fallback_without_levenshtein(monkeypatch):
    monkeypatch.setattr(danmu_engine_mod, "_LEVENSHTEIN_RATIO", _LEVENSHTEIN_UNAVAILABLE)
    monkeypatch.setattr(
        danmu_engine_dedup_mod,
        "_LEVENSHTEIN_RATIO",
        _LEVENSHTEIN_UNAVAILABLE,
    )

    assert danmu_engine_dedup_mod._get_levenshtein_ratio() is None
    assert DanmuEngine._similarity("kitten", "sitting") > 0.5


def test_similarity_uses_c_extension_when_available(dedup_profile_on):
    if _get_levenshtein_ratio() is None:
        pytest.skip("Levenshtein C extension not available")

    reset_dedup_profile_for_tests(clear_env_cache=False)
    DanmuEngine._similarity("hello", "hallo")
    snap = snapshot_dedup_profile()
    assert snap["similarity_fallback_calls"] == 0


def test_add_text_calls_is_duplicate_once(engine, monkeypatch):
    calls = []
    original = engine._is_duplicate

    def counting_duplicate(content):
        calls.append(content)
        return original(content)

    monkeypatch.setattr(engine, "_is_duplicate", counting_duplicate)
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 50.0)
    engine.set_screen_width(1000.0)

    result = engine.add_text("fresh-danmu")

    assert result is not None
    assert calls == ["fresh-danmu"]


def test_add_text_rejects_exact_duplicate_without_second_remember(engine, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 50.0)
    engine.set_screen_width(1000.0)
    engine._remember_content("seen")

    assert engine.add_text("seen") is None
    assert list(engine.recent).count("seen") == 1


def test_add_item_uses_remember_helper(engine):
    item = DanmuItem(content="via-item", x=900.0, width=10.0)
    engine.set_screen_width(1000.0)

    assert engine.add_item(item) is True
    assert "via-item" in engine.recent_exact_set
    assert engine.recent_exact_set == set(engine.recent)


def test_dedup_profile_disabled_by_default(engine, monkeypatch):
    monkeypatch.delenv("DANMU_DEDUP_PROFILE", raising=False)
    reset_dedup_profile_for_tests()

    assert dedup_profile_enabled() is False
    engine._remember_content("alpha")
    engine._is_duplicate("alpha")

    snap = snapshot_dedup_profile()
    assert snap["enabled"] is False
    assert snap["duplicate_checks"] == 0
    assert snap["similarity_calls"] == 0


def test_dedup_profile_counts_when_enabled(engine, dedup_profile_on):
    assert dedup_profile_enabled() is True

    engine._remember_content("hello world")
    assert engine._is_duplicate("hello wurld") is True

    snap = engine.get_dedup_profile_snapshot()
    assert snap["duplicate_checks"] == 1
    assert snap["duplicate_hits"] == 1
    assert snap["similarity_calls"] >= 1
    assert snap["avg_is_duplicate_us"] > 0


def test_dedup_profile_records_exact_set_hit(engine, dedup_profile_on):
    engine._remember_content("exact-hit")
    reset_dedup_profile_for_tests(clear_env_cache=False)

    assert engine._is_duplicate("exact-hit") is True

    snap = snapshot_dedup_profile()
    assert snap["duplicate_checks"] == 1
    assert snap["exact_set_hits"] == 1
    assert snap["similarity_calls"] == 0


def test_dedup_profile_records_fallback_path(engine, dedup_profile_on, monkeypatch):
    monkeypatch.setattr(danmu_engine_mod, "_LEVENSHTEIN_RATIO", _LEVENSHTEIN_UNAVAILABLE)
    monkeypatch.setattr(
        danmu_engine_dedup_mod,
        "_LEVENSHTEIN_RATIO",
        _LEVENSHTEIN_UNAVAILABLE,
    )
    engine._remember_content("kitten")

    assert engine._is_duplicate("sitting") is False

    snap = snapshot_dedup_profile()
    assert snap["similarity_calls"] >= 1
    assert snap["similarity_fallback_calls"] >= 1


def test_danmu_count_on_uninitialized_danmu_app():
    """DanmuApp.__new__ without QObject.__init__ must not raise via stats facade."""
    app = DanmuApp.__new__(DanmuApp)
    app.danmu_count = 3
    assert app.danmu_count == 3


def test_maybe_log_dedup_profile_throttles(monkeypatch):
    from main import DanmuApp

    from tests.fakes import FakeLogger

    monkeypatch.setenv("DANMU_DEDUP_PROFILE", "1")
    reset_dedup_profile_for_tests()

    app = DanmuApp.__new__(DanmuApp)
    app.logger = FakeLogger()
    app.danmu_count = 0
    app._dedup_profile_log_at_count = 0

    for _ in range(24):
        app.danmu_count += 1
        app._maybe_log_dedup_profile()
    assert app.logger.debug_messages == []

    app.danmu_count += 1
    app._maybe_log_dedup_profile()
    assert len(app.logger.debug_messages) == 1
    assert "dedup profile" in app.logger.debug_messages[0]


def test_add_text_skip_dedup_allows_fallback_repeat(engine, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 50.0)
    engine.set_screen_width(1000.0)
    text = "这画面有东西"

    assert engine.add_text(text) is not None
    assert engine.add_text(text) is None
    assert engine.add_text(text, skip_dedup=True) is not None


def test_forget_content_allows_repeat_after_drop(engine):
    from app.danmu_engine import DanmuItem

    engine.set_screen_width(1000.0)
    track = engine.tracks[0]
    item = DanmuItem("drop-me", batch_id=9, scene_generation=0, x=400.0, width=80.0)
    track.items = [item]
    engine._remember_content("drop-me")
    engine._rebuild_visibility_counts()

    removed = engine.drop_items_with_batch_id(9)

    assert removed == 1
    assert engine._is_duplicate("drop-me") is False


def test_forget_content_keeps_set_when_duplicate_still_in_deque(engine):
    engine._remember_content("shared")
    engine._remember_content("other")
    engine._remember_content("shared")

    engine._forget_content("shared")

    assert engine.recent.count("shared") == 1
    assert "shared" in engine.recent_exact_set


def test_normalize_danmu_display_text_matches_add_text_truncation(engine):
    engine.config.set("danmu_max_chars", "8")
    raw = "一二三四五六七八九十"
    assert normalize_danmu_display_text(raw, engine.config) == "一二三四五六七八..."


def test_normalize_danmu_display_text_skips_formula_custom_pool(engine):
    engine.config.set("danmu_max_chars", "8")
    long_line = "这是一句保存于公式化弹幕库的超长句子应完整上屏展示"
    engine.config.set_custom_danmu_pool([long_line])
    assert normalize_danmu_display_text(long_line, engine.config) == long_line


def test_normalize_danmu_display_text_skips_formula_meme_barrage(engine):
    engine.config.set("danmu_max_chars", "8")
    long_line = "瓦批的一天：查看商店，练呲水枪，打开麻麻模拟器，启动！"
    engine.config.meme_barrage_library_insert_many(
        [(long_line, None, None)],
        collected_at=0.0,
        max_rows=10_000,
    )
    assert normalize_danmu_display_text(long_line, engine.config) == long_line


def test_start_clears_dedup_window(monkeypatch, workspace_tmp):
    from app.config_store import ConfigStore

    from tests.fakes import FakeConfig

    store = ConfigStore(db_path=workspace_tmp / "start_dedup.db")
    eng = DanmuEngine(store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    eng._remember_content("这画面有东西")

    clear_calls: list[bool] = []
    original_clear = eng.clear_dedup_window

    def track_clear():
        clear_calls.append(True)
        original_clear()

    monkeypatch.setattr(eng, "start", lambda: None)
    monkeypatch.setattr(eng, "clear_dedup_window", track_clear)
    monkeypatch.setattr("main.resolve_screen_index", lambda _config: 0)
    monkeypatch.setattr("main.resolve_active_model_id", lambda _config: "test-model")

    app = DanmuApp.__new__(DanmuApp)

    def _noop(*_args, **_kwargs):
        pass

    overlay = type(
        "O",
        (),
        {"show_for_screen": _noop, "start_render_loop": _noop, "ensure_render_loop": _noop},
    )()
    tray = type("T", (), {"update_state": _noop})()
    timer = type("TM", (), {"stop": _noop, "start": _noop, "setInterval": _noop, "isActive": lambda *a, **k: False})()
    reply_buffer = type("B", (), {"set_max_items": _noop, "is_empty": lambda *a, **k: True})()

    stubs = {
        "config": FakeConfig({
            "api_key": "sk-test",
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": "test-model",
        }),
        "engine": eng,
        "logger": FakeLogger(),
        "_capture_screenshot": lambda: None,
        "_sync_mic_service": lambda: None,
        "overlay": overlay,
        "tray": tray,
        "ai_worker": type("W", (), {"reset_stopping": lambda *a, **k: None})(),
        "screenshot_timer": timer,
        "_live_status_timer": timer,
        "_lifetime_flush_timer": timer,
        "_pool_topup_timer": timer,
        "reply_buffer": reply_buffer,
        "reply_timer": timer,
        "_topmost_health_timer": timer,
        "lifetime_stats": type("L", (), {"flush_pending": _noop})(),
        "session_run_log": type("R", (), {"begin": _noop})(),
        "_pending_request_meta": {},
        "state_changed": type("S", (), {"emit": lambda *a: None})(),
        "_queue_capacity": lambda: 8,
        "_set_error_status_safe": lambda *a, **k: None,
    }
    for name, value in stubs.items():
        object.__setattr__(app, name, value)

    DanmuApp.start(app)

    assert clear_calls == [True]
    assert eng._is_duplicate("这画面有东西") is False


def test_consume_reply_queue_dedup_reject_does_not_increment_danmu_count(
    workspace_tmp, monkeypatch
):
    from app.config_store import ConfigStore
    from app.lifetime_stats import LifetimeStats

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 50.0)
    store = ConfigStore(db_path=workspace_tmp / "consume_dedup.db")
    eng = DanmuEngine(store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    eng.set_screen_width(1000.0)
    eng._remember_content("blocked-line")

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, engine=eng, config=store)
    object.__setattr__(app, "_update_stats", lambda success=True: DanmuApp._update_stats(app, success=success))
    object.__setattr__(app, "lifetime_stats", LifetimeStats(store))
    object.__setattr__(app, "_start_time", time.monotonic())
    object.__setattr__(app, "_total_input_tokens", 0)
    object.__setattr__(app, "_total_output_tokens", 0)
    object.__setattr__(app, "_visible_display_count", lambda: 0)
    object.__setattr__(app, "_estimated_reply_gap_ms", lambda: 100)
    object.__setattr__(app, "_latest_displayed_round", 0)
    object.__setattr__(app, "_latest_displayed_screenshot_id", 0)
    object.__setattr__(app, "_current_batch", None)

    app.reply_buffer.push(
        QueuedReply("p1", 1, 0, "blocked-line", screenshot_round=1, screenshot_id=1, captured_at=time.monotonic(), scene_generation=0)
    )
    DanmuApp._consume_reply_queue(app)

    assert app.danmu_count == 0
    assert app.lifetime_stats.snapshot()["lifetime_danmu_count"] == 0


def test_consume_reply_queue_skip_dedup_only_for_fallback(workspace_tmp, monkeypatch):
    from app.config_store import ConfigStore
    from app.reply_queue import QueuedReply


    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 50.0)
    store = ConfigStore(db_path=workspace_tmp / "skip_dedup_flag.db")
    eng = DanmuEngine(store)
    eng.set_screen_width(1000.0)
    captured: list[bool] = []

    def track_add_text(*args, **kwargs):
        captured.append(kwargs.get("skip_dedup", False))
        return None

    eng.add_text = track_add_text

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, engine=eng, config=store)
    object.__setattr__(app, "_update_stats", lambda *a, **k: None)
    object.__setattr__(app, "_visible_display_count", lambda: 0)
    object.__setattr__(app, "_estimated_reply_gap_ms", lambda: 100)
    object.__setattr__(app, "_current_batch", None)

    app.reply_buffer.push(
        QueuedReply(
            "p1",
            1,
            0,
            "fallback-line",
            screenshot_round=1,
            screenshot_id=1,
            captured_at=time.monotonic(),
            scene_generation=0,
            is_fallback=True,
            source="fallback",
        )
    )
    DanmuApp._consume_reply_queue(app)
    assert captured == [True]

    captured.clear()
    app.reply_buffer.push(
        QueuedReply(
            "p1",
            1,
            0,
            "ai-line",
            screenshot_round=1,
            screenshot_id=1,
            captured_at=time.monotonic(),
            scene_generation=0,
            is_fallback=False,
            source="ai",
        )
    )
    DanmuApp._consume_reply_queue(app)
    assert captured == [False]


def test_consume_reply_queue_applies_persona_name_prefix(workspace_tmp, monkeypatch):
    from app.config_store import ConfigStore
    from app.danmu_engine import resolve_danmu_display_text
    from app.reply_queue import QueuedReply

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 50.0)
    store = ConfigStore(db_path=workspace_tmp / "persona_prefix.db")
    store.set("persona_name_prefix_enabled", "1")
    eng = DanmuEngine(store)
    eng.set_screen_width(1000.0)
    captured: list[tuple[str, bool]] = []

    def track_add_text(content, persona="", *args, **kwargs):
        captured.append((content, kwargs.get("pre_resolved", False)))
        return DanmuItem(content=content, persona=persona)

    eng.add_text = track_add_text

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, engine=eng, config=store)
    object.__setattr__(app, "_update_stats", lambda *a, **k: None)
    object.__setattr__(app, "_visible_display_count", lambda: 0)
    object.__setattr__(app, "_estimated_reply_gap_ms", lambda: 100)
    object.__setattr__(app, "_latest_displayed_round", 0)
    object.__setattr__(app, "_latest_displayed_screenshot_id", 0)
    object.__setattr__(app, "_current_batch", None)

    app.reply_buffer.push(
        QueuedReply(
            "吐槽型",
            1,
            0,
            "上屏测试",
            screenshot_round=1,
            screenshot_id=1,
            captured_at=time.monotonic(),
            scene_generation=0,
        )
    )
    DanmuApp._consume_reply_queue(app)

    expected = resolve_danmu_display_text("上屏测试", store, "吐槽型")
    assert captured == [(expected, True)]
    assert expected == "吐槽型：上屏测试"


def test_log_dedup_profile_summary_noop_when_disabled(engine, monkeypatch):
    from tests.fakes import FakeLogger

    monkeypatch.delenv("DANMU_DEDUP_PROFILE", raising=False)
    reset_dedup_profile_for_tests()
    logger = FakeLogger()

    danmu_engine_mod.log_dedup_profile_summary(logger)

    assert logger.debug_messages == []
