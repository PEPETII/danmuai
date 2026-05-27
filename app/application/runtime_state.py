"""从 DanmuApp 只读投影的运行态视图，不拥有队列、截图或定时器。

供 StatusSnapshotBuilder 组装 /api/status；真实写入仍在 DanmuApp 与各 *State 服务。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.application.generation_pipeline_state import GenerationPipelineState
from app.danmu_engine import dedup_profile_enabled
from app.personae import persona_display_name

if TYPE_CHECKING:
    from main import DanmuApp


@dataclass(frozen=True)
class RuntimeState:
    """不可变运行态快照；通过 from_app 集中读取，避免 Web 层散落 getattr。"""

    running: bool
    danmu_count: int
    queue_count: int
    display_count: int
    input_tokens: int
    output_tokens: int
    runtime_sec: float
    error_message: str
    is_error: bool
    cached_danmu_lines: int
    cached_layout_mode: str
    live_snapshot: Any | None
    persona_names: list[str]
    screen_index: int
    has_api_key: bool
    dedup_profile: dict[str, Any] | None
    lifetime: dict[str, Any]
    session_runs: list[dict[str, Any]]
    generation_pipeline: GenerationPipelineState

    @classmethod
    def from_app(cls, app: "DanmuApp") -> "RuntimeState":
        """只读聚合；getattr 回退兼容 bind_minimal_danmu_app 等未完整初始化的测试实例。"""
        stats_state = getattr(app, "stats_state", None)
        web_runtime_state = getattr(app, "web_runtime_state", None)
        generation_pipeline = GenerationPipelineState.from_app(app)

        running = bool(getattr(app.engine, "running", False))
        queue_count = app.reply_buffer.size() if hasattr(app.reply_buffer, "size") else 0
        display_count = app._visible_display_count() if hasattr(app, "_visible_display_count") else 0
        input_tokens = int(
            getattr(stats_state, "total_input_tokens", getattr(app, "_total_input_tokens", 0)) or 0
        )
        output_tokens = int(
            getattr(stats_state, "total_output_tokens", getattr(app, "_total_output_tokens", 0)) or 0
        )
        start_time = float(
            getattr(stats_state, "start_time", getattr(app, "_start_time", 0.0)) or 0.0
        )
        runtime_sec = time.monotonic() - start_time if start_time > 0 else 0.0

        live_snapshot = app._build_live_status_snapshot() if running else None

        dedup_profile = None
        if dedup_profile_enabled() and hasattr(app.engine, "get_dedup_profile_snapshot"):
            dedup_profile = app.engine.get_dedup_profile_snapshot()

        lifetime: dict[str, Any] = {}
        lifetime_stats = getattr(app, "lifetime_stats", None)
        if lifetime_stats is not None:
            lifetime = lifetime_stats.snapshot(session_runtime_sec=runtime_sec)

        session_runs: list[dict[str, Any]] = []
        session_log = getattr(app, "session_run_log", None)
        if session_log is not None:
            session_runs = session_log.list_dicts_newest_first()

        return cls(
            running=running,
            danmu_count=int(
                getattr(stats_state, "danmu_count", getattr(app, "danmu_count", 0)) or 0
            ),
            queue_count=int(queue_count),
            display_count=int(display_count),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            runtime_sec=runtime_sec,
            error_message=str(
                getattr(web_runtime_state, "error_message", getattr(app, "_web_error_message", "")) or ""
            ),
            is_error=bool(
                getattr(web_runtime_state, "is_error", getattr(app, "_web_error_is_error", False))
            ),
            cached_danmu_lines=int(
                getattr(
                    web_runtime_state,
                    "cached_danmu_lines",
                    getattr(app, "_cached_danmu_lines", 0),
                )
                or 0
            ),
            cached_layout_mode=str(
                getattr(
                    web_runtime_state,
                    "cached_layout_mode",
                    getattr(app, "_cached_layout_mode", "fullscreen"),
                )
                or "fullscreen"
            ),
            live_snapshot=live_snapshot,
            persona_names=[persona_display_name(name) for name in app.personae.get_active()],
            screen_index=app.config.get_int("screen_index", 0),
            has_api_key=bool(app.config.get_api_key()),
            dedup_profile=dedup_profile,
            lifetime=lifetime,
            session_runs=session_runs,
            generation_pipeline=generation_pipeline,
        )
