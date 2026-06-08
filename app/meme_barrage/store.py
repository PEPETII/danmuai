"""烂梗本地库 SQLite 存取（config.db 内 meme_barrage_library 表）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_store import ConfigStore

LIBRARY_MAX_ROWS = 10_000


class MemeBarrageStore:
    def __init__(self, config: "ConfigStore") -> None:
        self._config = config

    def count(self) -> int:
        return self._config.meme_barrage_library_count()

    def clear(self) -> None:
        self._config.meme_barrage_library_clear()

    def insert_many(
        self,
        items: list[tuple[str, str | None, int | None]],
    ) -> int:
        """Insert (text, source_tag, remote_id) rows; skip duplicates. Returns added count."""
        return self._config.meme_barrage_library_insert_many(
            items,
            collected_at=time.time(),
            max_rows=LIBRARY_MAX_ROWS,
        )

    def fetch_batch_by_offset(self, offset: int, limit: int) -> tuple[list[str], int]:
        """FIFO read from library without deleting rows. Returns texts and next offset."""
        return self._config.meme_barrage_library_fetch_batch(offset, limit)

    def contains_text(self, text: str) -> bool:
        """True when text exactly matches a stored meme barrage line."""
        return self._config.meme_barrage_library_contains_text(text)
