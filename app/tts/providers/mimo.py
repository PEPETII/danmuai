"""Xiaomi MiMo V2.5 TTS provider adapter.

The adapter deliberately keeps the MiMo wire format inside this module.  The
normal provider contract returns one complete WAV result; the optional stream
method exposes PCM16 chunks separately and does not imply that playback is
streamed by the application.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator, Mapping
from typing import Any

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

MIMO_PROVIDER_ID = "mimo"
MIMO_MODEL_ID = "mimo-v2.5-tts"
MIMO_BASE_URL = "https://api.xiaomimimo.com"
MIMO_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
MIMO_DEFAULT_VOICE = "冰糖"
MIMO_STREAM_SAMPLE_RATE = 24_000

# Keep the existing user-visible voice IDs.  The adapter does not use this
# tuple as a legality gate: MiMo remains authoritative for a supplied voice ID.
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


def _voice_descriptors() -> tuple[VoiceDescriptor, ...]:
    return tuple(
        VoiceDescriptor(
            id=voice_id,
            name=voice_id,
            source=VoiceSource.STATIC_CATALOG,
        )
        for voice_id in MIMO_TTS_VOICES
    )


def _descriptor() -> ProviderDescriptor:
    model = ModelDescriptor(
        id=MIMO_MODEL_ID,
        label="MiMo V2.5 TTS",
        recommended=True,
        tags=("推荐", "预置音色"),
        transport="http",
        capabilities=TtsCapabilities(
            streaming=True,
            style_prompt=True,
            voice_list=True,
            output_formats=frozenset({"wav", "pcm16"}),
        ),
        pricing=PricingDescriptor(
            kind="promotional_free",
            note="限时免费；实际费用以 MiMo 官方账单为准",
        ),
        voices=_voice_descriptors(),
    )
    return ProviderDescriptor(
        id=MIMO_PROVIDER_ID,
        label="小米 MiMo",
        auth=AuthDescriptor(
            fields=(
                AuthFieldDescriptor(
                    id="api_key",
                    label="MiMo API Key",
                    required=True,
                    secret=True,
                ),
            )
        ),
        models=(model,),
    )


def _request_id(response: httpx.Response | None = None, body: Any = None) -> str | None:
    if response is not None:
        headers = getattr(response, "headers", None)
        value = (
            headers.get("x-request-id") or headers.get("request-id")
            if headers is not None
            else None
        )
        if value:
            return value
    value = body.get("id") if isinstance(body, dict) else None
    return value if isinstance(value, str) and value else None


def _error_for_status(
    status_code: int,
    *,
    request_id: str | None = None,
    cause: BaseException | None = None,
) -> Exception:
    kwargs = {"provider_request_id": request_id, "cause": cause}
    if status_code in (401, 403):
        return TtsAuthError("MiMo API key was rejected", **kwargs)
    if status_code == 402:
        return TtsQuotaError("MiMo TTS quota is unavailable", **kwargs)
    if status_code == 429:
        return TtsRateLimitError("MiMo TTS rate limit exceeded", **kwargs)
    if status_code >= 500:
        return TtsProviderNetworkError("MiMo TTS service is temporarily unavailable", **kwargs)
    return TtsProviderResponseError("MiMo TTS request was rejected", **kwargs)


class MimoProvider(BaseTtsProvider):
    """MiMo V2.5 TTS over the official OpenAI-style HTTP endpoint.

    ``transport`` is injectable solely for deterministic contract tests.  It
    is an ``httpx`` transport and never changes the public TTS request shape.
    """

    def __init__(
        self,
        *,
        base_url: str = MIMO_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(_descriptor())
        normalized_base_url = (base_url or "").strip().rstrip("/")
        if not normalized_base_url:
            raise TtsConfigurationError("MiMo TTS base URL must not be empty")
        self.base_url = normalized_base_url
        self._transport = transport

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}{MIMO_CHAT_COMPLETIONS_PATH}"

    def _client(self, timeout_sec: float) -> httpx.Client:
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(timeout_sec, connect=min(timeout_sec, 10.0)),
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def _validate_request(self, request: TtsRequest, *, streaming: bool) -> None:
        if request.provider_id.strip() != MIMO_PROVIDER_ID:
            raise TtsConfigurationError("TTS request provider does not match MiMo")
        if request.model_id.strip() != MIMO_MODEL_ID:
            raise TtsConfigurationError(f"Unsupported MiMo TTS model: {request.model_id}")
        if not request.text or not request.text.strip():
            raise TtsConfigurationError("TTS text must not be empty")
        if request.emotion is not None:
            raise TtsUnsupportedCapabilityError("emotion")
        if request.speed is not None:
            raise TtsUnsupportedCapabilityError("speed")
        if request.pitch is not None:
            raise TtsUnsupportedCapabilityError("pitch")
        if request.volume is not None:
            raise TtsUnsupportedCapabilityError("volume")
        if not streaming and request.streaming:
            raise TtsUnsupportedCapabilityError(
                "streaming",
                "Use MimoProvider.synthesize_stream for PCM16 chunks",
            )
        requested_format = request.output_format.strip().lower()
        expected_format = "pcm16" if streaming else "wav"
        if requested_format != expected_format:
            raise TtsUnsupportedCapabilityError(f"output_format:{requested_format}")

    @staticmethod
    def _payload(request: TtsRequest, *, audio_format: str, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        style = (request.style_prompt or "").strip()
        if style:
            messages.append({"role": "user", "content": style})
        messages.append({"role": "assistant", "content": request.text.strip()})

        audio: dict[str, str] = {"format": audio_format}
        voice = (request.voice_id or MIMO_DEFAULT_VOICE).strip()
        if voice:
            audio["voice"] = voice

        payload: dict[str, Any] = {
            "model": request.model_id,
            "messages": messages,
            "audio": audio,
        }
        if stream:
            payload["stream"] = True
        return payload

    def _raise_http_error(self, response: httpx.Response) -> None:
        if response.is_error:
            raise _error_for_status(response.status_code, request_id=_request_id(response))

    def _decode_audio(self, body: Any, *, request_id: str | None = None) -> TtsResult:
        if not isinstance(body, dict):
            raise TtsProviderResponseError(
                "MiMo returned a malformed TTS response",
                provider_request_id=request_id,
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise TtsProviderResponseError(
                "MiMo TTS response contains no choices",
                provider_request_id=_request_id(body=body) or request_id,
            )
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise TtsProviderResponseError(
                "MiMo TTS response contains no message",
                provider_request_id=_request_id(body=body) or request_id,
            )
        audio = message.get("audio")
        if not isinstance(audio, dict) or not audio.get("data"):
            raise TtsProviderResponseError(
                "MiMo TTS response contains no audio",
                provider_request_id=_request_id(body=body) or request_id,
            )
        encoded = audio["data"]
        if not isinstance(encoded, str):
            raise TtsProviderResponseError(
                "MiMo TTS audio data is malformed",
                provider_request_id=_request_id(body=body) or request_id,
            )
        try:
            audio_bytes = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError) as exc:
            raise TtsAudioDecodeError(
                "MiMo TTS audio data is not valid base64",
                provider_request_id=_request_id(body=body) or request_id,
                cause=exc,
            ) from exc
        if not audio_bytes:
            raise TtsProviderResponseError(
                "MiMo TTS response contains empty audio",
                provider_request_id=_request_id(body=body) or request_id,
            )
        return TtsResult(
            audio_bytes=audio_bytes,
            audio_format="wav",
            provider_request_id=_request_id(body=body) or request_id,
        )

    def synthesize(
        self,
        credentials: Mapping[str, str],
        request: TtsRequest,
        *,
        timeout_sec: float = 60.0,
    ) -> TtsResult:
        self.validate_credentials(credentials)
        self._validate_request(request, streaming=False)
        payload = self._payload(request, audio_format="wav", stream=False)
        key = str(credentials["api_key"]).strip()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        try:
            with self._client(timeout_sec) as client:
                response = client.post(self.endpoint, json=payload, headers=headers)
                self._raise_http_error(response)
                body = response.json()
        except (TtsAuthError, TtsQuotaError, TtsRateLimitError, TtsProviderNetworkError, TtsProviderResponseError):
            raise
        except httpx.TimeoutException as exc:
            raise TtsProviderNetworkError("MiMo TTS request timed out", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise TtsProviderNetworkError("MiMo TTS network request failed", cause=exc) from exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TtsProviderResponseError("MiMo returned invalid JSON", cause=exc) from exc
        return self._decode_audio(body, request_id=_request_id(response))

    @staticmethod
    def _stream_audio_data(event: Any) -> str | None:
        if not isinstance(event, dict):
            raise TtsProviderResponseError("MiMo streaming event is malformed")
        choices = event.get("choices")
        if not choices:
            return None
        if not isinstance(choices, list) or not isinstance(choices[0], dict):
            raise TtsProviderResponseError("MiMo streaming choices are malformed")
        chunk = choices[0].get("delta") or choices[0].get("message")
        if not isinstance(chunk, dict):
            return None
        audio = chunk.get("audio")
        if audio is None:
            return None
        if not isinstance(audio, dict) or not audio.get("data"):
            raise TtsProviderResponseError("MiMo streaming audio is malformed")
        encoded = audio["data"]
        if not isinstance(encoded, str):
            raise TtsProviderResponseError("MiMo streaming audio data is malformed")
        return encoded

    def synthesize_stream(
        self,
        credentials: Mapping[str, str],
        request: TtsRequest,
        *,
        timeout_sec: float = 60.0,
    ) -> Iterator[TtsResult]:
        """Yield MiMo PCM16 chunks; the caller owns any later playback policy."""

        self.validate_credentials(credentials)
        self._validate_request(request, streaming=True)
        payload = self._payload(request, audio_format="pcm16", stream=True)
        key = str(credentials["api_key"]).strip()
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        yielded = False
        try:
            with self._client(timeout_sec) as client:
                with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                    self._raise_http_error(response)
                    request_id = _request_id(response)
                    for line in response.iter_lines():
                        if not line:
                            continue
                        data = line.decode("utf-8") if isinstance(line, bytes) else line
                        if data.startswith("data:"):
                            data = data[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except (TypeError, ValueError) as exc:
                            raise TtsProviderResponseError(
                                "MiMo streaming event is not valid JSON",
                                provider_request_id=request_id,
                                cause=exc,
                            ) from exc
                        encoded = self._stream_audio_data(event)
                        if not encoded:
                            continue
                        try:
                            chunk = base64.b64decode(encoded, validate=True)
                        except (TypeError, ValueError) as exc:
                            raise TtsAudioDecodeError(
                                "MiMo streaming audio data is not valid base64",
                                provider_request_id=_request_id(body=event) or request_id,
                                cause=exc,
                            ) from exc
                        if not chunk:
                            continue
                        yielded = True
                        yield TtsResult(
                            audio_bytes=chunk,
                            audio_format="pcm16",
                            sample_rate=MIMO_STREAM_SAMPLE_RATE,
                            provider_request_id=_request_id(body=event) or request_id,
                        )
        except (TtsAuthError, TtsQuotaError, TtsRateLimitError, TtsProviderNetworkError, TtsProviderResponseError, TtsAudioDecodeError):
            raise
        except httpx.TimeoutException as exc:
            raise TtsProviderNetworkError("MiMo streaming request timed out", cause=exc) from exc
        except httpx.HTTPError as exc:
            raise TtsProviderNetworkError("MiMo streaming network request failed", cause=exc) from exc
        if not yielded:
            raise TtsProviderResponseError("MiMo streaming response contains no audio")


MimoTtsProvider = MimoProvider

__all__ = [
    "MIMO_BASE_URL",
    "MIMO_CHAT_COMPLETIONS_PATH",
    "MIMO_DEFAULT_VOICE",
    "MIMO_MODEL_ID",
    "MIMO_PROVIDER_ID",
    "MIMO_STREAM_SAMPLE_RATE",
    "MIMO_TTS_VOICES",
    "MimoProvider",
    "MimoTtsProvider",
]
