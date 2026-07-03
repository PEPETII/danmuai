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
from PyQt6.QtCore import QMetaObject, QObject, Qt, pyqtSignal

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
    """非阻塞播放；busy 期间 is_busy() 为 True；结束后发射 playback_finished。"""

    playback_finished = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None)
        self._busy = False
        self._lock = threading.Lock()

    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    def _set_busy(self, value: bool) -> None:
        with self._lock:
            self._busy = value

    def play_wav_bytes(self, wav_bytes: bytes) -> bool:
        if self.is_busy() or not wav_bytes:
            return False
        self._set_busy(True)
        threading.Thread(target=self._play_worker, args=(wav_bytes,), daemon=True).start()
        return True

    def _play_worker(self, wav_bytes: bytes) -> None:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                rate = wf.getframerate()
                nframes = wf.getnframes()
                frames = wf.readframes(nframes)
            if sample_width != 2:
                logger.warning("danmu tts playback: unsupported sample width %s", sample_width)
                return
            if len(frames) < nframes * sample_width * max(channels, 1):
                logger.warning(
                    "danmu tts playback: short wav read %s/%s frames",
                    len(frames),
                    nframes,
                )
            audio = np.frombuffer(frames, dtype=np.int16)
            if channels > 1:
                audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
            audio = _append_trailing_pause(audio, rate)
            sd.play(audio, samplerate=rate, blocking=True)
            sd.wait()
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("danmu tts playback failed: %s", exc)
        finally:
            self._set_busy(False)
            # 跨线程安全投递：通过 QMetaObject.invokeMethod + QueuedConnection 将信号
            # 投递到主线程事件循环，等价于 QTimer.singleShot(0, ...)。
            QMetaObject.invokeMethod(
                self, "playback_finished", Qt.ConnectionType.QueuedConnection
            )
