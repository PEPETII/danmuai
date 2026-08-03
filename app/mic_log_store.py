"""In-memory microphone speech-to-text log ring for the Web console.

Session-scoped like danmu runtime logs (``WebConsoleBridge._log_ring``); not persisted
to config.db. Entries are keyed by utterance id so partial rows can merge into final
success/failed rows without duplicate partial spam.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Literal

from PyQt6.QtCore import QObject, pyqtSignal

MicLogStatus = Literal["success", "partial", "failed"]
MAX_MIC_LOG_ENTRIES = 200


@dataclass(frozen=True)
class MicLogEntry:
    id: str
    timestamp: float
    text: str
    status: MicLogStatus
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MicLogStore(QObject):
    """Thread-safe enough for main-thread writes + background transcript completion slots."""

    entry_emitted = pyqtSignal(object)

    def __init__(self, *, max_entries: int = MAX_MIC_LOG_ENTRIES) -> None:
        super().__init__()
        self._max_entries = max(1, int(max_entries))
        self._entries: deque[MicLogEntry] = deque(maxlen=self._max_entries)
        self._index_by_id: dict[str, MicLogEntry] = {}

    def begin_partial(self, *, utterance_id: str | None = None) -> MicLogEntry:
        entry_id = (utterance_id or "").strip() or str(uuid.uuid4())
        entry = MicLogEntry(
            id=entry_id,
            timestamp=time.time(),
            text="",
            status="partial",
        )
        self._upsert(entry)
        return entry

    def finalize(
        self,
        entry_id: str,
        *,
        text: str,
        status: MicLogStatus,
        error: str = "",
    ) -> MicLogEntry | None:
        existing = self._index_by_id.get(entry_id)
        if existing is None:
            return None
        cleaned = (text or "").strip()
        if status == "success" and not cleaned:
            status = "failed"
            error = error or "empty_transcript"
        entry = MicLogEntry(
            id=entry_id,
            timestamp=existing.timestamp,
            text=cleaned,
            status=status,
            error=(error or "").strip(),
        )
        self._upsert(entry)
        return entry

    def discard(self, entry_id: str) -> None:
        if entry_id not in self._index_by_id:
            return
        self._entries = deque(
            (item for item in self._entries if item.id != entry_id),
            maxlen=self._max_entries,
        )
        self._index_by_id.pop(entry_id, None)
        self.entry_emitted.emit({"type": "discard", "id": entry_id})

    def clear(self) -> None:
        self._entries.clear()
        self._index_by_id.clear()
        self.entry_emitted.emit({"type": "clear"})

    def list_recent(self, since_ts: float = 0.0) -> list[dict[str, Any]]:
        cutoff = float(since_ts or 0.0)
        return [
            entry.to_dict()
            for entry in self._entries
            if entry.timestamp > cutoff
        ]

    def _upsert(self, entry: MicLogEntry) -> None:
        if entry.id in self._index_by_id:
            self._entries = deque(
                (item if item.id != entry.id else entry for item in self._entries),
                maxlen=self._max_entries,
            )
        else:
            if len(self._entries) >= self._max_entries:
                evicted = self._entries.popleft()
                self._index_by_id.pop(evicted.id, None)
            self._entries.append(entry)
        self._index_by_id[entry.id] = entry
        self.entry_emitted.emit({"type": "upsert", "entry": entry.to_dict()})
