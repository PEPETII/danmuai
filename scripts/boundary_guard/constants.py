"""rules 共享的常量与正则表。

本文件**不**做规则判定，只维护规则所需的"路径/正则/白名单"。每个规则模块
按职责域分组（web / runtime / request / config / pipeline / diagnostics /
status / baseline），常量与 [AGENTS.md](../../AGENTS.md) §9 + 三登记表
（`docs/runtime-state-map.md`、`docs/main-pipeline-sequence.md`、
`docs/final-architecture-baseline.md`）中的 Phase 4-A/B/C/D、Phase 4-F 等对应。
新增规则时务必先在本文件登记匹配模式 / 白名单，勿在 rules/*.py 中硬编码字符串。

维护者：见 [AGENTS.md](../../AGENTS.md) §9 与上述三登记表。
"""

from __future__ import annotations

import re
from pathlib import Path

RUNTIME_STATE_DOC = Path("docs/runtime-state-map.md")
PIPELINE_DOC = Path("docs/main-pipeline-sequence.md")
FINAL_ARCH_BASELINE_DOC = Path("docs/final-architecture-baseline.md")
WEB_CONSOLE_PATH = Path("app/web_console.py")
WEB_API_DIR = Path("app/web_api")
WEB_STATIC_DIR = Path("web/static")
CUSTOM_MODELS_PATH = Path("app/web_api/custom_models.py")
MAIN_PATH = Path("main.py")
APPLICATION_DIR = Path("app/application")
RUNTIME_STATE_PATH = Path("app/application/runtime_state.py")
GENERATION_PIPELINE_STATE_PATH = Path("app/application/generation_pipeline_state.py")
REQUEST_METADATA_STATE_PATH = Path("app/application/request_metadata_state.py")
STATS_STATE_PATH = Path("app/application/stats_state.py")
WEB_RUNTIME_STATE_PATH = Path("app/application/web_runtime_state.py")
REQUEST_SCHEDULER_PATH = Path("app/application/request_scheduler.py")
REQUEST_TIMING_SERVICE_PATH = Path("app/application/request_timing_service.py")
DIAGNOSTIC_SNAPSHOT_PATH = Path("app/application/diagnostic_snapshot.py")

WEB_PRIVATE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b_rtt_history\b",
        "Phase 4-F forbids Web/API direct reads of `_rtt_history`; add a diagnostic snapshot first if exposure is ever needed",
    ),
    (
        r"\b_last_api_trigger_at\b",
        "Phase 4-A 绂佹 Web/API 鐩存帴璇诲彇 `_last_api_trigger_at`锛涜嫢鏈潵闇€瑕佹毚闇诧紝蹇呴』鍏堣璁?diagnostic snapshot",
    ),
    (
        r"\b_request_started_at_by_id\b",
        "Phase 4-A 绂佹 Web/API 鐩存帴璇诲彇 `_request_started_at_by_id`锛涜嫢鏈潵闇€瑕佹毚闇诧紝蹇呴』鍏堣璁?diagnostic snapshot",
    ),
    (r"\bdanmu_app\._", "绂佹 Web/API 鐩存帴璁块棶 danmu_app 绉佹湁瀛楁"),
    (r"\bapp\._", "绂佹 Web/API 鐩存帴璁块棶 app 绉佹湁瀛楁"),
    (r"\bdanmu_app\.web_runtime_state\b", "绂佹 Web/API 鐩存帴璁块棶 danmu_app.web_runtime_state"),
    (r"\bapp\.web_runtime_state\b", "绂佹 Web/API 鐩存帴璁块棶 app.web_runtime_state"),
    (r"\bcached_danmu_lines\b", "绂佹 Web/API 缁曡繃 build_status_snapshot() 鐩存帴璇诲彇灞曠ず缂撳瓨"),
    (r"\bcached_layout_mode\b", "绂佹 Web/API 缁曡繃 build_status_snapshot() 鐩存帴璇诲彇灞曠ず缂撳瓨"),
    (r"\bai_worker\._", "绂佹 Web/API 鐩存帴璁块棶 ai_worker 绉佹湁瀹炵幇"),
    (r"\b_mic_service\b", "绂佹 Web/API 鐩存帴璁块棶 _mic_service"),
    (r"\b_set_error_status_safe\b", "绂佹 Web/API 鐩存帴璋冪敤 _set_error_status_safe"),
    (r"\b_build_live_status_snapshot\b", "绂佹 Web/API 鐩存帴璋冪敤 _build_live_status_snapshot"),
    (r"\b_visible_display_count\b", "绂佹 Web/API 鐩存帴璋冪敤 _visible_display_count"),
    (r"\b_resolve_request_credentials\b", "绂佹 Web/API 鐩存帴璋冪敤 _resolve_request_credentials"),
)

