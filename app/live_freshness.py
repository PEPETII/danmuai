"""Latest-frame-first live freshness helpers (request gating, fallback, status)."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from app.reply_parser import normalize_reply_batch
from app.translations import tr

# At most one visual request in flight; new captures do not queue another.
SLOW_REQUEST_SEC = 4.0
SLOW_RTT_P90_SEC = 6.0
STALE_DROP_WINDOW_SEC = 30.0
STALE_DROP_BURST_THRESHOLD = 4
MAX_SCREENSHOT_BACKOFF_LEVEL = 4
MAX_SCREENSHOT_INTERVAL_MS = 12_000

# Scene-change UX (medium/strict): rhythm pause before next API
SCENE_RHYTHM_PAUSE_SEC = 0.5
# Ignore rapid hash flicker (Alt-Tab / overlay) unless change is large
SCENE_CHANGE_DEBOUNCE_SEC = 2.0
SCENE_CHANGE_FORCE_DIST = 15


@dataclass(frozen=True)
class LiveStatusSnapshot:
    analyzing: bool = False
    local_fallback: bool = False
    delay_sec: float = 0.0
    stale_drops: int = 0

    def primary_message(self) -> str:
        if self.local_fallback:
            return tr("control.live_fallback")
        if self.analyzing:
            return tr("control.live_analyzing")
        return tr("control.status_running_desc")

    def detail_message(self) -> str:
        delay = max(0.0, self.delay_sec)
        return tr("control.live_detail").format(
            delay=f"{delay:.1f}",
            drops=self.stale_drops,
        )


def build_local_fallback_batch(
    scene_count: int = 2,
    filler_count: int = 3,
    *,
    config=None,
) -> list[str]:
    """Short danmu from built-in filler pools (no API)."""
    from app.danmu_pool import load_danmu_pool_for_config, sample_danmu_for_config
    from app.reply_parser import _legacy_generic_fillers, _legacy_scene_fillers

    pool = load_danmu_pool_for_config(config)
    if pool:
        total = scene_count + filler_count
        picked = sample_danmu_for_config(config, min(total, len(pool)))
        if len(picked) >= total:
            seed = picked[:total]
        else:
            seed = picked[:]
            while len(seed) < total:
                seed.append(picked[len(seed) % len(picked)])
    else:
        scene = _legacy_scene_fillers()
        generic = _legacy_generic_fillers() + [
            tr("reply.local_fallback_1"),
            tr("reply.local_fallback_2"),
            tr("reply.local_fallback_3"),
        ]
        random.shuffle(generic)
        seed = []
        for i in range(scene_count):
            seed.append(scene[i % len(scene)])
        for i in range(filler_count):
            seed.append(generic[i % len(generic)])
    return normalize_reply_batch(
        seed,
        scene_count=scene_count,
        filler_count=filler_count,
        allow_shortfall=True,
        config=config,
    )


def prune_stale_drop_times(times: list[float], now: float | None = None) -> list[float]:
    now = time.monotonic() if now is None else now
    cutoff = now - STALE_DROP_WINDOW_SEC
    return [t for t in times if t >= cutoff]


def should_backoff_screenshot(stale_drop_times: list[float], now: float | None = None) -> bool:
    pruned = prune_stale_drop_times(stale_drop_times, now)
    return len(pruned) >= STALE_DROP_BURST_THRESHOLD


def screenshot_interval_ms(base_interval_sec: int, backoff_level: int) -> int:
    base_ms = max(1000, base_interval_sec * 1000)
    level = min(max(0, backoff_level), MAX_SCREENSHOT_BACKOFF_LEVEL)
    scaled = int(base_ms * (1.0 + 0.5 * level))
    return min(scaled, MAX_SCREENSHOT_INTERVAL_MS)


def is_model_slow(rtt_history: list[float], inflight_elapsed: float, *, in_flight: bool) -> bool:
    if in_flight and inflight_elapsed >= SLOW_REQUEST_SEC:
        return True
    if len(rtt_history) >= 3:
        sorted_rtt = sorted(rtt_history)
        idx = int(len(sorted_rtt) * 0.9)
        p90 = sorted_rtt[min(idx, len(sorted_rtt) - 1)]
        if p90 >= SLOW_RTT_P90_SEC:
            return True
    return False
