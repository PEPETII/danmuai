"""Pet render-loop scheduling helpers (overlay idle-stop pattern, sprite frame cadence).

Overlay stops its 60fps QTimer when ``engine.needs_render_tick()`` is false.
PetWindow cannot fully stop while visible (idle sprites still cycle), but may drop
from 16ms polling to single-shot wakeups aligned to ``state_frame_interval_sec``.
"""

from __future__ import annotations

import time

BUBBLE_ALPHA_EPSILON = 0.001
_DEFAULT_FRAME_INTERVAL_SEC = 1100 / 6 / 1000.0
_MIN_WAKE_MS = 1


def needs_high_frequency_tick(
    *,
    dragging: bool,
    momentum_active: bool,
    bubble_alpha: float,
    bubble_target_alpha: float,
) -> bool:
    """16ms cadence: drag, throw momentum, or bubble alpha fade."""
    if dragging or momentum_active:
        return True
    return abs(bubble_alpha - bubble_target_alpha) > BUBBLE_ALPHA_EPSILON


def needs_animation_tick(
    *,
    visible: bool,
    assets_ready: bool,
    dragging: bool,
    momentum_active: bool,
    bubble_alpha: float,
    bubble_target_alpha: float,
    one_shot: str | None,
    one_shot_until: float,
    post_drag_waving_until: float,
    now: float | None = None,
) -> bool:
    """Whether any animation work remains (high- or low-frequency)."""
    if not visible:
        return False
    ts = now if now is not None else time.monotonic()
    if needs_high_frequency_tick(
        dragging=dragging,
        momentum_active=momentum_active,
        bubble_alpha=bubble_alpha,
        bubble_target_alpha=bubble_target_alpha,
    ):
        return True
    if one_shot and ts < one_shot_until:
        return True
    if post_drag_waving_until > ts:
        return True
    return assets_ready


def ms_until_next_frame_tick(
    *,
    frame_clock: float,
    frame_interval_sec: float,
) -> int:
    """Milliseconds until the next sprite frame should advance."""
    remaining = max(0.0, frame_interval_sec - frame_clock)
    return max(_MIN_WAKE_MS, int(remaining * 1000.0))
