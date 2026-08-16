"""DashScope TTS provider for the TTS V2 framework.

The provider deliberately keeps the three DashScope protocols separate:

* Qwen3-TTS HTTP generation;
* Qwen3-TTS Realtime WebSocket events;
* CosyVoice HTTP/SSE synthesis.

Only the stable model aliases selected for TTS V2 are described here.  The
legacy ``app.tts_providers`` adapter remains a separate compatibility path.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

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

DASHSCOPE_PROVIDER_ID = "dashscope"
DASHSCOPE_QWEN_HTTP_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
    "multimodal-generation/generation"
)
DASHSCOPE_COSYVOICE_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
)
DASHSCOPE_REALTIME_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

QWEN3_TTS_FLASH = "qwen3-tts-flash"
QWEN3_TTS_INSTRUCT_FLASH = "qwen3-tts-instruct-flash"
QWEN3_TTS_FLASH_REALTIME = "qwen3-tts-flash-realtime"
QWEN3_TTS_INSTRUCT_FLASH_REALTIME = "qwen3-tts-instruct-flash-realtime"
QWEN_AUDIO_30_TTS_PLUS = "qwen-audio-3.0-tts-plus"
QWEN_AUDIO_30_TTS_FLASH = "qwen-audio-3.0-tts-flash"
QWEN3_TTS_VC = "qwen3-tts-vc-2026-01-22"
QWEN3_TTS_VD = "qwen3-tts-vd-2026-01-26"
COSYVOICE_V35_FLASH = "cosyvoice-v3.5-flash"
COSYVOICE_V35_PLUS = "cosyvoice-v3.5-plus"
_QWEN_LANGUAGES = (
    "zh-CN", "en-US", "de-DE", "it-IT", "pt-PT", "es-ES", "ja-JP", "ko-KR", "fr-FR", "ru-RU"
)

_QWEN_VOICES: tuple[VoiceDescriptor, ...] = (
    VoiceDescriptor(
        "Cherry", "芊悦", "阳光积极、亲切自然小姐姐", "female",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Serena", "苏瑶", "温柔小姐姐", "female",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Ethan", "晨煦", "标准普通话，带部分北方口音。阳光、温暖、活力、朝气", "male",
        languages=_QWEN_LANGUAGES,
        tags=("北方口音",),
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Chelsie", "千雪", "二次元虚拟女友", "female",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Momo", "茉兔", "撒娇搞怪，逗你开心", "female",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Vivian", "十三", "拽拽的、可爱的小暴躁", "female",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Moon", "月白", "率性帅气的月白", "male",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Maia", "四月", "知性与温柔的碰撞", "female",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Kai", "凯", "耳朵的一场SPA", "male",
        languages=_QWEN_LANGUAGES,
        source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "Nofish", "不吃鱼", "不会翘舌音的设计师", "male",
        languages=_QWEN_LANGUAGES,
        tags=("不卷舌",),
        source=VoiceSource.STATIC_CATALOG,
    ),
)

_QWEN_AUDIO_PLUS_VOICES: tuple[VoiceDescriptor, ...] = (
    VoiceDescriptor(
        "longanlingxin", "龙安灵心", "知心温暖音", "female", age_group="25",
        languages=("zh-CN", "en-US"), tags=("旗舰音色",), source=VoiceSource.STATIC_CATALOG,
    ),
    VoiceDescriptor(
        "longanlufeng", "龙安鲁风", "明亮开朗音", "male", age_group="25",
        languages=("zh-CN", "en-US"), tags=("旗舰音色",), source=VoiceSource.STATIC_CATALOG,
    ),
)

_QWEN_AUDIO_FLASH_VOICES: tuple[VoiceDescriptor, ...] = tuple(
    VoiceDescriptor(
        voice_id,
        name,
        description,
        gender,
        age_group=age_group,
        languages=("zh-CN", "en-US"),
        tags=("系统音色",),
        source=VoiceSource.STATIC_CATALOG,
    )
    for voice_id, name, description, age_group, gender in (
        ("longanfengyue", "龙安风悦", "自然亲切音", "30", "female"),
        ("longanyuanfei", "龙安元妃", "高傲妃子音", "30", "female"),
        ("longanlingxi", "龙安灵希", "可爱甜美音", "25", "female"),
        ("longanxiaoxin", "龙安小昕", "亲切活泼音", "22", "female"),
        ("longanhuan_v3.6", "龙安欢", None, "25", "female"),
        ("longjielidou_v3.6", "龙杰力豆", "天真男童", "5", "male"),
        ("longpaopao_v3.6", "龙泡泡", "软糯可爱音", "5", "female"),
        ("longhuohuo_v3.6", "龙火火", "顽皮少年音", "8", "male"),
        ("longchuanshu_v3.6", "龙川叔", "川普大叔音", "40", "male"),
        ("loongmary", "loongmary", "温暖英音", "20", "female"),
    )
)


def _model(
    model_id: str,
    label: str,
    *,
    transport: str,
    capabilities: TtsCapabilities,
    voices: tuple[VoiceDescriptor, ...] = (),
    recommended: bool = False,
    pricing: PricingDescriptor | None = None,
    tags: tuple[str, ...] = (),
    status: str = "active",
    replacement_model_id: str | None = None,
) -> ModelDescriptor:
    return ModelDescriptor(
        id=model_id,
        label=label,
        recommended=recommended,
        tags=tags,
        transport=transport,
        capabilities=capabilities,
        voices=voices,
        pricing=pricing or PricingDescriptor(),
        status=status,
        replacement_model_id=replacement_model_id,
    )


_QWEN_HTTP_CAPABILITIES = TtsCapabilities(output_formats=frozenset({"wav"}))
_QWEN_AUDIO_CAPABILITIES = TtsCapabilities(
    streaming=True,
    style_prompt=True,
    custom_voice_id=True,
    voice_clone=True,
    output_formats=frozenset({"wav", "mp3", "pcm"}),
    notes=(
        "官方支持 HTTP/WebSocket、free-style 自然语言指令和细粒度标签，可控制情绪、语气、角色、语速、音量与风格。",
        "系统音色按模型严格区分；另有 500+ 个声音复刻基础音色，未在静态目录中伪装成系统音色。",
    ),
)
_QWEN_INSTRUCT_CAPABILITIES = TtsCapabilities(
    style_prompt=True,
    output_formats=frozenset({"wav"}),
    notes=("使用 input.instructions；仅 Qwen3 Instruct Flash 支持自然语言指令控制。",),
)
_QWEN_REALTIME_CAPABILITIES = TtsCapabilities(
    streaming=True,
    speed=True,
    pitch=True,
    volume=True,
    output_formats=frozenset({"pcm", "wav"}),
    notes=(
        "Realtime 使用 WebSocket；Qwen3 Flash Realtime 不开放 instructions。",
        "speech_rate 0.5–2.0、volume 0–100、pitch_rate 0.5–2.0；旧 Qwen-TTS-Realtime 不支持这些参数。",
    ),
)
_QWEN_INSTRUCT_REALTIME_CAPABILITIES = TtsCapabilities(
    streaming=True,
    style_prompt=True,
    speed=True,
    pitch=True,
    volume=True,
    output_formats=frozenset({"pcm", "wav", "mp3", "opus"}),
    notes=(
        "session.update 参数：speech_rate 0.5–2.0、volume 0–100、pitch_rate 0.5–2.0。",
        "instructions 最多 1600 Token，仅支持中文和英文。",
    ),
)
_COSYVOICE_CAPABILITIES = TtsCapabilities(
    streaming=True,
    style_prompt=True,
    custom_voice_id=True,
    voice_clone=True,
    voice_design=True,
    output_formats=frozenset({"wav", "pcm"}),
    notes=(
        "CosyVoice v3.5 Flash/Plus 支持 instruction、声音复刻和声音设计；v3.5 系列没有固定系统音色。",
    ),
)


def _pricing(
    amount: float,
    source_url: str,
    *,
    note: str = "按输入字符计费。",
) -> PricingDescriptor:
    return PricingDescriptor(
        kind="paygo",
        currency="CNY",
        amount=amount,
        unit="10k_chars",
        display=f"¥{amount:g} / 1万字符",
        note=note,
        verified_at="2026-08-17",
        source=source_url,
        source_url=source_url,
    )


_QWEN3_FLASH_PRICING = _pricing(
    0.8, "https://help.aliyun.com/zh/model-studio/qwen3-tts-flash"
)
_QWEN3_INSTRUCT_PRICING = _pricing(
    0.8, "https://help.aliyun.com/zh/model-studio/qwen3-tts-instruct-flash"
)
_QWEN3_REALTIME_PRICING = _pricing(
    1.0, "https://help.aliyun.com/zh/model-studio/qwen3-tts-flash-realtime"
)
_QWEN3_INSTRUCT_REALTIME_PRICING = _pricing(
    1.0, "https://help.aliyun.com/zh/model-studio/qwen3-tts-instruct-flash-realtime"
)
_QWEN_AUDIO_PLUS_PRICING = _pricing(
    1.4, "https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-tts-plus"
)
_QWEN_AUDIO_FLASH_PRICING = _pricing(
    1.0, "https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-tts-flash"
)
_QWEN3_VC_PRICING = _pricing(
    0.8,
    "https://help.aliyun.com/zh/model-studio/qwen3-tts-vc",
    note="按输入字符计费；声音复刻创建音色另按官方规则计费（北京原价 0.01 元/个）。",
)
_QWEN3_VD_PRICING = _pricing(
    0.8,
    "https://help.aliyun.com/zh/model-studio/qwen3-tts-vd",
    note="按输入字符计费；声音设计创建音色另按官方规则计费（北京原价 0.2 元/个）。",
)

DASHSCOPE_MODELS: tuple[ModelDescriptor, ...] = (
    _model(
        QWEN3_TTS_FLASH,
        "Qwen3-TTS Flash",
        transport="qwen_http",
        capabilities=_QWEN_HTTP_CAPABILITIES,
        voices=_QWEN_VOICES,
        recommended=True,
        pricing=_QWEN3_FLASH_PRICING,
        tags=("current", "推荐", "HTTP"),
    ),
    _model(
        QWEN3_TTS_INSTRUCT_FLASH,
        "Qwen3-TTS Instruct Flash",
        transport="qwen_http",
        capabilities=_QWEN_INSTRUCT_CAPABILITIES,
        voices=_QWEN_VOICES,
        pricing=_QWEN3_INSTRUCT_PRICING,
        tags=("current", "自然语言指令", "HTTP"),
    ),
    _model(
        QWEN3_TTS_FLASH_REALTIME,
        "Qwen3-TTS Flash Realtime",
        transport="qwen_realtime",
        capabilities=_QWEN_REALTIME_CAPABILITIES,
        voices=_QWEN_VOICES,
        pricing=_QWEN3_REALTIME_PRICING,
        tags=("current", "Realtime", "流式"),
    ),
    _model(
        COSYVOICE_V35_FLASH,
        "CosyVoice v3.5 Flash",
        transport="cosyvoice_http",
        capabilities=_COSYVOICE_CAPABILITIES,
        pricing=_pricing(
            0.8,
            "https://help.aliyun.com/zh/model-studio/cosyvoice-v3-5-flash",
        ),
        tags=("current", "流式", "需动态音色/自定义音色"),
    ),
    _model(
        COSYVOICE_V35_PLUS,
        "CosyVoice v3.5 Plus",
        transport="cosyvoice_http",
        capabilities=_COSYVOICE_CAPABILITIES,
        pricing=_pricing(
            1.5,
            "https://help.aliyun.com/zh/model-studio/cosyvoice-v3-5-plus",
        ),
        tags=("current", "流式", "需动态音色/自定义音色"),
    ),
    _model(
        QWEN_AUDIO_30_TTS_PLUS,
        "Qwen-Audio 3.0 TTS Plus（目录）",
        transport="catalog_only",
        capabilities=_QWEN_AUDIO_CAPABILITIES,
        voices=_QWEN_AUDIO_PLUS_VOICES,
        pricing=_QWEN_AUDIO_PLUS_PRICING,
        tags=("current", "官方可用", "需单独接入"),
        status="catalog_only",
    ),
    _model(
        QWEN_AUDIO_30_TTS_FLASH,
        "Qwen-Audio 3.0 TTS Flash（目录）",
        transport="catalog_only",
        capabilities=_QWEN_AUDIO_CAPABILITIES,
        voices=_QWEN_AUDIO_FLASH_VOICES,
        pricing=_QWEN_AUDIO_FLASH_PRICING,
        tags=("current", "官方可用", "需单独接入"),
        status="catalog_only",
    ),
    _model(
        QWEN3_TTS_INSTRUCT_FLASH_REALTIME,
        "Qwen3-TTS Instruct Flash Realtime（目录）",
        transport="qwen_realtime",
        capabilities=_QWEN_INSTRUCT_REALTIME_CAPABILITIES,
        voices=_QWEN_VOICES,
        pricing=_QWEN3_INSTRUCT_REALTIME_PRICING,
        tags=("current", "官方可用", "需单独接入", "流式"),
        status="catalog_only",
    ),
    _model(
        QWEN3_TTS_VC,
        "Qwen3-TTS Voice Clone（目录）",
        transport="catalog_only",
        capabilities=TtsCapabilities(
            custom_voice_id=True,
            voice_clone=True,
            output_formats=frozenset({"wav", "mp3"}),
            notes=("自定义音色必须与创建时的 target_model 一致，不能跨模型复用。",),
        ),
        pricing=_QWEN3_VC_PRICING,
        tags=("current", "官方可用", "需单独接入"),
        status="catalog_only",
    ),
    _model(
        QWEN3_TTS_VD,
        "Qwen3-TTS Voice Design（目录）",
        transport="catalog_only",
        capabilities=TtsCapabilities(
            custom_voice_id=True,
            voice_design=True,
            output_formats=frozenset({"wav", "mp3"}),
            notes=("自定义音色必须与创建时的 target_model 一致，不能跨模型复用。",),
        ),
        pricing=_QWEN3_VD_PRICING,
        tags=("current", "官方可用", "需单独接入"),
        status="catalog_only",
    ),
)

_MODELS_BY_ID = {model.id: model for model in DASHSCOPE_MODELS}


def _descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        id=DASHSCOPE_PROVIDER_ID,
        label="Alibaba Cloud DashScope",
        auth=AuthDescriptor(
            (AuthFieldDescriptor("api_key", "DashScope API Key", placeholder="sk-..."),)
        ),
        models=DASHSCOPE_MODELS,
    )


def _request_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("request_id", "requestId", "id"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
    return None


def _response_request_id(response: Any, body: Any = None) -> str | None:
    headers = getattr(response, "headers", {}) or {}
    for key in ("x-dashscope-request-id", "x-request-id", "request-id"):
        value = headers.get(key)
        if value:
            return str(value)
    return _request_id(body)


def _error_for_status(status: int, *, request_id: str | None = None) -> Exception:
    if status in (401, 403):
        return TtsAuthError("DashScope API Key 无效或无权限", provider_request_id=request_id)
    if status == 402:
        return TtsQuotaError("DashScope 额度不足", provider_request_id=request_id)
    if status == 429:
        return TtsRateLimitError("DashScope 请求过于频繁", provider_request_id=request_id)
    if status >= 500:
        return TtsProviderNetworkError(
            "DashScope 服务暂时不可用", provider_request_id=request_id
        )
    return TtsProviderResponseError(
        "DashScope 请求参数或模型不可用", provider_request_id=request_id
    )


def _decode_base64_audio(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if not isinstance(value, str) or not value.strip():
        raise TtsAudioDecodeError("DashScope 音频数据为空")
    encoded = value.strip()
    if encoded.startswith("data:"):
        try:
            encoded = encoded.split(",", 1)[1]
        except IndexError as exc:
            raise TtsAudioDecodeError("DashScope 音频 data URI 无效") from exc
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TtsAudioDecodeError("DashScope 音频 Base64 无效") from exc


def _audio_object(body: Mapping[str, Any]) -> Mapping[str, Any] | str | None:
    output = body.get("output")
    if isinstance(output, Mapping):
        audio = output.get("audio")
        if isinstance(audio, (Mapping, str)):
            return audio
    audio = body.get("audio")
    if isinstance(audio, (Mapping, str)):
        return audio
    return None


def _audio_format(audio: Mapping[str, Any], default: str = "wav") -> str:
    value = audio.get("format") or audio.get("audio_format") or default
    return str(value).strip().lower().replace("audio/", "")


def _download_audio(
    client: Any,
    url: str,
    *,
    timeout_sec: float,
    audio_format: str = "wav",
    request_id: str | None = None,
) -> TtsResult:
    try:
        response = client.get(url)
        status = int(getattr(response, "status_code", 200))
        if status >= 400:
            raise _error_for_status(status, request_id=request_id)
        data = bytes(getattr(response, "content", b""))
    except (TtsAuthError, TtsQuotaError, TtsRateLimitError, TtsProviderResponseError):
        raise
    except httpx.TimeoutException as exc:
        raise TtsProviderNetworkError("DashScope 音频下载超时", cause=exc) from exc
    except httpx.HTTPError as exc:
        raise TtsProviderNetworkError("DashScope 音频下载失败", cause=exc) from exc
    except OSError as exc:
        raise TtsProviderNetworkError("DashScope 音频下载失败", cause=exc) from exc
    except (TypeError, ValueError) as exc:
        raise TtsAudioDecodeError("DashScope 下载的音频无效") from exc
    if not data:
        raise TtsAudioDecodeError("DashScope 下载的音频为空")
    del timeout_sec
    return TtsResult(data, audio_format, provider_request_id=request_id)


def _result_from_body(
    body: Mapping[str, Any],
    *,
    client: Any,
    timeout_sec: float,
    default_format: str = "wav",
) -> TtsResult:
    request_id = _request_id(body)
    audio = _audio_object(body)
    if isinstance(audio, str):
        return _download_audio(
            client,
            audio,
            timeout_sec=timeout_sec,
            audio_format=default_format,
            request_id=request_id,
        )
    if not isinstance(audio, Mapping):
        raise TtsProviderResponseError(
            "DashScope 响应缺少音频", provider_request_id=request_id
        )
    url = audio.get("url")
    if isinstance(url, str) and url.strip():
        return _download_audio(
            client,
            url,
            timeout_sec=timeout_sec,
            audio_format=_audio_format(audio, default_format),
            request_id=request_id,
        )
    data = audio.get("data")
    if data:
        return TtsResult(
            _decode_base64_audio(data),
            _audio_format(audio, default_format),
            sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
            provider_request_id=request_id,
        )
    raise TtsProviderResponseError(
        "DashScope 响应缺少音频 URL 或数据", provider_request_id=request_id
    )


def parse_realtime_events(events: Iterable[Mapping[str, Any]]) -> tuple[bytes, str | None]:
    """Collect Qwen Realtime audio delta events without SDK or network access."""

    chunks: list[bytes] = []
    request_id: str | None = None
    for event in events:
        event_type = str(event.get("type", ""))
        request_id = request_id or _request_id(event)
        if event_type == "response.audio.delta":
            delta = event.get("delta") or event.get("audio")
            if delta:
                chunks.append(_decode_base64_audio(delta))
        elif event_type == "error":
            raise TtsProviderResponseError(
                "DashScope Realtime 返回错误", provider_request_id=request_id
            )
    if not chunks:
        raise TtsProviderResponseError(
            "DashScope Realtime 未返回音频", provider_request_id=request_id
        )
    return b"".join(chunks), request_id


def parse_sse_events(lines: Iterable[str | bytes]) -> Iterator[Mapping[str, Any]]:
    """Decode JSON ``data:`` SSE frames; protocol errors stay provider-local."""

    data_lines: list[str] = []

    def flush() -> Iterator[Mapping[str, Any]]:
        if not data_lines:
            return
        payload = "\n".join(data_lines)
        data_lines.clear()
        if payload == "[DONE]":
            return
        try:
            value = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise TtsProviderResponseError("DashScope SSE 数据格式无效") from exc
        if isinstance(value, Mapping):
            yield value
        else:
            raise TtsProviderResponseError("DashScope SSE 数据不是对象")

    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.rstrip("\r")
        if not line:
            yield from flush()
            continue
        if line.startswith(":") or line.startswith("event:"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    yield from flush()


class _RealtimeCollector:
    def __init__(self) -> None:
        self.events: list[Mapping[str, Any]] = []
        self.closed = False
        self.done = False

    def on_open(self) -> None:
        return None

    def on_close(self, *_args: Any) -> None:
        self.closed = True

    def on_event(self, response: Mapping[str, Any]) -> None:
        self.events.append(response)
        event_type = str(response.get("type", ""))
        if event_type in {"response.audio.done", "response.done", "session.finished"}:
            self.done = True


def _default_realtime_client(
    model_id: str, callback: _RealtimeCollector, url: str, api_key: str
) -> Any:
    try:
        import dashscope
        from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime
    except ImportError as exc:
        raise TtsConfigurationError("DashScope realtime SDK 不可用") from exc
    dashscope.api_key = api_key
    return QwenTtsRealtime(model=model_id, callback=callback, url=url)


@dataclass(frozen=True)
class _TransportContext:
    api_key: str
    request: TtsRequest
    model: ModelDescriptor
    timeout_sec: float
    client_factory: Callable[[float], Any] | None = None


def _new_http_client(context: _TransportContext) -> Any:
    if context.client_factory is not None:
        return context.client_factory(context.timeout_sec)
    return httpx.Client(
        timeout=httpx.Timeout(context.timeout_sec, connect=10.0),
    )


class _QwenHttpTransport:
    def synthesize(self, context: _TransportContext) -> TtsResult:
        request = context.request
        voice = request.voice_id or "Cherry"
        payload: dict[str, Any] = {
            "model": context.model.id,
            "input": {
                "text": request.text.strip(),
                "voice": voice,
                "language_type": "Chinese",
            },
        }
        if request.style_prompt:
            payload["input"]["instructions"] = request.style_prompt.strip()
            payload["input"]["optimize_instructions"] = True
        return _post_json_generation(
            DASHSCOPE_QWEN_HTTP_ENDPOINT,
            context,
            payload,
        )


class _CosyVoiceTransport:
    def synthesize(self, context: _TransportContext) -> TtsResult:
        request = context.request
        input_payload: dict[str, Any] = {
            "text": request.text.strip(),
            "format": request.output_format.strip().lower(),
            "sample_rate": 24000,
        }
        if request.voice_id:
            input_payload["voice"] = request.voice_id
        if request.style_prompt:
            input_payload["instruction"] = request.style_prompt.strip()
        payload = {"model": context.model.id, "input": input_payload}
        if request.streaming:
            return _post_cosyvoice_sse(context, payload)
        return _post_json_generation(
            DASHSCOPE_COSYVOICE_ENDPOINT,
            context,
            payload,
        )


class _QwenRealtimeTransport:
    def __init__(
        self,
        client_factory: Callable[[str, _RealtimeCollector, str, str], Any]
        | None = None,
    ) -> None:
        self.client_factory = client_factory or _default_realtime_client

    def synthesize(self, context: _TransportContext) -> TtsResult:
        collector = _RealtimeCollector()
        url = f"{DASHSCOPE_REALTIME_URL}?model={quote(context.model.id)}"
        try:
            client = self.client_factory(
                context.model.id, collector, url, context.api_key
            )
            client.connect()
            session_kwargs: dict[str, Any] = {
                "voice": context.request.voice_id or "Cherry",
                "response_format": "pcm",
                "sample_rate": 24000,
                "mode": "server_commit",
            }
            if context.request.style_prompt:
                session_kwargs["instructions"] = context.request.style_prompt.strip()
                session_kwargs["optimize_instructions"] = True
            if context.request.speed is not None:
                session_kwargs["speech_rate"] = context.request.speed
            if context.request.pitch is not None:
                session_kwargs["pitch_rate"] = context.request.pitch
            if context.request.volume is not None:
                session_kwargs["volume"] = context.request.volume
            client.update_session(**session_kwargs)
            client.append_text(context.request.text.strip())
            client.finish()
            deadline = time.monotonic() + context.timeout_sec
            while not collector.closed and not collector.done and time.monotonic() < deadline:
                time.sleep(0.01)
        except TtsAuthError:
            raise
        except (TtsConfigurationError, TtsProviderResponseError, TtsAudioDecodeError):
            raise
        except TimeoutError as exc:
            raise TtsProviderNetworkError("DashScope Realtime 超时", cause=exc) from exc
        except OSError as exc:
            raise TtsProviderNetworkError("DashScope Realtime 连接失败", cause=exc) from exc
        except Exception as exc:
            raise TtsProviderNetworkError("DashScope Realtime 请求失败", cause=exc) from exc
        if not collector.done and not collector.closed:
            raise TtsProviderNetworkError("DashScope Realtime 超时")
        audio, request_id = parse_realtime_events(collector.events)
        return TtsResult(audio, "pcm", sample_rate=24000, provider_request_id=request_id)


def _post_json_generation(
    endpoint: str,
    context: _TransportContext,
    payload: Mapping[str, Any],
) -> TtsResult:
    headers = {
        "Authorization": f"Bearer {context.api_key}",
        "Content-Type": "application/json",
    }
    try:
        with _new_http_client(context) as client:
            response = client.post(endpoint, json=dict(payload), headers=headers)
            status = int(getattr(response, "status_code", 200))
            if status >= 400:
                raise _error_for_status(
                    status, request_id=_response_request_id(response)
                )
            try:
                body = response.json()
            except (TypeError, ValueError) as exc:
                raise TtsProviderResponseError("DashScope JSON 响应无效") from exc
            if not isinstance(body, Mapping):
                raise TtsProviderResponseError("DashScope JSON 响应不是对象")
            try:
                result = _result_from_body(
                    body,
                    client=client,
                    timeout_sec=context.timeout_sec,
                    default_format=context.request.output_format,
                )
            except TtsAudioDecodeError:
                raise
            except (TypeError, ValueError, KeyError) as exc:
                raise TtsProviderResponseError("DashScope 音频响应字段无效") from exc
            if result.provider_request_id is None:
                result = TtsResult(
                    result.audio_bytes,
                    result.audio_format,
                    result.sample_rate,
                    _response_request_id(response, body),
                )
            return result
    except (
        TtsAuthError,
        TtsQuotaError,
        TtsRateLimitError,
        TtsProviderNetworkError,
        TtsProviderResponseError,
        TtsAudioDecodeError,
    ):
        raise
    except httpx.TimeoutException as exc:
        raise TtsProviderNetworkError("DashScope 请求超时", cause=exc) from exc
    except httpx.HTTPError as exc:
        raise TtsProviderNetworkError("DashScope 网络请求失败", cause=exc) from exc
    except OSError as exc:
        raise TtsProviderNetworkError("DashScope 网络请求失败", cause=exc) from exc


def _post_cosyvoice_sse(
    context: _TransportContext,
    payload: Mapping[str, Any],
) -> TtsResult:
    headers = {
        "Authorization": f"Bearer {context.api_key}",
        "Content-Type": "application/json",
        "X-DashScope-SSE": "enable",
    }
    chunks: list[bytes] = []
    request_id: str | None = None
    final_url: str | None = None
    try:
        with _new_http_client(context) as client:
            with client.stream(
                "POST",
                DASHSCOPE_COSYVOICE_ENDPOINT,
                json=dict(payload),
                headers=headers,
            ) as response:
                status = int(getattr(response, "status_code", 200))
                if status >= 400:
                    raise _error_for_status(
                        status, request_id=_response_request_id(response)
                    )
                for event in parse_sse_events(response.iter_lines()):
                    request_id = request_id or _request_id(event)
                    if event.get("type") == "error" or event.get("code"):
                        raise TtsProviderResponseError(
                            "DashScope CosyVoice SSE 返回错误",
                            provider_request_id=request_id,
                        )
                    audio = _audio_object(event)
                    if not isinstance(audio, Mapping):
                        continue
                    url = audio.get("url")
                    if isinstance(url, str) and url.strip():
                        final_url = url
                    data = audio.get("data")
                    if data:
                        chunks.append(_decode_base64_audio(data))
            if final_url:
                return _download_audio(
                    client,
                    final_url,
                    timeout_sec=context.timeout_sec,
                    audio_format=context.request.output_format,
                    request_id=request_id,
                )
    except (
        TtsAuthError,
        TtsQuotaError,
        TtsRateLimitError,
        TtsProviderNetworkError,
        TtsProviderResponseError,
        TtsAudioDecodeError,
    ):
        raise
    except httpx.TimeoutException as exc:
        raise TtsProviderNetworkError("DashScope CosyVoice SSE 超时", cause=exc) from exc
    except httpx.HTTPError as exc:
        raise TtsProviderNetworkError("DashScope CosyVoice SSE 失败", cause=exc) from exc
    except OSError as exc:
        raise TtsProviderNetworkError("DashScope CosyVoice SSE 失败", cause=exc) from exc
    if not chunks:
        raise TtsProviderResponseError(
            "DashScope CosyVoice SSE 未返回音频", provider_request_id=request_id
        )
    return TtsResult(
        b"".join(chunks),
        "pcm",
        sample_rate=24000,
        provider_request_id=request_id,
    )


class DashScopeProvider(BaseTtsProvider):
    """DashScope provider with catalog-driven transport dispatch."""

    def __init__(
        self,
        *,
        realtime_client_factory: Callable[[str, _RealtimeCollector, str, str], Any]
        | None = None,
        transport: httpx.BaseTransport | None = None,
        http_client_factory: Callable[[float], Any] | None = None,
    ) -> None:
        super().__init__(_descriptor())
        self._realtime = _QwenRealtimeTransport(realtime_client_factory)
        if http_client_factory is not None:
            self._http_client_factory = http_client_factory
        elif transport is not None:
            self._http_client_factory = lambda timeout_sec: httpx.Client(
                timeout=httpx.Timeout(timeout_sec, connect=10.0),
                transport=transport,
            )
        else:
            self._http_client_factory = None
        self._transports: dict[str, Any] = {
            "qwen_http": _QwenHttpTransport(),
            "qwen_realtime": self._realtime,
            "cosyvoice_http": _CosyVoiceTransport(),
        }

    def synthesize(
        self,
        credentials: Mapping[str, str],
        request: TtsRequest,
        *,
        timeout_sec: float = 60.0,
    ) -> TtsResult:
        self.validate_credentials(credentials)
        if request.provider_id.strip() != self.descriptor.id:
            raise TtsConfigurationError("TTS request provider does not match DashScope")
        text = (request.text or "").strip()
        if not text:
            raise TtsConfigurationError("TTS text must not be empty")
        model = _MODELS_BY_ID.get(request.model_id.strip())
        if model is None:
            raise TtsConfigurationError(
                f"Unknown DashScope TTS model: {request.model_id.strip()}"
            )
        self._validate_request(request, model)
        transport = self._transports.get(model.transport)
        if transport is None:
            raise TtsConfigurationError(f"Unsupported DashScope transport: {model.transport}")
        context = _TransportContext(
            credentials["api_key"].strip(),
            request,
            model,
            timeout_sec,
            self._http_client_factory,
        )
        return transport.synthesize(context)

    def _validate_request(self, request: TtsRequest, model: ModelDescriptor) -> None:
        if request.style_prompt and not model.capabilities.style_prompt:
            raise TtsUnsupportedCapabilityError("style_prompt")
        if request.streaming and not model.capabilities.streaming:
            raise TtsUnsupportedCapabilityError("streaming")
        if request.speed is not None and not 0.5 <= request.speed <= 2.0:
            raise TtsConfigurationError("DashScope speech_rate is out of range [0.5, 2.0]")
        if request.pitch is not None and not 0.5 <= request.pitch <= 2.0:
            raise TtsConfigurationError("DashScope pitch_rate is out of range [0.5, 2.0]")
        if request.volume is not None and not 0 <= request.volume <= 100:
            raise TtsConfigurationError("DashScope volume is out of range [0, 100]")
        output_format = request.output_format.strip().lower()
        if output_format not in model.capabilities.output_formats:
            raise TtsUnsupportedCapabilityError(f"output_format:{output_format}")
        voice_id = (request.voice_id or "").strip()
        if model.capabilities.custom_voice_id:
            return
        if voice_id and voice_id not in {voice.id for voice in model.voices}:
            raise TtsInvalidVoiceError(f"Unknown DashScope voice: {voice_id}")

    def list_voices(
        self,
        credentials: Mapping[str, str],
        *,
        model_id: str,
        force_refresh: bool = False,
    ) -> list[VoiceDescriptor]:
        del force_refresh
        self.validate_credentials(credentials)
        model = _MODELS_BY_ID.get(model_id.strip())
        if model is None:
            raise TtsConfigurationError(f"Unknown DashScope TTS model: {model_id.strip()}")
        return list(model.voices)


__all__ = [
    "COSYVOICE_V35_FLASH",
    "COSYVOICE_V35_PLUS",
    "DASHSCOPE_COSYVOICE_ENDPOINT",
    "DASHSCOPE_MODELS",
    "DASHSCOPE_PROVIDER_ID",
    "DASHSCOPE_QWEN_HTTP_ENDPOINT",
    "DASHSCOPE_REALTIME_URL",
    "DashScopeProvider",
    "QWEN3_TTS_FLASH",
    "QWEN3_TTS_FLASH_REALTIME",
    "QWEN3_TTS_INSTRUCT_FLASH",
    "parse_realtime_events",
    "parse_sse_events",
]
