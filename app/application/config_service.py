"""Web PUT /api/config 的业务写入入口：校验、归一化后写 ConfigStore 并 emit config_changed。

WEB_CONFIG_KEYS 白名单：仅允许这些键通过 Web API 修改，防止前端误改敏感配置（如加密相关）。
ConfigService 在主线程执行（经 bridge.invoke_on_main），不触达 Qt 对象。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from main import DanmuApp


MASKED_API_KEY = "********"

WEB_CONFIG_KEYS = (
    "model",
    "temperature",
    "max_tokens",
    "danmu_speed",
    "danmu_lines",
    "danmu_max_chars",
    "dedup_threshold",
    "danmu_recent_ttl_sec",
    "screen_index",
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
    # W-BILILIVE-DM-PLUGIN-MODE-005：弹幕姬模式
    "bililive_dm_mode_enabled",
    "floating_panel_width",
    "floating_panel_max_items",
    "floating_panel_speed",
    "floating_panel_x_offset",
    "floating_panel_y_offset",
    "floating_panel_opacity",
    "floating_panel_font_size",
    # W-FONT-001：字体设置
    "danmu_font_family",
    "danmu_font_bold",
    "floating_panel_font_family",
    "floating_panel_font_bold",
    # PET-003：桌宠
    "pet_enabled",
    "pet_visible",
    "pet_asset_source",
    "pet_asset_path",
    "pet_scale",
    "pet_opacity",
    "pet_always_on_top",
    "pet_click_through",
    "pet_position_x",
    "pet_position_y",
    "pet_command_box_enabled",
    "pet_command_ttl_sec",
    "pet_command_apply_count",
    "pet_barrage_mode_enabled",
    "pet_barrage_count",
    "pet_barrage_slots",
    "pet_barrage_slot_positions",
    "pet_barrage_previous_render_mode",
    "pet_barrage_previous_reply_count",
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
    "screen_index",
    "region_x",
    "region_y",
    "region_w",
    "region_h",
)

_SCENE_VERSION_INT_KEYS = frozenset(
    {"screen_index", "region_x", "region_y", "region_w", "region_h"}
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


def _submitted_api_key(value: Any) -> str:
    key = str(value or "").strip()
    if not key or key == MASKED_API_KEY:
        return ""
    return key


def _custom_model_identity(model: dict[str, Any]) -> tuple[str, str]:
    # W-CUSTOMMODEL-SCHEMA-002：优先按 default_model_id 去重，保留 modelId 兜底
    return (
        str(
            model.get("default_model_id")
            or model.get("modelId")
            or model.get("model")
            or ""
        ).strip(),
        str(model.get("name") or "").strip(),
    )


def set_default_model_selection(
    config,
    model_id: str,
    *,
    sync_legacy_model: bool = True,
) -> str:
    """同时维护 default_model_id 与 legacy model 键，避免 Web/自定义模型路径双写不一致。"""
    normalized = str(model_id or "").strip()
    if not normalized:
        return ""
    config.set_default_model_id(normalized)
    if sync_legacy_model:
        config.set("model", normalized)
    return normalized


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

        if "default_model_id" in payload:
            model_id = str(payload.get("default_model_id", "")).strip()
            if model_id:
                items["default_model_id"] = model_id
                items["model"] = model_id
        else:
            model_id = (items.get("model") or "").strip()
            if model_id:
                items["default_model_id"] = model_id

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
        if "mic_api_endpoint" in items or "mic_api_mode" in items:
            from app.model_providers import normalize_api_mode_for_select

            endpoint = items.get("mic_api_endpoint", self._config.get("mic_api_endpoint", ""))
            api_mode = items.get("mic_api_mode", self._config.get("mic_api_mode", "doubao"))
            items["mic_api_mode"] = normalize_api_mode_for_select(api_mode, endpoint)

        if "mic_use_visual_model" in items:
            value = str(items["mic_use_visual_model"]).strip()
            items["mic_use_visual_model"] = "1" if value in ("1", "true", "yes", "on") else "0"

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

        # W-CONFIG-UI-LINK-001 / W-RENDER-TOPMOST-BATCH-001：danmu_speed 钳位 0.5–10.0
        if "danmu_speed" in items:
            try:
                from app.config_defaults import (
                    DANMU_SPEED_MAX,
                    DANMU_SPEED_MIN,
                )

                speed = max(DANMU_SPEED_MIN, min(float(items["danmu_speed"]), DANMU_SPEED_MAX))
                items["danmu_speed"] = f"{speed:.3f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                from app.config_defaults import CONFIG_DEFAULTS

                items["danmu_speed"] = CONFIG_DEFAULTS["danmu_speed"]
        if "dedup_threshold" in items:
            try:
                threshold = max(0.0, min(float(items["dedup_threshold"]), 1.0))
                items["dedup_threshold"] = f"{threshold:.3f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                items["dedup_threshold"] = "0.5"
        if "danmu_recent_ttl_sec" in items:
            _clamp_int_key(items, "danmu_recent_ttl_sec", 30, 1, 600)
        if "empty_accel" in items:
            _v = str(items["empty_accel"]).strip().lower()
            items["empty_accel"] = "1" if _v in ("1", "true", "yes", "on") else "0"

        if "persona_name_prefix_enabled" in items:
            _v = str(items["persona_name_prefix_enabled"]).strip().lower()
            items["persona_name_prefix_enabled"] = "1" if _v in ("1", "true", "yes", "on") else "0"

        if (
            "danmu_pending_entry_cap" in items
            or "danmu_track_retention_cap" in items
            or "reply_queue_max_items" in items
        ):
            from app.danmu_engine import (
                DANMU_PENDING_ENTRY_CAP_MAX,
                DANMU_TRACK_RETENTION_CAP_MAX,
            )

            _clamp_int_key(items, "danmu_pending_entry_cap", 0, 0, DANMU_PENDING_ENTRY_CAP_MAX)
            _clamp_int_key(items, "danmu_track_retention_cap", 0, 0, DANMU_TRACK_RETENTION_CAP_MAX)
            _clamp_int_key(items, "reply_queue_max_items", 0, 0, 9999)

        if "layout_mode" in items:
            from app.danmu_engine import normalize_layout_mode

            items["layout_mode"] = normalize_layout_mode(items["layout_mode"])

        _clamp_int_key(items, "opacity", 100, 0, 100)

        if "normal_recognition_interval_sec" in items or "normal_reply_count" in items:
            from app.personae import DEFAULT_NORMAL_REPLY_COUNT, NORMAL_REPLY_COUNT_MAX

            _clamp_int_key(items, "normal_recognition_interval_sec", 5, 1, 60)
            _clamp_int_key(
                items,
                "normal_reply_count",
                DEFAULT_NORMAL_REPLY_COUNT,
                1,
                NORMAL_REPLY_COUNT_MAX,
            )

        # W-FP-V2-001：danmu_render_mode 与侧边悬浮窗配置归一化
        if "danmu_render_mode" in items:
            _clamp_choice(
                items,
                "danmu_render_mode",
                ("scrolling", "floating_panel"),
                "scrolling",
            )
        _clamp_int_key(items, "floating_panel_width", 360, 200, 800)
        _clamp_int_key(items, "floating_panel_max_items", 12, 1, 50)
        _clamp_int_key(items, "floating_panel_lifetime_sec", 7, 2, 60)
        if "floating_panel_speed" in items:
            try:
                speed = max(0.5, min(float(items["floating_panel_speed"]), 5.0))
                items["floating_panel_speed"] = f"{speed:.3f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                from app.config_defaults import DEFAULT_FLOATING_PANEL_SPEED

                items["floating_panel_speed"] = DEFAULT_FLOATING_PANEL_SPEED
        _clamp_int_key(items, "floating_panel_x_offset", 20, 0, 400)
        _clamp_int_key(items, "floating_panel_y_offset", 80, 0, 400)
        _clamp_int_key(items, "floating_panel_opacity", 85, 0, 100)
        _clamp_int_key(items, "floating_panel_font_size", 20, 12, 48)

        # W-FONT-001：字体名 / 加粗 / 字号归一化
        if "font_size" in items:
            _clamp_int_key(items, "font_size", 24, 12, 72)
        if "floating_panel_font_size" in items:
            _clamp_int_key(items, "floating_panel_font_size", 20, 12, 48)
        for _key in ("danmu_font_bold", "floating_panel_font_bold"):
            if _key in items:
                _v = str(items[_key]).strip().lower()
                items[_key] = "1" if _v in ("1", "true", "yes", "on") else "0"
        for _key in ("danmu_font_family", "floating_panel_font_family"):
            if _key in items:
                _v = str(items[_key]).strip()
                items[_key] = _v if _v else "Microsoft YaHei"

        # PET-003：桌宠配置归一化
        if "pet_asset_source" in items:
            _clamp_choice(items, "pet_asset_source", ("builtin", "local"), "builtin")
        for _key in (
            "pet_enabled",
            "pet_visible",
            "pet_always_on_top",
            "pet_click_through",
            "pet_command_box_enabled",
            "pet_barrage_mode_enabled",
            "bililive_dm_mode_enabled",
        ):
            if _key in items:
                _v = str(items[_key]).strip().lower()
                items[_key] = "1" if _v in ("1", "true", "yes", "on") else "0"
        if "pet_scale" in items:
            try:
                scale = float(items["pet_scale"])
                items["pet_scale"] = str(max(0.5, min(scale, 2.0)))
            except (TypeError, ValueError):
                items["pet_scale"] = "0.5"
        if "pet_opacity" in items:
            try:
                opacity = float(items["pet_opacity"])
                items["pet_opacity"] = str(max(0.2, min(opacity, 1.0)))
            except (TypeError, ValueError):
                items["pet_opacity"] = "1.0"
        _clamp_int_key(items, "pet_command_ttl_sec", 30, 5, 300)
        _clamp_int_key(items, "pet_command_apply_count", 1, 1, 5)
        _clamp_int_key(items, "pet_barrage_count", 5, 5, 5)
        if "pet_barrage_previous_render_mode" in items:
            _clamp_choice(
                items,
                "pet_barrage_previous_render_mode",
                ("scrolling", "floating_panel"),
                "scrolling",
            )
        if "pet_barrage_previous_reply_count" in items:
            from app.personae import DEFAULT_NORMAL_REPLY_COUNT, NORMAL_REPLY_COUNT_MAX

            _clamp_int_key(
                items,
                "pet_barrage_previous_reply_count",
                DEFAULT_NORMAL_REPLY_COUNT,
                1,
                NORMAL_REPLY_COUNT_MAX,
            )
        for _key in ("pet_position_x", "pet_position_y"):
            if _key not in items:
                continue
            raw = str(items[_key] or "").strip().lower()
            if not raw or raw in ("null", "none"):
                items[_key] = ""
                continue
            try:
                pos = int(raw)
            except (TypeError, ValueError):
                items[_key] = ""
                continue
            items[_key] = str(max(-32000, min(pos, 32000)))
        for _key in ("pet_barrage_slots", "pet_barrage_slot_positions"):
            if _key not in items:
                continue
            raw = str(items[_key] or "").strip()
            if not raw:
                items[_key] = "[]"
                continue
            items[_key] = raw
        if "use_thinking" in items:
            _v = str(items["use_thinking"]).strip().lower()
            items["use_thinking"] = "1" if _v in ("1", "true", "yes", "on") else "0"

    def _merge_custom_models(self, payload_models: list[Any]) -> list[dict[str, Any]]:
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
            row = dict(incoming)
            key = (row.get("apiKey") or row.get("api_key") or "").strip()
            previous = existing_by_identity.get(_custom_model_identity(row))
            if previous is None and index < len(existing):
                previous = existing[index]
            if key == MASKED_KEY and previous:
                row["apiKey"] = previous.get("apiKey", "")
            elif key == MASKED_KEY:
                row["apiKey"] = ""
            merged.append(row)
        return merged


def apply_web_config_patch(app: "DanmuApp", payload: dict[str, Any]) -> None:
    ConfigService(app).apply_web_payload(payload)
