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


def test_meme_display_tick_uses_engine_not_reply_buffer(tmp_path, monkeypatch):
    config = ConfigStore(db_path=tmp_path / "meme_display.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_display_batch_size", "2")

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

    service = app._meme_barrage_service
    service.enqueue_display(["烂梗1", "烂梗2", "烂梗3"])

    app._meme_display_tick()
    assert added == ["烂梗1", "烂梗2"]
    assert service.display_queue_size() == 1


def test_meme_collect_local_mode_ingests(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_local.db")
    config.set("meme_barrage_category", "local")
    config.set("meme_barrage_collect_batch_size", "2")
    service = MemeBarrageService(config)
    service.store.insert_many([("本地句1", None, None), ("本地句2", None, None)])
    texts = service.collect_local_batch()
    assert len(texts) == 2
    cleaned = service.ingest_collected_texts(texts)
    assert len(cleaned) == 2
    service.enqueue_display(cleaned)
    assert service.display_queue_size() == 2


def test_filter_remote_items_keeps_long_barrage_untruncated(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_filter.db")
    service = MemeBarrageService(config)
    long_text = "瓦批的一天：查看商店，练呲水枪，打开麻麻模拟器，启动！"
    items = [{"barrage": long_text, "tags": "06", "id": 1}]
    filtered = service.filter_remote_items(items)
    assert len(filtered) == 1
    assert filtered[0][0] == long_text


def test_apply_meme_settings_starts_timers_when_running(tmp_path):
    config = ConfigStore(db_path=tmp_path / "meme_apply.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_collect_interval_sec", "5")
    config.set("meme_barrage_display_interval_sec", "5")

    app = DanmuApp.__new__(DanmuApp)
    app.config = config
    app.engine = FakeEngine()
    app.engine.running = True
    app.logger = MagicMock()
    app._meme_collect_timer = FakeTimer()
    app._meme_display_timer = FakeTimer()
    app._meme_barrage_service = MemeBarrageService(config)

    app.apply_meme_barrage_settings()
    assert app._meme_collect_timer.isActive()
    assert app._meme_display_timer.isActive()
