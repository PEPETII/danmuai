"""Per-model Live2D display scale persistence and bottom-center anchor math."""

from __future__ import annotations

import json
from typing import Any

LIVE2D_MODEL_DISPLAY_SCALES_KEY = "live2d_model_display_scales"
DEFAULT_DISPLAY_SCALE_PERCENT = 100
MIN_DISPLAY_SCALE_PERCENT = 25
MAX_DISPLAY_SCALE_PERCENT = 300
# live2d-py fits the model into the fixed desktop window at SetScale(1.0).
# Values above 1.0 grow past the OpenGL viewport and get clipped, so the UI
# percent range is mapped into a safe uniform scale band instead.
DISPLAY_SCALE_UNIFORM_MIN = 0.25
DISPLAY_SCALE_UNIFORM_MID = 1.0
DISPLAY_SCALE_UNIFORM_MAX = 1.18


def clamp_display_scale_percent(value: object) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = DEFAULT_DISPLAY_SCALE_PERCENT
    return max(MIN_DISPLAY_SCALE_PERCENT, min(MAX_DISPLAY_SCALE_PERCENT, parsed))


def scale_factor_from_percent(percent: int) -> float:
    return resolve_uniform_scale(percent)


def resolve_uniform_scale(percent: int) -> float:
    """Map UI percent (25–300) to a viewport-safe ``SetScale`` factor."""

    percent = clamp_display_scale_percent(percent)
    if percent <= DEFAULT_DISPLAY_SCALE_PERCENT:
        span = DEFAULT_DISPLAY_SCALE_PERCENT - MIN_DISPLAY_SCALE_PERCENT
        ratio = (percent - MIN_DISPLAY_SCALE_PERCENT) / span
        return DISPLAY_SCALE_UNIFORM_MIN + ratio * (
            DISPLAY_SCALE_UNIFORM_MID - DISPLAY_SCALE_UNIFORM_MIN
        )
    span = MAX_DISPLAY_SCALE_PERCENT - DEFAULT_DISPLAY_SCALE_PERCENT
    ratio = (percent - DEFAULT_DISPLAY_SCALE_PERCENT) / span
    return DISPLAY_SCALE_UNIFORM_MID + ratio * (
        DISPLAY_SCALE_UNIFORM_MAX - DISPLAY_SCALE_UNIFORM_MID
    )


def compute_bottom_center_offset_y(scale: float) -> float:
    """Return normalized scene offset to keep the model foot anchored.

    live2d-py ``SetOffset`` uses scene-space units (see official examples using
  values like ``0.3`` / ``-0.5``), not widget pixels.
    """

    if scale <= 0:
        return 0.0
    return -(scale - 1.0) * 0.5


def _read_display_scales_raw(config) -> dict[str, int]:
    raw = config.get(LIVE2D_MODEL_DISPLAY_SCALES_KEY, "{}")
    if isinstance(raw, dict):
        source: dict[str, Any] = raw
    else:
        try:
            loaded = json.loads(str(raw or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            loaded = {}
        source = loaded if isinstance(loaded, dict) else {}
    result: dict[str, int] = {}
    for key, value in source.items():
        model_id = str(key or "").strip()
        if model_id:
            result[model_id] = clamp_display_scale_percent(value)
    return result


def get_model_display_scale_percent(config, model_id: str | None) -> int:
    model_id = str(model_id or "").strip()
    if not model_id:
        return DEFAULT_DISPLAY_SCALE_PERCENT
    return _read_display_scales_raw(config).get(model_id, DEFAULT_DISPLAY_SCALE_PERCENT)


def set_model_display_scale_percent(config, model_id: str, percent: int) -> int:
    model_id = str(model_id or "").strip()
    if not model_id:
        raise ValueError("live2d_model_id_required")
    normalized = clamp_display_scale_percent(percent)
    scales = _read_display_scales_raw(config)
    scales[model_id] = normalized
    setter = getattr(config, "set", None)
    if not callable(setter):
        raise RuntimeError("config store unavailable")
    setter(
        LIVE2D_MODEL_DISPLAY_SCALES_KEY,
        json.dumps(scales, ensure_ascii=False, separators=(",", ":")),
    )
    return normalized


def export_display_scale_settings(config, model_id: str | None) -> dict[str, object]:
    percent = get_model_display_scale_percent(config, model_id)
    return {
        "display_scale_percent": percent,
        "display_scale_min_percent": MIN_DISPLAY_SCALE_PERCENT,
        "display_scale_max_percent": MAX_DISPLAY_SCALE_PERCENT,
        "display_scale_default_percent": DEFAULT_DISPLAY_SCALE_PERCENT,
    }


__all__ = [
    "DEFAULT_DISPLAY_SCALE_PERCENT",
    "LIVE2D_MODEL_DISPLAY_SCALES_KEY",
    "MAX_DISPLAY_SCALE_PERCENT",
    "MIN_DISPLAY_SCALE_PERCENT",
    "clamp_display_scale_percent",
    "compute_bottom_center_offset_y",
    "export_display_scale_settings",
    "get_model_display_scale_percent",
    "resolve_uniform_scale",
    "scale_factor_from_percent",
    "set_model_display_scale_percent",
]
