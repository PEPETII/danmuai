"""请求耗时样本：拥有 request_started_at_by_id 与 rtt_history，供 RTT/cooldown 计算。

复合键设计：request_id = {request_round}:{screenshot_id}:{scene_generation}，
麦克风与视觉请求可在同一 screenshot_id 不冲突（request_round 负值区分来源）。
"""
from __future__ import annotations

from collections import deque


class RequestTimingService:
    """mark_started 在 _trigger_api_call；consume_timing 在 _on_ai_reply/_on_ai_error。

    仅由 Qt 主线程访问；无锁。
    """

    def __init__(
        self,
        *,
        request_started_at_by_id: dict[str, float] | None = None,
        rtt_history: deque[float] | list[float] | None = None,
    ) -> None:
        self.request_started_at_by_id = request_started_at_by_id or {}
        if rtt_history is None:
            self.rtt_history: deque[float] = deque(maxlen=20)
        elif isinstance(rtt_history, deque):
            self.rtt_history = rtt_history
        else:
            self.rtt_history = deque(rtt_history, maxlen=20)

    def reset_started(self) -> None:
        self.request_started_at_by_id = {}

    def clear_started(self) -> None:
        self.request_started_at_by_id.clear()

    def purge_stale(self, *, now: float, max_age_sec: float = 120.0) -> int:
        """移除超过 max_age_sec 仍未 consume 的 mark_started 条目（网络断开等孤儿请求）。"""
        cutoff = float(now) - float(max_age_sec)
        stale_keys = [
            key
            for key, started_at in self.request_started_at_by_id.items()
            if float(started_at) < cutoff
        ]
        for key in stale_keys:
            self.request_started_at_by_id.pop(key, None)
        return len(stale_keys)

    def reset_rtt_history(self) -> None:
        self.rtt_history = deque(maxlen=20)

    def clear_rtt_history(self) -> None:
        self.rtt_history.clear()

    def mark_started(
        self,
        *,
        request_id: tuple[int, int, int] | str,
        now: float,
    ) -> float:
        """记录请求开始时间；由 _trigger_api_call 在发起请求前调用。"""
        self.request_started_at_by_id[request_id] = float(now)
        return float(now)

    def consume_timing(
        self,
        *,
        request_id: tuple[int, int, int] | str,
        now: float,
        max_samples: int = 20,
    ) -> float | None:
        """消费 RTT 样本：计算耗时并记录到 rtt_history；无对应 mark_started 时返回 None。"""
        started_at = self.request_started_at_by_id.pop(request_id, None)
        if started_at is None:
            return None
        rtt = float(now) - float(started_at)
        self.record_rtt(rtt=rtt, max_samples=max_samples)
        return rtt

    def record_rtt(
        self,
        *,
        rtt: float,
        max_samples: int = 20,
    ) -> None:
        if (
            max_samples != self.rtt_history.maxlen
            and isinstance(self.rtt_history, deque)
        ):
            self.rtt_history = deque(self.rtt_history, maxlen=max_samples)
        self.rtt_history.append(float(rtt))

    def avg_rtt(self) -> float:
        if not self.rtt_history:
            return 0.0
        return sum(self.rtt_history) / len(self.rtt_history)

    def smart_cooldown_ms(
        self,
        *,
        fallback_interval_sec: int,
    ) -> int:
        if len(self.rtt_history) >= 3:
            sorted_rtt = sorted(self.rtt_history)
            idx = int(len(sorted_rtt) * 0.9)
            p90 = sorted_rtt[min(idx, len(sorted_rtt) - 1)]
            return max(1500, min(int(p90 * 0.9 * 1000), 30000))
        return max(2000, int(fallback_interval_sec) * 1000)
