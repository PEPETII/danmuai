"""Doubao Seed TTS V3 provider.

Only the V3 HTTP unidirectional streaming API is implemented here.  The V3
wire details intentionally stay inside this adapter because the repository's
shared TTS core must not know about vendor headers or frames.

The synthesis API uses the new TTS API key.  The ListSpeakers API is a
separate Volcengine OpenAPI operation and uses AK/SK HMAC credentials; those
credential sets are deliberately never interchangeable.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from app.tts.capabilities import CapabilityResolver
from app.tts.providers.base import BaseTtsProvider
from app.tts.types import (
    AuthDescriptor,
    AuthFieldDescriptor,
    ModelDescriptor,
    PricingDescriptor,
    ProviderDescriptor,
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
    VoiceDescriptor,
    VoiceSource,
)

DOUBAO_PROVIDER_ID = "doubao"
DOUBAO_MODEL_ID = "seed-tts-2.0"
DOUBAO_MODEL_LABEL = "Doubao-Seed-TTS-2.0"
DOUBAO_TTS_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DOUBAO_LIST_SPEAKERS_ENDPOINT = "https://open.volcengineapi.com"
DOUBAO_LIST_SPEAKERS_SERVICE = "speech_saas_prod"
DOUBAO_LIST_SPEAKERS_VERSION = "2025-05-20"
DOUBAO_LIST_SPEAKERS_REGION = "cn-beijing"
DOUBAO_PRICING_SOURCE_URL = "https://www.volcengine.com/product/doubao/"
DOUBAO_VOICE_SOURCE_URL = "https://www.volcengine.com/docs/6561/162929?lang=en"
DOUBAO_VERIFIED_AT = "2026-08-17"

DOUBAO_STATIC_VOICES: tuple[VoiceDescriptor, ...] = (
    VoiceDescriptor(
        "zh_female_vv_uranus_bigtts", "vivi 2.0", None, "female",
        languages=("zh-CN", "en-US"), tags=("官方预置", "通用场景"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "zh_male_dayi_saturn_bigtts", "大壹", None, "male",
        languages=("zh-CN",), tags=("官方预置", "视频配音"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "zh_female_mizai_saturn_bigtts", "黑猫侦探社咪仔", None, "female",
        languages=("zh-CN",), tags=("官方预置", "视频配音"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "zh_female_jitangnv_saturn_bigtts", "鸡汤女", None, "female",
        languages=("zh-CN",), tags=("官方预置", "视频配音"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "zh_female_meilinvyou_saturn_bigtts", "魅力女友", None, "female",
        languages=("zh-CN",), tags=("官方预置", "视频配音"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "zh_female_santongyongns_saturn_bigtts", "流畅女声", None, "female",
        languages=("zh-CN",), tags=("官方预置", "流畅女声"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "zh_male_ruyayichen_saturn_bigtts", "儒雅逸辰", None, "male",
        languages=("zh-CN",), tags=("官方预置", "视频配音"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "ICL_zh_female_keainvsheng_tob", "可爱女生", None, "female",
        languages=("zh-CN",), tags=("官方预置", "角色扮演"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "ICL_zh_female_tiaopigongzhu_tob", "调皮公主", None, "female",
        languages=("zh-CN",), tags=("官方预置", "角色扮演"),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "zh_female_vv_mars_bigtts", "Vivi", None, "female",
        languages=("zh-CN",), tags=("官方预置", "通用场景"),
        source=VoiceSource.STATIC_CATALOG,
    ),
)

_LEGACY_SYNTHESIS_KEYS = frozenset(
    {"app_id", "appid", "access_token", "accessToken", "token"}
)
_LIST_SPEAKERS_KEYS = frozenset(
    {
        "access_key_id",
        "access_key_secret",
        "secret_access_key",
        "access_key",
        "secret_key",
        "ak",
        "sk",
    }
)
_SECRET_NAME_RE = re.compile(
    r"(?i)(api[-_ ]?key|access[-_ ]?(?:key|token)|secret[-_ ]?key|authorization)"
    r"(?:\s*[:=]\s*|\s+)[^,;\s]+"
)


class DoubaoTransport(Protocol):
    """Minimal injectable transport used by both HTTP operations."""

    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        timeout: float,
    ) -> Any:
        ...

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, str] | None = None,
        timeout: float,
    ) -> Any:
        ...


class _HttpxTransport:
    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        timeout = kwargs.pop("timeout")
        return self._stream(method, url, timeout=timeout, **kwargs)

    @contextmanager
    def _stream(self, method: str, url: str, *, timeout: float, **kwargs: Any):
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0))) as client:
            with client.stream(method, url, **kwargs) as response:
                yield response

    def request(self, method: str, url: str, *, timeout: float, **kwargs: Any) -> Any:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0))) as client:
            return client.request(method, url, **kwargs)


@dataclass(frozen=True)
class _DoubaoV3Protocol:
    """V3 protocol constants kept together for later evidence-based updates."""

    endpoint: str = DOUBAO_TTS_ENDPOINT
    resource_header: str = "X-Api-Resource-Id"
    api_key_header: str = "X-Api-Key"
    request_id_header: str = "X-Api-Request-Id"
    resource_id: str = DOUBAO_MODEL_ID
    user_key: str = "user"
    request_key: str = "req_params"
    text_key: str = "text"
    voice_key: str = "speaker"
    audio_key: str = "audio"
    format_key: str = "format"
    sample_rate_key: str = "sample_rate"

    def headers(self, api_key: str, request_id: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            self.api_key_header: api_key,
            self.resource_header: self.resource_id,
            self.request_id_header: request_id,
        }

    def payload(self, request: TtsRequest, *, voice_id: str) -> dict[str, Any]:
        req_params: dict[str, Any] = {
            self.text_key: request.text.strip(),
            self.voice_key: voice_id,
            self.audio_key: {
                self.format_key: request.output_format.strip().lower(),
                self.sample_rate_key: 24000,
            },
        }
        if request.speed is not None:
            req_params["speed_ratio"] = request.speed
        if request.volume is not None:
            req_params["loudness_ratio"] = request.volume
        if request.emotion is not None:
            req_params["emotion"] = request.emotion.strip()
            req_params["enable_emotion"] = True
        return {
            self.user_key: {"uid": "danmuai"},
            self.request_key: req_params,
        }


_V3 = _DoubaoV3Protocol()


def _redact(value: Any, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in secrets:
        candidate = str(secret).strip()
        if candidate:
            text = text.replace(candidate, "<redacted>")
    return _SECRET_NAME_RE.sub(lambda match: match.group(1) + "=<redacted>", text)


def _credential_value(credentials: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = str(credentials.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _nonempty_keys(credentials: Mapping[str, str], keys: Iterable[str]) -> set[str]:
    return {key for key in keys if str(credentials.get(key, "") or "").strip()}


def _status_error(response: Any, *, secrets: Iterable[str], request_id: str | None = None) -> None:
    status = getattr(response, "status_code", None)
    try:
        status_code = int(status)
    except (TypeError, ValueError):
        status_code = 0
    if 200 <= status_code < 300:
        return

    detail = ""
    try:
        body = response.json()
        if isinstance(body, Mapping):
            detail = str(body.get("message") or body.get("msg") or body.get("error") or "")
        elif body:
            detail = str(body)
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        detail = str(getattr(response, "text", "") or "")
    detail = _redact(detail[:240], secrets)
    suffix = f": {detail}" if detail else ""
    message = f"Doubao V3 HTTP response error (status={status_code or 'unknown'}){suffix}"
    if status_code in (401, 403):
        raise TtsAuthError(message, provider_request_id=request_id)
    if status_code == 402:
        raise TtsQuotaError(message, provider_request_id=request_id)
    if status_code == 429:
        raise TtsRateLimitError(message, provider_request_id=request_id)
    if status_code >= 500 or status_code == 0:
        raise TtsProviderNetworkError(message, provider_request_id=request_id)
    raise TtsProviderResponseError(message, provider_request_id=request_id)


def _iter_response_bytes(response: Any) -> Iterable[bytes]:
    iterator = getattr(response, "iter_bytes", None) or getattr(response, "iter_raw", None)
    if iterator is None:
        content = getattr(response, "content", None)
        if content is None:
            raise TtsProviderResponseError("Doubao V3 response has no byte stream")
        yield bytes(content)
        return
    for chunk in iterator():
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise TtsProviderResponseError("Doubao V3 stream contained a non-byte chunk")
        if chunk:
            yield bytes(chunk)


def _iter_json_objects(chunks: Iterable[bytes]) -> Iterable[Mapping[str, Any]]:
    decoder = json.JSONDecoder()
    utf8 = codecs.getincrementaldecoder("utf-8")()
    pending = ""

    def decode_pending(*, final: bool) -> Iterable[Mapping[str, Any]]:
        nonlocal pending
        if final:
            try:
                pending += utf8.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise TtsProviderResponseError("Doubao V3 stream is not valid UTF-8") from exc
        while pending:
            pending = pending.lstrip()
            if not pending:
                return
            if pending.startswith("data:"):
                newline = pending.find("\n")
                if newline < 0:
                    if final:
                        raise TtsProviderResponseError("Doubao V3 data frame is incomplete")
                    return
                pending = pending[5:newline].lstrip() + pending[newline + 1 :]
                continue
            try:
                value, end = decoder.raw_decode(pending)
            except json.JSONDecodeError as exc:
                # A JSON string can be split at any byte, not only after a
                # punctuation character.  Defer all decode failures until
                # the stream is complete; the final pass still rejects
                # malformed or truncated frames explicitly.
                if not final:
                    return
                raise TtsProviderResponseError("Doubao V3 stream contains malformed JSON") from exc
            pending = pending[end:]
            if not isinstance(value, Mapping):
                raise TtsProviderResponseError("Doubao V3 stream frame must be a JSON object")
            yield value

    for chunk in chunks:
        try:
            pending += utf8.decode(chunk, final=False)
        except UnicodeDecodeError as exc:
            raise TtsProviderResponseError("Doubao V3 stream is not valid UTF-8") from exc
        yield from decode_pending(final=False)
    yield from decode_pending(final=True)
    if pending.strip():
        raise TtsProviderResponseError("Doubao V3 stream ended with an incomplete JSON frame")


def _as_format(value: Any) -> str:
    return str(value or "").strip().lower().replace("audio/", "")


def _find_audio_candidate(event: Mapping[str, Any]) -> tuple[Any, Mapping[str, Any]] | None:
    candidates: list[tuple[Any, Mapping[str, Any]]] = []
    for key in ("audio", "audio_data", "audio_base64", "base64", "data"):
        value = event.get(key)
        if isinstance(value, (str, bytes, bytearray, memoryview)) and value not in ("", b""):
            candidates.append((value, event))
    nested = event.get("audio")
    if isinstance(nested, Mapping):
        for key in ("data", "audio", "base64", "audio_base64"):
            value = nested.get(key)
            if value not in (None, "", b""):
                candidates.append((value, nested))
    data = event.get("data")
    if isinstance(data, Mapping):
        nested_data = _find_audio_candidate(data)
        if nested_data is not None:
            return nested_data
    return candidates[0] if candidates else None


def _decode_audio_event(
    event: Mapping[str, Any],
    *,
    secrets: Iterable[str] = (),
) -> tuple[bytes, str, int | None] | None:
    code = event.get("code")
    if code not in (None, 0, "0", "OK", "ok", "success"):
        detail = _redact(event.get("message") or event.get("msg") or code, secrets)
        raise TtsProviderResponseError(f"Doubao V3 provider error: {detail}")
    candidate = _find_audio_candidate(event)
    if candidate is None:
        return None
    encoded, metadata = candidate
    if not isinstance(encoded, str):
        raise TtsProviderResponseError("Doubao V3 audio field must be base64 text")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TtsProviderResponseError("Doubao V3 audio field is not valid base64") from exc
    if not audio:
        raise TtsProviderResponseError("Doubao V3 audio field is empty")
    audio_format = _as_format(
        metadata.get("format")
        or metadata.get("audio_format")
        or metadata.get("codec")
        or event.get("format")
        or event.get("audio_format")
    )
    if not audio_format:
        raise TtsProviderResponseError("Doubao V3 audio frame is missing required format")
    if audio_format not in {"wav", "mp3", "pcm", "raw", "pcm_s16le", "pcm_s24le", "pcm_s32le"}:
        raise TtsProviderResponseError(f"Doubao V3 audio format is unsupported: {audio_format}")
    sample_rate_value = metadata.get("sample_rate") or event.get("sample_rate")
    try:
        sample_rate = int(sample_rate_value) if sample_rate_value is not None else None
    except (TypeError, ValueError) as exc:
        raise TtsProviderResponseError("Doubao V3 sample_rate is invalid") from exc
    if audio_format in {"pcm", "raw", "pcm_s16le", "pcm_s24le", "pcm_s32le"} and not sample_rate:
        raise TtsProviderResponseError("Doubao V3 PCM frame is missing required sample_rate")
    return audio, audio_format, sample_rate


def parse_doubao_v3_chunks(
    chunks: Iterable[bytes],
    *,
    secrets: Iterable[str] = (),
) -> tuple[bytes, str, int | None]:
    """Parse JSON chunk frames and return concatenated encoded audio bytes."""

    audio_parts: list[bytes] = []
    audio_format = ""
    sample_rate: int | None = None
    for event in _iter_json_objects(chunks):
        parsed = _decode_audio_event(event, secrets=secrets)
        if parsed is None:
            continue
        audio, current_format, current_rate = parsed
        if audio_format and current_format != audio_format:
            raise TtsProviderResponseError("Doubao V3 stream changed audio format mid-response")
        if sample_rate and current_rate and sample_rate != current_rate:
            raise TtsProviderResponseError("Doubao V3 stream changed sample_rate mid-response")
        audio_format = audio_format or current_format
        sample_rate = sample_rate or current_rate
        audio_parts.append(audio)
    if not audio_parts:
        raise TtsProviderResponseError("Doubao V3 stream contained no audio data")
    return b"".join(audio_parts), audio_format, sample_rate


def _canonical_query(params: Mapping[str, str]) -> str:
    return urlencode(sorted((str(key), str(value)) for key, value in params.items()))


def build_list_speakers_signature(
    access_key_id: str,
    secret_access_key: str,
    *,
    method: str,
    uri: str,
    query: Mapping[str, str],
    body: bytes = b"",
    now: datetime | None = None,
) -> dict[str, str]:
    """Build the Volcengine HMAC-SHA256 headers without exposing AK/SK."""

    timestamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    date = timestamp[:8]
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_query = _canonical_query(query)
    canonical_headers = f"host:open.volcengineapi.com\nx-content-sha256:{payload_hash}\nx-date:{timestamp}\n"
    signed_headers = "host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        (method.upper(), uri, canonical_query, canonical_headers, signed_headers, payload_hash)
    )
    credential_scope = f"{date}/{DOUBAO_LIST_SPEAKERS_REGION}/{DOUBAO_LIST_SPEAKERS_SERVICE}/request"
    signing_key = hmac.new(
        secret_access_key.encode("utf-8"),
        f"HMAC-SHA256\n{timestamp}\n{credential_scope}\n".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signature = hmac.new(
        signing_key.encode("utf-8"), canonical_request.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "Host": "open.volcengineapi.com",
        "X-Date": timestamp,
        "X-Content-Sha256": payload_hash,
        "Authorization": (
            f"HMAC-SHA256 Credential={access_key_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }


def _voice_list_from_body(
    body: Any,
    *,
    secrets: Iterable[str] = (),
) -> list[Mapping[str, Any]]:
    if not isinstance(body, Mapping):
        raise TtsProviderResponseError("Doubao ListSpeakers response is not a JSON object")
    code = _mapping_value(body, "Code", "code")
    if code not in (None, 0, "0", "OK", "ok", "success"):
        detail = _redact(_mapping_value(body, "Message", "message", "msg") or code, secrets)
        raise TtsProviderResponseError(f"Doubao ListSpeakers provider error: {detail}")
    for key in ("Speakers", "speakers", "Voices", "voices", "Items", "items"):
        value = _mapping_value(body, key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    data = _mapping_value(body, "Result", "result", "Data", "data")
    if isinstance(data, Mapping):
        return _voice_list_from_body(data, secrets=secrets)
    raise TtsProviderResponseError("Doubao ListSpeakers response is missing speakers")


def _tuple_value(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Iterable):
        values: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                nested = (
                    item.get("Language")
                    or item.get("language")
                    or item.get("Text")
                    or item.get("text")
                    or item.get("Label")
                    or item.get("label")
                    or item.get("Value")
                    or item.get("value")
                )
                if nested is not None and str(nested).strip():
                    values.append(str(nested).strip())
            elif str(item).strip():
                values.append(str(item).strip())
        return tuple(values)
    return (str(value).strip(),) if str(value).strip() else ()


def _mapping_value(item: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in item and item[name] not in (None, ""):
            return item[name]
    lowered = {str(key).lower(): value for key, value in item.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _mapping_text(item: Mapping[str, Any], *names: str) -> str:
    value = _mapping_value(item, *names)
    return str(value).strip() if value is not None and str(value).strip() else ""


class DoubaoProvider(BaseTtsProvider):
    """Doubao Seed TTS 2.0 V3 adapter."""

    def __init__(
        self,
        *,
        transport: DoubaoTransport | Callable[..., Any] | None = None,
        speaker_transport: DoubaoTransport | Callable[..., Any] | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        descriptor = ProviderDescriptor(
            id=DOUBAO_PROVIDER_ID,
            label="火山引擎豆包",
            auth=AuthDescriptor(
                fields=(
                    AuthFieldDescriptor(
                        id="api_key",
                        label="Doubao TTS API Key",
                        placeholder="仅用于 V3 TTS 合成",
                    ),
                    AuthFieldDescriptor(
                        id="access_key_id",
                        label="ListSpeakers Access Key ID（仅动态音色）",
                        required=False,
                    ),
                    AuthFieldDescriptor(
                        id="secret_access_key",
                        label="ListSpeakers Secret Access Key（仅动态音色）",
                        required=False,
                    ),
                )
            ),
            models=(
                ModelDescriptor(
                    id=DOUBAO_MODEL_ID,
                    label=DOUBAO_MODEL_LABEL,
                    recommended=True,
                    tags=("v3", "http-chunked", "seed-tts-2.0"),
                    transport="http_chunked_unidirectional",
                    capabilities=TtsCapabilities(
                        streaming=True,
                        emotion=True,
                        speed=True,
                        volume=True,
                        voice_list=True,
                        voice_preview=True,
                        custom_voice_id=True,
                        output_formats=frozenset({"wav", "mp3", "pcm"}),
                        notes=(
                            "V3 HTTP Chunked 单向流式；wav 不支持流式，建议使用 mp3/pcm。",
                            "当前适配器支持 speed_ratio 0.1–2、loudness_ratio 0.5–2、emotion + enable_emotion。",
                            "pitch 与普通 V3 单向接口的公开支持范围未确认，因此不展示音调控件。",
                            "自然语言风格/语音指令主要属于端到端实时语音模型或指定音色能力，普通 TTS 不固化为 style_prompt。",
                        ),
                    ),
                    pricing=PricingDescriptor(
                        kind="paygo",
                        currency="CNY",
                        amount=5.0,
                        unit="10k_chars",
                        display="¥5 / 1万字符（产品页语音合成大模型）",
                        note="官方产品页展示的语音合成大模型价格点；账户实际后付费阶梯和资源包以控制台为准。",
                        verified_at=DOUBAO_VERIFIED_AT,
                        source=DOUBAO_PRICING_SOURCE_URL,
                        source_url=DOUBAO_PRICING_SOURCE_URL,
                    ),
                    voices=DOUBAO_STATIC_VOICES,
                ),
            ),
        )
        super().__init__(descriptor)
        self._transport = transport or _HttpxTransport()
        self._speaker_transport = speaker_transport or self._transport
        self._request_id_factory = request_id_factory or (lambda: str(uuid.uuid4()))

    @staticmethod
    def _model_id(model_id: str) -> str:
        normalized = (model_id or "").strip()
        if normalized == DOUBAO_MODEL_LABEL:
            return DOUBAO_MODEL_ID
        if normalized != DOUBAO_MODEL_ID:
            raise TtsConfigurationError(f"Unknown Doubao TTS model: {normalized or '<empty>'}")
        return normalized

    def validate_credentials(self, credentials: Mapping[str, str]) -> None:
        api_key = _credential_value(credentials, "api_key")
        legacy = _nonempty_keys(credentials, _LEGACY_SYNTHESIS_KEYS)
        list_keys = _nonempty_keys(credentials, _LIST_SPEAKERS_KEYS)
        if legacy:
            raise TtsAuthError("Doubao V3 TTS API Key cannot be mixed with legacy AppID/AccessToken")
        if api_key and list_keys:
            raise TtsAuthError("Doubao V3 synthesis API Key cannot be mixed with ListSpeakers AK/SK")
        if api_key:
            return
        if list_keys == {"access_key_id", "secret_access_key"} or (
            {"access_key", "secret_key"}.issubset(list_keys)
        ) or ({"ak", "sk"}.issubset(list_keys)):
            return
        raise TtsAuthError(
            "Doubao V3 requires a TTS API Key for synthesis or a complete AK/SK pair for ListSpeakers"
        )

    def _validate_speaker_credentials(self, credentials: Mapping[str, str]) -> tuple[str, str]:
        api_key = _credential_value(credentials, "api_key")
        if api_key:
            raise TtsAuthError("ListSpeakers requires AK/SK HMAC credentials, not the TTS API Key")
        ak = _credential_value(credentials, "access_key_id", "access_key", "ak")
        sk = _credential_value(credentials, "secret_access_key", "secret_key", "sk")
        if not ak or not sk:
            raise TtsAuthError("ListSpeakers requires access_key_id and secret_access_key")
        return ak, sk

    def _call_request(self, transport: Any, **kwargs: Any) -> Any:
        request = getattr(transport, "request", None)
        if request is not None:
            return request(**kwargs)
        if callable(transport):
            return transport(**kwargs)
        raise TtsConfigurationError("Doubao transport must provide request()")

    def _call_stream(self, transport: Any, **kwargs: Any) -> Any:
        stream = getattr(transport, "stream", None)
        if stream is not None:
            return stream(**kwargs)
        if callable(transport):
            return transport(**kwargs)
        raise TtsConfigurationError("Doubao transport must provide stream()")

    def list_voices(
        self,
        credentials: Mapping[str, str],
        *,
        model_id: str,
        force_refresh: bool = False,
    ) -> list[VoiceDescriptor]:
        del force_refresh
        self._model_id(model_id)
        ak, sk = self._validate_speaker_credentials(credentials)
        query = {
            "Action": "ListSpeakers",
            "Version": DOUBAO_LIST_SPEAKERS_VERSION,
            "ServiceName": DOUBAO_LIST_SPEAKERS_SERVICE,
            "Region": DOUBAO_LIST_SPEAKERS_REGION,
        }
        request_body = {
            "ResourceIDs": [DOUBAO_MODEL_ID],
            "Page": 1,
            "Limit": 30,
        }
        encoded_body = json.dumps(
            request_body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        headers = build_list_speakers_signature(
            ak,
            sk,
            method="POST",
            uri="/",
            query=query,
            body=encoded_body,
        )
        headers["Content-Type"] = "application/json; charset=UTF-8"
        try:
            response = self._call_request(
                self._speaker_transport,
                method="POST",
                url=DOUBAO_LIST_SPEAKERS_ENDPOINT,
                headers=headers,
                params=query,
                json=request_body,
                timeout=60.0,
            )
            _status_error(response, secrets=(ak, sk))
            body = response.json()
            items = _voice_list_from_body(body, secrets=(ak, sk))
        except (TtsAuthError, TtsRateLimitError, TtsQuotaError, TtsProviderResponseError):
            raise
        except (httpx.TimeoutException, TimeoutError, ConnectionError, OSError) as exc:
            raise TtsProviderNetworkError("Doubao ListSpeakers network request failed", cause=exc) from exc
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TtsProviderResponseError("Doubao ListSpeakers response could not be decoded") from exc

        voices: list[VoiceDescriptor] = []
        for item in items:
            voice_id = _mapping_text(item, "VoiceType", "voice_type", "VoiceID", "voice_id", "speaker", "id")
            if not voice_id:
                continue
            name = _mapping_text(item, "Name", "name", "speaker_name", "display_name") or voice_id
            voices.append(
                VoiceDescriptor(
                    id=voice_id,
                    name=name,
                    description=_mapping_text(item, "Description", "description") or None,
                    gender=_mapping_text(item, "Gender", "gender") or None,
                    age_group=_mapping_text(item, "Age", "age", "age_group") or None,
                    languages=_tuple_value(_mapping_value(item, "Languages", "languages", "Language", "language")),
                    dialects=_tuple_value(_mapping_value(item, "Dialects", "dialects")),
                    emotions=_tuple_value(_mapping_value(item, "Emotions", "emotions", "Emotion", "emotion")),
                    tags=_tuple_value(_mapping_value(item, "Categories", "categories", "NormalLabels", "SpecialLabels", "category", "tags")),
                    preview_url=(
                        _mapping_text(item, "TrialURL", "trial_url", "ShortTrialURL", "short_trial_url", "preview_url", "demo_url") or None
                    ),
                    source=VoiceSource.REMOTE_CATALOG,
                )
            )
        return voices

    def synthesize(
        self,
        credentials: Mapping[str, str],
        request: TtsRequest,
        *,
        timeout_sec: float = 60.0,
    ) -> TtsResult:
        self.validate_credentials(credentials)
        api_key = _credential_value(credentials, "api_key")
        if not api_key:
            raise TtsAuthError("Doubao V3 synthesis requires a TTS API Key")
        self._model_id(request.model_id)
        if request.provider_id.strip() != DOUBAO_PROVIDER_ID:
            raise TtsConfigurationError("TtsRequest provider_id does not match Doubao")
        text = request.text.strip()
        if not text:
            raise TtsConfigurationError("Doubao TTS text must not be empty")
        voice_id = (request.voice_id or "").strip()
        if not voice_id:
            raise TtsInvalidVoiceError("Doubao V3 requires a voice_id")
        CapabilityResolver().validate_request(request, self.descriptor.models[0].capabilities)
        if request.speed is not None and not 0.1 <= request.speed <= 2.0:
            raise TtsConfigurationError("Doubao speed_ratio is out of range [0.1, 2.0]")
        if request.volume is not None and not 0.5 <= request.volume <= 2.0:
            raise TtsConfigurationError("Doubao loudness_ratio is out of range [0.5, 2.0]")
        if request.emotion is not None and not request.emotion.strip():
            raise TtsConfigurationError("Doubao emotion must not be empty")
        request_id = self._request_id_factory()
        headers = _V3.headers(api_key, request_id)
        payload = _V3.payload(request, voice_id=voice_id)
        try:
            stream_context = self._call_stream(
                self._transport,
                method="POST",
                url=_V3.endpoint,
                headers=headers,
                json=payload,
                timeout=timeout_sec,
            )
            with stream_context as response:
                _status_error(response, secrets=(api_key,), request_id=request_id)
                audio, audio_format, sample_rate = parse_doubao_v3_chunks(
                    _iter_response_bytes(response), secrets=(api_key,)
                )
                response_request_id = _credential_value(
                    getattr(response, "headers", {}), "X-Api-Request-Id", "x-api-request-id"
                )
        except (TtsAuthError, TtsRateLimitError, TtsQuotaError, TtsProviderResponseError):
            raise
        except (httpx.TimeoutException, TimeoutError, ConnectionError, OSError) as exc:
            raise TtsProviderNetworkError("Doubao V3 synthesis network request failed", cause=exc) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise TtsProviderResponseError("Doubao V3 response could not be decoded") from exc
        return TtsResult(
            audio_bytes=audio,
            audio_format=audio_format,
            sample_rate=sample_rate,
            provider_request_id=response_request_id or request_id,
        )


DoubaoTtsProvider = DoubaoProvider


__all__ = [
    "DOUBAO_LIST_SPEAKERS_ENDPOINT",
    "DOUBAO_MODEL_ID",
    "DOUBAO_MODEL_LABEL",
    "DOUBAO_PROVIDER_ID",
    "DOUBAO_TTS_ENDPOINT",
    "DoubaoProvider",
    "DoubaoTtsProvider",
    "DoubaoTransport",
    "build_list_speakers_signature",
    "parse_doubao_v3_chunks",
    "TtsProviderResponseError",
]
