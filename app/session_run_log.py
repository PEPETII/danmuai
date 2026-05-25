"""In-memory log of completed danmu guard sessions (start → stop)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SessionRunRecord:
    started_at: float
    ended_at: float
    model: str
    input_tokens: int
    output_tokens: int
    danmu_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data


class SessionRunLog:
    def __init__(self, max_entries: int = 100) -> None:
        self._max = max(1, max_entries)
        self._entries: list[SessionRunRecord] = []
        self._pending_started_at: float = 0.0
        self._pending_model: str = ""

    def begin(self, *, started_at: float, model: str) -> None:
        self._pending_started_at = started_at
        self._pending_model = model or ""

    def complete(
        self,
        *,
        ended_at: float,
        input_tokens: int,
        output_tokens: int,
        danmu_count: int,
    ) -> SessionRunRecord | None:
        if self._pending_started_at <= 0:
            return None
        rec = SessionRunRecord(
            started_at=self._pending_started_at,
            ended_at=ended_at,
            model=self._pending_model,
            input_tokens=max(0, input_tokens),
            output_tokens=max(0, output_tokens),
            danmu_count=max(0, danmu_count),
        )
        self._entries.append(rec)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max :]
        self._pending_started_at = 0.0
        self._pending_model = ""
        return rec

    def list_dicts_newest_first(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in reversed(self._entries)]
