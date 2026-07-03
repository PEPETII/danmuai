"""从 DanmuApp 只读投影的运行态视图，不拥有队列、截图或定时器。

RuntimeState 是不可变 dataclass，通过 from_app() 工厂方法集中读取 DanmuApp 字段，
避免 Web 层散落 getattr。供 StatusSnapshotBuilder 组装 /api/status。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.ai_client_requests import visual_credentials_ready
from app.application.generation_pipeline_state import GenerationPipelineState
from app.config_defaults import resolve_danmu_render_mode
from app.danmu_engine import dedup_profile_enabled
from app.personae import persona_display_name_with_config

if TYPE_CHECKING:
    from main import DanmuApp


def _overlay_display_count(app: "DanmuApp") -> int:
    if hasattr(app, "visible_display_count"):
        return int(app.visible_display_count())
    if hasattr(app, "_visible_display_count"):
        return int(app._visible_display_count())
    return 0


def _floating_panel_metrics(app: "DanmuApp") -> tuple[int, bool]:
    optional_overlay = getattr(app, "optional_floating_panel_overlay", None)
    if callable(optional_overlay):
        overlay = optional_overlay()
    else:
        overlay = getattr(app, "floating_panel_overlay", None)
    if overlay is None:
        return 0, False
    active = int(overlay.active_count()) if hasattr(overlay, "active_count") else 0
    render_active = bool(overlay.is_render_active()) if hasattr(overlay, "is_render_active") else False
    return active, render_active


def _effective_display_count(render_mode: str, overlay_count: int, panel_count: int) -> int:
    if render_mode == "floating_panel":
        return panel_count
    return overlay_count


@dataclass(frozen=True)
class RuntimeState:
    """不可变运行态快照；通过 from_app 集中读取，避免 Web 层散落 getattr。"""

    running: bool
    danmu_count: int
    queue_count: int
    display_count: int
    danmu_render_mode: str
    overlay_display_count: int
    floating_panel_active_count: int
    floating_panel_render_active: bool
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
        """只读聚合；经 DanmuApp 公开 façade 读取运行态。"""
        stats_state = getattr(app, "stats_state", None)
        web_runtime_state = getattr(app, "web_runtime_state", None)
        generation_pipeline = GenerationPipelineState.from_app(app)

        running = bool(getattr(app.engine, "running", False))
        queue_count = app.reply_buffer.size() if hasattr(app.reply_buffer, "size") else 0
        render_mode = resolve_danmu_render_mode(app.config)
        overlay_display_count = _overlay_display_count(app)
        floating_panel_active_count, floating_panel_render_active = _floating_panel_metrics(app)
        display_count = _effective_display_count(
            render_mode,
            overlay_display_count,
            floating_panel_active_count,
        )
        if stats_state is not None:
            input_tokens = int(stats_state.total_input_tokens or 0)
            output_tokens = int(stats_state.total_output_tokens or 0)
            start_time = float(stats_state.start_time or 0.0)
            danmu_count = int(stats_state.danmu_count or 0)
        else:
            input_tokens = int(getattr(app, "total_input_tokens", 0) or 0)
            output_tokens = int(getattr(app, "total_output_tokens", 0) or 0)
            start_time = float(getattr(app, "session_start_time", 0.0) or 0.0)
            danmu_count = int(getattr(app, "danmu_count", 0) or 0)
        runtime_sec = time.monotonic() - start_time if start_time > 0 else 0.0

        if running:
            live_snapshot = (
                app.build_live_status_snapshot()
                if hasattr(app, "build_live_status_snapshot")
                else None
            )
        else:
            live_snapshot = None

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
            danmu_count=danmu_count,
            queue_count=int(queue_count),
            display_count=int(display_count),
            danmu_render_mode=render_mode,
            overlay_display_count=int(overlay_display_count),
            floating_panel_active_count=int(floating_panel_active_count),
            floating_panel_render_active=bool(floating_panel_render_active),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            runtime_sec=runtime_sec,
            error_message=str(
                web_runtime_state.error_message
                if web_runtime_state is not None
                else getattr(app, "web_error_message", "")
                or ""
            ),
            is_error=bool(
                web_runtime_state.is_error
                if web_runtime_state is not None
                else getattr(app, "web_is_error", False)
            ),
            cached_danmu_lines=int(
                web_runtime_state.cached_danmu_lines
                if web_runtime_state is not None
                else getattr(app, "cached_danmu_lines", 0)
                or 0
            ),
            cached_layout_mode=str(
                web_runtime_state.cached_layout_mode
                if web_runtime_state is not None
                else getattr(app, "cached_layout_mode", "fullscreen")
                or "fullscreen"
            ),
            live_snapshot=live_snapshot,
            persona_names=[persona_display_name_with_config(name, app.config) for name in app.personae.get_active()],
            screen_index=app.config.get_int("screen_index", 0),
            has_api_key=visual_credentials_ready(app.config),
            dedup_profile=dedup_profile,
            lifetime=lifetime,
            session_runs=session_runs,
            generation_pipeline=generation_pipeline,
        )

