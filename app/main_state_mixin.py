"""DanmuApp 状态代理与兼容性 Mixin（W-REFACTOR-MAIN-001）。

职责边界：
- 提供 DanmuApp 的状态访问代理（RequestScheduler、RequestTimingService、StatsState 等）
- 配置读取辅助（normal_recognition_interval、reply_count 等）
- 可选实例属性安全访问（_optional_instance_attr）

与 DanmuApp 关系：通过 self 访问 config、_request_scheduler、_request_timing_service、
_stats_state、web_runtime_state 等字段。

代码归属判断：纯状态读取/代理方法、不触达 Qt 对象、不发起 HTTP 请求的代码放这里。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.application.request_scheduler import RequestScheduler
from app.application.request_timing_service import RequestTimingService
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.persona_contract import normal_reply_count_from_config

if TYPE_CHECKING:
    from app.application.danmu_diagnostics import DanmuDiagnosticsRecorder


class DanmuAppStateMixin:
    """状态代理 Mixin：DanmuApp 通过多继承获得这些方法。

    通过 self 访问 DanmuApp 的 config、_request_scheduler 等字段。
    """

    def _get_request_scheduler(self) -> RequestScheduler:
        # W-MEDLOW-001：生产路径在 _init_request_pipeline_state eager 创建；以下为最小单测回退。
        try:
            return object.__getattribute__(self, "_request_scheduler")
        except AttributeError:
            scheduler = RequestScheduler()
            object.__setattr__(self, "_request_scheduler", scheduler)
            return scheduler

    def _get_request_timing_service(self) -> RequestTimingService:
        try:
            return object.__getattribute__(self, "_request_timing_service")
        except AttributeError:
            service = RequestTimingService()
            object.__setattr__(self, "_request_timing_service", service)
            return service

    def _normal_recognition_interval_ms(self) -> int:
        from app.config_defaults import (
            default_normal_recognition_interval_sec_for_mode,
            resolve_danmu_render_mode,
        )

        default_sec = default_normal_recognition_interval_sec_for_mode(
            resolve_danmu_render_mode(self.config)
        )
        try:
            sec = int(self.config.get("normal_recognition_interval_sec", str(default_sec)))
        except (TypeError, ValueError):
            sec = default_sec
        sec = max(1, min(sec, 60))
        return sec * 1000

    def _normal_reply_count(self) -> int:
        return normal_reply_count_from_config(self.config)

    def _sync_reply_batch_config(self) -> None:
        count = self._normal_reply_count()
        self._reply_scene_count = count
        self._reply_filler_count = 0
        self._queue_batch_size = count
        self._queue_low_watermark = max(1, count // 2)

    def _optional_instance_attr(self, name: str):
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            return None

    def _ensure_stats_state(self) -> StatsState:
        state = self._optional_instance_attr("stats_state")
        if state is None:
            state = StatsState()
            object.__setattr__(self, "stats_state", state)
        return state

    def _ensure_web_runtime_state(self) -> WebRuntimeState:
        state = self._optional_instance_attr("web_runtime_state")
        if state is None:
            state = WebRuntimeState()
            object.__setattr__(self, "web_runtime_state", state)
        return state

    @property
    def danmu_count(self) -> int:
        return self._ensure_stats_state().danmu_count

    @danmu_count.setter
    def danmu_count(self, value: int) -> None:
        self._ensure_stats_state().danmu_count = int(value or 0)

    @property
    def _total_input_tokens(self) -> int:
        return self._ensure_stats_state().total_input_tokens

    @_total_input_tokens.setter
    def _total_input_tokens(self, value: int) -> None:
        self._ensure_stats_state().total_input_tokens = int(value or 0)

    @property
    def _total_output_tokens(self) -> int:
        return self._ensure_stats_state().total_output_tokens

    @_total_output_tokens.setter
    def _total_output_tokens(self, value: int) -> None:
        self._ensure_stats_state().total_output_tokens = int(value or 0)

    @property
    def _start_time(self) -> float:
        return self._ensure_stats_state().start_time

    @_start_time.setter
    def _start_time(self, value: float) -> None:
        self._ensure_stats_state().start_time = float(value or 0.0)

    @property
    def _web_error_message(self) -> str:
        return self._ensure_web_runtime_state().error_message

    @_web_error_message.setter
    def _web_error_message(self, value: str) -> None:
        self._ensure_web_runtime_state().error_message = str(value or "")

    @property
    def _web_error_is_error(self) -> bool:
        return self._ensure_web_runtime_state().is_error

    @_web_error_is_error.setter
    def _web_error_is_error(self, value: bool) -> None:
        self._ensure_web_runtime_state().is_error = bool(value)

    @property
    def _cached_danmu_lines(self) -> int:
        return self._ensure_web_runtime_state().cached_danmu_lines

    @_cached_danmu_lines.setter
    def _cached_danmu_lines(self, value: int) -> None:
        state = self._ensure_web_runtime_state()
        state.cached_danmu_lines = int(value or 0)

    @property
    def _cached_layout_mode(self) -> str:
        return self._ensure_web_runtime_state().cached_layout_mode

    @_cached_layout_mode.setter
    def _cached_layout_mode(self, value: str) -> None:
        state = self._ensure_web_runtime_state()
        state.cached_layout_mode = str(value or "fullscreen")

    # --- Generation pipeline ID 投影只读访问器（W-T5-GP-004）---
    # 写路径：set_latest_displayed_from_pipeline（main_web_facade_mixin）；
    # 读路径：GenerationPipelineState.from_app 与本 @property 对称。

    @property
    def latest_displayed_round(self) -> int:
        return int(self._optional_instance_attr("_latest_displayed_round") or 0)

    @property
    def latest_requested_screenshot_id(self) -> int:
        return int(self._optional_instance_attr("_latest_requested_screenshot_id") or 0)

    @property
    def latest_queued_screenshot_id(self) -> int:
        return int(self._optional_instance_attr("_latest_queued_screenshot_id") or 0)

    @property
    def latest_displayed_screenshot_id(self) -> int:
        return int(self._optional_instance_attr("_latest_displayed_screenshot_id") or 0)

    @property
    def region_selection_state(self) -> str:
        return str(self._optional_instance_attr("_region_selection_state") or "idle")

    @property
    def danmu_diagnostics(self) -> "DanmuDiagnosticsRecorder | None":
        return self._optional_instance_attr("_danmu_diagnostics")

    @property
    def total_input_tokens(self) -> int:
        return self._ensure_stats_state().total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._ensure_stats_state().total_output_tokens

    @property
    def session_start_time(self) -> float:
        return self._ensure_stats_state().start_time

    @property
    def web_error_message(self) -> str:
        return self._ensure_web_runtime_state().error_message

    @property
    def web_is_error(self) -> bool:
        return self._ensure_web_runtime_state().is_error

    @property
    def cached_danmu_lines(self) -> int:
        return self._ensure_web_runtime_state().cached_danmu_lines

    @property
    def cached_layout_mode(self) -> str:
        return self._ensure_web_runtime_state().cached_layout_mode

    def optional_pet_barrage_controller(self):
        return self._optional_instance_attr("pet_barrage_controller")

    def optional_floating_panel_engine(self):
        return self._optional_instance_attr("floating_panel_engine")

    def optional_floating_panel_overlay(self):
        return self._optional_instance_attr("floating_panel_overlay")
