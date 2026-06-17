"""Recent no-danmu diagnostics for user-facing troubleshooting.

This module intentionally has no Qt dependency. It records only coarse reasons
and counters; it must not store screenshots, AI raw replies, API keys, or other
private payloads.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any

MAX_RECENT_EVENTS = 50
COALESCE_WINDOW_SEC = 2.0

REASON_LABELS = {
    "ai_error": "AI 请求失败",
    "capture_failed": "截图失败",
    "duplicate": "去重拦截",
    "empty_parse": "AI 回复解析为空",
    "empty_text": "空文本",
    "entry_overloaded": "入口区过载",
    "floating_panel_spacing": "悬浮窗间距不足",
    "layout_reject": "轨道/布局未接纳",
}


@dataclass
class DanmuDiagnosticEvent:
    reason: str
    stage: str
    source: str
    detail: str
    screenshot_id: int
    request_round: int
    at: float
    repeat_count: int = 1

    def to_dict(self, *, now: float) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "label": REASON_LABELS.get(self.reason, self.reason),
            "stage": self.stage,
            "source": self.source,
            "detail": self.detail,
            "screenshot_id": self.screenshot_id,
            "request_round": self.request_round,
            "age_sec": max(0.0, float(now) - float(self.at)),
            "repeat_count": self.repeat_count,
        }


class DanmuDiagnostics:
    """Bounded, in-memory ring buffer for recent no-display reasons."""

    def __init__(self, max_events: int = MAX_RECENT_EVENTS) -> None:
        self._events: deque[DanmuDiagnosticEvent] = deque(maxlen=max(1, int(max_events)))
        self._counts: Counter[str] = Counter()

    def reset(self) -> None:
        self._events.clear()
        self._counts.clear()

    def record(
        self,
        reason: str,
        *,
        stage: str,
        source: str = "visual",
        detail: str = "",
        screenshot_id: int = 0,
        request_round: int = 0,
        at: float | None = None,
    ) -> None:
        reason = str(reason or "unknown").strip() or "unknown"
        stage = str(stage or "unknown").strip() or "unknown"
        source = str(source or "visual").strip() or "visual"
        detail = str(detail or "").strip()
        now = time.monotonic() if at is None else float(at)

        previous = self._events[-1] if self._events else None
        if (
            previous is not None
            and previous.reason == reason
            and previous.stage == stage
            and previous.source == source
            and now - previous.at <= COALESCE_WINDOW_SEC
        ):
            previous.detail = detail
            previous.screenshot_id = max(0, int(screenshot_id or 0))
            previous.request_round = int(request_round or 0)
            previous.at = now
            previous.repeat_count += 1
            self._counts[reason] += 1
            return

        self._events.append(
            DanmuDiagnosticEvent(
                reason=reason,
                stage=stage,
                source=source,
                detail=detail,
                screenshot_id=max(0, int(screenshot_id or 0)),
                request_round=int(request_round or 0),
                at=now,
            )
        )
        self._counts[reason] += 1

    def snapshot(self, *, now: float | None = None, recent_limit: int = 5) -> dict[str, Any]:
        now_value = time.monotonic() if now is None else float(now)
        recent = [
            event.to_dict(now=now_value)
            for event in list(self._events)[-max(0, int(recent_limit)) :]
        ]
        recent.reverse()
        top_reasons = [
            {
                "reason": reason,
                "label": REASON_LABELS.get(reason, reason),
                "count": int(count),
            }
            for reason, count in self._counts.most_common(5)
        ]
        latest = recent[0] if recent else None
        return {
            "recent_count": len(self._events),
            "total_recorded": int(sum(self._counts.values())),
            "top_reasons": top_reasons,
            "latest": latest,
            "recent": recent,
        }
