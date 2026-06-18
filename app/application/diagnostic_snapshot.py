"""只读诊断快照：调度/timing/代际 ID 投影，供 /api/diagnostics，与 /api/status 分离。

分离原因：诊断信息包含 API Key 掩码、调度器内部状态等敏感数据，不应暴露在 status 轮询中。
DiagnosticSnapshotBuilder 是 /api/diagnostics 的唯一数据源。
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from app.api_schedule import min_api_interval_elapsed
from app.application.generation_pipeline_state import GenerationPipelineState
from app.model_providers import guess_provider_from_endpoint, resolve_active_model_id

if TYPE_CHECKING:
    from main import DanmuApp


class DiagnosticSnapshotBuilder:
    """只读读取 RequestScheduler / RequestTimingService；禁止写回 DanmuApp 或调用主链路函数。"""

    def __init__(self, app: "DanmuApp") -> None:
        self._app = app

    def build(self) -> dict[str, object]:
        """经 DanmuApp 公开 façade 只读调度/timing；Web 不得直接读 _last_api_trigger_at 等私有字段。"""
        scheduler = self._app.get_request_scheduler()
        timing = self._app.get_request_timing_service()
        stats_state = getattr(self._app, "stats_state", None)
        web_runtime_state = getattr(self._app, "web_runtime_state", None)
        danmu_diagnostics_state = getattr(self._app, "danmu_diagnostics", None)
        generation_pipeline = GenerationPipelineState.from_app(self._app)

        last_trigger_at = float(scheduler.last_api_trigger_at)
        now = time.monotonic()
        recent_rtt_samples = [float(sample) for sample in list(timing.rtt_history)[-5:]]
        request_started_count = len(timing.request_started_at_by_id)
        avg_rtt = float(timing.avg_rtt())
        block_reason = self._app.api_schedule_block_reason(enforce_min_interval=True)
        smart_cooldown_ms = int(
            timing.smart_cooldown_ms(
                fallback_interval_sec=self._app.config.get_int("screenshot_interval", 3)
            )
        )
        stats_runtime_sec = 0.0
        if stats_state is not None and hasattr(stats_state, "runtime_sec"):
            stats_runtime_sec = float(stats_state.runtime_sec(now=now))

        return {
            "config_context": self._config_context_summary(),
            "scheduler": {
                "last_api_trigger_at": last_trigger_at,
                "seconds_since_last_trigger": 0.0
                if last_trigger_at <= 0.0
                else max(0.0, now - last_trigger_at),
                "min_interval_blocked": bool(
                    last_trigger_at > 0.0 and not min_api_interval_elapsed(last_trigger_at)
                ),
                "block_reason": block_reason,
            },
            "timing": {
                "request_started_count": request_started_count,
                "rtt_history_len": len(timing.rtt_history),
                "avg_rtt": avg_rtt,
                "smart_cooldown_ms": smart_cooldown_ms,
                "recent_rtt_samples": recent_rtt_samples,
            },
            "runtime_state": {
                "web_runtime": self._web_runtime_summary(web_runtime_state),
                "stats": self._stats_summary(stats_state, runtime_sec=stats_runtime_sec),
                "generation_pipeline": asdict(generation_pipeline),
            },
            "danmu_diagnostics": self._danmu_diagnostics_summary(
                danmu_diagnostics_state,
                now=now,
            ),
            "diagnosis": {
                "scheduler_blocked": bool(block_reason),
                "high_rtt": avg_rtt >= 3.0,
                "has_pending_timing": request_started_count > 0,
            },
        }

    def _config_context_summary(self) -> dict[str, Any]:
        config = getattr(self._app, "config", None)
        if config is None:
            return {
                "active_model_id": "",
                "provider_id": "",
                "api_endpoint_host": "",
                "api_mode": "",
            }
        endpoint = str(config.get("api_endpoint", "") or "").strip()
        api_mode = str(config.get("api_mode", "doubao") or "doubao")
        host = urlparse(endpoint).netloc if endpoint else ""
        return {
            "active_model_id": resolve_active_model_id(config),
            "provider_id": guess_provider_from_endpoint(endpoint, api_mode),
            "api_endpoint_host": host,
            "api_mode": api_mode,
        }

    @staticmethod
    def _web_runtime_summary(web_runtime_state: Any) -> dict[str, Any]:
        return {
            "error_message": str(getattr(web_runtime_state, "error_message", "") or ""),
            "is_error": bool(getattr(web_runtime_state, "is_error", False)),
            "cached_danmu_lines": int(
                getattr(web_runtime_state, "cached_danmu_lines", 0) or 0
            ),
            "cached_layout_mode": str(
                getattr(web_runtime_state, "cached_layout_mode", "fullscreen") or "fullscreen"
            ),
        }

    @staticmethod
    def _stats_summary(stats_state: Any, *, runtime_sec: float) -> dict[str, Any]:
        return {
            "danmu_count": int(getattr(stats_state, "danmu_count", 0) or 0),
            "total_input_tokens": int(getattr(stats_state, "total_input_tokens", 0) or 0),
            "total_output_tokens": int(getattr(stats_state, "total_output_tokens", 0) or 0),
            "runtime_sec": float(runtime_sec),
        }

    @staticmethod
    def _danmu_diagnostics_summary(danmu_diagnostics_state: Any, *, now: float) -> dict[str, Any]:
        if danmu_diagnostics_state is None or not hasattr(danmu_diagnostics_state, "snapshot"):
            return {
                "recent_count": 0,
                "total_recorded": 0,
                "top_reasons": [],
                "latest": None,
                "recent": [],
            }
        return dict(danmu_diagnostics_state.snapshot(now=now))


def build_diagnostic_report(snapshot: dict[str, object]) -> str:
    config_context = snapshot.get("config_context", {}) if isinstance(snapshot, dict) else {}
    scheduler = snapshot.get("scheduler", {}) if isinstance(snapshot, dict) else {}
    timing = snapshot.get("timing", {}) if isinstance(snapshot, dict) else {}
    runtime_state = snapshot.get("runtime_state", {}) if isinstance(snapshot, dict) else {}
    danmu_diagnostics = snapshot.get("danmu_diagnostics", {}) if isinstance(snapshot, dict) else {}
    diagnosis = snapshot.get("diagnosis", {}) if isinstance(snapshot, dict) else {}
    web_runtime = runtime_state.get("web_runtime", {}) if isinstance(runtime_state, dict) else {}
    stats = runtime_state.get("stats", {}) if isinstance(runtime_state, dict) else {}
    generation = (
        runtime_state.get("generation_pipeline", {}) if isinstance(runtime_state, dict) else {}
    )

    recommendations: list[str] = []
    if diagnosis.get("scheduler_blocked"):
        recommendations.append(
            f"- Inspect scheduler block reason: {scheduler.get('block_reason') or 'unknown'}"
        )
    if diagnosis.get("high_rtt"):
        recommendations.append("- Inspect network latency or upstream model response time")
    if diagnosis.get("has_pending_timing"):
        recommendations.append("- Inspect in-flight request completion and timing cleanup paths")
    top_reasons = danmu_diagnostics.get("top_reasons", [])
    if top_reasons:
        top = top_reasons[0]
        recommendations.append(
            f"- Inspect recent no-danmu reason: {top.get('label') or top.get('reason')}"
        )
    if not recommendations:
        recommendations.append("- No immediate scheduler/timing anomaly detected from snapshot")

    lines = [
        "DanmuAI Diagnostic Report",
        "",
        "[config_context]",
        f"active_model_id: {config_context.get('active_model_id', '')}",
        f"provider_id: {config_context.get('provider_id', '')}",
        f"api_endpoint_host: {config_context.get('api_endpoint_host', '')}",
        f"api_mode: {config_context.get('api_mode', '')}",
        "",
        "[scheduler]",
        f"last_api_trigger_at: {scheduler.get('last_api_trigger_at', 0.0)}",
        f"seconds_since_last_trigger: {scheduler.get('seconds_since_last_trigger', 0.0)}",
        f"min_interval_blocked: {scheduler.get('min_interval_blocked', False)}",
        f"block_reason: {scheduler.get('block_reason', '')}",
        "",
        "[timing]",
        f"request_started_count: {timing.get('request_started_count', 0)}",
        f"rtt_history_len: {timing.get('rtt_history_len', 0)}",
        f"avg_rtt: {timing.get('avg_rtt', 0.0)}",
        f"smart_cooldown_ms: {timing.get('smart_cooldown_ms', 0)}",
        f"recent_rtt_samples: {timing.get('recent_rtt_samples', [])}",
        "",
        "[runtime_state.web_runtime]",
        f"error_message: {web_runtime.get('error_message', '')}",
        f"is_error: {web_runtime.get('is_error', False)}",
        f"cached_danmu_lines: {web_runtime.get('cached_danmu_lines', 0)}",
        f"cached_layout_mode: {web_runtime.get('cached_layout_mode', 'fullscreen')}",
        "",
        "[runtime_state.stats]",
        f"danmu_count: {stats.get('danmu_count', 0)}",
        f"total_input_tokens: {stats.get('total_input_tokens', 0)}",
        f"total_output_tokens: {stats.get('total_output_tokens', 0)}",
        f"runtime_sec: {stats.get('runtime_sec', 0.0)}",
        "",
        "[runtime_state.generation_pipeline]",
        f"latest_displayed_round: {generation.get('latest_displayed_round', 0)}",
        f"latest_requested_screenshot_id: {generation.get('latest_requested_screenshot_id', 0)}",
        f"latest_queued_screenshot_id: {generation.get('latest_queued_screenshot_id', 0)}",
        f"latest_displayed_screenshot_id: {generation.get('latest_displayed_screenshot_id', 0)}",
        "",
        "[danmu_diagnostics]",
        f"recent_count: {danmu_diagnostics.get('recent_count', 0)}",
        f"total_recorded: {danmu_diagnostics.get('total_recorded', 0)}",
        f"top_reasons: {danmu_diagnostics.get('top_reasons', [])}",
        f"latest: {danmu_diagnostics.get('latest')}",
        "",
        "[diagnosis]",
        f"scheduler_blocked: {diagnosis.get('scheduler_blocked', False)}",
        f"high_rtt: {diagnosis.get('high_rtt', False)}",
        f"has_pending_timing: {diagnosis.get('has_pending_timing', False)}",
        "",
        "[boundary_guard]",
        "- Phase 4 ownership freeze remains in force",
        "- Diagnostics remain read-only and separate from /api/status",
        "",
        "[recommended_next_steps]",
        *recommendations,
    ]
    return "\n".join(lines)
