"""PanelBridge buffer and threadsafe enqueue tests."""

from __future__ import annotations

import asyncio
import threading
import time

from app.floating_panel_web.panel_bridge import PanelBridge, new_panel_queue


def test_enqueue_card_no_consumer_writes_buffer():
    bridge = PanelBridge()
    bridge.enqueue_card({"type": "card", "id": "1", "content": "a"})
    assert len(bridge._backfill_buffer) == 1
    assert bridge._backfill_buffer[0]["id"] == "1"


def test_enqueue_card_with_consumer_calls_soon_threadsafe():
    bridge = PanelBridge()
    loop = asyncio.new_event_loop()
    bridge.set_event_loop(loop)
    queue = new_panel_queue()
    bridge.register_panel_consumer(queue)
    # clear any flush side-effects
    while not queue.empty():
        queue.get_nowait()

    calls: list[object] = []
    original = loop.call_soon_threadsafe

    def tracking(cb, *args):
        calls.append(cb)
        return original(cb, *args)

    loop.call_soon_threadsafe = tracking  # type: ignore[method-assign]
    bridge.enqueue_card({"type": "card", "id": "2", "content": "b"})
    assert calls, "expected call_soon_threadsafe"
    # drain scheduled put
    loop.call_soon(lambda: None)
    loop._run_once()
    assert queue.get_nowait()["id"] == "2"
    loop.close()


def test_buffer_maxlen_50():
    bridge = PanelBridge()
    for i in range(60):
        bridge.enqueue_card({"type": "card", "id": str(i), "content": str(i)})
    assert len(bridge._backfill_buffer) == 50
    assert bridge._backfill_buffer[0]["id"] == "10"
    assert bridge._backfill_buffer[-1]["id"] == "59"


def test_register_consumer_flushes_buffer():
    bridge = PanelBridge()
    bridge.enqueue_card({"type": "card", "id": "a"})
    bridge.enqueue_card({"type": "card", "id": "b"})
    queue = new_panel_queue()
    bridge.register_panel_consumer(queue)
    assert bridge.snapshot_backfill() == []
    assert queue.get_nowait()["id"] == "a"
    assert queue.get_nowait()["id"] == "b"


def test_unregister_consumer_removes_queue():
    bridge = PanelBridge()
    queue = new_panel_queue()
    bridge.register_panel_consumer(queue)
    assert bridge.consumer_count() == 1
    bridge.unregister_panel_consumer(queue)
    assert bridge.consumer_count() == 0
    assert queue not in bridge._ws_queues


def test_shutdown_clears_buffer_and_queues():
    bridge = PanelBridge()
    bridge.enqueue_card({"type": "card", "id": "x"})
    queue = new_panel_queue()
    bridge.register_panel_consumer(queue)
    bridge.shutdown()
    assert list(bridge._backfill_buffer) == []
    assert bridge._ws_queues == []
    assert bridge._loop is None


def test_thread_safety_concurrent_enqueue():
    bridge = PanelBridge()
    loop = asyncio.new_event_loop()
    bridge.set_event_loop(loop)
    queue = new_panel_queue()
    bridge.register_panel_consumer(queue)
    while not queue.empty():
        queue.get_nowait()

    errors: list[BaseException] = []

    def worker(start: int) -> None:
        try:
            for i in range(start, start + 20):
                bridge.enqueue_card({"type": "card", "id": str(i), "content": str(i)})
        except BaseException as exc:  # noqa: BLE001 — collect for assert
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i * 20,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        loop.call_soon(lambda: None)
        loop._run_once()
        if queue.qsize() >= 60:
            break
        time.sleep(0.01)

    assert not errors
    assert queue.qsize() == 60
    loop.close()
