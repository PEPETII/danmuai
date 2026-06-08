"""烂梗公式化运行时：展示队列、采集游标、文本过滤。"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from app.danmu_pool_overlay import is_overlay_safe
from app.meme_barrage.client import parse_barrage_page
from app.meme_barrage.config import read_meme_barrage_settings
from app.meme_barrage.store import MemeBarrageStore

if TYPE_CHECKING:
    from app.config_store import ConfigStore


class MemeBarrageService:
    """主线程持有：展示 FIFO 队列与采集分页游标。"""

    def __init__(self, config: "ConfigStore") -> None:
        self._config = config
        self._store = MemeBarrageStore(config)
        self._display_queue: deque[str] = deque()
        self._page_num = 1
        self._local_read_offset = 0
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
        self._page_num = 1
        self._local_read_offset = 0

    def clear_all(self) -> None:
        self._display_queue.clear()
        self._store.clear()
        self.reset_cursors()

    def enqueue_display(self, texts: list[str]) -> int:
        added = 0
        for text in texts:
            t = str(text).strip()
            if t:
                self._display_queue.append(t)
                added += 1
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
        settings = read_meme_barrage_settings(self._config)
        batch_size = int(settings["collect_batch_size"])
        texts, next_offset = self._store.fetch_batch_by_offset(self._local_read_offset, batch_size)
        self._local_read_offset = next_offset
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
            self._page_num = 1
        else:
            self._page_num += 1
        return filtered

    def next_page_num(self) -> int:
        return max(1, self._page_num)

    def settings(self) -> dict[str, object]:
        return read_meme_barrage_settings(self._config)