CONFIG_CONN_PATTERNS: tuple[str, ...] = (
    "config.conn",
    "self.config.conn",
)

CONFIG_CONN_WHITELIST = {
    Path("app/config_store/__init__.py"),
    Path("app/config_store/storage.py"),
    Path("app/config_store/pool.py"),
    Path("app/config_store/crypto.py"),
    Path("app/history_writer.py"),
    Path("app/session_run_log.py"),
    Path("app/templates.py"),
    Path("app/danmu_engine/__init__.py"),
    Path("app/danmu_engine/track.py"),
    Path("app/danmu_engine/render.py"),
    Path("app/danmu_engine/screen.py"),
}

THREAD_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bQTimer\(", "QTimer"),
    (r"\bQThreadPool\b", "QThreadPool"),
    (r"\bglobalInstance\(\)\.start\b", "QThreadPool.globalInstance().start"),
    (r"\bthreading\.Thread\b", "threading.Thread"),
    (r"\basyncio\.create_task\b", "asyncio.create_task"),
)

RUNTIME_FIELD_EXCLUDE = {
    "web_launch_mode",
    "config",
    "logger",
    "personae",
    "templates",
    "history",
    "history_writer",
    "capturer",
    "engine",
    "overlay",
    "tray",
    "hotkey",
    "ai_worker",
    "floating_panel_overlay",  # W-FP-V2-001
    "floating_panel_engine",  # W-FP-V2-001
    "font_registry",  # W-FONT-002
}

LEGACY_RUNTIME_ASSIGNMENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\bself\._web_error_message\s*(?:\+?=|-=)",
        "Web 閿欒鐘舵€佸凡杩佸叆 WebRuntimeState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `_web_error_message`",
    ),
    (
        r"\bself\._web_error_is_error\s*(?:\+?=|-=)",
        "Web 閿欒鐘舵€佸凡杩佸叆 WebRuntimeState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `_web_error_is_error`",
    ),
    (
        r"\bself\.danmu_count\s*(?:\+?=|-=)",
        "缁熻瀛楁宸茶縼鍏?StatsState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `danmu_count`",
    ),
    (
        r"\bself\._total_input_tokens\s*(?:\+?=|-=)",
        "缁熻瀛楁宸茶縼鍏?StatsState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `_total_input_tokens`",
    ),
    (
        r"\bself\._total_output_tokens\s*(?:\+?=|-=)",
        "缁熻瀛楁宸茶縼鍏?StatsState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `_total_output_tokens`",
    ),
    (
        r"\bself\._start_time\s*(?:\+?=|-=)",
        "缁熻瀛楁宸茶縼鍏?StatsState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `_start_time`",
    ),
    (
        r"\bself\._cached_danmu_lines\s*(?:\+?=|-=)",
        "灞曠ず缂撳瓨宸茶縼鍏?WebRuntimeState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `_cached_danmu_lines`",
    ),
    (
        r"\bself\._cached_layout_mode\s*(?:\+?=|-=)",
        "灞曠ず缂撳瓨宸茶縼鍏?WebRuntimeState锛岀姝㈠湪 DanmuApp 涓噸鏂扮洿鎺ュ啓 `_cached_layout_mode`",
    ),
)

