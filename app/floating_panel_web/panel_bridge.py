"""主进程 ↔ uvicorn 线程的浮动面板 WS 桥接。

主线程 enqueue_card；uvicorn WS endpoint register/unregister consumer。
无消费者时写入 backfill 缓冲区；有消费者时 loop.call_soon_threadsafe 入队。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

_BACKFILL_MAXLEN = 50
_QUEUE_MAXSIZE = 64


class PanelBridge:
    """Thread-safe bridge from Qt main thread to /ws/panel consumers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backfill_buffer: deque[dict[str, Any]] = deque(maxlen=_BACKFILL_MAXLEN)
        self._ws_queues: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    # --- naming aliases expected by web_console_ws / WebConsoleBridge ---
    @property
    def _ws_panel_queues(self) -> list[asyncio.Queue]:
        return self._ws_queues

    @property
    def _panel_backfill_buffer(self) -> deque[dict[str, Any]]:
        return self._backfill_buffer

    def set_event_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        with self._lock:
            self._loop = loop

    def enqueue_card(self, card_dict: dict[str, Any]) -> None:
        """Main-thread safe: buffer or fan-out card payload to WS consumers."""
        if not isinstance(card_dict, dict):
            raise TypeError("card_dict must be a dict")
        payload = dict(card_dict)
        if payload.get("type") != "card":
            payload["type"] = "card"
        with self._lock:
            queues = list(self._ws_queues)
            loop = self._loop
            if not queues:
                if len(self._backfill_buffer) >= _BACKFILL_MAXLEN:
                    logger.debug("panel backfill overflow reason=panel_buffer_overflow")
                self._backfill_buffer.append(payload)
                return
        if loop is None or loop.is_closed():
            with self._lock:
                if len(self._backfill_buffer) >= _BACKFILL_MAXLEN:
                    logger.debug("panel backfill overflow reason=panel_buffer_overflow")
                self._backfill_buffer.append(payload)
            return
        for queue in queues:
            self._enqueue_threadsafe(loop, queue, payload)

    def enqueue_message(self, message: dict[str, Any]) -> None:
        """Fan-out arbitrary panel message (config/clear/ping/get-state/reload)."""
        if not isinstance(message, dict):
            raise TypeError("message must be a dict")
        payload = dict(message)
        with self._lock:
            queues = list(self._ws_queues)
            loop = self._loop
        if not queues or loop is None or loop.is_closed():
            return
        for queue in queues:
            self._enqueue_threadsafe(loop, queue, payload)

    def register_panel_consumer(self, queue: asyncio.Queue) -> None:
        """Register WS consumer queue and flush backfill into it (uvicorn thread)."""
        with self._lock:
            if queue not in self._ws_queues:
                self._ws_queues.append(queue)
            cached = list(self._backfill_buffer)
            self._backfill_buffer.clear()
        for item in cached:
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
                    break

    def unregister_panel_consumer(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._ws_queues:
                self._ws_queues.remove(queue)

    def flush_backfill_to_queue(self, queue: asyncio.Queue) -> None:
        """Explicit flush helper (register already flushes; kept for tests/API)."""
        with self._lock:
            cached = list(self._backfill_buffer)
            self._backfill_buffer.clear()
        for item in cached:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                break

    def snapshot_backfill(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._backfill_buffer)

    def consumer_count(self) -> int:
        with self._lock:
            return len(self._ws_queues)

    def shutdown(self) -> None:
        with self._lock:
            self._backfill_buffer.clear()
            self._ws_queues.clear()
            self._loop = None

    @staticmethod
    def _enqueue_threadsafe(
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        item: Any,
    ) -> None:
        def _put() -> None:
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

        loop.call_soon_threadsafe(_put)


def new_panel_queue() -> asyncio.Queue:
    return asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
