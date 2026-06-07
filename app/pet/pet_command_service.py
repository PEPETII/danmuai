"""Pending desktop-pet commands injected into the next visual AI request."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

MAX_COMMAND_LEN = 200
MAX_PENDING = 1


@dataclass
class PetCommand:
    id: str
    text: str
    created_at: float
    ttl_sec: int
    remaining_apply_count: int
    source: str = "desktop_pet"


@dataclass
class PetCommandService:
    """At most one pending command; consumed only when visual request actually fires."""

    _pending: PetCommand | None = field(default=None, init=False)

    def purge_expired(self, *, now: float | None = None) -> None:
        if self._pending is None:
            return
        ts = now if now is not None else time.monotonic()
        age = ts - self._pending.created_at
        if age > self._pending.ttl_sec:
            self._pending = None

    def has_pending(self) -> bool:
        self.purge_expired()
        return self._pending is not None

    def peek_summary(self) -> dict[str, object] | None:
        self.purge_expired()
        if self._pending is None:
            return None
        text = self._pending.text
        preview = text if len(text) <= 40 else f"{text[:40]}…"
        return {
            "id": self._pending.id,
            "preview": preview,
            "ttl_sec": self._pending.ttl_sec,
            "remaining_apply_count": self._pending.remaining_apply_count,
        }

    def submit(
        self,
        text: str,
        *,
        ttl_sec: int,
        apply_count: int,
        source: str = "desktop_pet",
    ) -> dict[str, object]:
        cleaned = (text or "").strip()
        if not cleaned:
            raise ValueError("指令内容不能为空")
        if len(cleaned) > MAX_COMMAND_LEN:
            cleaned = cleaned[:MAX_COMMAND_LEN]
        self.purge_expired()
        self._pending = PetCommand(
            id=uuid.uuid4().hex[:12],
            text=cleaned,
            created_at=time.monotonic(),
            ttl_sec=max(5, min(int(ttl_sec), 300)),
            remaining_apply_count=max(1, min(int(apply_count), 5)),
            source=source,
        )
        return {"ok": True, "id": self._pending.id, "preview": cleaned[:40]}

    def consume_for_prompt(self) -> str | None:
        """Return command text when a visual request is about to fire; decrements apply count."""
        self.purge_expired()
        if self._pending is None:
            return None
        cmd = self._pending
        text = cmd.text
        cmd.remaining_apply_count -= 1
        if cmd.remaining_apply_count <= 0:
            self._pending = None
        return text
