"""WAV 字节本地播放（sounddevice + wave）。

``DanmuTtsPlayback`` 提供**互斥播放**：同一时间只允许一段 TTS 播音。
``play_wav_bytes`` 在 busy 期间返回 False，调用方（``DanmuReadService``）应丢弃或排队新请求。
``playback_finished`` 信号用于驱动下一句抽样。

线程模型：播放 worker 在独立 ``threading.Thread``，与 Qt 主线程解耦；``is_busy`` 跨线程安全
（``threading.Lock``）。
"""

from __future__ import annotations

import io
import logging
import threading
import wave

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import Q_ARG, QMetaObject, QObject, Qt, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)

# 句末留白，避免 API 音频尾音被截断或听起来「硬切」
TRAILING_SILENCE_SEC = 1.0
# 句尾短淡出（毫秒），减轻语音→静音的突变
TRAILING_FADE_MS = 80


def _append_trailing_pause(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """在整句自然播完后追加静音尾韵，不截断原音频。"""
    if audio.size == 0 or sample_rate <= 0:
        return audio
    out = audio.astype(np.float32, copy=True)
    fade_samples = min(out.size, int(sample_rate * TRAILING_FADE_MS / 1000.0))
    if fade_samples > 0:
        ramp = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        out[-fade_samples:] *= ramp
    out = np.clip(out, -32768, 32767).astype(np.int16)
    tail = np.zeros(int(sample_rate * TRAILING_SILENCE_SEC), dtype=np.int16)
    return np.concatenate([out, tail])


class DanmuTtsPlayback(QObject):
    """非阻塞播放；busy 期间 is_busy() 为 True。

    终态信号（均经主线程 QueuedConnection 投递）：
    - ``playback_finished``：整句自然播完
    - ``playback_failed``：WAV/输出设备错误，非成功完成
    - ``playback_stopped``：``stop()`` 或外部中断，非成功完成
    """

    playback_finished = pyqtSignal(int)
    playback_failed = pyqtSignal(int)
    playback_stopped = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__(None)
        self._busy = False
        self._active_playback_id = 0
        self._lock = threading.Lock()
        self._next_playback_id = 0
        self._stopped_playback_ids: set[int] = set()

    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def _release_playback_if_active(self, playback_id: int) -> None:
        with self._lock:
            if int(playback_id) != self._active_playback_id:
                return
            self._busy = False
            self._active_playback_id = 0

    def play_wav_bytes(self, wav_bytes: bytes) -> int:
        """开始播放；成功返回大于 0 的 playback_id，拒绝时返回 0。"""
        if not wav_bytes:
            return 0
        with self._lock:
            if self._busy:
                return 0
            self._next_playback_id += 1
            playback_id = self._next_playback_id
            self._active_playback_id = playback_id
            self._busy = True
        threading.Thread(
            target=self._play_worker,
            args=(wav_bytes, playback_id),
            daemon=True,
        ).start()
        return playback_id

    def _play_worker(self, wav_bytes: bytes, playback_id: int) -> None:
        failed = False
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                rate = wf.getframerate()
                nframes = wf.getnframes()
                frames = wf.readframes(nframes)
            if sample_width != 2:
                logger.warning("danmu tts playback: unsupported sample width %s", sample_width)
                failed = True
            elif len(frames) < nframes * sample_width * max(channels, 1):
                logger.warning(
                    "danmu tts playback: short wav read %s/%s frames",
                    len(frames),
                    nframes,
                )
            else:
                audio = np.frombuffer(frames, dtype=np.int16)
                if channels > 1:
                    audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
                audio = _append_trailing_pause(audio, rate)
                sd.play(audio, samplerate=rate, blocking=True)
                sd.wait()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("danmu tts playback failed: %s", exc)
            with self._lock:
                if playback_id not in self._stopped_playback_ids:
                    failed = True
        finally:
            with self._lock:
                was_stopped = playback_id in self._stopped_playback_ids
                self._stopped_playback_ids.discard(playback_id)
            self._release_playback_if_active(playback_id)
            if was_stopped:
                self._invoke_playback_terminal(playback_id, "_deliver_playback_stopped")
            elif failed:
                self._invoke_playback_terminal(playback_id, "_deliver_playback_failed")
            else:
                self._invoke_playback_terminal(playback_id, "_deliver_playback_finished")

    def _invoke_playback_terminal(self, playback_id: int, slot_name: str) -> None:
        # 跨线程安全投递：通过 QMetaObject.invokeMethod + QueuedConnection 将信号
        # 投递到主线程事件循环，等价于 QTimer.singleShot(0, ...)。
        QMetaObject.invokeMethod(
            self,
            slot_name,
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, int(playback_id)),
        )

    @pyqtSlot(int)
    def _deliver_playback_finished(self, playback_id: int) -> None:
        self.playback_finished.emit(int(playback_id))

    @pyqtSlot(int)
    def _deliver_playback_failed(self, playback_id: int) -> None:
        self.playback_failed.emit(int(playback_id))

    @pyqtSlot(int)
    def _deliver_playback_stopped(self, playback_id: int) -> None:
        self.playback_stopped.emit(int(playback_id))

    def stop(self) -> None:
        """停止当前播放并释放 busy 状态；幂等，可在任意线程调用。"""
        with self._lock:
            if self._busy and self._active_playback_id:
                self._stopped_playback_ids.add(self._active_playback_id)
            self._busy = False
            self._active_playback_id = 0
        try:
            sd.stop()
        except (OSError, RuntimeError):
            pass

    def pause(self) -> bool:
        """sounddevice 无真正 pause/resume；不支持暂停语义。"""
        return False
