"""MiniMax synchronous T2A v2 provider.

The adapter deliberately contains only MiniMax protocol details.  Catalog
composition and request orchestration remain owned by the shared TTS v2
framework.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

import httpx
from app.tts.providers.base import BaseTtsProvider
from app.tts.types import (
    AuthDescriptor,
    AuthFieldDescriptor,
    ModelDescriptor,
    PricingDescriptor,
    ProviderDescriptor,
    TtsAudioDecodeError,
    TtsAuthError,
    TtsCapabilities,
    TtsConfigurationError,
    TtsInvalidVoiceError,
    TtsProviderNetworkError,
    TtsProviderResponseError,
    TtsQuotaError,
    TtsRateLimitError,
    TtsRequest,
    TtsResult,
    TtsUnsupportedCapabilityError,
    VoiceDescriptor,
    VoiceSource,
)

MINIMAX_PROVIDER_ID = "minimax"
MINIMAX_T2A_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
MINIMAX_GET_VOICE_ENDPOINT = "https://api.minimaxi.com/v1/get_voice"
MINIMAX_RECOMMENDED_VOICES = (
    "Chinese (Mandarin)_BashfulGirl",
    "Chinese (Mandarin)_Mature_Woman",
    "Chinese_worker_female",
    "Chinese (Mandarin)_Warm_Bestie",
    "Chinese (Mandarin)_Sweet_Lady",
    "Chinese_crisp_podcaster_nv1",
    "Chinese (Mandarin)_IntellectualGirl",
    "Chinese (Mandarin)_Warm_HeartedGirl",
    "Chinese (Mandarin)_ExplorativeGirl",
)
MINIMAX_DEFAULT_VOICE = MINIMAX_RECOMMENDED_VOICES[0]
MINIMAX_PRICING_SOURCE_URL = "https://platform.minimaxi.com/docs/guides/pricing-paygo"
MINIMAX_VOICE_SOURCE_URL = "https://platform.minimaxi.com/docs/api-reference/voice-management-get"
MINIMAX_VERIFIED_AT = "2026-08-17"
MINIMAX_EMOTIONS = frozenset(
    {"happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm", "whipser"}
)

MINIMAX_CURRENT_MODELS = ("speech-2.8-turbo", "speech-2.8-hd")
MINIMAX_HISTORICAL_MODELS = (
    "speech-2.6-turbo",
    "speech-2.6-hd",
    "speech-02-turbo",
    "speech-02-hd",
)

_MINIMAX_AUDIO_FORMAT = "wav"
_MINIMAX_OUTPUT_FORMAT = "hex"
_MINIMAX_CAPABILITIES = TtsCapabilities(
    emotion=True,
    speed=True,
    pitch=True,
    volume=True,
    voice_list=True,
    custom_voice_id=True,
    voice_clone=True,
    voice_design=True,
    output_formats=frozenset({_MINIMAX_AUDIO_FORMAT}),
    notes=(
        "voice_setting 参数：speed 范围 0.5–2.0，pitch 范围 -12–12，vol 默认 1.0；官方未公布 vol 的数值边界。",
        "emotion 使用官方枚举；Speech 2.8/2.6/02 支持语气词标签，普通 T2A 没有独立 style_prompt 参数。",
        "官方支持 HTTP stream=true 与 WebSocket；当前 DanmuAI 单句播放适配器使用非流式 WAV。",
    ),
)


def _fallback_voices() -> tuple[VoiceDescriptor, ...]:
    # Official static system voices are the no-credential fallback.  The
    # account-scoped get_voice response can replace/enrich this list later.
    return tuple(
        VoiceDescriptor(
            id=voice_id,
            name=voice_id,
            description=None,
            gender=None,
            age_group="adult",
            languages=("zh-CN",),
            tags=("官方系统音色", "推荐1"),
            source=VoiceSource.STATIC_CATALOG,
        )
        for voice_id in MINIMAX_RECOMMENDED_VOICES
    )


def _pricing(model_id: str) -> PricingDescriptor:
    amount = 3.5 if model_id.endswith("-hd") else 2.0
    return PricingDescriptor(
        kind="paygo",
        currency="CNY",
        amount=amount,
        unit="10k_chars",
        display=f"¥{amount:g} / 1万字符",
        note=(
            "同步/异步 T2A 按输入字符计费；中文字符按官方字符规则折算。"
            "Voice Design/Cloning 创建音色为 9.9 元/个，试听按 2 元/万字符。"
        ),
        verified_at=MINIMAX_VERIFIED_AT,
        source=MINIMAX_PRICING_SOURCE_URL,
        source_url=MINIMAX_PRICING_SOURCE_URL,
    )


def _model_descriptor(model_id: str, *, historical: bool = False) -> ModelDescriptor:
    replacement_model_id = {
        "speech-2.6-turbo": "speech-2.8-turbo",
        "speech-02-turbo": "speech-2.8-turbo",
        "speech-2.6-hd": "speech-2.8-hd",
        "speech-02-hd": "speech-2.8-hd",
    }.get(model_id)
    return ModelDescriptor(
        id=model_id,
        label={
            "speech-2.8-turbo": "Speech 2.8 Turbo",
            "speech-2.8-hd": "Speech 2.8 HD",
            "speech-2.6-turbo": "Speech 2.6 Turbo（历史）",
            "speech-2.6-hd": "Speech 2.6 HD（历史）",
            "speech-02-turbo": "Speech 02 Turbo（历史）",
            "speech-02-hd": "Speech 02 HD（历史）",
        }.get(model_id, model_id),
        recommended=model_id == "speech-2.8-turbo",
        tags=("historical",) if historical else ("current",),
        transport="http",
        capabilities=_MINIMAX_CAPABILITIES,
        pricing=_pricing(model_id),
        voices=_fallback_voices(),
        status="historical" if historical else "active",
        replacement_model_id=replacement_model_id,
    )


def _descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        id=MINIMAX_PROVIDER_ID,
        label="MiniMax",
        auth=AuthDescriptor(
            fields=(
                AuthFieldDescriptor(
                    id="api_key",
                    label="MiniMax API Key",
                    placeholder="Enter MiniMax API Key",
                ),
            )
        ),
        models=tuple(
            _model_descriptor(model_id)
            for model_id in MINIMAX_CURRENT_MODELS
        )
        + tuple(
            _model_descriptor(model_id, historical=True)
            for model_id in MINIMAX_HISTORICAL_MODELS
        ),
    )


def _trace_id(body: Mapping[str, Any]) -> str | None:
    value = body.get("trace_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _status_message(body: Mapping[str, Any]) -> str:
    base_resp = body.get("base_resp")
    if not isinstance(base_resp, Mapping):
        return ""
    message = base_resp.get("status_msg")
    return message.strip() if isinstance(message, str) else ""


def _vendor_error(body: Mapping[str, Any]) -> type[Exception] | None:
    message = _status_message(body).lower()
    if any(token in message for token in ("auth", "api key", "apikey", "token", "unauthorized")):
        return TtsAuthError
    if any(token in message for token in ("rate", "throttle", "频繁", "限流")):
        return TtsRateLimitError
    if any(token in message for token in ("balance", "quota", "余额", "额度")):
        return TtsQuotaError
    return None


def _raise_http_error(status_code: int, *, trace_id: str | None = None) -> None:
    if status_code in (401, 403):
        raise TtsAuthError("MiniMax API Key is invalid or unauthorized", provider_request_id=trace_id)
    if status_code == 429:
        raise TtsRateLimitError("MiniMax rate limit exceeded", provider_request_id=trace_id)
    if status_code == 402:
        raise TtsQuotaError("MiniMax quota is unavailable", provider_request_id=trace_id)
    if status_code >= 500:
        raise TtsProviderNetworkError("MiniMax service is temporarily unavailable", provider_request_id=trace_id)
    if status_code >= 400:
        raise TtsProviderResponseError("MiniMax request was rejected", provider_request_id=trace_id)


class MiniMaxProvider(BaseTtsProvider):
    """MiniMax T2A v2 adapter using synchronous, non-streaming WAV output."""

    def __init__(
        self,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(_descriptor())
        self._client_factory = client_factory or httpx.Client

    def _model(self, model_id: str) -> ModelDescriptor:
        model_key = (model_id or "").strip()
        for model in self.descriptor.models:
            if model.id == model_key:
                return model
        raise TtsConfigurationError(f"Unknown MiniMax TTS model: {model_key}")

    def validate_credentials(self, credentials: Mapping[str, str]) -> None:
        super().validate_credentials(credentials)

    def _post_json(
        self,
        credentials: Mapping[str, str],
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_sec: float,
    ) -> Mapping[str, Any]:
        self.validate_credentials(credentials)
        api_key = str(credentials.get("api_key", "")).strip()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            with self._client_factory(
                timeout=httpx.Timeout(timeout_sec, connect=min(10.0, timeout_sec))
            ) as client:
                response = client.post(url, json=dict(payload), headers=headers)
        except httpx.TimeoutException as exc:
            raise TtsProviderNetworkError("MiniMax request timed out", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise TtsProviderNetworkError("MiniMax network request failed", cause=exc) from exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise TtsProviderNetworkError("MiniMax network request failed", cause=exc) from exc

        status_code = getattr(response, "status_code", 200)
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            raise TtsProviderResponseError("MiniMax returned an invalid HTTP status") from None
        if status_code >= 400:
            _raise_http_error(status_code)

        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise TtsProviderResponseError("MiniMax returned malformed JSON") from exc
        if not isinstance(body, Mapping):
            raise TtsProviderResponseError("MiniMax returned a malformed response")
        return body

    def _validate_request(self, request: TtsRequest) -> ModelDescriptor:
        if request.provider_id.strip() != MINIMAX_PROVIDER_ID:
            raise TtsConfigurationError("TTS request provider does not match MiniMax")
        model = self._model(request.model_id)
        if not request.text or not request.text.strip():
            raise TtsConfigurationError("TTS text must not be empty")
        if request.output_format.strip().lower() != _MINIMAX_AUDIO_FORMAT:
            raise TtsUnsupportedCapabilityError(
                f"output_format:{request.output_format.strip().lower()}"
            )
        if request.style_prompt:
            raise TtsUnsupportedCapabilityError("style_prompt")
        if request.streaming:
            raise TtsUnsupportedCapabilityError("streaming")
        if request.speed is not None and not 0.5 <= request.speed <= 2.0:
            raise TtsConfigurationError("MiniMax speed is out of range [0.5, 2.0]")
        if request.pitch is not None and not -12.0 <= request.pitch <= 12.0:
            raise TtsConfigurationError("MiniMax pitch is out of range [-12, 12]")
        if request.volume is not None and request.volume < 0:
            raise TtsConfigurationError("MiniMax volume must not be negative")
        if request.emotion is not None and request.emotion.strip() not in MINIMAX_EMOTIONS:
            raise TtsConfigurationError(
                "MiniMax emotion must be one of the official emotion values"
            )
        if request.voice_id is not None and not request.voice_id.strip():
            raise TtsInvalidVoiceError("MiniMax voice ID must not be empty")
        return model

    def synthesize(
        self,
        credentials: Mapping[str, str],
        request: TtsRequest,
        *,
        timeout_sec: float = 60.0,
    ) -> TtsResult:
        self._validate_request(request)
        voice_id = (request.voice_id or MINIMAX_DEFAULT_VOICE).strip()
        voice_setting: dict[str, Any] = {
            "voice_id": voice_id,
            "speed": 1 if request.speed is None else request.speed,
            "vol": 1 if request.volume is None else request.volume,
            "pitch": 0 if request.pitch is None else request.pitch,
        }
        if request.emotion is not None:
            emotion = request.emotion.strip()
            if not emotion:
                raise TtsConfigurationError("MiniMax emotion must not be empty")
            voice_setting["emotion"] = emotion

        body = self._post_json(
            credentials,
            MINIMAX_T2A_ENDPOINT,
            {
                "model": request.model_id.strip(),
                "text": request.text.strip(),
                "stream": False,
                "voice_setting": voice_setting,
                "audio_setting": {"format": _MINIMAX_AUDIO_FORMAT},
                "output_format": _MINIMAX_OUTPUT_FORMAT,
            },
            timeout_sec=timeout_sec,
        )
        trace_id = _trace_id(body)
        base_resp = body.get("base_resp")
        if not isinstance(base_resp, Mapping):
            raise TtsProviderResponseError(
                "MiniMax response is missing base_resp", provider_request_id=trace_id
            )
        try:
            provider_status = int(base_resp.get("status_code"))
        except (TypeError, ValueError):
            raise TtsProviderResponseError(
                "MiniMax response has an invalid base_resp", provider_request_id=trace_id
            ) from None
        if provider_status != 0:
            error_type = _vendor_error(body) or TtsProviderResponseError
            raise error_type(
                "MiniMax synthesis request failed", provider_request_id=trace_id
            )
        data = body.get("data")
        audio_hex = data.get("audio") if isinstance(data, Mapping) else None
        if not isinstance(audio_hex, str) or not audio_hex:
            raise TtsProviderResponseError(
                "MiniMax response does not contain audio", provider_request_id=trace_id
            )
        try:
            audio_bytes = bytes.fromhex(audio_hex)
        except ValueError as exc:
            raise TtsAudioDecodeError(
                "MiniMax audio hex is malformed", provider_request_id=trace_id, cause=exc
            ) from exc
        if not audio_bytes:
            raise TtsAudioDecodeError(
                "MiniMax audio is empty", provider_request_id=trace_id
            )
        extra_info = body.get("extra_info")
        sample_rate = extra_info.get("audio_sample_rate") if isinstance(extra_info, Mapping) else None
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
            sample_rate = None
        return TtsResult(
            audio_bytes=audio_bytes,
            audio_format=_MINIMAX_AUDIO_FORMAT,
            sample_rate=sample_rate,
            provider_request_id=trace_id,
        )

    def list_voices(
        self,
        credentials: Mapping[str, str],
        *,
        model_id: str,
        force_refresh: bool = False,
    ) -> list[VoiceDescriptor]:
        del force_refresh
        model = self._model(model_id)
        try:
            body = self._post_json(
                credentials,
                MINIMAX_GET_VOICE_ENDPOINT,
                {"voice_type": "all"},
                timeout_sec=30.0,
            )
            base_resp = body.get("base_resp")
            if not isinstance(base_resp, Mapping) or int(base_resp.get("status_code")) != 0:
                raise TtsProviderResponseError("MiniMax voice response is malformed")
            voices: list[VoiceDescriptor] = []
            categories = (
                ("system_voice", VoiceSource.REMOTE_CATALOG),
                ("voice_cloning", VoiceSource.CLONED_VOICE),
                ("voice_generation", VoiceSource.DESIGNED_VOICE),
            )
            for key, source in categories:
                values = body.get(key, [])
                if not isinstance(values, list):
                    raise TtsProviderResponseError("MiniMax voice response is malformed")
                for item in values:
                    if not isinstance(item, Mapping):
                        raise TtsProviderResponseError("MiniMax voice response is malformed")
                    voice_id = item.get("voice_id")
                    if not isinstance(voice_id, str) or not voice_id.strip():
                        raise TtsProviderResponseError("MiniMax voice response is malformed")
                    voice_name = item.get("voice_name")
                    voices.append(
                        VoiceDescriptor(
                            id=voice_id.strip(),
                            name=(voice_name.strip() if isinstance(voice_name, str) and voice_name.strip() else voice_id.strip()),
                            description=(
                                item.get("description")
                                if isinstance(item.get("description"), str)
                                else None
                            ),
                            gender=(
                                item.get("gender")
                                if isinstance(item.get("gender"), str)
                                else None
                            ),
                            languages=("zh-CN",),
                            source=source,
                        )
                    )
            return voices or list(model.voices)
        except (TtsAuthError, TtsRateLimitError):
            raise
        except Exception:
            return list(model.voices)


__all__ = [
    "MINIMAX_CURRENT_MODELS",
    "MINIMAX_DEFAULT_VOICE",
    "MINIMAX_GET_VOICE_ENDPOINT",
    "MINIMAX_HISTORICAL_MODELS",
    "MINIMAX_PROVIDER_ID",
    "MINIMAX_RECOMMENDED_VOICES",
    "MINIMAX_T2A_ENDPOINT",
    "MiniMaxProvider",
]
