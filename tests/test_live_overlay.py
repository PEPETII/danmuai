"""直播网页弹幕层：LiveOverlayHub、SSE 与旁路广播。"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

from app.danmu_engine_models import DanmuItem
from app.live_overlay_hub import LiveOverlayHub
from app.web_api.live_overlay import register_live_overlay_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app


def test_hub_broadcast_batch_without_subscribers():
    hub = LiveOverlayHub()
    hub.broadcast_batch(["a", "b"], source="ai")
    assert hub.connection_count == 0
    snap = hub.snapshot()
    assert snap["connections"] == 0
    assert snap["last_broadcast_at"] is None


def test_broadcast_item_default_source():
    hub = LiveOverlayHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    hub.register(queue)
    hub.broadcast_item("hello", y=10.0, screen_width=1920.0, screen_height=1080.0, speed=1.0, source=None)
    loop.run_until_complete(asyncio.sleep(0.05))
    item = queue.get_nowait()
    assert item["source"] == "ai"


def test_hub_broadcast_updates_snapshot_when_connected():
    hub = LiveOverlayHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    hub.register(queue)
    hub.broadcast_test(["测试1"])
    loop.run_until_complete(asyncio.sleep(0.05))
    item = queue.get_nowait()
    assert item["event"] == "danmu_item"
    assert item["text"] == "测试1"
    assert item["source"] == "test"
    snap = hub.snapshot()
    assert snap["connections"] == 1
    assert snap["last_batch_size"] == 1
    assert snap["last_source"] == "test"
    assert snap["last_broadcast_at"] is not None
    loop.close()


def test_live_overlay_routes_status_and_page():
    app = FastAPI()
    hub = LiveOverlayHub()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_live_overlay_routes(app, hub, "http://127.0.0.1:18765", _check_token)
    client = TestClient(app)

    res = client.get("/api/live-overlay/status")
    assert res.status_code == 200
    body = res.json()
    assert body["connections"] == 0
    assert body["overlay_url"] == "http://127.0.0.1:18765/live-overlay"

    page = client.get("/live-overlay")
    assert page.status_code == 200
    assert "text/html" in page.headers.get("content-type", "")


def test_live_overlay_test_requires_token():
    app = FastAPI()
    hub = LiveOverlayHub()

    def _check_token(authorization: str | None = None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            from fastapi import HTTPException

            raise HTTPException(status_code=401)

    register_live_overlay_routes(app, hub, "http://127.0.0.1:18765", _check_token)
    client = TestClient(app)

    denied = client.post("/api/live-overlay/test", json={})
    assert denied.status_code == 401

    ok = client.post(
        "/api/live-overlay/test",
        json={"items": ["A", "B"]},
        headers={"Authorization": "Bearer secret"},
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_post_test_reaches_registered_subscriber():
    """POST /api/live-overlay/test → hub → 已注册队列（等同 SSE 客户端订阅）。"""
    app = FastAPI()
    hub = LiveOverlayHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    hub.register(queue)

    def _check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer secret":
            from fastapi import HTTPException

            raise HTTPException(status_code=401)

    register_live_overlay_routes(app, hub, "http://127.0.0.1:18765", _check_token)
    client = TestClient(app)

    res = client.post(
        "/api/live-overlay/test",
        json={"items": ["SSE测试"]},
        headers={"Authorization": "Bearer secret"},
    )
    assert res.status_code == 200
    loop.run_until_complete(asyncio.sleep(0.05))
    item = queue.get_nowait()
    assert item["event"] == "danmu_item"
    assert item["text"] == "SSE测试"
    assert item["source"] == "test"


def test_broadcast_failure_does_not_break_enqueue():
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app)
    broken_hub = MagicMock()
    broken_hub.broadcast_item.side_effect = RuntimeError("hub down")
    app.__dict__["web_server"] = MagicMock(live_overlay_hub=broken_hub)

    app._enqueue_reply_batch(
        "p1",
        1,
        10,
        time.time(),
        0,
        ["弹幕一", "弹幕二"],
    )
    assert app.reply_buffer.size() == 2
    broken_hub.broadcast_item.assert_not_called()

    fake_item = DanmuItem(content="x", y=90.0, speed=2.0)
    app._broadcast_live_overlay_item(fake_item, "x", source="ai")
    broken_hub.broadcast_item.assert_called_once()


def test_broadcast_live_overlay_no_hub_noop():
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app)
    app.web_server = None
    fake_item = MagicMock(y=50.0, speed=2.0)
    app._broadcast_live_overlay_item(fake_item, "不会崩溃", source="ai")


def test_hub_remembers_recent_for_sse_replay():
    hub = LiveOverlayHub()
    hub.broadcast_item(
        "回放",
        y=50.0,
        screen_width=1920.0,
        screen_height=1080.0,
        speed=2.0,
        source="ai",
    )
    assert len(hub.recent_items()) == 1
    assert hub.recent_items()[0]["text"] == "回放"
    hub.broadcast_item(
        "第二条",
        y=90.0,
        screen_width=1920.0,
        screen_height=1080.0,
        speed=2.0,
        source="ai",
    )
    assert len(hub.recent_items()) == 2


def test_hub_broadcast_item_payload():
    hub = LiveOverlayHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    hub.register(queue)
    hub.broadcast_item(
        "单条",
        y=130.0,
        screen_width=1920.0,
        screen_height=1080.0,
        speed=2.5,
        source="ai",
    )
    loop.run_until_complete(asyncio.sleep(0.05))
    item = queue.get_nowait()
    assert item["event"] == "danmu_item"
    assert item["text"] == "单条"
    assert item["y"] == 130.0
    loop.close()


def test_hub_burst_broadcast_coalesces_call_soon_threadsafe():
    """BUG-035：同线程突发 N 条只应调度一次 call_soon_threadsafe。"""
    hub = LiveOverlayHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    hub.register(queue)
    scheduled: list = []

    def _capture(cb, *_args, **_kwargs):
        scheduled.append(cb)

    loop.call_soon_threadsafe = _capture  # type: ignore[method-assign]

    for index in range(100):
        hub.broadcast_item(
            f"burst-{index}",
            y=50.0 + index,
            screen_width=1920.0,
            screen_height=1080.0,
            speed=2.0,
            source="ai",
        )

    assert len(scheduled) == 1
    scheduled[0]()
    received = []
    while not queue.empty():
        received.append(queue.get_nowait())
    assert len(received) == 100
    assert received[0]["text"] == "burst-0"
    assert received[99]["text"] == "burst-99"
    snap = hub.snapshot()
    assert snap["last_batch_size"] == 100
    assert snap["last_source"] == "ai"
    loop.close()


def test_hub_burst_without_subscribers_schedules_nothing():
    hub = LiveOverlayHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    scheduled: list = []

    def _capture(cb, *_args, **_kwargs):
        scheduled.append(cb)

    loop.call_soon_threadsafe = _capture  # type: ignore[method-assign]

    for index in range(50):
        hub.broadcast_item(
            f"noop-{index}",
            y=50.0,
            screen_width=1920.0,
            screen_height=1080.0,
            speed=2.0,
            source="ai",
        )

    assert scheduled == []
    assert hub.snapshot()["last_broadcast_at"] is None
    loop.close()


def test_hub_broadcast_batch_under_high_fps_coalesces_enqueue():
    """TEST-GAPS：broadcast_batch 多行突发合并 enqueue。"""
    hub = LiveOverlayHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    hub.register(queue)
    scheduled: list = []

    def _capture(cb, *_args, **_kwargs):
        scheduled.append(cb)

    loop.call_soon_threadsafe = _capture  # type: ignore[method-assign]

    lines = [f"line-{i}" for i in range(100)]
    hub.broadcast_batch(lines, source="test")

    assert len(scheduled) == 1
    scheduled[0]()
    count = 0
    while not queue.empty():
        item = queue.get_nowait()
        assert item["event"] == "danmu_item"
        count += 1
    assert count == 100
    loop.close()


def _app_with_hub():
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app)
    hub = MagicMock()
    app.__dict__["web_server"] = MagicMock(live_overlay_hub=hub)
    return app, hub


def test_pool_topup_broadcasts_with_source(monkeypatch):
    app, hub = _app_with_hub()
    app.engine.running = True
    app._scene_generation = 0
    monkeypatch.setattr(
        "app.danmu_pool.plan_pool_topup",
        lambda _engine, _config: (2, ["pool-a", "pool-b"]),
    )

    def _add_text(text, persona="", **kwargs):
        return DanmuItem(content=text, y=90.0, speed=2.2)

    app.engine.add_text = _add_text

    added = app._maybe_pool_topup()
    assert added == 2
    assert hub.broadcast_item.call_count == 2
    hub.broadcast_item.assert_any_call(
        "pool-a",
        y=90.0,
        screen_width=1920.0,
        screen_height=1080.0,
        speed=2.2,
        source="pool_topup",
    )


def test_duplicate_loss_topup_broadcasts_with_source(monkeypatch):
    app, hub = _app_with_hub()
    app.engine.running = True
    monkeypatch.setattr(
        "app.danmu_pool.plan_duplicate_loss_topup",
        lambda *_args, **_kwargs: ["dup-a"],
    )

    def _add_text(text, persona="", **kwargs):
        return DanmuItem(content=text, y=130.0, speed=2.5)

    app.engine.add_text = _add_text

    queued = MagicMock(scene_generation=3)
    stats: dict[str, int | str] = {"duplicate_loss_total": 2, "duplicate_topup_triggered": 0}
    added = app._maybe_duplicate_loss_topup(queued, stats)
    assert added == 1
    assert stats["duplicate_topup_triggered"] == 1
    hub.broadcast_item.assert_called_once_with(
        "dup-a",
        y=130.0,
        screen_width=1920.0,
        screen_height=1080.0,
        speed=2.5,
        source="pool_duplicate_topup",
    )


def test_meme_display_tick_broadcasts_with_source(tmp_path, monkeypatch):
    from app.config_store import ConfigStore
    from app.meme_barrage.service import MemeBarrageService

    config = ConfigStore(db_path=tmp_path / "meme_overlay.db")
    config.set("meme_barrage_enabled", "1")
    config.set("meme_barrage_display_batch_size", "2")

    app, hub = _app_with_hub()
    app.config = config
    app.engine.running = True
    app._scene_generation = 0
    app._update_stats = MagicMock()
    app._meme_barrage_service = MemeBarrageService(config)
    app._meme_barrage_service.enqueue_display(["烂梗1", "烂梗2"])
    app._meme_display_ticking = False

    def _add_text(text, persona="", **kwargs):
        return DanmuItem(content=text, y=50.0, speed=2.0)

    app.engine.add_text = _add_text

    app._meme_display_tick()
    assert hub.broadcast_item.call_count == 2
    hub.broadcast_item.assert_any_call(
        "烂梗1",
        y=50.0,
        screen_width=1920.0,
        screen_height=1080.0,
        speed=2.0,
        source="meme_barrage",
    )


def test_formula_add_text_failure_skips_broadcast(monkeypatch):
    app, hub = _app_with_hub()
    app.engine.running = True
    monkeypatch.setattr(
        "app.danmu_pool.plan_pool_topup",
        lambda _engine, _config: (1, ["pool-fail"]),
    )
    app.engine.add_text = lambda *_args, **_kwargs: None

    added = app._maybe_pool_topup()
    assert added == 0
    hub.broadcast_item.assert_not_called()


def test_ai_reply_broadcast_unchanged():
    app, hub = _app_with_hub()
    fake_item = DanmuItem(content="AI弹幕", y=90.0, speed=2.0)
    app._broadcast_live_overlay_item(fake_item, "AI弹幕", source="ai")
    hub.broadcast_item.assert_called_once_with(
        "AI弹幕",
        y=90.0,
        screen_width=1920.0,
        screen_height=1080.0,
        speed=2.0,
        source="ai",
    )
