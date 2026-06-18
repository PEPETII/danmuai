"""最近未上屏弹幕诊断：记录粗粒度元信息，聚合为 diagnostics 可读摘要。

设计约束：
- 不存储截图内容、原始 AI 回复全文、API Key、prompt 正文
- 不新增数据库持久化（纯内存，进程生命周期内有效）
- 线程安全（主线程记录，HTTP 线程读取快照）
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field

# 最近保留的事件数（足够展示 "最近原因列表" 与 Top reason）
_MAX_RECENT_EVENTS = 50

# 已知未上屏原因（与 main.py / main_display_mixin.py 中的日志标签对齐）
KNOWN_REASONS = frozenset(
    {
        "capture_failure",
        "ai_request_failure",
        "empty_parse",
        "duplicate",
        "duplicate_exact_set_hit",
        "duplicate_exact_window_hit",
        "duplicate_similarity_hit",
        "empty_text",
        "floating_panel_spacing",
        "entry_zone_overload",
        "layout_rejection",
    }
)


@dataclass
class UndisplayedEvent:
    """单条未上屏事件元信息（不含弹幕正文、截图、prompt）。"""

    reason: str
    timestamp: float
    persona_id: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason,
            "timestamp": self.timestamp,
            "persona_id": self.persona_id,
        }


@dataclass
class UndisplayedSummary:
    """聚合摘要，供 diagnostic_snapshot 暴露。"""

    recent_count: int = 0
    total_count: int = 0
    latest_reason: str = ""
    latest_timestamp: float = 0.0
    top_reason: str = ""
    top_reason_count: int = 0
    recent_events: list[dict[str, object]] = field(default_factory=list)
    reason_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "recent_count": self.recent_count,
            "total_count": self.total_count,
            "latest_reason": self.latest_reason,
            "latest_timestamp": self.latest_timestamp,
            "top_reason": self.top_reason,
            "top_reason_count": self.top_reason_count,
            "recent_events": self.recent_events,
            "reason_counts": self.reason_counts,
        }


class DanmuDiagnosticsRecorder:
    """记录最近未上屏事件，聚合为粗粒度摘要。

    线程安全：主线程记录（_consume_reply_queue / _on_ai_reply / _on_ai_error），
    HTTP 线程读取快照（DiagnosticSnapshotBuilder.build）。
    """

    def __init__(self, max_recent: int = _MAX_RECENT_EVENTS) -> None:
        self._lock = threading.Lock()
        self._recent: deque[UndisplayedEvent] = deque(maxlen=max_recent)
        self._total_count = 0
        self._reason_counter: Counter[str] = Counter()

    def record(
        self,
        reason: str,
        *,
        persona_id: str = "",
        timestamp: float | None = None,
    ) -> None:
        """记录一条未上屏事件。reason 应为 KNOWN_REASONS 之一。"""
        if not reason:
            return
        ts = timestamp if timestamp is not None else time.time()
        event = UndisplayedEvent(reason=reason, timestamp=ts, persona_id=persona_id or "")
        with self._lock:
            self._recent.append(event)
            self._total_count += 1
            self._reason_counter[reason] += 1

    def reset(self) -> None:
        """清空所有记录（start / stop 时调用）。"""
        with self._lock:
            self._recent.clear()
            self._total_count = 0
            self._reason_counter.clear()

    def snapshot(self) -> UndisplayedSummary:
        """生成只读摘要。"""
        with self._lock:
            recent_list = [ev.to_dict() for ev in self._recent]
            latest_reason = recent_list[-1]["reason"] if recent_list else ""
            latest_ts = recent_list[-1]["timestamp"] if recent_list else 0.0
            top_reason = ""
            top_count = 0
            if self._reason_counter:
                top_reason, top_count = self._reason_counter.most_common(1)[0]
            return UndisplayedSummary(
                recent_count=len(recent_list),
                total_count=self._total_count,
                latest_reason=str(latest_reason),
                latest_timestamp=float(latest_ts),
                top_reason=str(top_reason),
                top_reason_count=int(top_count),
                recent_events=recent_list,
                reason_counts=dict(self._reason_counter),
            )
