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
from app.application.danmu_diagnostics import DanmuDiagnosticsRecorder
from app.application.generation_pipeline_state import GenerationPipelineState
from app.model_providers import guess_provider_from_endpoint, resolve_active_model_id
from app.model_selection import resolve_model_status

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

        undisplayed_recorder = getattr(self._app, "danmu_diagnostics", None)
        undisplayed_summary = (
            undisplayed_recorder.snapshot().to_dict()
            if isinstance(undisplayed_recorder, DanmuDiagnosticsRecorder)
            else {}
        )

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
            "diagnosis": {
                "scheduler_blocked": bool(block_reason),
                "high_rtt": avg_rtt >= 3.0,
                "has_pending_timing": request_started_count > 0,
            },
            "undisplayed": undisplayed_summary,
            "knowledge": self._knowledge_summary(),
        }

    @staticmethod
    def _sanitize_api_endpoint(endpoint: str) -> str:
        """Return scheme + host + path, stripping query/fragment/userinfo."""
        parsed = urlparse(endpoint.strip())
        if not parsed.scheme or not parsed.hostname:
            return ""
        netloc = parsed.hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc, params="", query="", fragment="").geturl()

    def _config_context_summary(self) -> dict[str, Any]:
        config = getattr(self._app, "config", None)
        if config is None:
            return {
                "active_model_id": "",
                "provider_id": "",
                "api_endpoint_host": "",
                "api_mode": "",
                "model_name": "",
                "api_endpoint": "",
            }
        endpoint = str(config.get("api_endpoint", "") or "").strip()
        api_mode = str(config.get("api_mode", "doubao") or "doubao")
        host = urlparse(endpoint).netloc if endpoint else ""
        active_model_id = resolve_active_model_id(config)
        model_status = resolve_model_status(config)
        return {
            "active_model_id": active_model_id,
            "provider_id": guess_provider_from_endpoint(endpoint, api_mode),
            "api_endpoint_host": host,
            "api_mode": api_mode,
            "model_name": model_status.get("model_display_name") or active_model_id,
            "api_endpoint": self._sanitize_api_endpoint(endpoint),
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

    def _knowledge_summary(self) -> dict[str, Any]:
        """只读投影 knowledge_runtime 状态；任何异常返回降级字段。

        用 ``self._app.__dict__.get("knowledge_runtime")`` 而非 ``getattr``：在测试
        场景下 ``make_minimal_danmu_app()`` 创建的 QObject 未走 ``__init__``，直接
        ``getattr`` 会触发 ``RuntimeError: super-class __init__() of type DanmuApp
        was never called``。
        """
        runtime = self._app.__dict__.get("knowledge_runtime")
        if runtime is None:
            return {
                "enabled": False,
                "fts_backend": "",
                "packages_count": 0,
                "enabled_packages_count": 0,
                "items_count": 0,
                "enabled_items_count": 0,
                "last_injected_count": 0,
                "last_injected_public_ids": [],
                "last_query_brief": "",
            }
        retriever = getattr(runtime, "retriever", None)
        repo = getattr(runtime, "repository", None)
        fts_backend = ""
        last_injected_count = 0
        last_injected_public_ids: list[str] = []
        last_query_brief = ""
        if retriever is not None:
            fts_backend = str(getattr(retriever, "_fts_backend", "") or "")
            last_injected_count = len(
                getattr(retriever, "_last_injected_contents", []) or []
            )
        try:
            last_inj = getattr(runtime, "get_last_injection", None)
            if callable(last_inj):
                inj = last_inj()
                if inj is not None:
                    last_injected_public_ids = list(
                        getattr(inj, "public_ids", ()) or ()
                    )
                    last_query_brief = str(getattr(inj, "scene_brief", "") or "")
                    if not last_injected_count:
                        last_injected_count = len(last_injected_public_ids)
        except Exception:
            pass
        packages_count = 0
        enabled_packages_count = 0
        items_count = 0
        enabled_items_count = 0
        if repo is not None:
            try:
                packages_count = len(repo.list_packages() or [])
                enabled_packages_count = len(
                    repo.list_packages(enabled_only=True) or []
                )
            except Exception:
                pass
            try:
                items_count = int(
                    repo.list_items(page=1, page_size=1).get("total", 0) or 0
                )
                enabled_items_count = int(
                    repo.list_items(enabled=True, page=1, page_size=1).get("total", 0)
                    or 0
                )
            except Exception:
                pass
        return {
            "enabled": True,
            "fts_backend": fts_backend,
            "packages_count": packages_count,
            "enabled_packages_count": enabled_packages_count,
            "items_count": items_count,
            "enabled_items_count": enabled_items_count,
            "last_injected_count": last_injected_count,
            "last_injected_public_ids": last_injected_public_ids,
            "last_query_brief": last_query_brief,
        }


def build_diagnostic_report(snapshot: dict[str, object]) -> str:
    config_context = snapshot.get("config_context", {}) if isinstance(snapshot, dict) else {}
    scheduler = snapshot.get("scheduler", {}) if isinstance(snapshot, dict) else {}
    timing = snapshot.get("timing", {}) if isinstance(snapshot, dict) else {}
    runtime_state = snapshot.get("runtime_state", {}) if isinstance(snapshot, dict) else {}
    diagnosis = snapshot.get("diagnosis", {}) if isinstance(snapshot, dict) else {}
    undisplayed = snapshot.get("undisplayed", {}) if isinstance(snapshot, dict) else {}
    knowledge = snapshot.get("knowledge", {}) if isinstance(snapshot, dict) else {}
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
        f"model_name: {config_context.get('model_name', '')}",
        f"api_endpoint: {config_context.get('api_endpoint', '')}",
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
        "[diagnosis]",
        f"scheduler_blocked: {diagnosis.get('scheduler_blocked', False)}",
        f"high_rtt: {diagnosis.get('high_rtt', False)}",
        f"has_pending_timing: {diagnosis.get('has_pending_timing', False)}",
        "",
        "[undisplayed]",
        f"recent_count: {undisplayed.get('recent_count', 0)}",
        f"total_count: {undisplayed.get('total_count', 0)}",
        f"latest_reason: {undisplayed.get('latest_reason', '')}",
        f"top_reason: {undisplayed.get('top_reason', '')} ({undisplayed.get('top_reason_count', 0)})",
        f"reason_counts: {undisplayed.get('reason_counts', {})}",
        "",
        "[knowledge]",
        f"enabled: {knowledge.get('enabled', False)}",
        f"fts_backend: {knowledge.get('fts_backend', '')}",
        f"packages_count: {knowledge.get('packages_count', 0)}",
        f"enabled_packages_count: {knowledge.get('enabled_packages_count', 0)}",
        f"items_count: {knowledge.get('items_count', 0)}",
        f"enabled_items_count: {knowledge.get('enabled_items_count', 0)}",
        f"last_injected_count: {knowledge.get('last_injected_count', 0)}",
        "",
        "[boundary_guard]",
        "- Phase 4 ownership freeze remains in force",
        "- Diagnostics remain read-only and separate from /api/status",
        "",
        "[recommended_next_steps]",
        *recommendations,
    ]
    return "\n".join(lines)