GENERATION_PIPELINE_CANDIDATE_FIELDS: tuple[str, ...] = (
    "_latest_displayed_round",
    "_latest_requested_screenshot_id",
    "_latest_queued_screenshot_id",
    "_latest_displayed_screenshot_id",
    "_last_api_trigger_at",
    "_request_started_at_by_id",
)

GENERATION_PIPELINE_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bQTimer\b", "GenerationPipelineState must not reference QTimer"),
    (r"\bQThreadPool\b", "GenerationPipelineState must not reference QThreadPool"),
    (r"\bQPixmap\b", "GenerationPipelineState must not reference QPixmap"),
    (r"\bai_in_flight\b", "Phase 3-C forbids moving ai_in_flight into GenerationPipelineState"),
    (r"\breply_buffer\b", "Phase 3-C forbids moving reply_buffer into GenerationPipelineState"),
    (r"\bdanmu_queue\b", "Phase 3-C forbids moving danmu_queue into GenerationPipelineState"),
    (r"\b_scene_generation\b", "Phase 3-C forbids moving _scene_generation into GenerationPipelineState"),
    (r"\b_pending_request_meta\b", "Phase 3-C forbids moving _pending_request_meta into GenerationPipelineState"),
    (r"\b_inflight_screenshot_id\b", "Phase 3-C forbids moving _inflight_screenshot_id into GenerationPipelineState"),
    (r"\b_latest_screenshot\b", "Phase 3-C forbids moving _latest_screenshot into GenerationPipelineState"),
)

GENERATION_PIPELINE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_on_screenshot_timer(",
    "_check_rhythm_trigger(",
    "_trigger_api_call(",
    "_consume_reply_queue(",
    "_enqueue_reply_batch(",
    "_on_ai_reply(",
    "_on_ai_error(",
)

# W-GENPIPELINE-EXTRACT: app/application/generation_pipeline.py 服务边界
# 该文件承载回复消费与三路分发逻辑（从 DanmuApp 委托迁出）。
GENERATION_PIPELINE_PATH = Path("app/application/generation_pipeline.py")

# 禁止实例化 Qt 对象（QTimer/QThreadPool/QPixmap 所有权属 DanmuApp）
GENERATION_PIPELINE_SERVICE_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (
        r"\bQTimer\s*\(",
        "generation_pipeline.py must not instantiate QTimer; ownership stays in DanmuApp (call app.reply_timer.start() instead)",
    ),
    (
        r"\bQThreadPool\s*\(",
        "generation_pipeline.py must not instantiate QThreadPool; ownership stays in DanmuApp",
    ),
    (
        r"\bQPixmap\s*\(",
        "generation_pipeline.py must not instantiate QPixmap; ownership stays in DanmuApp",
    ),
)

# 禁止调用主链路触发函数（仍属 DanmuApp，W-GENPIPELINE-EXTRACT 未解冻）
# 注意：_enqueue_reply_batch( 允许（Phase 3 handle_reply_parsed 调用）；
# _consume_reply_queue( 禁止（服务用自身 consume_reply_queue，禁止回调 DanmuApp façade 成循环）
GENERATION_PIPELINE_SERVICE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_on_screenshot_timer(",
    "_on_normal_capture_tick(",
    "_on_ai_reply(",
    "_on_ai_error(",
    "_check_rhythm_trigger(",
    "_consume_reply_queue(",
)

REQUEST_METADATA_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (
        r"\b_last_api_trigger_at\b",
        "Phase 4-A forbids moving _last_api_trigger_at ownership into RequestMetadataState",
    ),
    (
        r"\b_request_started_at_by_id\b",
        "Phase 4-A forbids moving _request_started_at_by_id ownership into RequestMetadataState",
    ),
    (r"\bQTimer\b", "RequestMetadataState must not reference QTimer"),
    (r"\bQThreadPool\b", "RequestMetadataState must not reference QThreadPool"),
    (r"\bQPixmap\b", "RequestMetadataState must not reference QPixmap"),
    (r"\bai_in_flight\b", "RequestMetadataState must not hold ai_in_flight"),
    (r"\breply_buffer\b", "RequestMetadataState must not hold reply_buffer"),
    (r"\bdanmu_queue\b", "RequestMetadataState must not hold danmu_queue"),
    (r"\b_scene_generation\b", "RequestMetadataState must not hold _scene_generation"),
    (r"\b_pending_request_meta\b", "RequestMetadataState must not hold _pending_request_meta"),
)

