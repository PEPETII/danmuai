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
        self._active_playback_id = 0
        playback.playback_finished.connect(self._handle_finished)

    def _handle_finished(self, playback_id: int) -> None:
        if int(playback_id) != self._active_playback_id:
            return
        callback = self._on_complete
        self._on_complete = None
        self._active_playback_id = 0
        if callback is not None:
            callback()

    def play(self, audio_bytes: bytes, on_complete: Callable[[], None]) -> object:
        playback_id = self._playback.play_wav_bytes(audio_bytes)
        if not playback_id:
            return False
        self._on_complete = on_complete
        self._active_playback_id = int(playback_id)
        return object()

    def stop(self) -> Any:
        self._on_complete = None
        self._active_playback_id = 0
        return self._playback.stop()

    def pause(self) -> Any:
        return self._playback.pause()


__all__ = ["DanmuTtsPlaybackAdapter"]
