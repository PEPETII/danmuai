"""RMS-based utterance-end detection for mic insert mode (no VAD library).

MicUtteranceDetector 由 DanmuApp._poll_mic_utterance 周期轮询 PCM 块，无 VAD 库。
四状态机：IDLE → SPEAKING → SILENCE_PENDING → COOLDOWN → IDLE。
- 进入：RMS ≥ 动态 enter 阈值（噪声底 + 配置下限）
- 结束：静音持续 silence_ms 且此前语音 ≥ min_speech_ms → 回调 on_utterance_end
- 冷却：cooldown_sec 内忽略新语音，避免连发触发多次 mic API

动态阈值：enter 取 max(配置, floor+120, floor*1.6+60) 抬高门槛抑制环境噪声误触；
exit 取 max(80, floor+40, peak*0.45) 相对峰值回落判定「说完了」，避免单帧抖动。
**滞回保证**：`_speech_exit_threshold()` 返回值始终严格小于 `_speech_enter_threshold()`，
用 `min(raw_exit, enter - 1)` 钳位（user 大声说话时 peak_rms 推高 raw_exit）；否则
SILENCE_PENDING ↔ SPEAKING 死循环，on_utterance_end 永不触发（W-MIC-UTTERANCE-HYSTERESIS-001）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from app.mic_test import QUIET_RMS, pcm_metrics


class UtteranceState(str, Enum):
    """端点检测状态；poll() 每 400ms 左右推进一次。"""

    IDLE = "idle"  # 等待语音，RMS 超 enter 阈值进入 SPEAKING
    SPEAKING = "speaking"  # 累计 peak_rms，RMS 跌破 exit 阈值进入 SILENCE_PENDING
    SILENCE_PENDING = "silence_pending"  # 计时静音；过短则回 IDLE，够长且语音够长则触发回调
    COOLDOWN = "cooldown"  # 已触发 on_utterance_end，冷却期内不检测


@dataclass(frozen=True)
class MicUtteranceConfig:
    speech_rms: int = QUIET_RMS
    silence_ms: int = 400
    min_speech_ms: int = 300
    cooldown_sec: float = 4.0


def mic_utterance_config_from_store(config) -> MicUtteranceConfig:
    """从 ConfigStore 读取 mic_* 键，与 Web 控制台配置项对齐。"""
    return MicUtteranceConfig(
        speech_rms=config.get_int("mic_speech_rms", QUIET_RMS),
        silence_ms=config.get_int("mic_silence_ms", 400),
        min_speech_ms=config.get_int("mic_min_speech_ms", 300),
        cooldown_sec=float(config.get_float("mic_cooldown_sec", 4.0)),
    )


def calibrate_noise_floor_rms(pcm: bytes) -> int:
    """用开麦前短缓冲估计环境噪声底 RMS，供 set_noise_floor 抬高 enter/exit 基准。"""
    rms, _ = pcm_metrics(pcm)
    return max(0, rms)


class MicUtteranceDetector:
    """轮询 PCM 块，每完成一句语音调用一次 on_utterance_end（经 COOLDOWN 防抖）。

    生命周期：reset() 清空状态；开麦前 calibrate_noise_floor_rms + set_noise_floor；
    poll() 由主线程定时驱动。不使用 WebRTC VAD，仅用 RMS 与双阈值滞回。
    """

    def __init__(
        self,
        *,
        on_utterance_end: Callable[[], None],
        config: MicUtteranceConfig | None = None,
    ) -> None:
        self._on_utterance_end = on_utterance_end
        self._config = config or MicUtteranceConfig()
        self._state = UtteranceState.IDLE
        self._speech_started_at = 0.0
        self._silence_started_at = 0.0
        self._cooldown_until = 0.0
        self._noise_floor = 0
        self._peak_rms = 0

    @property
    def state(self) -> UtteranceState:
        return self._state

    def update_config(self, config: MicUtteranceConfig) -> None:
        self._config = config

    def reset(self) -> None:
        """停麦或模式切换时清空状态机与噪声底，避免沿用上一会话阈值。"""
        self._state = UtteranceState.IDLE
        self._speech_started_at = 0.0
        self._silence_started_at = 0.0
        self._cooldown_until = 0.0
        self._noise_floor = 0
        self._peak_rms = 0

    def set_noise_floor(self, floor_rms: int) -> None:
        """开麦校准后写入；enter/exit 阈值均相对 floor 抬高，抑制环境底噪误触。"""
        self._noise_floor = max(0, int(floor_rms))

    def enter_threshold(self) -> int:
        """当前进入阈值（调试/UI 展示用）。"""
        return self._speech_enter_threshold()

    def _speech_enter_threshold(self) -> int:
        # 三者取 max：配置下限、绝对偏移(+120)、相对噪声底(*1.6+60)，环境越吵门槛越高
        floor = self._noise_floor
        return max(
            self._config.speech_rms,
            floor + 120,
            int(floor * 1.6) + 60,
        )

    def _speech_exit_threshold(self) -> int:
        # 相对本次 utterance 的 peak 回落到 45% 以下视为「音量下降」；并与噪声底+40 取 max
        floor = self._noise_floor
        raw_exit = max(80, floor + 40, int(self._peak_rms * 0.45))
        # 关键不变量：exit < enter 形成滞回；用户大声说话时 peak_rms 推高 raw_exit，
        # 一旦 raw_exit 追平/反超 enter，状态机会在 SILENCE_PENDING/SPEAKING 死循环。
        # 用 enter - 1 钳位，确保滞回区至少 1 RMS 宽度（W-MIC-UTTERANCE-HYSTERESIS-001）。
        enter = self._speech_enter_threshold()
        if enter <= 0:
            return raw_exit
        return min(raw_exit, enter - 1)

    def poll(self, pcm_chunk: bytes, *, now: float | None = None) -> None:
        """推进状态机；COOLDOWN 到期回 IDLE，其余状态按 RMS 与时长转换。"""
        now = now if now is not None else time.monotonic()
        if self._state == UtteranceState.COOLDOWN:
            if now >= self._cooldown_until:
                self._state = UtteranceState.IDLE
                self._peak_rms = 0
            else:
                return

        rms, _ = pcm_metrics(pcm_chunk)
        enter_threshold = self._speech_enter_threshold()

        if self._state == UtteranceState.IDLE:
            # 语音开始：锁定 speech_started_at 与初始 peak
            if rms >= enter_threshold:
                self._state = UtteranceState.SPEAKING
                self._speech_started_at = now
                self._peak_rms = rms
            return

        exit_threshold = self._speech_exit_threshold()

        if self._state == UtteranceState.SPEAKING:
            self._peak_rms = max(self._peak_rms, rms)
            if rms >= exit_threshold:
                return
            # 音量跌破 exit：开始计静音，不要求立刻结束（防换气短静音）
            self._state = UtteranceState.SILENCE_PENDING
            self._silence_started_at = now
            return

        if self._state == UtteranceState.SILENCE_PENDING:
            # 静音段内再次大声：视为同一句继续（如句中停顿），回到 SPEAKING
            if rms >= enter_threshold:
                self._state = UtteranceState.SPEAKING
                self._peak_rms = max(self._peak_rms, rms)
                return
            # enter > exit 形成滞回：RMS 在 [exit, enter) 仍视为「未够安静」，继续计静音
            if rms >= exit_threshold:
                return
            silence_ms = (now - self._silence_started_at) * 1000.0
            if silence_ms < self._config.silence_ms:
                return
            speech_ms = (self._silence_started_at - self._speech_started_at) * 1000.0
            if speech_ms >= self._config.min_speech_ms:
                self._fire(now)  # 有效 utterance：进入 COOLDOWN 并回调
            else:
                # 过短语音（咳嗽/按键声）丢弃，不触发 mic API
                self._state = UtteranceState.IDLE
                self._peak_rms = 0

    def _fire(self, now: float) -> None:
        """有效 utterance 结束：先进入 COOLDOWN 再回调，避免回调内重入 poll 连发 mic API。"""
        self._state = UtteranceState.COOLDOWN
        self._cooldown_until = now + self._config.cooldown_sec
        self._peak_rms = 0
        self._on_utterance_end()
