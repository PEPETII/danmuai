"""守卫测试：DanmuApp 新增主链路 _xxx 方法时，make_minimal_danmu_app 必须补 __get__ 绑定。

W-TEST-BINDING-GUARD-001：防止单测静默 AttributeError（conftest.py 模式已文档化，
本测试是一道防线，不改 conftest.py 行为）。

新增主链路方法（如 _on_xxx / _consume_xxx / _schedule_xxx 等被主链路单测调用的方法）
应在 ``tests/conftest.py:make_minimal_danmu_app`` 补 ``__get__`` 绑定；
新增 UI / 生命周期 / 启动编排方法（单测不需要的）应加入本文件 ``KNOWN_OPTIONAL`` 白名单。
"""
import inspect

from main import DanmuApp
from tests.conftest import make_minimal_danmu_app


# 显式白名单：DanmuApp 上存在但 make_minimal_danmu_app 刻意不绑定的方法。
# 这些方法属于 UI / 显示同步 / 生命周期编排 / 烂梗 / 麦 / TTS / Web façade，
# 已在各自专属测试覆盖，主链路单测不需要。
KNOWN_OPTIONAL: frozenset[str] = frozenset({
    # 生命周期 / 启动编排（_init_* / start / stop / quit 等）
    "_init_runtime_bridge_state", "_init_core_subsystems", "_ensure_pet_components",
    "_init_request_pipeline_state", "_init_runtime_tracking_state",
    "_reset_scene_generation_baseline", "_maybe_bump_scene_generation_on_config",
    "_on_scene_generation_bumped", "_init_startup_services", "_start_web_console_stack",
    # UI / 显示同步（_sync_* / _on_config_changed / _on_app_focus_changed 等）
    "_sync_overlay_visibility", "_sync_floating_panel_visibility",
    "_floating_panel_v2_enabled", "_overlay_display_enabled",
    "_on_config_changed", "_on_app_focus_changed", "_on_state_changed",
    "_display_danmu_text", "_danmu_render_mode", "_sync_pet_window_visibility",
    "_publish_live_status", "_on_topmost_health_tick",
    # 烂梗 / 麦 / TTS（已在各自 mixin 专属测试覆盖）
    "_init_meme_barrage_timers", "_stop_meme_barrage_timers",
    "_ensure_meme_barrage_service", "_ensure_meme_barrage_client",
    "close_meme_barrage_client", "_on_meme_fetch_success", "_on_meme_fetch_error",
    "_on_meme_ai_select_done_signal", "_on_meme_ai_select_failed",
    "_maybe_meme_display_tick", "_on_mic_utterance_end", "_poll_mic_utterance",
    # Web façade / 桥接（已在 web_bridge / web_api 测试覆盖）
    "build_status_snapshot", "build_diagnostic_snapshot",
    "apply_config_patch", "request_capture_region_selection", "reset_capture_region",
    # 公开 façade（非 _ 前缀但需显式排除）
    "start", "stop", "quit", "toggle",
})


def test_make_minimal_danmu_app_binds_all_main_pipeline_methods():
    """DanmuApp 上所有 _xxx（非 dunder）方法应在 make_minimal_danmu_app 中绑定。"""
    app = make_minimal_danmu_app()

    declared = {
        name for name, member in inspect.getmembers(DanmuApp, predicate=inspect.isfunction)
        if name.startswith("_") and not name.startswith("__")
    }
    bound = {
        name for name in declared
        if callable(getattr(app, name, None))
    }
    missing = declared - bound - KNOWN_OPTIONAL
    assert missing == set(), (
        f"make_minimal_danmu_app 未绑定以下 DanmuApp 方法（请在 tests/conftest.py "
        f"make_minimal_danmu_app 补 __get__ 绑定，或加入 KNOWN_OPTIONAL 白名单）: "
        f"{sorted(missing)}"
    )
