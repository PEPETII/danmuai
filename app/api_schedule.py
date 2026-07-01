"""API scheduling helpers: debug logging, min-interval throttling, anchor-boundary timing."""

from __future__ import annotations

import time

from app.env_config import get as get_env

# Matches DanmuEngine: x -= speed * factor * (dt / (1/60)) → ~speed*60 px/s at factor=1.
ENGINE_BASE_FPS = 60.0
DEFAULT_MIN_API_INTERVAL_MS = 800


def api_schedule_debug_enabled() -> bool:
    value = get_env("DANMU_API_SCHEDULE_DEBUG").strip().lower()
    return value in ("1", "true", "yes", "on")


def min_api_interval_ms() -> int:
    raw = get_env("DANMU_MIN_API_INTERVAL_MS").strip()
    if not raw:
        return DEFAULT_MIN_API_INTERVAL_MS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MIN_API_INTERVAL_MS


def min_api_interval_elapsed(last_trigger_at: float, now: float | None = None) -> bool:
    if last_trigger_at <= 0:
        return True
    now = time.monotonic() if now is None else now
    elapsed_ms = (now - last_trigger_at) * 1000.0
    return elapsed_ms >= min_api_interval_ms()


def pixels_per_second(speed: float, speed_factor: float = 1.0) -> float:
    return max(speed * speed_factor * ENGINE_BASE_FPS, 1e-6)


def time_to_anchor_boundary(distance: float, speed: float, speed_factor: float = 1.0) -> float:
    if distance <= 0 or speed <= 0:
        return 0.0
    return distance / pixels_per_second(speed, speed_factor)


def format_api_schedule_log(
    *,
    decision: str,
    source: str,
    batch_id: int | None,
    next_generation_time: float,
    rtt_avg: float,
    buffer_size: int,
    visible_count: int,
    in_flight: bool,
    block_reason: str = "",
    scene_gen: int = 0,
    cooldown_left_ms: int = 0,
) -> str:
    bid = batch_id if batch_id is not None else -1
    return (
        f"api_schedule decision={decision} source={source} batch_id={bid} "
        f"next_gen={next_generation_time:.3f} rtt_avg={rtt_avg:.2f} buffer={buffer_size} "
        f"visible={visible_count} in_flight={int(in_flight)} block_reason={block_reason} "
        f"scene_gen={scene_gen} cooldown_left_ms={cooldown_left_ms}"
    )
