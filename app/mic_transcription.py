"""Best-effort speech-to-text for microphone log entries.

Uses the mic credential bundle. OpenAI-compatible providers use
``/audio/transcriptions``; Doubao uses its existing Responses audio-input path
because Ark does not expose the OpenAI transcription route at its model endpoint.
Failures are returned to callers; they must not interrupt mic danmu flow.
"""

from __future__ import annotations

import base64
import io
import logging
import wave
from dataclasses import dataclass

import httpx

from app.ai_client_requests import resolve_mic_request_credentials
from app.doubao_responses_stream import extract_text_from_response
from app.mic_buffer import BYTES_PER_SAMPLE, DEFAULT_MIC_SAMPLE_RATE
from app.mic_encode import MIN_PCM_BYTES
from app.model_providers import normalize_endpoint, resolve_api_transport
from app.providers.request_planner import GenerationRequest, plan_http_request

logger = logging.getLogger(__name__)

DEFAULT_TRANSCRIPTION_MODEL = "whisper-1"
_TRANSCRIPTION_TIMEOUT_SEC = 25.0


@dataclass(frozen=True)
class MicTranscriptionResult:
    ok: bool
    text: str = ""
    error: str = ""


def pcm_to_wav_bytes(
    pcm: bytes,
    *,
    sample_rate: int = DEFAULT_MIC_SAMPLE_RATE,
    channels: int = 1,
) -> bytes | None:
    if not pcm or len(pcm) < MIN_PCM_BYTES:
        return None
    if len(pcm) % BYTES_PER_SAMPLE != 0:
        pcm = pcm[: len(pcm) - (len(pcm) % BYTES_PER_SAMPLE)]
    if not pcm:
        return None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(BYTES_PER_SAMPLE)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _transcription_url(endpoint: str) -> str:
    base = normalize_endpoint(endpoint).rstrip("/")
    for suffix in ("/responses", "/chat/completions", "/completions"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base}/audio/transcriptions"


def _wav_data_uri(wav_bytes: bytes) -> str:
    encoded = base64.b64encode(wav_bytes).decode("ascii")
    return f"data:audio/wav;base64,{encoded}"


def _transcribe_with_doubao(
    *,
    endpoint: str,
    api_key: str,
    model_id: str,
    api_mode: str,
    audio_data_uri: str,
    http_client: httpx.Client,
) -> MicTranscriptionResult:
    planned = plan_http_request(
        GenerationRequest(
            purpose="mic_danmu",
            model_id=model_id,
            endpoint=endpoint,
            api_key=api_key,
            api_mode=api_mode,
            user_text="请逐字转写这段音频中的人声。只返回转写文本，不要解释或补充内容。",
            audio_data_uri=audio_data_uri,
            stream=False,
            force_thinking_off=True,
            supports_mic_override=True,
        )
    )
    response = http_client.post(
        planned.url,
        headers=planned.headers,
        json=planned.json_body,
    )
    if response.status_code >= 400:
        snippet = (response.text or "")[:240]
        logger.info(
            "mic transcription http error status=%s endpoint=%s snippet=%r",
            response.status_code,
            planned.url,
            snippet,
        )
        return MicTranscriptionResult(ok=False, error=f"http_{response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        return MicTranscriptionResult(ok=False, error="invalid_response")
    text = extract_text_from_response(payload).strip()
    if not text:
        return MicTranscriptionResult(ok=False, error="empty_transcript")
    return MicTranscriptionResult(ok=True, text=text)


def transcribe_pcm(config, pcm: bytes, *, http_client: httpx.Client | None = None) -> MicTranscriptionResult:
    """Transcribe one utterance PCM buffer; safe to call from a worker thread."""
    wav_bytes = pcm_to_wav_bytes(pcm)
    if not wav_bytes:
        return MicTranscriptionResult(ok=False, error="audio_too_short")

    resolved = resolve_mic_request_credentials(config)
    if resolved is None:
        return MicTranscriptionResult(ok=False, error="incomplete_credentials")

    endpoint, api_key, model_id, api_mode = resolved

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=httpx.Timeout(_TRANSCRIPTION_TIMEOUT_SEC, connect=5.0))
    try:
        if resolve_api_transport(endpoint, api_mode) == "doubao":
            return _transcribe_with_doubao(
                endpoint=endpoint,
                api_key=api_key,
                model_id=model_id,
                api_mode=api_mode,
                audio_data_uri=_wav_data_uri(wav_bytes),
                http_client=client,
            )

        url = _transcription_url(endpoint)
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": ("utterance.wav", wav_bytes, "audio/wav")}
        data = {"model": DEFAULT_TRANSCRIPTION_MODEL}
        if model_id and "whisper" in model_id.lower():
            data["model"] = model_id
        response = client.post(url, headers=headers, data=data, files=files)
        if response.status_code >= 400:
            snippet = (response.text or "")[:240]
            logger.info(
                "mic transcription http error status=%s endpoint=%s snippet=%r",
                response.status_code,
                url,
                snippet,
            )
            return MicTranscriptionResult(ok=False, error=f"http_{response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            return MicTranscriptionResult(ok=False, error="invalid_response")
        text = str(payload.get("text") or "").strip()
        if not text:
            return MicTranscriptionResult(ok=False, error="empty_transcript")
        return MicTranscriptionResult(ok=True, text=text)
    except httpx.HTTPError as exc:
        logger.info("mic transcription request failed: %r", exc)
        return MicTranscriptionResult(ok=False, error=type(exc).__name__)
    except (TypeError, ValueError, KeyError) as exc:
        logger.info("mic transcription parse failed: %r", exc)
        return MicTranscriptionResult(ok=False, error="parse_error")
    finally:
        if owns_client:
            client.close()
