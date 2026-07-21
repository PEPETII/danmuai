"""烂梗公式化运行时：队列 FIFO 与独立上屏。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.config_store import ConfigStore
from app.meme_barrage.service import MemeBarrageService
from main import DanmuApp

from tests.fakes import FakeEngine, FakeTimer


def test_display_queue_fifo(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_fifo.db")
    service = MemeBarrageService(config)
    service.enqueue_display([f"line-{i}" for i in range(40)])
    first = service.pop_display_batch(20)
    second = service.pop_display_batch(20)
    assert len(first) == 20
    assert len(second) == 20
    assert first[0] == "line-0"
    assert second[0] == "line-20"
    assert service.display_queue_size() == 0


def test_clear_resets_library_and_queue(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_clear.db")
    service = MemeBarrageService(config)
    service.store.insert_many([("A", None, None), ("B", None, None)])
    service.enqueue_display(["A", "B"])
    service.clear_all()
    assert service.library_count() == 0
    assert service.display_queue_size() == 0


def test_meme_display_tick_uses_display_danmu_text(tmp_path, monkeypatch):
    """烂梗 display tick 按 render_mode 路由上屏（scrolling 模式走 engine.add_text）。"""
    config = ConfigStore(db_path=tmp_path / "meme_display.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_display_batch_size", "2")
    config.set("danmu_render_mode", "scrolling")

    engine = FakeEngine()
    engine.running = True
    added: list[str] = []

    def _add_text(content, persona="", **kwargs):
        added.append(content)
        return MagicMock()

    engine.add_text = _add_text

    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.engine = engine
    app.logger = MagicMock()
    app._scene_generation = 0
    app._update_stats = MagicMock()
    app._meme_barrage_service = MemeBarrageService(config)
    # display_danmu_text → _display_danmu_text 在 scrolling 模式下委托 engine.add_text
    app._pet_barrage_mode_enabled = lambda: False
    app._danmu_render_mode = lambda: "scrolling"

    service = app._meme_barrage_service
    service.enqueue_display(["烂梗1", "烂梗2", "烂梗3"])

    app._meme_display_tick()
    assert added == ["烂梗1", "烂梗2"]
    assert service.display_queue_size() == 1


def test_meme_display_tick_routes_to_floating_panel(tmp_path, monkeypatch):
    """floating_panel 模式下烂梗 display tick 路由到浮动面板而非横向引擎。"""
    config = ConfigStore(db_path=tmp_path / "meme_fp.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_display_batch_size", "2")
    config.set("danmu_render_mode", "floating_panel")

    engine = FakeEngine()
    engine.running = True

    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.engine = engine
    app.logger = MagicMock()
    app._scene_generation = 0
    app._update_stats = MagicMock()
    app._meme_barrage_service = MemeBarrageService(config)
    app._pet_barrage_mode_enabled = lambda: False
    app._danmu_render_mode = lambda: "floating_panel"

    fp_added: list[str] = []

    def _fp_display(content, persona_id, **kwargs):
        fp_added.append(content)
        return MagicMock()

    app._display_floating_panel_text = _fp_display

    # 横向引擎不应被调用
    engine_added: list[str] = []

    def _engine_add_text(content, persona="", **kwargs):
        engine_added.append(content)
        return MagicMock()

    engine.add_text = _engine_add_text

    service = app._meme_barrage_service
    service.enqueue_display(["烂梗A", "烂梗B"])

    app._meme_display_tick()
    assert fp_added == ["烂梗A", "烂梗B"]
    assert engine_added == []


def test_meme_collect_local_mode_skips_reingest(tmp_path):
    """DP-003: local 模式不再 ingest_collected_texts，库条数不变。"""
    config = ConfigStore(db_path=tmp_path / "meme_local.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_category", "local")
    config.set("meme_barrage_collect_batch_size", "2")
    config.set("meme_barrage_display_mode", "full")

    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.engine = FakeEngine()
    app.engine.running = True
    app.logger = MagicMock()
    app._scene_generation = 0
    app._update_stats = MagicMock()
    app._meme_barrage_service = MemeBarrageService(config)
    app._meme_display_ticking = False

    service = app._meme_barrage_service
    service.store.insert_many([("本地句1", None, None), ("本地句2", None, None)])
    count_before = service.library_count()

    app._meme_collect_tick()

    assert service.library_count() == count_before
    assert service.display_queue_size() == 2


def test_meme_display_tick_reentrancy_guard(tmp_path):
    """DP-004: 展示 tick 执行中重入调用被忽略。"""
    from app.main_meme_mixin import _MEME_DISPLAY_MAX_PER_TICK

    config = ConfigStore(db_path=tmp_path / "meme_reentry.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_display_batch_size", "4")
    config.set("danmu_render_mode", "scrolling")

    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.engine = FakeEngine()
    app.engine.running = True
    app.logger = MagicMock()
    app._scene_generation = 0
    app._update_stats = MagicMock()
    app._meme_display_ticking = False
    app._meme_barrage_service = MemeBarrageService(config)
    app._pet_barrage_mode_enabled = lambda: False
    app._danmu_render_mode = lambda: "scrolling"

    added: list[str] = []

    def _add_text(content, persona="", **kwargs):
        added.append(content)
        if len(added) == 1:
            app._meme_display_tick()
        return MagicMock()

    app.engine.add_text = _add_text
    service = app._meme_barrage_service
    service.enqueue_display(["A", "B", "C", "D"])

    app._meme_display_tick()
    assert len(added) == _MEME_DISPLAY_MAX_PER_TICK


def test_meme_display_tick_recursion_depth_limit(tmp_path, monkeypatch):
    """BUG-G06: 递归调度有深度上限，超限 backlog 保留在队列中。"""
    from app.main_meme_mixin import _MEME_DISPLAY_MAX_PER_TICK, _MEME_DISPLAY_MAX_RECURSION

    config = ConfigStore(db_path=tmp_path / "meme_recursion.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_display_batch_size", "100")
    config.set("danmu_render_mode", "scrolling")

    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.engine = FakeEngine()
    app.engine.running = True
    app.logger = MagicMock()
    app._scene_generation = 0
    app._update_stats = MagicMock()
    app._meme_display_ticking = False
    app._meme_barrage_service = MemeBarrageService(config)
    app._pet_barrage_mode_enabled = lambda: False
    app._danmu_render_mode = lambda: "scrolling"

    added: list[str] = []

    def _add_text(content, persona="", **kwargs):
        added.append(content)
        return MagicMock()

    app.engine.add_text = _add_text

    # Collect scheduled callbacks; execute them after the current tick finishes
    # (simulating QTimer.singleShot(0, ...) deferring to next event loop iteration).
    scheduled: list[object] = []

    def _fake_single_shot(_ms, fn):
        scheduled.append(fn)

    monkeypatch.setattr("app.main_meme_mixin.QTimer.singleShot", _fake_single_shot)

    # Enqueue more items than max recursion can handle
    total_items = _MEME_DISPLAY_MAX_PER_TICK * _MEME_DISPLAY_MAX_RECURSION + 5
    service = app._meme_barrage_service
    service.enqueue_display([f"item-{i}" for i in range(total_items)])

    app._meme_display_tick()

    # Drain scheduled callbacks (each may schedule more)
    while scheduled:
        fn = scheduled.pop(0)
        fn()

    # Should have processed at most _MEME_DISPLAY_MAX_RECURSION rounds
    max_expected = _MEME_DISPLAY_MAX_PER_TICK * _MEME_DISPLAY_MAX_RECURSION
    assert len(added) == max_expected
    # Remaining backlog should still exist
    remaining = list(app.__dict__.get("_meme_display_backlog") or [])
    assert len(remaining) == total_items - max_expected


def test_filter_remote_items_keeps_long_barrage_untruncated(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_filter.db")
    service = MemeBarrageService(config)
    long_text = "瓦批的一天：查看商店，练呲水枪，打开麻麻模拟器，启动！"
    items = [{"barrage": long_text, "tags": "06", "id": 1}]
    filtered = service.filter_remote_items(items)
    assert len(filtered) == 1
    assert filtered[0][0] == long_text


def _make_meme_app(config: ConfigStore) -> DanmuApp:
    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.engine = FakeEngine()
    app.engine.running = True
    app.logger = MagicMock()
    app._meme_collect_timer = FakeTimer()
    app._meme_display_timer = FakeTimer()
    app._meme_barrage_service = MemeBarrageService(config)
    return app


def test_apply_meme_settings_starts_timers_when_running(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_apply.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_collect_interval_sec", "5")
    config.set("meme_barrage_display_interval_sec", "5")

    app = _make_meme_app(config)
    app.apply_meme_barrage_settings()
    assert app._meme_collect_timer.isActive()
    assert app._meme_display_timer.isActive()


def test_apply_meme_settings_updates_collect_timer_interval(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_interval.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_collect_interval_sec", "5")
    config.set("meme_barrage_display_interval_sec", "5")

    app = _make_meme_app(config)
    app.apply_meme_barrage_settings()
    assert app._meme_collect_timer.interval() == 5000

    config.set("meme_barrage_collect_interval_sec", "30")
    app._meme_collect_timer.active = True
    app.apply_meme_barrage_settings()
    assert app._meme_collect_timer.interval() == 30000


def test_apply_meme_settings_does_not_immediate_collect(tmp_path, monkeypatch):
    config = ConfigStore(db_path=tmp_path / "meme_no_immediate.db")
    config.set("meme_barrage_enabled", "1")

    app = _make_meme_app(config)
    app._meme_collect_timer.active = True
    app._meme_display_timer.active = True

    calls = {"count": 0}

    def _tick():
        calls["count"] += 1

    monkeypatch.setattr(app, "_meme_collect_tick", _tick)

    def _single_shot(_ms, fn):
        fn()

    monkeypatch.setattr("app.main_meme_mixin.QTimer.singleShot", _single_shot)

    app.apply_meme_barrage_settings()
    assert calls["count"] == 0


def test_meme_collect_tick_uses_updated_batch_size(tmp_path, monkeypatch):
    config = ConfigStore(db_path=tmp_path / "meme_batch.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_category", "random")
    config.set("meme_barrage_collect_batch_size", "10")

    app = _make_meme_app(config)
    from app.main_meme_mixin import _MemeBarrageBridge

    app._meme_barrage_bridge = _MemeBarrageBridge()

    captured: dict[str, object] = {}

    class FakeRunnable:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def setAutoDelete(self, _value: bool) -> None:
            return None

    monkeypatch.setattr("app.main_meme_mixin.MemeFetchRunnable", FakeRunnable)
    pool = MagicMock()
    pool.start = lambda _runnable: None
    monkeypatch.setattr(
        "app.main_meme_mixin.meme_fetch_pool",
        lambda: pool,
    )

    app._meme_collect_tick()
    assert captured.get("page_size") == 10


def test_local_read_offset_persists_across_service_restart(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_cursor_local.db")
    config.set("meme_barrage_collect_batch_size", "2")

    first = MemeBarrageService(config)
    first.store.insert_many(
        [(f"line-{i}", None, None) for i in range(6)],
    )
    batch1 = first.collect_local_batch()
    assert batch1 == ["line-0", "line-1"]
    assert config.get("meme_barrage_local_read_offset") == "2"

    second = MemeBarrageService(config)
    batch2 = second.collect_local_batch()
    assert batch2 == ["line-2", "line-3"]
    assert config.get("meme_barrage_local_read_offset") == "4"


def test_remote_page_num_persists_across_service_restart(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_cursor_remote.db")
    config.set("meme_barrage_remote_page_num", "3")

    first = MemeBarrageService(config)
    assert first.next_page_num() == 3

    data = {
        "data": {
            "list": [{"barrage": "远程句", "tags": "06", "id": 1}],
            "lastPage": False,
        }
    }
    first.apply_remote_page(data)
    assert config.get("meme_barrage_remote_page_num") == "4"

    second = MemeBarrageService(config)
    assert second.next_page_num() == 4


def test_clear_all_resets_persisted_cursors(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_cursor_clear.db")
    config.set("meme_barrage_local_read_offset", "8")
    config.set("meme_barrage_remote_page_num", "5")

    service = MemeBarrageService(config)
    service.store.insert_many([("A", None, None)])
    service.enqueue_display(["A"])
    service.clear_all()

    assert config.get("meme_barrage_local_read_offset") == "0"
    assert config.get("meme_barrage_remote_page_num") == "1"
    restarted = MemeBarrageService(config)
    assert restarted.next_page_num() == 1


def test_meme_start_ai_select_does_not_compress_on_main_thread(tmp_path, monkeypatch):
    """W-PERF-MED-004 P-14: 截图压缩在工作线程，不在主线程阻塞。"""
    config = ConfigStore(db_path=tmp_path / "meme_ai_compress.db")
    config.set("meme_barrage_display_batch_size", "2")
    config.set("meme_barrage_display_mode", "ai")

    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.logger = MagicMock()
    app.ai_worker = MagicMock()
    app._meme_barrage_service = MemeBarrageService(config)
    app._meme_barrage_bridge = MagicMock()

    pixmap = MagicMock()
    pixmap.isNull.return_value = False
    app._latest_screenshot = pixmap

    captured: dict[str, object] = {}

    class FakeRunnable:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def setAutoDelete(self, _value: bool) -> None:
            return None

    pool = MagicMock()
    monkeypatch.setattr("app.main_meme_mixin.MemeAiSelectRunnable", FakeRunnable)
    monkeypatch.setattr("app.main_meme_mixin.meme_ai_pool", lambda: pool)

    compress_calls: list[str] = []

    def _track_main_compress(pix, max_width=0, quality=0):
        compress_calls.append("main")
        return "data:image/jpeg;base64,BBB"

    monkeypatch.setattr("app.main_meme_mixin.compress_screenshot", _track_main_compress)

    service = app._meme_barrage_service
    settings = {"display_batch_size": 2, "display_mode": "ai"}
    candidates = ["A", "B", "C"]

    app._meme_start_ai_select(service, candidates, settings)

    assert compress_calls == []
    assert captured.get("pixmap") is pixmap
    assert callable(captured.get("compress_fn"))
    pool.start.assert_called_once()
