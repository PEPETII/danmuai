"""Mic 模式编排器：管理 MicService / 端点检测器生命周期与轮询调度。

DanmuApp 保留：
- _mic_poll_timer（Qt QTimer）
- _trigger_mic_api_call（操作冻结字段）
- _on_mic_utterance_end（回调入口，会调用 _trigger_mic_api_call）

本模块不导入 Qt，只负责状态判断和调度逻辑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from app.mic_service import mic_input_device_id_from_config, mic_mode_enabled
from app.mic_test import pcm_metrics
from app.mic_utterance import (
    MicUtteranceDetector,
    calibrate_noise_floor_rms,
    mic_utterance_config_from_store,
)

if TYPE_CHECKING:
    from app.mic_service import MicService

MIC_POLL_MS = 600


class MicOrchestrator:
    """编排 mic 采集、utterance 检测与轮询调度。"""

    def __init__(
        self,
        *,
        mic_service: MicService,
        on_utterance_end: Callable[[], None],
        log_fn: Callable[[str], None],
    ) -> None:
        self._mic_service = mic_service
        self._on_utterance_end = on_utterance_end
        self._log = log_fn
        self._mic_utterance_detector: MicUtteranceDetector | None = None
        self._mic_poll_ms: int = MIC_POLL_MS

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    def sync(self, *, engine_running: bool, config, mic_audio_supported_fn: Callable[[], bool], resolve_active_model_id_fn: Callable[[], str]) -> None:
        """按配置与运行状态启停 MicService / 端点检测器。"""
        mic_on = mic_mode_enabled(config)
        if not mic_on:
            self._mic_service.sync(enabled=False)
            self.stop_detector()
            return
        preferred_device_id = mic_input_device_id_from_config(config)
        if engine_running:
            self._mic_service.sync(enabled=True, preferred_device_id=preferred_device_id)
        elif not self._mic_service.is_running():
            self.stop_detector()
            self._log("mic mode enabled; capture starts when danmu is running")
            return
        else:
            self.stop_detector()
            self._log("mic mode enabled; keeping mic capture open until danmu starts")
            return
        if not self._mic_service.is_running():
            err = self._mic_service.last_error() or "unknown"
            self._log(f"mic capture not running: {err}")
            self.stop_detector()
            return
        if not mic_audio_supported_fn():
            model_id = resolve_active_model_id_fn()
            self._log(f"mic unsupported for model {model_id or '?'}")
            self.stop_detector()
            return
        self.start_detector(config)

    def start_detector(self, config) -> None:
        """启动 utterance 检测器（不操作 QTimer）。"""
        if self._mic_utterance_detector is None:
            self._mic_utterance_detector = MicUtteranceDetector(
                on_utterance_end=self._on_utterance_end,
                config=mic_utterance_config_from_store(config),
            )
        else:
            self._mic_utterance_detector.update_config(mic_utterance_config_from_store(config))

    def stop_detector(self) -> None:
        """停止检测器（不操作 QTimer）。"""
        if self._mic_utterance_detector is not None:
            self._mic_utterance_detector.reset()

    # ------------------------------------------------------------------ #
    # 轮询
    # ------------------------------------------------------------------ #

    def poll(self, *, engine_running: bool, config) -> bool:
        """执行一次 utterance 轮询。

        Returns True if polling should continue, False otherwise.
        """
        if not mic_mode_enabled(config) or not engine_running:
            return False
        if not self._mic_service.is_running() or self._mic_utterance_detector is None:
            return False
        pcm = self._mic_service.try_snapshot_pcm_ms(self._mic_poll_ms)
        if pcm is None:
            return True
        self._mic_utterance_detector.poll(pcm)
        return True

    def should_schedule_next_poll(self, *, engine_running: bool, config) -> bool:
        """判断是否应该调度下一次轮询。"""
        if not mic_mode_enabled(config) or not engine_running:
            return False
        if self._mic_utterance_detector is None or not self._mic_service.is_running():
            return False
        return True

    # ------------------------------------------------------------------ #
    # 校准
    # ------------------------------------------------------------------ #

    def calibrate_noise_floor(self, *, engine_running: bool, config) -> None:
        """校准噪声基底。"""
        if self._mic_utterance_detector is None:
            return
        if not mic_mode_enabled(config) or not engine_running:
            return
        if not self._mic_service.is_running():
            return
        pcm = self._mic_service.snapshot_pcm_ms(1500)
        floor = calibrate_noise_floor_rms(pcm)
        self._mic_utterance_detector.set_noise_floor(floor)
        enter = self._mic_utterance_detector.enter_threshold()
        self._log(
            f"mic utterance calibrated: noise_floor={floor} enter_rms>={enter} "
            f"poll_ms={self._mic_poll_ms}"
        )

    # ------------------------------------------------------------------ #
    # 采集（供 _on_mic_utterance_end 使用）
    # ------------------------------------------------------------------ #

    def snapshot_pcm_for_utterance(self, config) -> bytes | None:
        """在 utterance 结束时采集 PCM。"""
        from app.mic_service import mic_window_sec_from_config

        window = mic_window_sec_from_config(config)
        return self._mic_service.snapshot_pcm(window)

    def pcm_metrics(self, pcm: bytes) -> tuple[int, int]:
        return pcm_metrics(pcm)

    # ------------------------------------------------------------------ #
    # 属性
    # ------------------------------------------------------------------ #

    @property
    def detector(self) -> MicUtteranceDetector | None:
        return self._mic_utterance_detector

    @property
    def poll_ms(self) -> int:
        return self._mic_poll_ms
