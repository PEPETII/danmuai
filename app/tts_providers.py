"""读弹幕 TTS provider 注册表与适配层（MiMo 默认 + OpenAI-compat chat/audio）。

MiMo TTS + 播放链路：
1. ``DanmuReadService._pick_and_synthesize`` 抽样一条可见弹幕 → ``resolve_tts_config``。
2. ``synthesize_tts`` 按 ``resolved.provider`` 选 adapter：
   - ``mimo``：``MimoTtsAdapter`` → MiMo ``/chat/completions`` + ``audio: {format: wav, voice: ...}``，
     voice 走 ``MIMO_TTS_VOICES`` 白名单。
   - ``custom_openai``：``OpenAiCompatAudioTtsAdapter`` → 同结构，voice 字段自由。
3. 响应 ``choices[0].message.audio.data``（base64 WAV）→ ``DanmuTtsPlayback.play_wav_bytes``。

新增 provider：实现 ``TtsSynthesisAdapter`` 子类并注册到 ``_ADAPTERS``；不需改主链路。
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.model_providers import is_valid_endpoint, normalize_endpoint

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
TTS_PROBE_TEXT = "你好，这是一条读弹幕试听。"

TTS_PROVIDER_MIMO = "mimo"
TTS_PROVIDER_CUSTOM_OPENAI = "custom_openai"


class DanmuTtsError(Exception):
    """TTS 请求或响应解析失败。"""


def tts_audio_unsupported_message(model_id: str) -> str:
    """读弹幕为 TTS 链路；普通 chat 模型响应无 message.audio.data 时提示用户。"""
    mid = (model_id or "").strip() or "?"
    return (
        f"当前 provider/model「{mid}」不支持读弹幕 TTS 音频输出。"
        "请使用支持 chat/completions 且响应含 message.audio.data 的 TTS 模型"
        "（如小米 MiMo mimo-v2.5-tts）；普通聊天/视觉模型无法朗读。"
    )


def _extract_http_error_message(exc: httpx.HTTPStatusError) -> str:
    try:
        err_body = exc.response.json()
    except Exception:
        return ""
    if not isinstance(err_body, dict):
        return ""
    message = err_body.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    err = err_body.get("error")
    if isinstance(err, dict):
        nested = err.get("message")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
        code = err.get("code")
        if code is not None:
            return str(code)
    if isinstance(err, str) and err.strip():
        return err.strip()
    return ""


def normalize_tts_voice(voice: str | None) -> str:
    raw = (voice or "").strip()
    if raw in MIMO_TTS_VOICES:
        return raw
    return DEFAULT_TTS_VOICE


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
        id=TTS_PROVIDER_CUSTOM_OPENAI,
        label_zh="自定义（OpenAI 兼容）",
        default_endpoint="",
        default_model="",
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
    return _TTS_PROVIDER_BY_ID.get((provider_id or "").strip())


def _stored_custom_fields(config) -> tuple[str, str, str]:
    provider = (config.get("tts_provider") or "").strip()
    endpoint = normalize_endpoint(config.get("tts_endpoint") or "")
    model_id = (config.get("tts_model_id") or "").strip()
    return provider, endpoint, model_id


def is_custom_tts_config(provider: str, endpoint: str, model_id: str) -> bool:
    return bool(provider or endpoint or model_id)


def validate_custom_tts_fields(
    provider: str,
    endpoint: str,
    model_id: str,
) -> None:
    """自定义模式要求 endpoint 与 model_id 均非空且 URL 合法。"""
    if not is_custom_tts_config(provider, endpoint, model_id):
        return
    if not endpoint:
        raise ValueError("API 地址不能为空")
    if not model_id:
        raise ValueError("模型名称不能为空")
    if not is_valid_endpoint(endpoint):
        raise ValueError("API 地址格式无效")


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

    if not is_custom_tts_config(provider, endpoint, model_id):
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

    validate_custom_tts_fields(provider, endpoint, model_id)
    resolved_provider = provider or TTS_PROVIDER_CUSTOM_OPENAI
    return ResolvedTtsConfig(
        provider=resolved_provider,
        endpoint=endpoint,
        model=model_id,
        is_custom=True,
        stored_provider=provider,
        stored_endpoint=endpoint,
        stored_model_id=model_id,
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
        raise DanmuTtsError("朗读文本为空")

    messages: list[dict[str, str]] = []
    style = (style_prompt or "").strip()
    if style:
        messages.append({"role": "user", "content": style})
    messages.append({"role": "assistant", "content": content})

    voice_value = (
        normalize_tts_voice(voice) if normalize_voice else (voice or DEFAULT_TTS_VOICE).strip()
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
        raise DanmuTtsError("未配置 TTS API Key")

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
        raise DanmuTtsError("TTS 请求超时") from exc
    except httpx.HTTPStatusError as exc:
        detail = _extract_http_error_message(exc)
        code = exc.response.status_code
        raise DanmuTtsError(detail or f"TTS HTTP {code}") from exc
    except httpx.HTTPError as exc:
        raise DanmuTtsError(f"TTS 网络错误: {exc}") from exc

    try:
        return _decode_audio_wav_from_body(body, model_id=resolved.model)
    except DanmuTtsError:
        raise
    except Exception as exc:
        logger.debug("tts response parse failed: %s", exc)
        raise DanmuTtsError("TTS 响应解析失败") from exc


def _decode_audio_wav_from_body(body: dict[str, Any], *, model_id: str) -> bytes:
    """解析 chat/completions 响应中的 base64 WAV；文本-only 响应给出 TTS 能力提示。"""
    choices = body.get("choices") or []
    if not choices:
        raise DanmuTtsError("TTS 响应无音频数据")
    message = choices[0].get("message") or {}
    audio = message.get("audio") or {}
    data_b64 = audio.get("data") or ""
    if data_b64:
        return base64.b64decode(data_b64)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        raise DanmuTtsError(tts_audio_unsupported_message(model_id))
    raise DanmuTtsError("TTS 响应无音频数据")


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


class OpenAiCompatAudioTtsAdapter:
    """OpenAI-compat chat/completions + message.audio.data（与 MiMo TTS 同结构）。"""

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
            normalize_voice=False,
        )
        return _post_chat_audio(api_key, resolved, payload, timeout_sec=timeout_sec)


_ADAPTERS: dict[str, TtsSynthesisAdapter] = {
    TTS_PROVIDER_MIMO: MimoTtsAdapter(),
    TTS_PROVIDER_CUSTOM_OPENAI: OpenAiCompatAudioTtsAdapter(),
}


def get_tts_adapter(provider_id: str) -> TtsSynthesisAdapter:
    adapter = _ADAPTERS.get(provider_id)
    if adapter is not None:
        return adapter
    return _ADAPTERS[TTS_PROVIDER_CUSTOM_OPENAI]


def synthesize_tts(
    api_key: str,
    text: str,
    *,
    resolved: ResolvedTtsConfig,
    style_prompt: str = "",
    voice: str = DEFAULT_TTS_VOICE,
    timeout_sec: float = 60.0,
) -> bytes:
    adapter = get_tts_adapter(resolved.provider)
    return adapter.synthesize(
        api_key,
        text,
        resolved=resolved,
        style_prompt=style_prompt,
        voice=voice,
        timeout_sec=timeout_sec,
    )
