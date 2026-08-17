"""读弹幕：定时从屏上可见弹幕抽样 → MiMo TTS → 本地播放。

与 TTS 子系统的关系：
- 本模块是「读弹幕」业务编排；HTTP 合成在 ``_DanmuTtsRunnable`` 经 QThreadPool，
  WAV 字节经 ``_tts_ready`` Qt 信号回主线程。
- ``DanmuTtsPlayback`` 负责互斥播放；busy 期间 ``_on_tick`` 跳过新一轮。
- 抽样源是 ``app.engine.visible_display_texts()``，不修改主链路 ``add_text``。

配置入口：``danmu_read_enabled`` / ``tts_*`` 等键经 ``apply_config`` 写入；不经 ``PUT /api/config``。
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from app.application.config_service import MASKED_API_KEY
from app.danmu_tts_playback import DanmuTtsPlayback
from app.model_providers import normalize_endpoint
from app.translations import tr
from app.tts.config_credentials import (
    all_masked_tts_credentials,
    masked_tts_credentials,
    stored_tts_credentials,
)
from app.tts_providers import (
    MIMO_TTS_MODEL,
    TTS_PROBE_TEXT,
    TTS_PROVIDER_MIMO,
    DanmuTtsError,
    ResolvedTtsConfig,
    canonical_tts_provider_id,
    clamp_read_interval_sec,
    get_tts_manager,
    normalize_tts_voice,
    resolve_tts_config,
    synthesize_tts,
    validate_custom_tts_fields,
)

if TYPE_CHECKING:
    from main import DanmuApp


def _service_alive(service: "DanmuReadService | None") -> bool:
    if service is None or getattr(service, "_shutdown", False):
        return False
    try:
        from PyQt6 import sip

        return not sip.isdeleted(service)
    except ImportError:
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


def _normalize_tts_provider(value: object) -> str:
    raw = str(value or "").strip()
    if raw in ("", "mimo", TTS_PROVIDER_MIMO):
        return ""
    if raw == "custom_openai":
        raise ValueError(tr("tts.unsupportedCustom"))
    if get_tts_manager().catalog.get_provider(canonical_tts_provider_id(raw)) is not None:
        return raw
    raise ValueError(tr("tts.error.unsupportedPlatform").format(platform=raw))


def _stored_tts_credentials(config, provider: str) -> dict[str, str]:
    return stored_tts_credentials(config, provider)


def _masked_tts_credentials(config, provider: str) -> dict[str, str]:
    return masked_tts_credentials(config, provider)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _model_for_runtime(provider: str, model_id: str):
    canonical_provider = canonical_tts_provider_id(provider) or TTS_PROVIDER_MIMO
    from app.tts_providers import canonical_tts_model_id

    canonical_model = canonical_tts_model_id(canonical_provider, model_id)
    try:
        return get_tts_manager().catalog.require_model(canonical_provider, canonical_model)
    except (AttributeError, ValueError):
        return None


def _apply_supported_options(
    *,
    provider: str,
    model_id: str,
    style_prompt: str | None,
    emotion: str | None,
    speed: float | None,
    pitch: float | None,
    volume: float | None,
) -> dict[str, object]:
    """Drop stale hidden controls before a request reaches TtsManager."""

    model = _model_for_runtime(provider, model_id)
    if model is None:
        return {
            "style_prompt": style_prompt,
            "emotion": emotion,
            "speed": speed,
            "pitch": pitch,
            "volume": volume,
        }
    capabilities = model.capabilities
    return {
        "style_prompt": style_prompt if capabilities.style_prompt else None,
        "emotion": emotion if capabilities.emotion else None,
        "speed": speed if capabilities.speed else None,
        "pitch": pitch if capabilities.pitch else None,
        "volume": volume if capabilities.volume else None,
    }


class _DanmuTtsRunnable(QRunnable):
    def __init__(
        self,
        service: "DanmuReadService",
        *,
        text: str,
        api_key: str,
        voice: str,
        style_prompt: str,
        emotion: str | None = None,
        speed: float | None = None,
        pitch: float | None = None,
        volume: float | None = None,
        resolved: ResolvedTtsConfig,
        credentials: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._text = text
        self._api_key = api_key
        self._voice = voice
        self._style_prompt = style_prompt
        self._emotion = emotion
        self._speed = speed
        self._pitch = pitch
        self._volume = volume
        self._resolved = resolved
        self._credentials = dict(credentials or {})
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            wav = synthesize_tts(
                self._api_key,
                self._text,
                style_prompt=self._style_prompt,
                emotion=self._emotion,
                speed=self._speed,
                pitch=self._pitch,
                volume=self._volume,
                voice=self._voice,
                resolved=self._resolved,
                credentials=self._credentials,
            )
        except DanmuTtsError as exc:
            _emit_tts_failed(self._service, str(exc))
            return
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
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
        self._probe_pending = False
        self._last_text = ""
        self._skip_log_flags: set[str] = set()

    def shutdown(self) -> None:
        """退出前调用：停止定时器并忽略池线程迟到的 emit。"""
        self._shutdown = True
        self._timer.stop()
        self._tts_in_flight = False
        self._probe_pending = False

    def on_engine_started(self) -> None:
        config = self._app.config
        try:
            active_provider = resolve_tts_config(config).provider
        except ValueError:
            active_provider = TTS_PROVIDER_MIMO
        self._app.logger.info(
            "danmu read: engine start enabled=%s has_key=%s interval=%ss",
            danmu_read_enabled(config),
            bool(_stored_tts_credentials(config, active_provider)),
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
        interval_ms = clamp_read_interval_sec(
            config.get("danmu_read_interval_sec", "10")
        ) * 1000
        self._timer.setInterval(interval_ms)
        if not self._timer.isActive():
            self._timer.start()
            self._app.logger.info(
                "danmu read: timer started every %ss",
                clamp_read_interval_sec(
                    config.get("danmu_read_interval_sec", "10")
                ),
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
        provider = (
            _normalize_tts_provider(patch.get("provider", ""))
            if "provider" in patch
            else (config.get("tts_provider") or "").strip()
        )
        endpoint = (
            normalize_endpoint(str(patch.get("endpoint") or ""))
            if "endpoint" in patch
            else normalize_endpoint(config.get("tts_endpoint") or "")
        )
        model_id = (
            str(patch.get("model_id") or "").strip()
            if "model_id" in patch
            else (config.get("tts_model_id") or "").strip()
        )
        if "provider" in patch or "endpoint" in patch or "model_id" in patch:
            if provider == "custom_openai":
                raise ValueError(tr("tts.unsupportedCustom"))
            if endpoint:
                raise ValueError(tr("tts.unsupportedCustom"))
            if not provider and not endpoint and not model_id:
                items["tts_provider"] = ""
                items["tts_endpoint"] = ""
                items["tts_model_id"] = ""
            elif not provider and model_id:
                raise ValueError(tr("danmuRead.providerRequired"))
            else:
                validate_custom_tts_fields(provider, "", model_id)
                items["tts_provider"] = provider
                items["tts_endpoint"] = ""
                items["tts_model_id"] = model_id

        if "voice" in patch:
            eff_provider = items.get("tts_provider", config.get("tts_provider") or "")
            eff_model = items.get("tts_model_id", config.get("tts_model_id") or "")
            if not eff_provider and not eff_model:
                resolved_tmp = resolve_tts_config(config)
                eff_provider = resolved_tmp.provider
                eff_model = resolved_tmp.model
            items["tts_voice"] = normalize_tts_voice(
                str(patch.get("voice") or ""),
                provider=eff_provider or TTS_PROVIDER_MIMO,
                model_id=eff_model,
            )
        if "style_prompt" in patch:
            items["tts_style_prompt"] = str(patch.get("style_prompt", ""))
        if "emotion" in patch:
            items["tts_emotion"] = str(patch.get("emotion") or "")
        for field in ("speed", "pitch", "volume"):
            if field in patch:
                value = _optional_float(patch.get(field))
                items[f"tts_{field}"] = "" if value is None else str(value)

        effective_provider = items.get("tts_provider", provider) or TTS_PROVIDER_MIMO
        effective_model = items.get("tts_model_id", model_id)
        if not effective_model:
            try:
                effective_model = resolve_tts_config(config).model
            except ValueError:
                effective_model = MIMO_TTS_MODEL
        supported = _apply_supported_options(
            provider=str(effective_provider),
            model_id=str(effective_model),
            style_prompt=_optional_text(items.get("tts_style_prompt", config.get("tts_style_prompt", ""))),
            emotion=_optional_text(items.get("tts_emotion", config.get("tts_emotion", ""))),
            speed=_optional_float(items.get("tts_speed", config.get("tts_speed", ""))),
            pitch=_optional_float(items.get("tts_pitch", config.get("tts_pitch", ""))),
            volume=_optional_float(items.get("tts_volume", config.get("tts_volume", ""))),
        )
        items["tts_style_prompt"] = str(supported["style_prompt"] or "")
        items["tts_emotion"] = str(supported["emotion"] or "")
        for field in ("speed", "pitch", "volume"):
            value = supported[field]
            items[f"tts_{field}"] = "" if value is None else str(value)

        if items:
            config.set_batch(items)
        credential_provider = canonical_tts_provider_id(
            items.get("tts_provider") or provider or config.get("tts_provider") or ""
        ) or TTS_PROVIDER_MIMO
        api_key = patch.get("api_key")
        if isinstance(api_key, str):
            key = api_key.strip()
            if key and key != MASKED_API_KEY:
                config.set_tts_secret(credential_provider, "api_key", key)
        credentials = patch.get("credentials")
        if isinstance(credentials, Mapping):
            for field, value in credentials.items():
                if not isinstance(field, str) or not isinstance(value, str):
                    continue
                value = value.strip()
                if value and value != MASKED_API_KEY:
                    config.set_tts_secret(credential_provider, field, value)
        self._skip_log_flags.discard("no_key")
        self._sync_timer()
        try:
            is_custom = resolve_tts_config(config).is_custom
        except ValueError:
            is_custom = _export_use_custom_model(
                config.get("tts_provider") or "",
                config.get("tts_endpoint") or "",
                config.get("tts_model_id") or "",
            )
        try:
            saved_provider = resolve_tts_config(config).provider
        except ValueError:
            saved_provider = TTS_PROVIDER_MIMO
        self._app.logger.info(
            "danmu read: config saved enabled=%s interval=%ss has_key=%s custom=%s",
            danmu_read_enabled(config),
            config.get("danmu_read_interval_sec", "10"),
            bool(_stored_tts_credentials(config, saved_provider)),
            is_custom,
        )
        return export_danmu_read_config(config)

    def run_probe(
        self,
        *,
        api_key_override: str | None = None,
        provider_override: str | None = None,
        endpoint_override: str | None = None,
        model_id_override: str | None = None,
        voice_override: str | None = None,
        style_prompt_override: str | None = None,
        emotion_override: str | None = None,
        speed_override: float | None = None,
        pitch_override: float | None = None,
        volume_override: float | None = None,
        credentials_override: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        config = self._app.config
        if self._playback.is_busy() or self._tts_in_flight:
            return {"ok": False, "message": tr("danmuRead.busyProbe")}
        try:
            resolved = resolve_tts_config(
                config,
                provider_override=provider_override,
                endpoint_override=endpoint_override,
                model_id_override=model_id_override,
            )
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        credentials = dict(credentials_override or _stored_tts_credentials(config, resolved.provider))
        api_key = (api_key_override or "").strip() or credentials.get("api_key", "")
        if api_key:
            credentials["api_key"] = api_key
        if not api_key:
            return {"ok": False, "message": tr("danmuRead.fillApiKey")}
        voice = normalize_tts_voice(
            voice_override if voice_override is not None else config.get("tts_voice", ""),
            provider=resolved.provider,
            model_id=resolved.model,
        )
        style = (
            style_prompt_override
            if style_prompt_override is not None
            else config.get("tts_style_prompt", "")
        )
        options = _apply_supported_options(
            provider=resolved.provider,
            model_id=resolved.model,
            style_prompt=_optional_text(style),
            emotion=(
                _optional_text(emotion_override)
                if emotion_override is not None
                else _optional_text(config.get("tts_emotion", ""))
            ),
            speed=(
                speed_override
                if speed_override is not None
                else _optional_float(config.get("tts_speed", ""))
            ),
            pitch=(
                pitch_override
                if pitch_override is not None
                else _optional_float(config.get("tts_pitch", ""))
            ),
            volume=(
                volume_override
                if volume_override is not None
                else _optional_float(config.get("tts_volume", ""))
            ),
        )
        self._tts_in_flight = True
        self._probe_pending = True
        runnable = _DanmuTtsRunnable(
            self,
            text=TTS_PROBE_TEXT,
            api_key=api_key,
            voice=voice,
            style_prompt=str(options["style_prompt"] or ""),
            emotion=options["emotion"],
            speed=options["speed"],
            pitch=options["pitch"],
            volume=options["volume"],
            resolved=resolved,
            credentials=credentials,
        )
        QThreadPool.globalInstance().start(runnable)
        self._app.logger.info("danmu read: probe synthesis submitted")
        message = tr("danmuRead.probeSubmitted")
        if not danmu_read_enabled(config):
            message += tr("danmuRead.probeNotEnabledHint")
        return {"ok": True, "message": message}

    def _on_tick(self) -> None:
        app = self._app
        if not app.engine.running or not danmu_read_enabled(app.config):
            return
        if self._tts_in_flight or self._playback.is_busy():
            return
        texts = app.engine.visible_display_texts()
        if not texts:
            on_tracks = app.engine.current_display_count()
            visible_n = app.engine.visible_display_count()
            if on_tracks > 0:
                self._log_skip_once(
                    "no_visible_text",
                    tr("danmuRead.noVisibleText").format(on_tracks=on_tracks, visible_n=visible_n),
                )
            return
        candidates = [t for t in texts if t != self._last_text]
        if not candidates:
            return
        text = random.choice(candidates)
        self._last_text = text
        try:
            resolved = resolve_tts_config(app.config)
        except ValueError as exc:
            self._log_skip_once("bad_tts_config", tr("danmuRead.invalidTtsConfig").format(error=exc))
            return
        credentials = _stored_tts_credentials(app.config, resolved.provider)
        api_key = credentials.get("api_key", "")
        if not api_key:
            self._log_skip_once("no_key", tr("danmuRead.skipNoKey"))
            return
        voice = normalize_tts_voice(
            app.config.get("tts_voice", ""),
            provider=resolved.provider,
            model_id=resolved.model,
        )
        options = _apply_supported_options(
            provider=resolved.provider,
            model_id=resolved.model,
            style_prompt=_optional_text(app.config.get("tts_style_prompt", "")),
            emotion=_optional_text(app.config.get("tts_emotion", "")),
            speed=_optional_float(app.config.get("tts_speed", "")),
            pitch=_optional_float(app.config.get("tts_pitch", "")),
            volume=_optional_float(app.config.get("tts_volume", "")),
        )
        preview = text if len(text) <= 24 else f"{text[:24]}..."
        app.logger.info("danmu read: synthesizing %s", preview)
        self._tts_in_flight = True
        runnable = _DanmuTtsRunnable(
            self,
            text=text,
            api_key=api_key,
            voice=voice,
            style_prompt=str(options["style_prompt"] or ""),
            emotion=options["emotion"],
            speed=options["speed"],
            pitch=options["pitch"],
            volume=options["volume"],
            resolved=resolved,
            credentials=credentials,
        )
        QThreadPool.globalInstance().start(runnable)

    def _on_tts_ready(self, wav_bytes: bytes) -> None:
        if self._shutdown:
            return
        is_probe = self._probe_pending
        self._probe_pending = False
        if not is_probe and not self._app.engine.running:
            self._tts_in_flight = False
            self._app.logger.warning("danmu read: tts_ready dropped (engine stopped)")
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

    def _on_playback_finished(self, _playback_id: int = 0) -> None:
        self._tts_in_flight = False
        self._app.logger.debug("danmu read: playback finished")

    def _on_tts_failed(self, message: str) -> None:
        self._tts_in_flight = False
        self._probe_pending = False
        self._app.logger.warning("danmu read tts failed: %s", message)


def _export_use_custom_model(provider: str, endpoint: str, model_id: str) -> bool:
    from app.tts_providers import is_custom_tts_config

    try:
        return is_custom_tts_config(provider, endpoint, model_id)
    except ValueError:
        return False


def export_danmu_read_config(config) -> dict[str, object]:
    stored_provider = (config.get("tts_provider") or "").strip()
    stored_endpoint = normalize_endpoint(config.get("tts_endpoint") or "")
    stored_model_id = (config.get("tts_model_id") or "").strip()
    if stored_provider == "custom_openai":
        config.set_batch({"tts_provider": "", "tts_endpoint": ""})
        stored_provider = ""
        stored_endpoint = ""
    effective_provider = canonical_tts_provider_id(stored_provider) or TTS_PROVIDER_MIMO
    credentials = _masked_tts_credentials(config, effective_provider)
    try:
        resolved = resolve_tts_config(config)
    except ValueError:
        return {
            "enabled": danmu_read_enabled(config),
            "interval_sec": clamp_read_interval_sec(
                config.get("danmu_read_interval_sec", "10")
            ),
            "voice": normalize_tts_voice(config.get("tts_voice", "")),
            "style_prompt": config.get("tts_style_prompt", ""),
            "emotion": config.get("tts_emotion", ""),
            "speed": _optional_float(config.get("tts_speed", "")),
            "pitch": _optional_float(config.get("tts_pitch", "")),
            "volume": _optional_float(config.get("tts_volume", "")),
            "api_key": credentials.get("api_key", ""),
            "credentials": credentials,
            "provider_credentials": all_masked_tts_credentials(config),
            "provider": stored_provider,
            "custom_endpoint": stored_endpoint,
            "custom_model_id": stored_model_id,
            "model_id": stored_model_id,
            "model": stored_model_id or MIMO_TTS_MODEL,
            "endpoint": stored_endpoint,
            "use_custom_model": _export_use_custom_model(
                stored_provider, stored_endpoint, stored_model_id
            ),
        }
    credentials = _masked_tts_credentials(config, resolved.provider)
    return {
        "enabled": danmu_read_enabled(config),
        "interval_sec": clamp_read_interval_sec(
            config.get("danmu_read_interval_sec", "10")
        ),
        "voice": normalize_tts_voice(
            config.get("tts_voice", ""),
            provider=resolved.provider,
            model_id=resolved.model,
        ),
        "style_prompt": config.get("tts_style_prompt", ""),
        "emotion": config.get("tts_emotion", ""),
        "speed": _optional_float(config.get("tts_speed", "")),
        "pitch": _optional_float(config.get("tts_pitch", "")),
        "volume": _optional_float(config.get("tts_volume", "")),
        "api_key": credentials.get("api_key", ""),
        "credentials": credentials,
        "provider_credentials": all_masked_tts_credentials(config),
        "provider": stored_provider,
        "custom_endpoint": stored_endpoint,
        "custom_model_id": stored_model_id,
        "model_id": stored_model_id,
        "model": resolved.model,
        "endpoint": resolved.endpoint,
        "use_custom_model": resolved.is_custom,
    }
