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
- API（``api_mode`` + ``api_endpoint`` + ``api_key`` + ``model`` + ``temperature`` + ``max_tokens`` + ``use_thinking``）
- 记忆（``scene_memory_enabled`` + ``scene_memory_interval_sec`` + ``prompt_dedup_enabled``） — **默认关闭**；首装 / 恢复默认时 `scene_memory_enabled=0` / `prompt_dedup_enabled=0`（W-SCENE-MEMORY-DEFAULTS-OFF-001），`scene_memory_interval_sec=5` 与 `normal_recognition_interval_sec=5` 对齐
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
DEFAULT_IMAGE_MAX_WIDTH = 768
DEFAULT_LANGUAGE = "zh"
# 横屏 scrolling 与从下到上 floating_panel 的节奏默认值（仅键缺失时按 render mode 回落）
SCROLLING_NORMAL_RECOGNITION_INTERVAL_SEC = 5
FLOATING_PANEL_NORMAL_RECOGNITION_INTERVAL_SEC = 5
FLOATING_PANEL_NORMAL_REPLY_COUNT = 10
DEFAULT_FLOATING_PANEL_SPEED = "1"

# String values aligned with runtime fallbacks in main.py / danmu_engine / ai_client.
CONFIG_DEFAULTS: dict[str, str] = {
    "api_mode": "openai",
    "temperature": "0.8",
    "max_tokens": "512",
    "use_thinking": "0",
    "danmu_speed": "2",
    "danmu_lines": "20",
    "danmu_max_chars": "15",
    "dedup_threshold": "0.5",
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
    "danmu_pending_entry_cap": "0",
    "danmu_track_retention_cap": "0",
    "reply_queue_max_items": "0",
    "image_max_width": "768",
    "image_quality": "85",
    "hotkey": "Ctrl+Shift+B",
    "language": DEFAULT_LANGUAGE,
    "scene_memory_enabled": "0",  # W-SCENE-MEMORY-DEFAULTS-OFF-001
    "prompt_dedup_enabled": "0",  # W-SCENE-MEMORY-DEFAULTS-OFF-001
    "scene_memory_interval_sec": "5",
    "mic_mode_enabled": "0",
    "mic_window_sec": "5",
    "mic_use_visual_model": "1",
    "mic_api_mode": "doubao",
    "mic_model": "doubao-seed-2-0-mini-260428",
    "normal_recognition_interval_sec": "5",
    "normal_reply_count": str(DEFAULT_NORMAL_REPLY_COUNT),
    "danmu_read_enabled": "0",
    "danmu_read_interval_sec": "10",
    "user_nickname": "",  # W-NICKNAME-001
    "live_topic": "",  # W-LIVE-TOPIC-001
    "tts_voice": "冰糖",
    "tts_style_prompt": (
        "温柔微颤语气，1.0倍速，温暖音色，独白式表达，"
        "句尾轻收配合自然呼吸停顿，情绪克制有层次，适配泪目治愈类弹幕"
    ),
    "tts_provider": "",
    "tts_endpoint": "",
    "tts_model_id": "",
    "console_theme": "light",
    # W-FP-V2-001：弹幕渲染模式（互斥）
    "danmu_render_mode": "scrolling",
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
    defaults["api_endpoint"] = _default_api_endpoint()
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


def _legacy_memory_flags(mode: str) -> tuple[str, str]:
    """Map legacy memory_mode to (scene_memory_enabled, prompt_dedup_enabled)."""
    normalized = str(mode or "off").strip().lower()
    if normalized == "dedup_only":
        return "0", "1"
    if normalized in ("scene_card", "strong"):
        return "1", "1"
    return "0", "0"


def migrate_legacy_memory_mode(config: "ConfigStore") -> bool:
    """Map legacy memory_mode to scene_memory_enabled / prompt_dedup_enabled."""
    if "scene_memory_enabled" in config._cache:
        return False
    legacy_mode = str(config._cache.get("memory_mode", "off") or "off")
    scene, dedup = _legacy_memory_flags(legacy_mode)
    config.set_batch(
        {
            "scene_memory_enabled": scene,
            "prompt_dedup_enabled": dedup,
        }
    )
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
