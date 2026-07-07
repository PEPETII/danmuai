"""Default config values for export and first-run seeding.

``CONFIG_DEFAULTS`` 分组说明（新增字段时请同步到对应组并核对 ``WEB_CONFIG_KEYS``）：

- 弹幕显示（``danmu_*`` + ``layout_mode`` + ``opacity`` + ``eviction_mode`` + ``empty_accel`` +
  ``danmu_pending_entry_cap`` + ``danmu_track_retention_cap`` + ``reply_queue_max_items``）
- 截图策略（``screen_index`` + ``region_*`` + ``image_max_width`` + ``image_quality`` + ``normal_recognition_interval_sec``）
- 麦克风（``mic_*``）
- 悬浮窗（``danmu_render_mode`` + ``floating_panel_*``；W-FP-V2-001/002） — 枚举 ``danmu_render_mode``：
  - ``scrolling``（默认）：横向 DanmuOverlay
  - ``floating_panel``：侧边悬浮窗 V2
  - 遗留 ``display_mode`` 在 ConfigStore 启动时由 ``migrate_legacy_display_mode_to_render_mode`` 写回 ``danmu_render_mode``
- 字体（``danmu_font_*`` + ``floating_panel_font_*`` + ``imported_fonts``；W-FONT-001/002/003）
- API（``api_mode`` + ``api_endpoint`` + ``api_key`` + ``model`` + ``temperature`` + ``max_tokens``）
- TTS / 读弹幕（``tts_*`` + ``danmu_read_*``）
- 公告 / 主题 / 更新 / 用户（``user_nickname`` / ``live_topic`` + ``console_theme`` + ``app_update_state``）

新增字段时务必：① 同步 ``app.application.config_service.WEB_CONFIG_KEYS``；② 同步
``main.py`` / ``danmu_engine.py`` / ``ai_client.py`` 等 runtime fallback。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.personae import DEFAULT_NORMAL_REPLY_COUNT

if TYPE_CHECKING:
    from app.config_store import ConfigStore

# Numeric fallbacks when a key is missing from the store (keep in sync with CONFIG_DEFAULTS).
DEFAULT_DANMU_SPEED = 2.0
DANMU_SPEED_MIN = 0.5
DANMU_SPEED_MAX = 10.0
DEFAULT_FONT_SIZE = 24
DEFAULT_DANMU_FONT_FAMILY = "Microsoft YaHei"
DEFAULT_DEDUP_THRESHOLD = 0.5
DEFAULT_DANMU_RECENT_TTL_SEC = 30
DEFAULT_IMAGE_MAX_WIDTH = 1024
LEGACY_IMAGE_MAX_WIDTH = 768
LEGACY_DANMU_MAX_CHARS_FACTORY = "15"
DEFAULT_LANGUAGE = "zh"
# 横屏 scrolling 与从下到上 floating_panel 的节奏默认值（仅键缺失时按 render mode 回落）
SCROLLING_NORMAL_RECOGNITION_INTERVAL_SEC = 5
FLOATING_PANEL_NORMAL_RECOGNITION_INTERVAL_SEC = 5
FLOATING_PANEL_NORMAL_REPLY_COUNT = 10
DEFAULT_FLOATING_PANEL_SPEED = "1"
# 弹幕容量保护默认（0=用户显式无限制；键缺失时回落到下列值）
DEFAULT_DANMU_PENDING_ENTRY_CAP = 300
DEFAULT_DANMU_TRACK_RETENTION_CAP = 600

# String values aligned with runtime fallbacks in main.py / danmu_engine / ai_client.
CONFIG_DEFAULTS: dict[str, str] = {
    "api_mode": "openai",
    "temperature": "0.8",
    "max_tokens": "512",
    "danmu_speed": "2",
    "danmu_lines": "20",
    "danmu_max_chars": "",
    "dedup_threshold": "0.5",
    "danmu_recent_ttl_sec": str(DEFAULT_DANMU_RECENT_TTL_SEC),
    "screen_index": "0",
    "layout_mode": "fullscreen",
    "opacity": "100",
    "font_size": "24",
    "danmu_font_family": "Microsoft YaHei",
    "danmu_font_bold": "1",
    "floating_panel_font_family": "Microsoft YaHei",
    "floating_panel_font_bold": "1",
    "danmu_pool_use_custom": "0",
    "min_on_screen": "5",
    "meme_barrage_enabled": "0",
    "meme_barrage_category": "random",
    "meme_barrage_tag": "06",
    "meme_barrage_display_mode": "full",
    "meme_barrage_collect_interval_sec": "5",
    "meme_barrage_collect_batch_size": "2",
    "meme_barrage_display_interval_sec": "5",
    "meme_barrage_display_batch_size": "2",
    "meme_barrage_local_read_offset": "0",
    "meme_barrage_remote_page_num": "1",
    "empty_accel": "1",
    "eviction_mode": "natural",
    "danmu_pending_entry_cap": str(DEFAULT_DANMU_PENDING_ENTRY_CAP),
    "danmu_track_retention_cap": str(DEFAULT_DANMU_TRACK_RETENTION_CAP),
    "reply_queue_max_items": "0",
    "image_max_width": "1024",
    "image_quality": "85",
    "hotkey": "Ctrl+Shift+B",
    "language": DEFAULT_LANGUAGE,
    "mic_mode_enabled": "0",
    "mic_window_sec": "5",
    "mic_input_device_id": "",
    "mic_use_visual_model": "1",
    "mic_api_mode": "doubao",
    "mic_model": "doubao-seed-2-0-mini-260428",
    "normal_recognition_interval_sec": "5",
    "normal_reply_count": str(DEFAULT_NORMAL_REPLY_COUNT),
    "danmu_read_enabled": "0",
    "danmu_read_interval_sec": "10",
    "user_nickname": "",  # W-NICKNAME-001
    "live_topic": "",  # W-LIVE-TOPIC-001
    "persona_name_prefix_enabled": "0",  # W-PERSONA-NAME-DISPLAY-001
    "tts_voice": "冰糖",
    "tts_style_prompt": (
        "温柔微颤语气，1.0倍速，温暖音色，独白式表达，"
        "句尾轻收配合自然呼吸停顿，情绪克制有层次，适配泪目治愈类弹幕"
    ),
    "tts_provider": "",
    "tts_endpoint": "",
    "tts_model_id": "",
    "console_theme": "dark",
    # W-FP-V2-001：弹幕渲染模式（互斥）
    "danmu_render_mode": "scrolling",
    # W-BILILIVE-DM-PLUGIN-MODE-005：弹幕姬模式（关闭屏幕层，仅 bililive_dm 显示）
    "bililive_dm_mode_enabled": "0",
    "floating_panel_width": "360",
    "floating_panel_max_items": "12",
    "floating_panel_x_offset": "20",
    "floating_panel_y_offset": "80",
    "floating_panel_opacity": "85",
    "floating_panel_font_size": "20",
    "floating_panel_speed": DEFAULT_FLOATING_PANEL_SPEED,
    "imported_fonts": "[]",  # W-FONT-002：[{sha256, family, original_name, size, imported_at}, ...]
    # PET-003：桌宠显示与指令注入（无独立模型配置）
    "pet_enabled": "0",
    "pet_visible": "0",
    "pet_asset_source": "builtin",
    "pet_asset_path": "",
    "pet_scale": "0.5",
    "pet_opacity": "1.0",
    "pet_always_on_top": "1",
    "pet_click_through": "0",
    "pet_position_x": "",
    "pet_position_y": "",
    "pet_command_box_enabled": "1",
    "pet_command_ttl_sec": "30",
    "pet_command_apply_count": "1",
    "pet_barrage_mode_enabled": "0",
    "pet_barrage_count": "5",
    "pet_barrage_slots": "[]",
    "pet_barrage_slot_positions": "[]",
    "pet_barrage_previous_render_mode": "scrolling",
    "pet_barrage_previous_reply_count": str(DEFAULT_NORMAL_REPLY_COUNT),
    "use_thinking": "0",
    "danmu_font_color_selected": "[\"#FFFFFF\"]",
    "danmu_font_color_mode": "equal",
    "danmu_font_color_weights": "{}",
}

# 首装视觉 API 默认服务商（与 model_providers.DEFAULT_PROVIDER_ID 一致）
_DEFAULT_PROVIDER_ID = "custom_openai"
# 麦克风「恢复默认」仍使用火山方舟预设地址
_DEFAULT_MIC_PROVIDER_ID = "doubao"


def _default_api_endpoint(provider_id: str = _DEFAULT_PROVIDER_ID) -> str:
    from app.model_providers import get_provider

    spec = get_provider(provider_id)
    return spec.default_endpoint if spec else ""


def _default_mic_api_endpoint() -> str:
    return _default_api_endpoint(_DEFAULT_MIC_PROVIDER_ID)


def _default_model_id() -> str:
    from app.model_catalog import default_catalog_model_id

    return default_catalog_model_id(_DEFAULT_PROVIDER_ID)


def export_web_config_defaults() -> dict[str, str]:
    """Web「恢复默认」唯一来源：覆盖 WEB_CONFIG_KEYS，不含 api_key / 自定义模型 / 人格 / 识图区域。

    修改默认值时须同步 CONFIG_DEFAULTS 与 main.py / danmu_engine 等 runtime fallback。
    """
    from app.application.config_service import WEB_CONFIG_KEYS

    defaults = {key: CONFIG_DEFAULTS.get(key, "") for key in WEB_CONFIG_KEYS}
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: api_endpoint 已从 WEB_CONFIG_KEYS 移除，不再注入默认值
    default_model = _default_model_id()
    defaults["model"] = default_model
    defaults["mic_api_endpoint"] = _default_mic_api_endpoint()
    return defaults


def default_normal_reply_count_for_mode(mode: str) -> int:
    if mode == "floating_panel":
        return FLOATING_PANEL_NORMAL_REPLY_COUNT
    return DEFAULT_NORMAL_REPLY_COUNT


def default_normal_recognition_interval_sec_for_mode(mode: str) -> int:
    if mode == "floating_panel":
        return FLOATING_PANEL_NORMAL_RECOGNITION_INTERVAL_SEC
    return SCROLLING_NORMAL_RECOGNITION_INTERVAL_SEC


def default_config_value_for_mode(key: str, mode: str) -> str:
    """Mode-aware documented default (does not read the store)."""
    if key == "normal_reply_count":
        return str(default_normal_reply_count_for_mode(mode))
    if key == "normal_recognition_interval_sec":
        return str(default_normal_recognition_interval_sec_for_mode(mode))
    if key == "floating_panel_speed":
        return DEFAULT_FLOATING_PANEL_SPEED
    return CONFIG_DEFAULTS.get(key, "")


def config_value_with_default(config, key: str) -> str:
    """Return stored value or documented default (for API export / UI)."""
    val = config.get(key, "")
    if val != "":
        return val
    if key in ("normal_reply_count", "normal_recognition_interval_sec", "floating_panel_speed"):
        mode = resolve_danmu_render_mode(config)
        return default_config_value_for_mode(key, mode)
    return CONFIG_DEFAULTS.get(key, "")


def migrate_legacy_image_max_width(config) -> bool:
    """Upgrade stored default 768 → current DEFAULT_IMAGE_MAX_WIDTH (1024).

    Only rewrites the previous factory default; user-customized widths are left unchanged.
    Returns True if image_max_width was written.
    """
    raw = str(config.get("image_max_width", "") or "").strip()
    if raw != str(LEGACY_IMAGE_MAX_WIDTH):
        return False
    config.set("image_max_width", str(DEFAULT_IMAGE_MAX_WIDTH))
    return True


def migrate_legacy_danmu_max_chars_factory(config) -> bool:
    """Clear historic language-blind factory default 15 so lang fallback applies.

    Only rewrites the previous factory default; other values are left unchanged.
    Returns True if danmu_max_chars was cleared.
    """
    raw = str(config.get("danmu_max_chars", "") or "").strip()
    if raw != LEGACY_DANMU_MAX_CHARS_FACTORY:
        return False
    config.set("danmu_max_chars", "")
    return True


def migrate_legacy_display_mode_to_render_mode(config) -> bool:
    """Write legacy display_mode → danmu_render_mode when render mode is empty or invalid.

    display_mode=floating_panel → floating_panel; overlay/both/other/empty → scrolling.
    Returns True if danmu_render_mode was written.
    """
    raw = str(config.get("danmu_render_mode", "") or "").strip().lower()
    if raw in ("scrolling", "floating_panel"):
        return False
    legacy = str(config.get("display_mode", "") or "").strip().lower()
    mapped = "floating_panel" if legacy == "floating_panel" else "scrolling"
    config.set("danmu_render_mode", mapped)
    return True


def resolve_danmu_render_mode(config) -> str:
    """Effective render mode from danmu_render_mode only; invalid/missing → scrolling."""
    raw = str(config.get("danmu_render_mode", "") or "").strip().lower()
    if raw in ("scrolling", "floating_panel"):
        return raw
    return "scrolling"


def seed_config_defaults(config: "ConfigStore") -> None:
    """Persist defaults for keys that are missing or blank."""
    items = {
        key: default
        for key, default in CONFIG_DEFAULTS.items()
        if not config.get(key, "")
    }
    if items:
        config.set_batch(items)
