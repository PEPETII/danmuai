"""读弹幕 TTS provider 注册表与适配层（MiMo 默认 + 百炼）。

MiMo TTS + 播放链路：
1. ``DanmuReadService._pick_and_synthesize`` 抽样一条可见弹幕 → ``resolve_tts_config``。
2. ``synthesize_tts`` 按 ``resolved.provider`` 选 adapter（mimo / dashscope_qwen）。
3. 响应音频 → ``DanmuTtsPlayback.play_wav_bytes``。

新增 provider：实现 ``TtsSynthesisAdapter`` 子类并注册到 ``_ADAPTERS``；不需改主链路。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

import httpx

from app.ai_client_support import extract_http_error_message
from app.errors import TtsError
from app.model_providers import normalize_endpoint
from app.translations import tr
from app.tts.audio import normalize_tts_result
from app.tts.catalog import TtsCatalog as V2TtsCatalog
from app.tts.manager import TtsManager
from app.tts.providers.dashscope import DashScopeProvider
from app.tts.providers.doubao import DoubaoProvider
from app.tts.providers.mimo import MimoProvider
from app.tts.providers.minimax import MiniMaxProvider
from app.tts.registry import ProviderRegistry
from app.tts.types import TtsAuthError, TtsRequest
from app.tts_audio_utils import ensure_wav_bytes, pcm_to_wav

logger = logging.getLogger(__name__)

MIMO_TTS_ENDPOINT = "https://api.xiaomimimo.com/v1"
MIMO_TTS_MODEL = "mimo-v2.5-tts"
MIMO_TTS_VOICES: tuple[str, ...] = (
    "mimo_default",
    "冰糖",
    "茉莉",
    "苏打",
    "白桦",
    "Mia",
    "Chloe",
    "Milo",
    "Dean",
)
DEFAULT_TTS_VOICE = "冰糖"
TTS_PROBE_TEXT = tr("tts.probeText")

TTS_PROVIDER_MIMO = "mimo"
TTS_PROVIDER_DASHSCOPE_QWEN = "dashscope_qwen"
TTS_PROVIDER_DASHSCOPE = "dashscope"
TTS_PROVIDER_MINIMAX = "minimax"
TTS_PROVIDER_DOUBAO = "doubao"
_LEGACY_TTS_CUSTOM_OPENAI = "custom_openai"
_LEGACY_TTS_DOUBAO = TTS_PROVIDER_DOUBAO

_UNSUPPORTED_CUSTOM_TTS_MSG = tr("tts.unsupportedCustom")
_UNSUPPORTED_DOUBAO_TTS_MSG = tr("tts.unsupportedDoubao")

_PRESET_TTS_PROVIDERS = frozenset(
    {
        TTS_PROVIDER_MIMO,
        TTS_PROVIDER_DASHSCOPE,
        TTS_PROVIDER_DASHSCOPE_QWEN,
        TTS_PROVIDER_MINIMAX,
        TTS_PROVIDER_DOUBAO,
    }
)
_NON_MIMO_PRESET_PROVIDERS = _PRESET_TTS_PROVIDERS - {TTS_PROVIDER_MIMO}

_TTS_PROVIDER_ALIASES = {
    TTS_PROVIDER_DASHSCOPE_QWEN: TTS_PROVIDER_DASHSCOPE,
    TTS_PROVIDER_MIMO: TTS_PROVIDER_MIMO,
    TTS_PROVIDER_DASHSCOPE: TTS_PROVIDER_DASHSCOPE,
    TTS_PROVIDER_MINIMAX: TTS_PROVIDER_MINIMAX,
    TTS_PROVIDER_DOUBAO: TTS_PROVIDER_DOUBAO,
}

_TTS_MODEL_ALIASES = {
    "qwen3-tts-flash-2025-11-27": "qwen3-tts-flash",
    "mimo-v2-tts": "mimo-v2.5-tts",
    "speech-2.6-turbo": "speech-2.8-turbo",
    "speech-02-turbo": "speech-2.8-turbo",
    "speech-2.6-hd": "speech-2.8-hd",
    "speech-02-hd": "speech-2.8-hd",
}


def _reject_removed_doubao_tts(provider: str) -> None:
    """Retained as a compatibility symbol; Doubao is a supported provider."""
    del provider


def canonical_tts_provider_id(provider_id: str | None) -> str:
    raw = (provider_id or "").strip().lower()
    return _TTS_PROVIDER_ALIASES.get(raw, raw)


def canonical_tts_model_id(provider_id: str, model_id: str) -> str:
    del provider_id
    raw = (model_id or "").strip()
    return _TTS_MODEL_ALIASES.get(raw, raw)


DanmuTtsError = TtsError


def tts_audio_unsupported_message(model_id: str) -> str:
    """读弹幕为 TTS 链路；普通 chat 模型响应无 message.audio.data 时提示用户。"""
    mid = (model_id or "").strip() or "?"
    return tr("tts.unsupportedProvider").format(model_id=mid)


def normalize_tts_voice(
    voice: str | None,
    *,
    provider: str = TTS_PROVIDER_MIMO,
    model_id: str = "",
) -> str:
    pid = canonical_tts_provider_id(provider) or TTS_PROVIDER_MIMO
    raw = (voice or "").strip()
    if pid == TTS_PROVIDER_MIMO and not model_id:
        return raw if raw in MIMO_TTS_VOICES else DEFAULT_TTS_VOICE

    # Keep the legacy catalog import and its alias-specific voice contract.
    # The old catalog deliberately remains outside the V2 composition root.
    if (provider or "").strip() == TTS_PROVIDER_DASHSCOPE_QWEN:
        from app.tts_catalog import normalize_catalog_voice

        return normalize_catalog_voice(
            raw,
            provider_id=TTS_PROVIDER_DASHSCOPE_QWEN,
            model_id=model_id or "qwen3-tts-flash-2025-11-27",
        )
    if pid == TTS_PROVIDER_MIMO:
        from app.tts_catalog import normalize_catalog_voice

        return normalize_catalog_voice(
            raw,
            provider_id=TTS_PROVIDER_MIMO,
            model_id=model_id or MIMO_TTS_MODEL,
        )

    try:
        model = get_tts_manager().catalog.require_model(
            pid,
            canonical_tts_model_id(pid, model_id),
        )
    except (AttributeError, ValueError):
        return raw or DEFAULT_TTS_VOICE
    voice_ids = {voice_item.id for voice_item in model.voices}
    if raw in voice_ids:
        return raw
    if model.voices:
        return model.voices[0].id
    return raw or DEFAULT_TTS_VOICE


def clamp_read_interval_sec(value: object, *, default: int = 10) -> int:
    try:
        sec = int(value)
    except (TypeError, ValueError):
        sec = default
    return max(3, min(sec, 120))


@dataclass(frozen=True)
class TtsProviderSpec:
    id: str
    label_zh: str
    default_endpoint: str
    default_model: str


TTS_PROVIDERS: tuple[TtsProviderSpec, ...] = (
    TtsProviderSpec(
        id=TTS_PROVIDER_MIMO,
        label_zh="小米 MiMo（默认）",
        default_endpoint=MIMO_TTS_ENDPOINT,
        default_model=MIMO_TTS_MODEL,
    ),
    TtsProviderSpec(
        id=TTS_PROVIDER_DASHSCOPE,
        label_zh="阿里百炼 Qwen3",
        default_endpoint="https://dashscope.aliyuncs.com/api/v1",
        default_model="qwen3-tts-flash",
    ),
    TtsProviderSpec(
        id=TTS_PROVIDER_DASHSCOPE_QWEN,
        label_zh="阿里百炼 Qwen3",
        default_endpoint="https://dashscope.aliyuncs.com/api/v1",
        default_model="qwen3-tts-flash-2025-11-27",
    ),
    TtsProviderSpec(
        id=TTS_PROVIDER_MINIMAX,
        label_zh="MiniMax",
        default_endpoint="https://api.minimaxi.com/v1",
        default_model="speech-2.8-turbo",
    ),
    TtsProviderSpec(
        id=TTS_PROVIDER_DOUBAO,
        label_zh="火山引擎豆包",
        default_endpoint="https://openspeech.bytedance.com/api/v3/tts/unidirectional",
        default_model="seed-tts-2.0",
    ),
)

_TTS_PROVIDER_BY_ID = {p.id: p for p in TTS_PROVIDERS}


@dataclass(frozen=True)
class ResolvedTtsConfig:
    provider: str
    endpoint: str
    model: str
    is_custom: bool
    stored_provider: str
    stored_endpoint: str
    stored_model_id: str


def get_tts_provider(provider_id: str) -> TtsProviderSpec | None:
    raw = (provider_id or "").strip()
    return _TTS_PROVIDER_BY_ID.get(raw) or _TTS_PROVIDER_BY_ID.get(
        canonical_tts_provider_id(raw)
    )


class _LegacyCompatibleMimoProvider(MimoProvider):
    """Accept the legacy httpx test-double shape at this bridge boundary."""

    def _raise_http_error(self, response) -> None:
        if hasattr(response, "is_error"):
            super()._raise_http_error(response)
            return
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()


def _build_v2_registry() -> ProviderRegistry:
    providers = (
        _LegacyCompatibleMimoProvider(),
        DashScopeProvider(),
        MiniMaxProvider(),
        DoubaoProvider(),
    )
    return ProviderRegistry(providers)


def _build_v2_manager(registry: ProviderRegistry | None = None) -> TtsManager:
    registry = registry or _build_v2_registry()
    return TtsManager(
        registry,
        V2TtsCatalog([provider.descriptor for provider in registry]),
    )


_TTS_V2_MANAGER: TtsManager | None = None
_TTS_V2_REGISTRY: ProviderRegistry | None = None


def get_tts_registry() -> ProviderRegistry:
    """Return the process-local registry containing all V2 TTS providers."""
    global _TTS_V2_REGISTRY
    if _TTS_V2_REGISTRY is None:
        _TTS_V2_REGISTRY = _build_v2_registry()
    return _TTS_V2_REGISTRY


def get_tts_manager() -> TtsManager:
    """Return the process-local V2 registry/manager composition root."""
    global _TTS_V2_MANAGER
    if _TTS_V2_MANAGER is None:
        _TTS_V2_MANAGER = _build_v2_manager(get_tts_registry())
    return _TTS_V2_MANAGER


def get_tts_v2_descriptors():
    return get_tts_manager().registry.descriptors()


def _stored_custom_fields(config) -> tuple[str, str, str]:
    provider = (config.get("tts_provider") or "").strip()
    endpoint = normalize_endpoint(config.get("tts_endpoint") or "")
    model_id = (config.get("tts_model_id") or "").strip()
    return provider, endpoint, model_id


def _reject_legacy_custom_tts(provider: str, endpoint: str) -> None:
    pid = (provider or "").strip()
    if pid == _LEGACY_TTS_CUSTOM_OPENAI:
        raise ValueError(_UNSUPPORTED_CUSTOM_TTS_MSG)
    if pid and canonical_tts_provider_id(pid) not in {
        TTS_PROVIDER_MIMO,
        TTS_PROVIDER_DASHSCOPE,
        TTS_PROVIDER_MINIMAX,
        TTS_PROVIDER_DOUBAO,
    }:
        raise ValueError(tr("tts.error.unsupportedPlatform").format(platform=pid))
    if (endpoint or "").strip() and not pid:
        raise ValueError(_UNSUPPORTED_CUSTOM_TTS_MSG)


def is_custom_tts_config(provider: str, endpoint: str, model_id: str) -> bool:
    _reject_legacy_custom_tts(provider, endpoint)
    del model_id
    return canonical_tts_provider_id(provider) in {
        TTS_PROVIDER_DASHSCOPE,
        TTS_PROVIDER_MINIMAX,
        TTS_PROVIDER_DOUBAO,
    }


def validate_custom_tts_fields(
    provider: str,
    endpoint: str,
    model_id: str,
) -> None:
    """按 provider 校验 TTS 配置字段。"""
    pid = (provider or "").strip()
    _reject_legacy_custom_tts(pid, endpoint)
    canonical = canonical_tts_provider_id(pid)
    if not canonical:
        return
    spec = get_tts_provider(canonical)
    if spec is None:
        raise ValueError(tr("tts.error.unsupportedPlatform").format(platform=pid))
    selected_model = canonical_tts_model_id(canonical, model_id) or spec.default_model
    try:
        model = get_tts_manager().catalog.require_model(canonical, selected_model)
        if model.status != "active":
            raise ValueError(
                tr("tts.error.unsupportedModel").format(model=selected_model)
            )
    except (AttributeError, ValueError) as exc:
        raise ValueError(tr("tts.error.unsupportedModel").format(model=selected_model)) from exc


def resolve_tts_config(
    config,
    *,
    provider_override: str | None = None,
    endpoint_override: str | None = None,
    model_id_override: str | None = None,
) -> ResolvedTtsConfig:
    stored_provider, stored_endpoint, stored_model_id = _stored_custom_fields(config)
    provider = (provider_override if provider_override is not None else stored_provider).strip()
    endpoint = normalize_endpoint(
        endpoint_override if endpoint_override is not None else stored_endpoint
    )
    model_id = (
        (model_id_override if model_id_override is not None else stored_model_id) or ""
    ).strip()
    _reject_legacy_custom_tts(provider, endpoint)
    canonical = canonical_tts_provider_id(provider)

    if not canonical:
        default = get_tts_provider(TTS_PROVIDER_MIMO)
        assert default is not None
        return ResolvedTtsConfig(
            provider=TTS_PROVIDER_MIMO,
            endpoint=default.default_endpoint,
            model=default.default_model,
            is_custom=False,
            stored_provider="",
            stored_endpoint="",
            stored_model_id="",
        )

    spec = get_tts_provider(canonical)
    if spec is None:
        raise ValueError(tr("tts.error.unsupportedPlatform").format(platform=provider))
    resolved_model = model_id or spec.default_model
    canonical_model = canonical_tts_model_id(canonical, resolved_model)
    try:
        model = get_tts_manager().catalog.require_model(canonical, canonical_model)
    except (AttributeError, ValueError) as exc:
        raise ValueError(tr("tts.error.unsupportedModel").format(model=resolved_model)) from exc
    if model.status != "active":
        # A previously saved catalog-only/historical value must not make the
        # runtime unusable. Explicit new selections are rejected by
        # validate_custom_tts_fields; only an existing stored value reaches
        # this compatibility fallback.
        if model_id_override is not None:
            raise ValueError(tr("tts.error.unsupportedModel").format(model=resolved_model))
        provider_descriptor = get_tts_manager().catalog.require_provider(canonical)
        fallback = next(
            (candidate for candidate in provider_descriptor.models if candidate.status == "active"),
            None,
        )
        if fallback is None:
            raise ValueError(tr("tts.error.unsupportedModel").format(model=resolved_model))
        resolved_model = fallback.id
    return ResolvedTtsConfig(
        provider=provider or canonical,
        endpoint=spec.default_endpoint,
        model=resolved_model,
        is_custom=canonical != TTS_PROVIDER_MIMO,
        stored_provider=provider,
        stored_endpoint="",
        stored_model_id=resolved_model,
    )


class TtsSynthesisAdapter(Protocol):
    def synthesize(
        self,
        api_key: str,
        text: str,
        *,
        resolved: ResolvedTtsConfig,
        style_prompt: str = "",
        voice: str = DEFAULT_TTS_VOICE,
        timeout_sec: float = 60.0,
    ) -> bytes:
        ...


def _build_chat_audio_payload(
    resolved: ResolvedTtsConfig,
    text: str,
    *,
    style_prompt: str,
    voice: str,
    normalize_voice: bool,
) -> dict[str, Any]:
    content = (text or "").strip()
    if not content:
        raise DanmuTtsError(tr("tts.error.emptyText"))

    messages: list[dict[str, str]] = []
    style = (style_prompt or "").strip()
    if style:
        messages.append({"role": "user", "content": style})
    messages.append({"role": "assistant", "content": content})

    voice_value = (
        normalize_tts_voice(voice, provider=resolved.provider, model_id=resolved.model)
        if normalize_voice
        else (voice or DEFAULT_TTS_VOICE).strip()
    )
    return {
        "model": resolved.model,
        "messages": messages,
        "audio": {"format": "wav", "voice": voice_value},
    }


def _post_chat_audio(
    api_key: str,
    resolved: ResolvedTtsConfig,
    payload: dict[str, Any],
    *,
    timeout_sec: float,
) -> bytes:
    key = (api_key or "").strip()
    if not key:
        raise DanmuTtsError(tr("tts.error.noApiKey"))

    url = f"{resolved.endpoint.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=10.0)) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
    except httpx.TimeoutException as exc:
        raise DanmuTtsError(tr("tts.error.timeout")) from exc
    except httpx.HTTPStatusError as exc:
        detail = extract_http_error_message(exc)
        code = exc.response.status_code
        raise DanmuTtsError(detail or f"TTS HTTP {code}") from exc
    except httpx.HTTPError as exc:
        raise DanmuTtsError(tr("tts.error.network").format(error=exc)) from exc

    try:
        return _decode_audio_wav_from_body(body, model_id=resolved.model)
    except DanmuTtsError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.debug("tts response parse failed: %s", exc)
        raise DanmuTtsError(tr("tts.error.parseFailed")) from exc


def _decode_audio_wav_from_body(body: dict[str, Any], *, model_id: str) -> bytes:
    """解析 chat/completions 响应中的 base64 WAV；文本-only 响应给出 TTS 能力提示。"""
    choices = body.get("choices") or []
    if not choices:
        raise DanmuTtsError(tr("tts.error.noAudioData"))
    message = choices[0].get("message") or {}
    audio = message.get("audio") or {}
    data_b64 = audio.get("data") or ""
    if data_b64:
        return base64.b64decode(data_b64)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        raise DanmuTtsError(tts_audio_unsupported_message(model_id))
    raise DanmuTtsError(tr("tts.error.noAudioData"))


class MimoTtsAdapter:
    def synthesize(
        self,
        api_key: str,
        text: str,
        *,
        resolved: ResolvedTtsConfig,
        style_prompt: str = "",
        voice: str = DEFAULT_TTS_VOICE,
        timeout_sec: float = 60.0,
    ) -> bytes:
        payload = _build_chat_audio_payload(
            resolved,
            text,
            style_prompt=style_prompt,
            voice=voice,
            normalize_voice=True,
        )
        return _post_chat_audio(api_key, resolved, payload, timeout_sec=timeout_sec)


class QwenTtsHttpAdapter:
    """百炼 Qwen3 非实时 HTTP TTS。"""

    def synthesize(
        self,
        api_key: str,
        text: str,
        *,
        resolved: ResolvedTtsConfig,
        style_prompt: str = "",
        voice: str = DEFAULT_TTS_VOICE,
        timeout_sec: float = 60.0,
    ) -> bytes:
        key = (api_key or "").strip()
        if not key:
            raise DanmuTtsError(tr("tts.error.bailianNoApiKey"))
        try:
            import dashscope
            from dashscope import MultiModalConversation
        except ImportError as exc:
            raise DanmuTtsError(tr("tts.error.dashscopeMissing")) from exc

        dashscope.api_key = key
        voice_id = normalize_tts_voice(
            voice, provider=TTS_PROVIDER_DASHSCOPE_QWEN, model_id=resolved.model
        )
        content = (text or "").strip()
        if not content:
            raise DanmuTtsError(tr("tts.error.emptyText"))

        try:
            response = MultiModalConversation.call(
                model=resolved.model,
                api_key=key,
                text=content,
                voice=voice_id,
                language_type="Chinese",
                stream=False,
            )
        except (ImportError, AttributeError, TypeError, ValueError, OSError) as exc:
            raise DanmuTtsError(tr("tts.error.bailianRequestFailed").format(error=exc)) from exc

        if getattr(response, "status_code", None) != 200:
            code = getattr(response, 'status_code', '?')
            raise DanmuTtsError(
                getattr(response, "message", None)
                or tr("tts.error.bailianHttpError").format(code=code)
            )

        output = getattr(response, "output", None) or {}
        audio = output.get("audio") if isinstance(output, dict) else getattr(output, "audio", None)
        if not audio:
            raise DanmuTtsError(tr("tts.error.bailianNoAudio"))

        url = audio.get("url") if isinstance(audio, dict) else getattr(audio, "url", "")
        if url:
            try:
                with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=10.0)) as client:
                    r = client.get(url)
                    r.raise_for_status()
                    return ensure_wav_bytes(r.content)
            except httpx.HTTPError as exc:
                raise DanmuTtsError(tr("tts.error.bailianDownloadFailed").format(error=exc)) from exc

        data_b64 = audio.get("data") if isinstance(audio, dict) else getattr(audio, "data", "")
        if data_b64:
            return ensure_wav_bytes(base64.b64decode(data_b64))
        raise DanmuTtsError(tr("tts.error.bailianNoAudioUrl"))


class QwenTtsRealtimeAdapter:
    """百炼 Qwen3 实时 WebSocket TTS（整句提交）。"""

    def synthesize(
        self,
        api_key: str,
        text: str,
        *,
        resolved: ResolvedTtsConfig,
        style_prompt: str = "",
        voice: str = DEFAULT_TTS_VOICE,
        timeout_sec: float = 60.0,
    ) -> bytes:
        import time

        key = (api_key or "").strip()
        if not key:
            raise DanmuTtsError(tr("tts.error.bailianNoApiKey"))
        content = (text or "").strip()
        if not content:
            raise DanmuTtsError(tr("tts.error.emptyText"))

        try:
            import dashscope
            from dashscope.audio.qwen_tts_realtime import (
                AudioFormat,
                QwenTtsRealtime,
                QwenTtsRealtimeCallback,
            )
        except ImportError as exc:
            raise DanmuTtsError(tr("tts.error.dashscopeMissing")) from exc

        from app.tts_catalog import model_supports_style

        dashscope.api_key = key
        voice_id = normalize_tts_voice(
            voice, provider=TTS_PROVIDER_DASHSCOPE_QWEN, model_id=resolved.model
        )
        pcm_chunks: list[bytes] = []
        state = {"closed": False, "error": ""}

        class _Cb(QwenTtsRealtimeCallback):
            def on_open(self) -> None:
                pass

            def on_close(self, close_status_code, close_msg) -> None:
                state["closed"] = True

            def on_event(self, response: dict) -> None:
                typ = response.get("type", "")
                if typ == "response.audio.delta":
                    delta = response.get("delta", "")
                    if delta:
                        pcm_chunks.append(base64.b64decode(delta))
                elif typ == "error":
                    state["error"] = str(response.get("error", response))

        callback = _Cb()
        client = QwenTtsRealtime(
            model=resolved.model,
            callback=callback,
            url="wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
        )
        session_kwargs: dict[str, Any] = {
            "voice": voice_id,
            "response_format": AudioFormat.PCM_24000HZ_MONO_16BIT,
            "mode": "server_commit",
        }
        style = (style_prompt or "").strip()
        if style and model_supports_style(TTS_PROVIDER_DASHSCOPE_QWEN, resolved.model):
            session_kwargs["instructions"] = style
            session_kwargs["optimize_instructions"] = True

        try:
            client.connect()
            client.update_session(**session_kwargs)
            client.append_text(content)
            client.finish()
            t0 = time.perf_counter()
            while not state["closed"] and (time.perf_counter() - t0) < timeout_sec:
                time.sleep(0.05)
        except (ImportError, AttributeError, TypeError, ValueError, OSError) as exc:
            raise DanmuTtsError(tr("tts.error.bailianRealtimeFailed").format(error=exc)) from exc

        if state["error"]:
            raise DanmuTtsError(state["error"])
        if not pcm_chunks:
            raise DanmuTtsError(tr("tts.error.bailianRealtimeNoAudio"))
        return pcm_to_wav(b"".join(pcm_chunks))


_ADAPTERS: dict[str, TtsSynthesisAdapter] = {
    TTS_PROVIDER_MIMO: MimoTtsAdapter(),
    TTS_PROVIDER_DASHSCOPE_QWEN: QwenTtsHttpAdapter(),
}


def get_qwen_tts_adapter(model_id: str) -> TtsSynthesisAdapter:
    if (model_id or "").endswith("-realtime"):
        return QwenTtsRealtimeAdapter()
    return QwenTtsHttpAdapter()


def get_tts_adapter(provider_id: str, *, model_id: str = "") -> TtsSynthesisAdapter:
    pid = (provider_id or "").strip()
    if pid == TTS_PROVIDER_DASHSCOPE_QWEN:
        return get_qwen_tts_adapter(model_id)
    adapter = _ADAPTERS.get(pid)
    if adapter is not None:
        return adapter
    raise ValueError(tr("tts.error.unsupportedPlatform").format(platform=pid or '?'))


def synthesize_tts(
    api_key: str,
    text: str,
    *,
    resolved: ResolvedTtsConfig,
    style_prompt: str = "",
    voice: str = DEFAULT_TTS_VOICE,
    emotion: str | None = None,
    speed: float | None = None,
    pitch: float | None = None,
    volume: float | None = None,
    timeout_sec: float = 60.0,
    credentials: Mapping[str, str] | None = None,
) -> bytes:
    canonical_provider = canonical_tts_provider_id(resolved.provider)
    canonical_model = canonical_tts_model_id(canonical_provider, resolved.model)
    manager = get_tts_manager()
    is_v2_model = False
    try:
        manager.catalog.require_model(canonical_provider, canonical_model)
        is_v2_model = True
    except (AttributeError, ValueError):
        pass

    if is_v2_model:
        request_format = (
            "mp3"
            if canonical_provider in {TTS_PROVIDER_MINIMAX, TTS_PROVIDER_DOUBAO}
            else "wav"
        )
        request = TtsRequest(
            text=text,
            provider_id=canonical_provider,
            model_id=canonical_model,
            voice_id=(voice or "").strip() or None,
            style_prompt=(style_prompt or "").strip() or None,
            emotion=(emotion or "").strip() or None,
            speed=speed,
            pitch=pitch,
            volume=volume,
            output_format=request_format,
        )
        provider_credentials = dict(credentials or {})
        if api_key and "api_key" not in provider_credentials:
            provider_credentials["api_key"] = api_key
        try:
            result = manager.synthesize(
                request,
                credentials=provider_credentials,
                timeout_sec=timeout_sec,
            )
            normalized = normalize_tts_result(result)
        except DanmuTtsError:
            raise
        except TtsAuthError as exc:
            if "api_key" in str(exc).lower() and not provider_credentials.get("api_key"):
                raise DanmuTtsError(tr("tts.error.noApiKey")) from exc
            raise DanmuTtsError(str(exc)) from exc
        except Exception as exc:
            # Keep the old public exception type at this compatibility seam;
            # the V2 error taxonomy remains available on the manager itself.
            raise DanmuTtsError(str(exc)) from exc
        return normalized.audio_bytes

    # Legacy model IDs remain readable for one compatibility cycle.  New
    # provider/model combinations must go through the V2 registry above.
    adapter = get_tts_adapter(resolved.provider, model_id=resolved.model)
    return adapter.synthesize(
        api_key,
        text,
        resolved=resolved,
        style_prompt=style_prompt,
        voice=voice,
        timeout_sec=timeout_sec,
    )
