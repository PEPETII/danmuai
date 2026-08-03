"""WebConsoleBridge microphone log ring + WebSocket fan-out helpers."""

from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import pyqtSlot

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


def init_mic_log_state(bridge: "WebConsoleBridge") -> None:
    bridge._mic_log_ring = deque(maxlen=200)
    bridge._ws_mic_log_queues = []
    bridge._pending_mic_log_items = []
    bridge._mic_log_flush_scheduled = False


def list_recent_mic_logs(bridge: "WebConsoleBridge", since_ts: float = 0.0) -> list[dict[str, Any]]:
    cutoff = float(since_ts or 0.0)
    return [
        dict(item)
        for item in bridge._mic_log_ring
        if float(item.get("timestamp") or 0.0) > cutoff
    ]


def clear_mic_logs(bridge: "WebConsoleBridge") -> None:
    bridge._mic_log_ring.clear()
    bridge.danmu_app.clear_mic_logs()
    broadcast_mic_log_event(bridge, {"type": "clear"})


def register_mic_log_consumer(bridge: "WebConsoleBridge", queue: asyncio.Queue) -> None:
    bridge._ws_mic_log_queues.append(queue)
    for item in bridge._mic_log_ring:
        payload = {"type": "upsert", "entry": dict(item)}
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            break
    bridge._ws_log_debug(
        f"register_mic_log_consumer consumers={len(bridge._ws_mic_log_queues)}"
    )


def unregister_mic_log_consumer(bridge: "WebConsoleBridge", queue: asyncio.Queue) -> None:
    if queue in bridge._ws_mic_log_queues:
        bridge._ws_mic_log_queues.remove(queue)
    bridge._ws_log_debug(
        f"unregister_mic_log_consumer consumers={len(bridge._ws_mic_log_queues)}"
    )


@pyqtSlot(object)
def on_mic_log_event(bridge: "WebConsoleBridge", event: object) -> None:
    if not isinstance(event, dict):
        return
    event_type = str(event.get("type") or "")
    if event_type == "clear":
        bridge._mic_log_ring.clear()
        broadcast_mic_log_event(bridge, {"type": "clear"})
        return
    if event_type == "discard":
        entry_id = str(event.get("id") or "")
        if not entry_id:
            return
        bridge._mic_log_ring = deque(
            (item for item in bridge._mic_log_ring if item.get("id") != entry_id),
            maxlen=bridge._mic_log_ring.maxlen,
        )
        broadcast_mic_log_event(bridge, {"type": "discard", "id": entry_id})
        return
    entry = event.get("entry")
    if not isinstance(entry, dict):
        return
    entry_id = str(entry.get("id") or "")
    replaced = False
    items = list(bridge._mic_log_ring)
    for index, item in enumerate(items):
        if item.get("id") == entry_id:
            items[index] = dict(entry)
            replaced = True
            break
    if not replaced:
        items.append(dict(entry))
        if len(items) > bridge._mic_log_ring.maxlen:
            items = items[-bridge._mic_log_ring.maxlen :]
    bridge._mic_log_ring = deque(items, maxlen=bridge._mic_log_ring.maxlen)
    broadcast_mic_log_event(bridge, {"type": "upsert", "entry": dict(entry)})


def broadcast_mic_log_event(bridge: "WebConsoleBridge", payload: dict[str, Any]) -> None:
    if not bridge._ws_loop_active():
        return
    bridge._pending_mic_log_items.append(payload)
    schedule_mic_log_flush(bridge)


def schedule_mic_log_flush(bridge: "WebConsoleBridge") -> None:
    if bridge._mic_log_flush_scheduled:
        return
    loop = bridge._loop
    if loop is None or loop.is_closed():
        return
    bridge._mic_log_flush_scheduled = True
    loop.call_soon_threadsafe(lambda: flush_pending_mic_logs(bridge))


def flush_pending_mic_logs(bridge: "WebConsoleBridge") -> None:
    bridge._mic_log_flush_scheduled = False
    pending = bridge._pending_mic_log_items
    bridge._pending_mic_log_items = []
    if not pending:
        return
    queues = list(bridge._ws_mic_log_queues)
    bridge._maybe_log_broadcast("mic_log", len(queues))
    for queue in queues:
        for item in pending:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    pass
