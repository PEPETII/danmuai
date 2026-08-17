"""将 ``DanmuTtsPlayback`` 桥接到 ``virtual_host.playback.AudioPlayer`` 协议。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.danmu_tts_playback import DanmuTtsPlayback


class DanmuTtsPlaybackAdapter:
    """桌面 TTS 播放器适配器，供 ``PlaybackQueue`` 注入。"""

    def __init__(self, playback: DanmuTtsPlayback) -> None:
        self._playback = playback
        self._on_complete: Callable[[], None] | None = None
        playback.playback_finished.connect(self._handle_finished)

    def _handle_finished(self) -> None:
        callback = self._on_complete
        self._on_complete = None
        if callback is not None:
            callback()

    def play(self, audio_bytes: bytes, on_complete: Callable[[], None]) -> object:
        self._on_complete = on_complete
        if not self._playback.play_wav_bytes(audio_bytes):
            self._on_complete = None
            return False
        return object()

    def stop(self) -> Any:
        return self._playback.stop()

    def pause(self) -> Any:
        return self._playback.pause()


__all__ = ["DanmuTtsPlaybackAdapter"]
