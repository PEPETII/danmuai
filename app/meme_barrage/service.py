"""烂梗公式化运行时：展示队列、采集游标、文本过滤。"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from app.danmu_pool_overlay import is_overlay_safe
from app.meme_barrage.client import parse_barrage_page
from app.meme_barrage.config import (
    DEFAULT_LOCAL_READ_OFFSET,
    DEFAULT_REMOTE_PAGE_NUM,
    load_meme_barrage_cursors,
    persist_meme_barrage_cursors,
    read_meme_barrage_settings,
)
from app.meme_barrage.store import MemeBarrageStore

if TYPE_CHECKING:
    from app.config_store import ConfigStore


class MemeBarrageService:
    """主线程持有：展示 FIFO 队列与采集分页游标。

    _display_queue 的 enqueue/pop 组合仅在 Qt 主线程定时器内调用，无跨线程写入。
    """

    def __init__(self, config: "ConfigStore") -> None:
        self._config = config
        self._store = MemeBarrageStore(config)
        self._display_queue: deque[str] = deque()
        self._settings_cache: dict[str, object] | None = None
        local_offset, page_num = load_meme_barrage_cursors(config)
        self._page_num = page_num
        self._local_read_offset = local_offset
        self._fetch_in_flight = False
        self._ai_select_in_flight = False

    @property
    def store(self) -> MemeBarrageStore:
        return self._store

    def library_count(self) -> int:
        return self._store.count()

    def display_queue_size(self) -> int:
        return len(self._display_queue)

    def is_fetch_in_flight(self) -> bool:
        return self._fetch_in_flight

    def is_ai_select_in_flight(self) -> bool:
        return self._ai_select_in_flight

    def set_fetch_in_flight(self, value: bool) -> None:
        self._fetch_in_flight = bool(value)

    def set_ai_select_in_flight(self, value: bool) -> None:
        self._ai_select_in_flight = bool(value)

    def reset_cursors(self) -> None:
        self._page_num = DEFAULT_REMOTE_PAGE_NUM
        self._local_read_offset = DEFAULT_LOCAL_READ_OFFSET
        persist_meme_barrage_cursors(
            self._config,
            local_offset=self._local_read_offset,
            page_num=self._page_num,
        )

    def clear_all(self) -> None:
        self._display_queue.clear()
        self._store.clear()
        self.reset_cursors()
        self.invalidate_settings_cache()

    def invalidate_settings_cache(self) -> None:
        self._settings_cache = None

    def _cached_settings(self) -> dict[str, object]:
        if self._settings_cache is None:
            self._settings_cache = read_meme_barrage_settings(self._config)
        return self._settings_cache

    def enqueue_display(self, texts: list[str]) -> int:
        added = 0
        for text in texts:
            t = str(text).strip()
            if t:
                self._display_queue.append(t)
                added += 1
        # Backpressure: drop oldest items when queue exceeds limit
        from app.meme_barrage.config import DISPLAY_QUEUE_MAX

        dropped = len(self._display_queue) - DISPLAY_QUEUE_MAX
        if dropped > 0:
            for _ in range(dropped):
                self._display_queue.popleft()
        return added

    def pop_display_batch(self, count: int) -> list[str]:
        if count <= 0:
            return []
        batch: list[str] = []
        while self._display_queue and len(batch) < count:
            batch.append(self._display_queue.popleft())
        return batch

    def filter_remote_items(self, raw_items: list[dict[str, Any]]) -> list[tuple[str, str | None, int | None]]:
        out: list[tuple[str, str | None, int | None]] = []
        seen: set[str] = set()
        for item in raw_items:
            text = str(item.get("barrage", "") or "").strip()
            if not text or text in seen:
                continue
            if not is_overlay_safe(text, max_chars=None):
                continue
            seen.add(text)
            tags = str(item.get("tags", "") or "").strip() or None
            remote_id = item.get("id")
            try:
                rid = int(remote_id) if remote_id is not None else None
            except (TypeError, ValueError):
                rid = None
            out.append((text, tags, rid))
        return out

    def collect_local_batch(self) -> list[str]:
        settings = self._cached_settings()
        batch_size = int(settings["collect_batch_size"])
        texts, next_offset = self._store.fetch_batch_by_offset(self._local_read_offset, batch_size)
        self._local_read_offset = next_offset
        persist_meme_barrage_cursors(
            self._config,
            local_offset=self._local_read_offset,
            page_num=self._page_num,
        )
        return texts

    def ingest_collected_texts(self, texts: list[str], *, source_tag: str | None = None) -> list[str]:
        """Normalize, store in library, return cleaned list for display pipeline."""
        cleaned: list[str] = []
        seen: set[str] = set()
        store_rows: list[tuple[str, str | None, int | None]] = []
        for raw in texts:
            text = str(raw).strip()
            if not text or text in seen:
                continue
            if not is_overlay_safe(text, max_chars=None):
                continue
            seen.add(text)
            cleaned.append(text)
            store_rows.append((text, source_tag, None))
        if store_rows:
            self._store.insert_many(store_rows)
        return cleaned

    def apply_remote_page(self, data: dict[str, Any]) -> list[tuple[str, str | None, int | None]]:
        items, last_page = parse_barrage_page(data)
        filtered = self.filter_remote_items(items)
        if last_page:
            self._page_num = DEFAULT_REMOTE_PAGE_NUM
        else:
            self._page_num += 1
        persist_meme_barrage_cursors(
            self._config,
            local_offset=self._local_read_offset,
            page_num=self._page_num,
        )
        return filtered

    def next_page_num(self) -> int:
        return max(1, self._page_num)

    def settings(self) -> dict[str, object]:
        return dict(self._cached_settings())
