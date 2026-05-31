"""读弹幕：定时从屏上可见弹幕抽样 → MiMo TTS → 本地播放。"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from app.application.config_service import MASKED_API_KEY
from app.danmu_tts import (
    TTS_PROBE_TEXT,
    DanmuTtsError,
    clamp_read_interval_sec,
    normalize_tts_voice,
    synthesize_mimo_tts,
)
from app.danmu_tts_playback import DanmuTtsPlayback

if TYPE_CHECKING:
    from main import DanmuApp


def _service_alive(service: "DanmuReadService | None") -> bool:
    if service is None or getattr(service, "_shutdown", False):
        return False
    try:
        import shiboken6

        return shiboken6.isValid(service)
    except Exception:
        return False


def _emit_tts_ready(service: "DanmuReadService", wav: bytes) -> None:
    if not _service_alive(service):
        return
    try:
        service._tts_ready.emit(wav)
    except RuntimeError:
        pass


def _emit_tts_failed(service: "DanmuReadService", message: str) -> None:
    if not _service_alive(service):
        return
    try:
        service._tts_failed.emit(message)
    except RuntimeError:
        pass


def danmu_read_enabled(config) -> bool:
    return config.get("danmu_read_enabled", "0") == "1"


class _DanmuTtsRunnable(QRunnable):
    def __init__(
        self,
        service: "DanmuReadService",
        *,
        text: str,
        api_key: str,
        voice: str,
        style_prompt: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._text = text
        self._api_key = api_key
        self._voice = voice
        self._style_prompt = style_prompt
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            wav = synthesize_mimo_tts(
                self._api_key,
                self._text,
                style_prompt=self._style_prompt,
                voice=self._voice,
            )
        except DanmuTtsError as exc:
            _emit_tts_failed(self._service, str(exc))
            return
        except Exception as exc:
            _emit_tts_failed(self._service, str(exc))
            return
        _emit_tts_ready(self._service, wav)


class DanmuReadService(QObject):
    """主线程 QObject；TTS HTTP 在 QThreadPool，结果经 Qt 信号回主线程。"""

    _tts_ready = pyqtSignal(bytes)
    _tts_failed = pyqtSignal(str)

    def __init__(self, app: "DanmuApp") -> None:
        super().__init__(app)
        self._app = app
        self._shutdown = False
        self._playback = DanmuTtsPlayback()
        self._playback.playback_finished.connect(self._on_playback_finished)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._tts_ready.connect(self._on_tts_ready)
        self._tts_failed.connect(self._on_tts_failed)
        self._tts_in_flight = False
        self._last_text = ""
        self._skip_log_flags: set[str] = set()

    def shutdown(self) -> None:
        """退出前调用：停止定时器并忽略池线程迟到的 emit。"""
        self._shutdown = True
        self._timer.stop()
        self._tts_in_flight = False

    def on_engine_started(self) -> None:
        config = self._app.config
        self._app.logger.info(
            "danmu read: engine start enabled=%s has_key=%s interval=%ss",
            danmu_read_enabled(config),
            bool(config.get_tts_api_key()),
            config.get("danmu_read_interval_sec", "10"),
        )
        self._skip_log_flags.clear()
        self._sync_timer()

    def on_engine_stopped(self) -> None:
        self._timer.stop()
        self._tts_in_flight = False

    def _log_skip_once(self, reason: str, message: str) -> None:
        if reason in self._skip_log_flags:
            return
        self._skip_log_flags.add(reason)
        self._app.logger.warning(f"danmu read: {message}")

    def _sync_timer(self) -> None:
        config = self._app.config
        if not self._app.engine.running or not danmu_read_enabled(config):
            self._timer.stop()
            return
        if not config.get_tts_api_key():
            self._log_skip_once("no_key", "已启用但无 TTS API Key，请在「读弹幕」页保存 Key")
            self._timer.stop()
            return
        interval_ms = clamp_read_interval_sec(
            config.get("danmu_read_interval_sec", "10")
        ) * 1000
        self._timer.setInterval(interval_ms)
        if not self._timer.isActive():
            self._timer.start()
            self._app.logger.info(
                "danmu read: timer started every %ss",
                config.get("danmu_read_interval_sec", "10"),
            )
            # 首条略延迟，等弹幕滚入可见区
            QTimer.singleShot(800, self._on_tick)

    def apply_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        config = self._app.config
        items: dict[str, str] = {}
        if "enabled" in patch:
            items["danmu_read_enabled"] = "1" if patch.get("enabled") else "0"
        if "interval_sec" in patch:
            items["danmu_read_interval_sec"] = str(
                clamp_read_interval_sec(patch.get("interval_sec"))
            )
        if "voice" in patch:
            items["tts_voice"] = normalize_tts_voice(str(patch.get("voice") or ""))
        if "style_prompt" in patch:
            items["tts_style_prompt"] = str(patch.get("style_prompt", ""))
        if items:
            config.set_batch(items)
        api_key = patch.get("api_key")
        if isinstance(api_key, str):
            key = api_key.strip()
            if key and key != MASKED_API_KEY:
                config.set_tts_api_key(key)
        self._skip_log_flags.discard("no_key")
        self._sync_timer()
        self._app.logger.info(
            "danmu read: config saved enabled=%s interval=%ss has_key=%s",
            danmu_read_enabled(config),
            config.get("danmu_read_interval_sec", "10"),
            bool(config.get_tts_api_key()),
        )
        return export_danmu_read_config(config)

    def run_probe(self, *, api_key_override: str | None = None) -> dict[str, object]:
        config = self._app.config
        api_key = (api_key_override or "").strip() or config.get_tts_api_key()
        if not api_key:
            return {"ok": False, "message": "请先填写 TTS API Key（可直接试听，保存后用于定时朗读）"}
        if self._playback.is_busy() or self._tts_in_flight:
            return {"ok": False, "message": "正在播放或合成，请稍后再试听"}
        voice = normalize_tts_voice(config.get("tts_voice", ""))
        style = config.get("tts_style_prompt", "")
        self._tts_in_flight = True
        try:
            wav = synthesize_mimo_tts(
                api_key,
                TTS_PROBE_TEXT,
                style_prompt=style,
                voice=voice,
            )
        except DanmuTtsError as exc:
            self._tts_in_flight = False
            return {"ok": False, "message": str(exc)}
        except Exception as exc:
            self._tts_in_flight = False
            return {"ok": False, "message": str(exc)}
        if not self._playback.play_wav_bytes(wav):
            self._tts_in_flight = False
            return {"ok": False, "message": "无法开始播放"}
        self._app.logger.info("danmu read: probe playback started")
        return {"ok": True, "message": "试听播放中（播放结束后才可发起下一条）"}

    def _on_tick(self) -> None:
        app = self._app
        if not app.engine.running or not danmu_read_enabled(app.config):
            return
        if self._tts_in_flight or self._playback.is_busy():
            return
        api_key = app.config.get_tts_api_key()
        if not api_key:
            self._log_skip_once("no_key", "无 TTS API Key，跳过朗读")
            return
        texts = app.engine.visible_display_texts()
        if not texts:
            on_tracks = app.engine.current_display_count()
            visible_n = app.engine.visible_display_count()
            if on_tracks > 0:
                self._log_skip_once(
                    "no_visible_text",
                    f"屏上暂无可见弹幕正文（轨道内 {on_tracks} 条，可见计数 {visible_n}），稍后重试",
                )
            return
        candidates = [t for t in texts if t != self._last_text] or texts
        text = random.choice(candidates)
        self._last_text = text
        voice = normalize_tts_voice(app.config.get("tts_voice", ""))
        style = app.config.get("tts_style_prompt", "")
        preview = text if len(text) <= 24 else f"{text[:24]}..."
        app.logger.info("danmu read: synthesizing %s", preview)
        self._tts_in_flight = True
        runnable = _DanmuTtsRunnable(
            self,
            text=text,
            api_key=api_key,
            voice=voice,
            style_prompt=style,
        )
        QThreadPool.globalInstance().start(runnable)

    def _on_tts_ready(self, wav_bytes: bytes) -> None:
        if self._shutdown:
            return
        if not self._app.engine.running:
            self._tts_in_flight = False
            return
        if not wav_bytes:
            self._tts_in_flight = False
            self._app.logger.warning("danmu read: empty audio response")
            return
        if not self._playback.play_wav_bytes(wav_bytes):
            self._tts_in_flight = False
            self._app.logger.warning("danmu read: playback skipped (busy)")
            return
        # 保持 _tts_in_flight 直至 playback_finished，避免定时 tick 触发新的 sd.play 打断当前句
        self._app.logger.info("danmu read: playback started (%s bytes)", len(wav_bytes))

    def _on_playback_finished(self) -> None:
        self._tts_in_flight = False
        self._app.logger.debug("danmu read: playback finished")

    def _on_tts_failed(self, message: str) -> None:
        self._tts_in_flight = False
        self._app.logger.warning("danmu read tts failed: %s", message)


def export_danmu_read_config(config) -> dict[str, object]:
    from app.danmu_tts import MIMO_TTS_ENDPOINT, MIMO_TTS_MODEL

    key = config.get_tts_api_key()
    return {
        "enabled": danmu_read_enabled(config),
        "interval_sec": clamp_read_interval_sec(
            config.get("danmu_read_interval_sec", "10")
        ),
        "voice": normalize_tts_voice(config.get("tts_voice", "")),
        "style_prompt": config.get("tts_style_prompt", ""),
        "api_key": MASKED_API_KEY if key else "",
        "model": MIMO_TTS_MODEL,
        "endpoint": MIMO_TTS_ENDPOINT,
    }
