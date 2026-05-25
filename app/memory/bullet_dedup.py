"""Recent displayed bullets and expression angles for dedup hints."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.memory.types import MAX_BULLET_SNIPPET_LEN, DisplayedBullet


def _truncate_bullet(content: str, max_len: int = MAX_BULLET_SNIPPET_LEN) -> str:
    text = (content or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


@dataclass
class BulletDedupMemory:
    recent_bullets: list[DisplayedBullet] = field(default_factory=list)
    recent_angles: list[str] = field(default_factory=list)
    avoid_angles: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.recent_bullets

    def record(
        self,
        content: str,
        *,
        angle: str = "",
        window: int = 10,
    ) -> None:
        snippet = _truncate_bullet(content)
        if not snippet:
            return
        bullet = DisplayedBullet(text=snippet, angle=angle or "", recorded_at=time.monotonic())
        self.recent_bullets.append(bullet)
        if window > 0 and len(self.recent_bullets) > window:
            self.recent_bullets = self.recent_bullets[-window:]
        self._rebuild_angles()

    def _rebuild_angles(self) -> None:
        angles: list[str] = []
        seen: set[str] = set()
        for bullet in reversed(self.recent_bullets):
            angle = (bullet.angle or "").strip()
            if not angle or angle in seen:
                continue
            seen.add(angle)
            angles.insert(0, angle)
        self.recent_angles = angles
        self.avoid_angles = list(angles)

    def clear(self) -> None:
        self.recent_bullets.clear()
        self.recent_angles.clear()
        self.avoid_angles.clear()

    def trim_to(self, count: int) -> None:
        if count <= 0:
            self.clear()
            return
        if len(self.recent_bullets) > count:
            self.recent_bullets = self.recent_bullets[-count:]
        self._rebuild_angles()
