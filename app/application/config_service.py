"""Web PUT /api/config 的业务写入入口：校验、归一化后写 ConfigStore 并 emit config_changed。

WEB_CONFIG_KEYS 白名单：仅允许这些键通过 Web API 修改，防止前端误改敏感配置（如加密相关）。
ConfigService 在主线程执行（经 bridge.invoke_on_main），不触达 Qt 对象。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config_defaults import DEFAULT_REPLY_QUEUE_MAX_ITEMS

if TYPE_CHECKING:
    from main import DanmuApp


MASKED_API_KEY = "********"

WEB_CONFIG_KEYS = (
    "temperature",
    "danmu_speed",
    "danmu_lines",
    "danmu_max_chars",
    "dedup_threshold",
    "danmu_recent_ttl_sec",
    "screen_index",
    "capture_screen_index",
    "layout_mode",
    "opacity",
    "font_size",
    "empty_accel",
    "eviction_mode",
    "danmu_pending_entry_cap",
    "danmu_track_retention_cap",
    "reply_queue_max_items",
    "image_max_width",
    "image_quality",
    "hotkey",
    "mic_mode_enabled",
    "mic_window_sec",
    "mic_input_device_id",
    "mic_use_visual_model",
    "mic_api_endpoint",
    "mic_api_mode",
    "mic_model",
    "normal_recognition_interval_sec",
    "normal_reply_count",
    "user_nickname",  # W-NICKNAME-001
    "live_topic",  # W-LIVE-TOPIC-001
    "persona_name_prefix_enabled",  # W-PERSONA-NAME-DISPLAY-001
    # W-FP-V2-001：弹幕渲染模式与侧边悬浮窗配置
    "danmu_render_mode",
    "floating_panel_width",
    "floating_panel_max_items",
    "floating_panel_danmu_per_second",
    "floating_panel_speed",
    "floating_panel_x_offset",
    "floating_panel_y_offset",
    "floating_panel_x",
    "floating_panel_y",
    "floating_panel_opacity",
    "floating_panel_font_size",
    "floating_panel_click_through",
    # W-FP-STYLE-CONTRACT-001：从下到上样式扁平字段（无单一 JSON 档）
    "floating_panel_style_preset",
    "floating_panel_custom_css_file",
    "floating_panel_shape",
    "floating_panel_layout",
    "floating_panel_card_colors",
    "floating_panel_card_color_mode",
    "floating_panel_card_color_weights",
    "floating_panel_text_colors",
    "floating_panel_text_color_mode",
    "floating_panel_text_color_weights",
    "floating_panel_card_opacity",
    "floating_panel_outline_enabled",
    "floating_panel_outline_color",
    "floating_panel_outline_width",
    "floating_panel_shadow_enabled",
    "floating_panel_shadow_color",
    "floating_panel_shadow_opacity",
    "floating_panel_shadow_blur",
    "floating_panel_shadow_offset_x",
    "floating_panel_shadow_offset_y",
    "floating_panel_border_enabled",
    "floating_panel_border_color",
    "floating_panel_border_width",
    "floating_panel_border_opacity",
    "floating_panel_padding_x",
    "floating_panel_padding_y",
    "floating_panel_radius",
    "floating_panel_tail_enabled",
    "floating_panel_tail_style",
    "floating_panel_tail_width",
    "floating_panel_tail_height",
    "floating_panel_tail_size",
    "floating_panel_tail_offset_y",
    "floating_panel_tail_border",
    "floating_panel_tail_long_side",
    "floating_panel_tail_rotate_deg",
    "floating_panel_username_enabled",
    "floating_panel_username_text",
    "floating_panel_username_color",
    "floating_panel_username_size",
    "floating_panel_username_weight",
    "floating_panel_username_separator",
    "floating_panel_content_size",
    "floating_panel_content_weight",
    "floating_panel_content_line_height",
    "floating_panel_gap_username_content",
    "floating_panel_entry_animation",
    "floating_panel_entry_duration_ms",
    "floating_panel_push_duration_ms",
    "floating_panel_exit_animation",
    "floating_panel_exit_duration_ms",
    "floating_panel_stack_gap",
    # W-FONT-001：字体设置
    "danmu_font_family",
    "danmu_font_bold",
    "floating_panel_font_family",
    "floating_panel_font_bold",
    "use_thinking",
    "danmu_font_color_selected",
    "danmu_font_color_mode",
    "danmu_font_color_weights",
)

# 弹幕设置「恢复默认」可恢复的键（= WEB_CONFIG_KEYS；不含 api_key / custom_models / region_*）
RESTORABLE_CONFIG_KEYS = WEB_CONFIG_KEYS

# W-THEME-LAG-SCENE-VERSION-001：变更时递增 _scene_generation 的配置键
SCENE_VERSION_CONFIG_KEYS = (
    "live_topic",
    "user_nickname",
    "capture_screen_index",
    "region_x",
    "region_y",
    "region_w",
    "region_h",
)

_SCENE_VERSION_INT_KEYS = frozenset(
    {"capture_screen_index", "region_x", "region_y", "region_w", "region_h"}
)


def scene_version_fingerprint(config) -> tuple[str, ...]:
    """Return a stable tuple fingerprint for scene-affecting config values."""
    parts: list[str] = []
    for key in SCENE_VERSION_CONFIG_KEYS:
        if key in _SCENE_VERSION_INT_KEYS:
            parts.append(str(config.get_int(key, 0)))
        else:
            parts.append(str(config.get(key, "") or "").strip())
    return tuple(parts)


def normalize_legacy_display_mode(items: dict[str, str]) -> None:
    """Map removed realtime display mode to normal on Web config patch."""
    mode = str(items.get("danmu_display_mode", "")).strip().lower()
    if mode == "realtime":
        items["danmu_display_mode"] = "normal"


def _clamp_choice(
    items: dict[str, str],
    key: str,
    allowed: tuple[str, ...],
    default: str,
) -> None:
    if key not in items:
        return
    value = str(items[key]).strip().lower()
    items[key] = value if value in allowed else default


def _clamp_int_key(
    items: dict[str, str],
    key: str,
    default: int,
    min_value: int,
    max_value: int,
) -> None:
    if key not in items:
        return
    try:
        value = int(items[key])
        items[key] = str(max(min_value, min(value, max_value)))
    except (TypeError, ValueError):
        items[key] = str(default)


def _normalize_reply_queue_capacity(items: dict[str, str]) -> None:
    """Keep reply backlog bounded; accept legacy zero as the new safe default."""
    key = "reply_queue_max_items"
    if key not in items:
        return
    try:
        value = int(items[key])
    except (TypeError, ValueError):
        value = DEFAULT_REPLY_QUEUE_MAX_ITEMS
    if value <= 0:
        value = DEFAULT_REPLY_QUEUE_MAX_ITEMS
    items[key] = str(min(value, 9999))


_SIMPLE_INT_RULES = (
    ("danmu_recent_ttl_sec", 30, 1, 600),
    ("opacity", 100, 0, 100),
    ("floating_panel_width", 360, 200, 800),
    ("floating_panel_max_items", 12, 1, 50),
    ("floating_panel_danmu_per_second", 1, 1, 5),
    ("floating_panel_lifetime_sec", 7, 2, 60),
    ("floating_panel_x_offset", 20, 0, 400),
    ("floating_panel_y_offset", 80, 0, 400),
    ("floating_panel_opacity", 85, 0, 100),
    ("font_size", 24, 12, 72),
    ("floating_panel_font_size", 20, 12, 48),
)
_SIMPLE_BOOL_KEYS = (
    "empty_accel", "persona_name_prefix_enabled", "danmu_font_bold",
    "floating_panel_font_bold", "floating_panel_click_through",
    "live2d_click_through", "use_thinking",
)


def _normalize_bool_key(items: dict[str, str], key: str, *, case_sensitive: bool = False) -> None:
    if key not in items:
        return
    value = str(items[key]).strip()
    if not case_sensitive:
        value = value.lower()
    items[key] = "1" if value in ("1", "true", "yes", "on") else "0"


def _clamp_float_key(
    items: dict[str, str], key: str, default: str, min_value: float, max_value: float,
) -> None:
    if key not in items:
        return
    try:
        value = max(min_value, min(float(items[key]), max_value))
        items[key] = f"{value:.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        items[key] = default


def _submitted_api_key(value: Any) -> str:
    key = str(value or "").strip()
    if not key or key == MASKED_API_KEY:
        return ""
    return key


def _custom_model_identity(model: dict[str, Any]) -> tuple[str, str]:
    return (
        str(model.get("default_model_id") or "").strip(),
        str(model.get("name") or "").strip(),
    )


class ConfigService:
    """DanmuApp.apply_web_config_payload 的委托实现；勿在 web_console 路由内直接 set_batch。"""

    def __init__(self, app: "DanmuApp"):
        self._app = app
        self._config = app.config

    def apply_web_payload(self, payload: dict[str, Any]) -> None:
        """仅接受 WEB_CONFIG_KEYS 子集 + api_key / custom_models / active_personae；经 ConfigStore 写缓存，不直连 SQLite 连接对象。"""
        from app.model_selection import validate_web_config_patch

        validate_web_config_patch(self._config, payload)

        items: dict[str, str] = {}
        for key in WEB_CONFIG_KEYS:
            if key in payload and payload[key] is not None:
                items[key] = str(payload[key])

        if items:
            self._normalize_items(items)

        # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 视觉 api_key 写入口已移除；仅 mic_api_key 走加密路径
        mic_api_key = _submitted_api_key(payload.get("mic_api_key", ""))

        custom_models: list[dict[str, Any]] | None = None
        if isinstance(payload.get("custom_models"), list):
            custom_models = self._merge_custom_models(payload["custom_models"])

        if items or mic_api_key or custom_models is not None:
            self._config.apply_web_save(
                items=items or None,
                api_key=None,
                mic_api_key=mic_api_key or None,
                custom_models=custom_models,
            )

        active = payload.get("active_personae")
        if isinstance(active, list) and active:
            self._app.personae.set_active([str(name) for name in active])

        self._app.config_changed.emit()

    def _normalize_items(self, items: dict[str, str]) -> None:
        # Cross-field mode resolution stays ahead of single-field rules.
        if "mic_api_endpoint" in items or "mic_api_mode" in items:
            from app.model_providers import normalize_api_mode_for_select

            endpoint = items.get("mic_api_endpoint", self._config.get("mic_api_endpoint", ""))
            api_mode = items.get("mic_api_mode", self._config.get("mic_api_mode", "doubao"))
            items["mic_api_mode"] = normalize_api_mode_for_select(api_mode, endpoint)

        # Preserve the legacy case-sensitive microphone switch contract.
        _normalize_bool_key(items, "mic_use_visual_model", case_sensitive=True)
        for key in _SIMPLE_BOOL_KEYS:
            _normalize_bool_key(items, key)
        for rule in _SIMPLE_INT_RULES:
            _clamp_int_key(items, *rule)

        if "mic_window_sec" in items:
            from app.mic_buffer import clamp_mic_window_sec

            try:
                items["mic_window_sec"] = str(clamp_mic_window_sec(int(items["mic_window_sec"])))
            except (TypeError, ValueError):
                items["mic_window_sec"] = "5"

        if "danmu_max_chars" in items:
            from app.danmu_engine import DANMU_MAX_CHARS_MAX, DANMU_MAX_CHARS_MIN

            try:
                value = int(items["danmu_max_chars"])
                items["danmu_max_chars"] = str(max(DANMU_MAX_CHARS_MIN, min(value, DANMU_MAX_CHARS_MAX)))
            except (TypeError, ValueError):
                items["danmu_max_chars"] = ""

        if "danmu_lines" in items:
            from app.danmu_engine import DEFAULT_DANMU_LINES, clamp_danmu_lines

            try:
                items["danmu_lines"] = str(clamp_danmu_lines(int(items["danmu_lines"])))
            except (TypeError, ValueError):
                items["danmu_lines"] = str(DEFAULT_DANMU_LINES)

        from app.config_defaults import (
            CONFIG_DEFAULTS,
            DANMU_SPEED_MAX,
            DANMU_SPEED_MIN,
            DEFAULT_FLOATING_PANEL_SPEED,
        )

        _clamp_float_key(items, "danmu_speed", CONFIG_DEFAULTS["danmu_speed"], DANMU_SPEED_MIN, DANMU_SPEED_MAX)
        _clamp_float_key(items, "dedup_threshold", "0.5", 0.0, 1.0)
        _clamp_float_key(items, "floating_panel_speed", DEFAULT_FLOATING_PANEL_SPEED, 0.5, 5.0)

        if any(key in items for key in (
            "danmu_pending_entry_cap", "danmu_track_retention_cap", "reply_queue_max_items",
        )):
            from app.danmu_engine import (
                DANMU_PENDING_ENTRY_CAP_MAX,
                DANMU_TRACK_RETENTION_CAP_MAX,
            )

            _clamp_int_key(items, "danmu_pending_entry_cap", 0, 0, DANMU_PENDING_ENTRY_CAP_MAX)
            _clamp_int_key(items, "danmu_track_retention_cap", 0, 0, DANMU_TRACK_RETENTION_CAP_MAX)
            _normalize_reply_queue_capacity(items)

        if "layout_mode" in items:
            from app.danmu_engine import normalize_layout_mode

            items["layout_mode"] = normalize_layout_mode(items["layout_mode"])

        if "normal_recognition_interval_sec" in items or "normal_reply_count" in items:
            from app.persona_contract import DEFAULT_NORMAL_REPLY_COUNT, NORMAL_REPLY_COUNT_MAX

            _clamp_int_key(items, "normal_recognition_interval_sec", 5, 1, 60)
            _clamp_int_key(items, "normal_reply_count", DEFAULT_NORMAL_REPLY_COUNT, 1, NORMAL_REPLY_COUNT_MAX)

        _clamp_choice(items, "danmu_render_mode", ("scrolling", "floating_panel"), "scrolling")
        # Absolute origins may be negative; blank values retain legacy offsets.
        for key in ("floating_panel_x", "floating_panel_y"):
            if key not in items:
                continue
            raw = str(items[key] or "").strip().lower()
            if not raw or raw in ("null", "none"):
                items[key] = ""
                continue
            try:
                position = int(raw)
            except (TypeError, ValueError):
                items[key] = ""
                continue
            items[key] = str(max(-32000, min(position, 32000)))

        for key in ("danmu_font_family", "floating_panel_font_family"):
            if key in items:
                value = str(items[key]).strip()
                items[key] = value if value else "Microsoft YaHei"

        # Preset expansion consumes normalized fields; secrets remain in apply_web_payload.
        from app.floating_panel_style import normalize_floating_panel_style_items

        normalize_floating_panel_style_items(items)
        if "floating_panel_custom_css_file" in items:
            from app.floating_panel_custom_css import normalize_custom_css_file_name

            items["floating_panel_custom_css_file"] = normalize_custom_css_file_name(items["floating_panel_custom_css_file"])

    def _merge_custom_models(self, payload_models: list[Any]) -> list[dict[str, Any]]:
        from app.config_store.crypto import (
            CustomModelApiKeyConflictError,
            canonicalize_custom_model_profile,
            read_custom_model_api_key,
        )
        from app.web_api.custom_models import MASKED_KEY

        existing = [model for model in self._config.get_custom_models() if isinstance(model, dict)]
        existing_by_identity = {
            _custom_model_identity(model): model
            for model in existing
            if any(_custom_model_identity(model))
        }
        merged: list[dict[str, Any]] = []
        for index, incoming in enumerate(payload_models):
            if not isinstance(incoming, dict):
                continue
            try:
                row = canonicalize_custom_model_profile(dict(incoming))
            except CustomModelApiKeyConflictError as exc:
                raise ValueError(str(exc)) from None
            key = read_custom_model_api_key(row)
            previous = existing_by_identity.get(_custom_model_identity(row))
            if previous is None and index < len(existing):
                previous = existing[index]
            if key == MASKED_KEY and previous:
                row["apiKey"] = read_custom_model_api_key(previous)
            elif key == MASKED_KEY:
                row["apiKey"] = ""
            merged.append(row)
        return merged


def apply_web_config_patch(app: "DanmuApp", payload: dict[str, Any]) -> None:
    ConfigService(app).apply_web_payload(payload)
