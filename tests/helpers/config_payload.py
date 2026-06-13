"""Web config payload builders for round-trip / full-form tests (W-TEST-COVER-001)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.application.config_service import WEB_CONFIG_KEYS
from app.config_defaults import export_web_config_defaults


def full_web_config_payload(**overrides: str) -> dict[str, str]:
    """Baseline = export_web_config_defaults(); merge overrides for boundary cases."""
    from app.model_providers import get_provider

    payload = export_web_config_defaults()
    # export defaults leave api_endpoint/model empty until user configures; full form needs valid ids.
    doubao = get_provider("doubao")
    if not str(payload.get("api_endpoint", "")).strip():
        payload["api_endpoint"] = doubao.default_endpoint
        payload["api_mode"] = "doubao"
    if not str(payload.get("model", "")).strip():
        payload["model"] = "doubao-seed-1-6-flash-250828"
    if not str(payload.get("mic_api_endpoint", "")).strip():
        payload["mic_api_endpoint"] = doubao.default_endpoint
    payload.update(overrides)
    if not str(payload.get("model", "")).strip():
        payload["model"] = "doubao-seed-1-6-flash-250828"
    if not str(payload.get("api_endpoint", "")).strip():
        payload["api_endpoint"] = doubao.default_endpoint
        payload["api_mode"] = "doubao"
    return payload


def boundary_web_config_overrides() -> dict[str, str]:
    """Values that exercise _normalize_items clamp / fallback branches."""
    return {
        "danmu_speed": "0",
        "font_size": "9999",
        "danmu_render_mode": "invalid",
        "danmu_max_chars": "999",
        "dedup_threshold": "2.0",
        "opacity": "150",
        "floating_panel_speed": "99",
        "floating_panel_max_items": "9999",
        "pet_scale": "9",
        "pet_opacity": "0.01",
        "mic_window_sec": "999",
        "normal_recognition_interval_sec": "0",
        "normal_reply_count": "0",
        "reply_queue_max_items": "-1",
        "danmu_lines": "0",
        "layout_mode": "bogus",
        "empty_accel": "yes",
        "mic_use_visual_model": "on",
        "danmu_font_bold": "true",
        "pet_enabled": "yes",
    }


def make_config_app_stub(store) -> SimpleNamespace:
    """Minimal DanmuApp stand-in for apply_web_config_patch (no Qt init)."""

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    return SimpleNamespace(
        config=store,
        personae=_PersonaeStub(),
        config_changed=MagicMock(),
    )


def expected_normalized_web_config(store, payload: dict[str, str]) -> dict[str, str]:
    """Run the same normalization path as ConfigService.apply_web_payload."""
    from app.application.config_service import ConfigService

    app = make_config_app_stub(store)
    service = ConfigService(app)
    items = {key: str(payload[key]) for key in WEB_CONFIG_KEYS if key in payload}
    service._normalize_items(items)
    return items