REQUEST_METADATA_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_api_schedule_block_reason(",
    "_consume_request_timing(",
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
)

STATE_OBJECT_FORBIDDEN_FIELDS: tuple[str, ...] = (
    "_last_api_trigger_at",
    "_request_started_at_by_id",
    "_rtt_history",
)

REQUEST_SCHEDULER_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "RequestScheduler must not import Qt modules"),
    (r"\bQTimer\b", "RequestScheduler must not reference QTimer"),
    (r"\bQThreadPool\b", "RequestScheduler must not reference QThreadPool"),
    (r"\bQPixmap\b", "RequestScheduler must not reference QPixmap"),
    (r"\breply_buffer\b", "RequestScheduler must not hold reply_buffer"),
    (r"\bdanmu_queue\b", "RequestScheduler must not hold danmu_queue"),
    (r"\b_scene_generation\b", "RequestScheduler must not hold _scene_generation"),
    (r"\b_pending_request_meta\b", "RequestScheduler must not hold _pending_request_meta"),
    (r"\bself\.app\s*=", "RequestScheduler must not become a God Object by storing app"),
    (r"\bself\._app\s*=", "RequestScheduler must not become a God Object by storing app"),
    (r"\bself\.danmu_app\s*=", "RequestScheduler must not become a God Object by storing app"),
    (r"\bapp\.web_console\b|\bfrom app\.web_console\b", "RequestScheduler must not import web_console"),
    (r"\bapp\.web_api\b|\bfrom app\.web_api\b", "RequestScheduler must not import web_api"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "RequestScheduler must not import overlay"),
    (r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b", "RequestScheduler must not import danmu_engine"),
)

REQUEST_SCHEDULER_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
    "_consume_reply_queue(",
)

REQUEST_TIMING_SERVICE_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "RequestTimingService must not import Qt modules"),
    (r"\bQTimer\b", "RequestTimingService must not reference QTimer"),
    (r"\bQThreadPool\b", "RequestTimingService must not reference QThreadPool"),
    (r"\bQPixmap\b", "RequestTimingService must not reference QPixmap"),
    (r"\breply_buffer\b", "RequestTimingService must not hold reply_buffer"),
    (r"\bdanmu_queue\b", "RequestTimingService must not hold danmu_queue"),
    (r"\boverlay\b", "RequestTimingService must not handle Overlay"),
    (r"\bDanmuEngine\b", "RequestTimingService must not handle DanmuEngine"),
    (r"\bself\.app\s*=", "RequestTimingService must not become a God Object by storing app"),
    (r"\bself\._app\s*=", "RequestTimingService must not become a God Object by storing app"),
    (r"\bself\.danmu_app\s*=", "RequestTimingService must not become a God Object by storing app"),
    (r"\bapp\.web_console\b|\bfrom app\.web_console\b", "RequestTimingService must not import web_console"),
    (r"\bapp\.web_api\b|\bfrom app\.web_api\b", "RequestTimingService must not import web_api"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "RequestTimingService must not import overlay"),
    (r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b", "RequestTimingService must not import danmu_engine"),
)

REQUEST_TIMING_SERVICE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_consume_reply_queue(",
)

DIAGNOSTIC_SNAPSHOT_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "DiagnosticSnapshot must not import Qt modules"),
    (r"\bQTimer\b", "DiagnosticSnapshot must not reference QTimer"),
    (r"\bQThreadPool\b", "DiagnosticSnapshot must not reference QThreadPool"),
    (r"\bQPixmap\b", "DiagnosticSnapshot must not reference QPixmap"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "DiagnosticSnapshot must not import overlay"),
    (
        r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b",
        "DiagnosticSnapshot must not import danmu_engine",
    ),
)

