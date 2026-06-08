"""组装 /api/status 的 JSON 形状；禁止在此触发 AI、改队列或写 ConfigStore。

只读投影：StatusSnapshotBuilder 是 /api/status 的唯一数据源，不触达 Qt，不调用主链路函数。
诊断数据走 DiagnosticSnapshotBuilder，勿混入本 dict。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.application.runtime_state import RuntimeState

if TYPE_CHECKING:
    from main import DanmuApp


def _safe_app_attr(app: object, name: str, default: object = None) -> object:
    """Read DanmuApp field without triggering QObject.__getattr__ (DanmuApp.__new__ tests)."""
    try:
        return object.__getattribute__(app, name)
    except AttributeError:
        return default


class StatusSnapshotBuilder:
    """DanmuApp.build_status_snapshot() 的唯一实现委托目标。"""

    def __init__(self, app: "DanmuApp"):
        self._app = app

    def build(self) -> dict[str, object]:
        """字段契约供 Web/WS 使用；诊断数据走 DiagnosticSnapshotBuilder，勿混入本 dict。"""
        from app.model_selection import resolve_model_status
        from app.translations import tr

        state = RuntimeState.from_app(self._app)
        live_snapshot = state.live_snapshot
        lifetime = state.lifetime
        total_tokens = state.input_tokens + state.output_tokens
        model_status = resolve_model_status(self._app.config)
        rx, ry, rw, rh = self._app.config.get_region()
        from app.web_api.capture_region import capture_region_mode

        selection_state = _safe_app_attr(self._app, "_region_selection_state", "idle")
        if selection_state not in (
            "selecting",
            "saved",
            "cancelled",
            "invalid",
        ):
            selection_state = "idle"

        return {
            "running": state.running,
            "danmu_count": state.danmu_count,
            "queue_count": state.queue_count,
            # W-FP-V2-001：display_count 按 danmu_render_mode 语义化
            "display_count": state.display_count,
            "danmu_render_mode": state.danmu_render_mode,
            "overlay_display_count": state.overlay_display_count,
            "floating_panel_active_count": state.floating_panel_active_count,
            "floating_panel_render_active": state.floating_panel_render_active,
            "total_tokens": total_tokens,
            "input_tokens": state.input_tokens,
            "output_tokens": state.output_tokens,
            "runtime_sec": state.runtime_sec,
            "error_message": state.error_message,
            "is_error": state.is_error,
            "live_analyzing": bool(live_snapshot.analyzing) if live_snapshot else False,
            "live_local_fallback": bool(live_snapshot.local_fallback) if live_snapshot else False,
            "live_delay_sec": float(live_snapshot.delay_sec) if live_snapshot else 0.0,
            "live_message": (
                tr("control.status_stopped_desc")
                if not state.running
                else live_snapshot.primary_message() if live_snapshot else ""
            ),
            "persona_names": state.persona_names,
            "screen_index": state.screen_index,
            "has_api_key": state.has_api_key,
            "dedup_profile": state.dedup_profile,
            "lifetime_danmu_count": int(lifetime.get("lifetime_danmu_count", 0)),
            "lifetime_runtime_sec": float(lifetime.get("lifetime_runtime_sec", 0.0)),
            "lifetime_total_tokens": int(lifetime.get("lifetime_total_tokens", 0)),
            "lifetime_input_tokens": int(lifetime.get("lifetime_input_tokens", 0)),
            "lifetime_output_tokens": int(lifetime.get("lifetime_output_tokens", 0)),
            "session_runs": state.session_runs,
            "capture_region_mode": capture_region_mode(self._app.config),
            "region_x": rx,
            "region_y": ry,
            "region_w": rw,
            "region_h": rh,
            "region_selection_state": selection_state,
            "meme_barrage": (
                _safe_app_attr(self._app, "get_meme_barrage_status")()
                if callable(_safe_app_attr(self._app, "get_meme_barrage_status"))
                else {}
            ),
            **model_status,
        }