DIAGNOSTIC_SNAPSHOT_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
    "_consume_reply_queue(",
)

DIAGNOSTICS_ROUTE_FORBIDDEN_TOKENS: tuple[tuple[str, str], ...] = (
    (r"\bPyQt6\b", "Diagnostics route must not import Qt modules"),
    (r"\bapp\.overlay\b|\bfrom app\.overlay\b", "Diagnostics route must not import overlay"),
    (
        r"\bapp\.danmu_engine\b|\bfrom app\.danmu_engine\b",
        "Diagnostics route must not import danmu_engine",
    ),
)

DIAGNOSTICS_ROUTE_FORBIDDEN_CALLS: tuple[str, ...] = (
    "_trigger_api_call(",
    "_on_ai_reply(",
    "_on_ai_error(",
    "_consume_reply_queue(",
)

WEB_DIAGNOSTICS_UI_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b_last_api_trigger_at\b", "Diagnostics UI must not reference `_last_api_trigger_at` directly"),
    (
        r"\b_request_started_at_by_id\b",
        "Diagnostics UI must not reference `_request_started_at_by_id` directly",
    ),
    (r"\b_rtt_history\b", "Diagnostics UI must not reference `_rtt_history` directly"),
    (r"\b_scene_generation\b", "Diagnostics UI must not reference `_scene_generation` directly"),
    (r"\breply_buffer\b", "Diagnostics UI must not reference `reply_buffer` directly"),
    (r"\bdanmu_queue\b", "Diagnostics UI must not reference `danmu_queue` directly"),
)

LAST_API_TRIGGER_AT_WRITE_PATTERN = re.compile(
    r"\bself\._last_api_trigger_at\s*(?::[^=]+)?(?:\+?=|-=)"
)
LAST_API_TRIGGER_AT_WRITE_MESSAGE = (
    "Phase 4-D has moved `_last_api_trigger_at` into RequestScheduler; "
    "DanmuApp may only keep a compatibility facade that delegates to RequestScheduler"
)
REQUEST_STARTED_AT_BY_ID_WRITE_PATTERN = re.compile(
    r"\bself\._request_started_at_by_id\s*(?::[^=]+)?(?:\+?=|-=)|\bself\._request_started_at_by_id\.clear\("
)
REQUEST_STARTED_AT_BY_ID_WRITE_MESSAGE = (
    "Phase 4-E has moved `_request_started_at_by_id` into RequestTimingService; "
    "DanmuApp may only keep a compatibility facade that delegates to RequestTimingService"
)
RTT_HISTORY_WRITE_PATTERN = re.compile(
    r"\bself\._rtt_history\s*(?::[^=]+)?(?:\+?=|-=)|\bself\._rtt_history\.(?:append|clear|extend|insert|pop|remove)\("
)
RTT_HISTORY_WRITE_MESSAGE = (
    "Phase 4-F has moved `_rtt_history` into RequestTimingService; "
    "DanmuApp may only keep a compatibility facade that delegates to RequestTimingService"
)

APPLICATION_PRIVATE_READ_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r'getattr\s*\(\s*app\s*,\s*"_',
        "application/ must not read DanmuApp private fields via getattr(app, \"_...\"); use DanmuApp public façade properties",
    ),
    (
        r'getattr\s*\(\s*self\._app\s*,\s*"_',
        "application/ must not read DanmuApp private fields via getattr(self._app, \"_...\"); use DanmuApp public façade properties",
    ),
    (
        r'__dict__\.get\s*\(\s*"_',
        "application/ must not read DanmuApp private fields via app.__dict__.get(\"_...\"); use DanmuApp public façade properties",
    ),
    (
        r'_safe_app_attr\s*\([^,]+,\s*"_',
        "application/ must not read DanmuApp private fields via _safe_app_attr(..., \"_...\"); use DanmuApp public façade properties",
    ),
)
