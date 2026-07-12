"""Record microphone audio and send one probe request (Doubao Responses or MiMo Chat).

W-AUDIT-FIX-002 改进：通过 DanmuApp 公开 facade 访问麦克风（``app.run_mic_test``），
避免直接读 ``DanmuApp._mic_service`` 私有字段。HTTP 线程经 ``WebConsoleBridge.invoke_on_main``
回到主线程执行采集与发送，不在 HTTP 线程直接调用 sounddevice。
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image

from app.ai_client import AiProbeResult
from app.mic_encode import pcm_to_wav_data_uri
from app.model_providers import mic_audio_unsupported_message, model_supports_mic_audio
from app.translations import tr

_TEST_USER_PT = tr("micTestSend.probePrompt")
_PREVIEW_MAX_LEN = 200
_AUDIO_MODEL_HINT = tr("micTestSend.audioModelHint")

def _mic_unsupported_config_message(model_id: str = "") -> str:
    if model_id:
        return mic_audio_unsupported_message(model_id)
    return tr("micTestSend.unsupportedConfig")
@dataclass(frozen=True)
class MicSendProbeResult:
    ok: bool
    message: str
    input_tokens: int = 0
    output_tokens: int = 0
    reply_preview: str = ""
    error: str = ""


@dataclass(frozen=True)
class MicTestSendResult:
    ok: bool
    message: str
    pcm_bytes: int = 0
    rms: int = 0
    level: str = ""
    audio_attached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    reply_preview: str = ""
    used_placeholder_image: bool = True
    active_input_device_id: int | None = None
    active_input_device_label: str = ""
    default_input: str = ""
    fallback_to_default: bool = False
    error: str = ""


def placeholder_image_data_uri() -> str:
    image = Image.new("RGB", (64, 64), (128, 128, 128))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _resolve_supports_mic_declared(danmu_app, model_id: str):
    from app.model_providers import custom_model_profile_id, find_custom_model_profile

    try:
        config = danmu_app.config
    except (AttributeError, RuntimeError):
        return None
    if config is None or not hasattr(config, "get_custom_models"):
        return None
    default_id = (config.get_default_model_id() or "").strip()
    if default_id != (model_id or "").strip():
        return None
    entry = find_custom_model_profile(config.get_custom_models(), default_id)
    if entry is None:
        return None
    return entry.get("supportsMic")


def _probe_result_from_ai(outcome: AiProbeResult) -> MicSendProbeResult:
    if outcome.signal == "finished" and outcome.message.strip():
        preview = outcome.message.strip()
        if len(preview) > _PREVIEW_MAX_LEN:
            preview = preview[:_PREVIEW_MAX_LEN] + "…"
        return MicSendProbeResult(
            ok=True,
            message=tr("micTestSend.sendSuccess").format(
                input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens
            ),
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            reply_preview=preview,
        )

    message = outcome.message or tr("ai.error_empty_response")
    if outcome.signal != "finished":
        if message == tr("ai.error_empty_response"):
            message = f"{message} {_AUDIO_MODEL_HINT}"
        error = "api_error"
    else:
        error = "empty_response"

    return MicSendProbeResult(
        ok=False,
        message=message,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        error=error,
    )


def send_mic_probe(
    danmu_app,
    image_data_uri: str,
    user_pt: str,
    audio_data_uri: str,
) -> MicSendProbeResult:
    resolved = danmu_app.ai_worker.resolve_mic_request_credentials()
    if resolved is None:
        from app.ai_client_requests import format_mic_credential_error

        return MicSendProbeResult(
            ok=False,
            message=format_mic_credential_error(danmu_app.config),
            error="incomplete_credentials",
        )

    endpoint, _, model_id, api_mode = resolved
    supports_declared = _resolve_supports_mic_declared(danmu_app, model_id)
    if not model_supports_mic_audio(
        model_id,
        endpoint=endpoint,
        api_mode=api_mode,
        supports_mic_declared=supports_declared,
    ):
        return MicSendProbeResult(
            ok=False,
            message=f"{mic_audio_unsupported_message(model_id)} {_AUDIO_MODEL_HINT}",
            error="unsupported_model",
        )

    outcome = danmu_app.run_mic_probe_in_pool(
        image_data_uri,
        user_pt,
        audio_data_uri,
    )
    return _probe_result_from_ai(outcome)


def run_mic_test_send(danmu_app, duration_sec: float = 3.0) -> MicTestSendResult:
    if not danmu_app.mic_audio_supported():
        resolved = danmu_app.ai_worker.resolve_mic_request_credentials()
        model_id = resolved[2] if resolved else ""
        return MicTestSendResult(
            ok=False,
            message=_mic_unsupported_config_message(model_id),
            error="unsupported_api_mode",
        )

    from app.mic_service import mic_mode_enabled

    keep_running = mic_mode_enabled(danmu_app.config)
    pcm, capture = danmu_app.capture_mic_test_sample(
        duration_sec,
        keep_running=keep_running,
    )
    if not capture.wav_ok:
        return MicTestSendResult(
            ok=False,
            message=capture.message,
            pcm_bytes=capture.pcm_bytes,
            rms=capture.rms,
            level=capture.level,
            active_input_device_id=capture.active_input_device_id,
            active_input_device_label=capture.active_input_device_label,
            default_input=capture.default_input,
            fallback_to_default=capture.fallback_to_default,
            error=capture.error or "capture_failed",
        )

    audio_uri = pcm_to_wav_data_uri(pcm)
    if not audio_uri:
        return MicTestSendResult(
            ok=False,
            message=tr("micTestSend.encodeFailed"),
            pcm_bytes=len(pcm),
            rms=capture.rms,
            level=capture.level,
            active_input_device_id=capture.active_input_device_id,
            active_input_device_label=capture.active_input_device_label,
            default_input=capture.default_input,
            fallback_to_default=capture.fallback_to_default,
            error="encode_failed",
        )

    user_pt = _TEST_USER_PT
    image_uri = placeholder_image_data_uri()
    probe = send_mic_probe(
        danmu_app,
        image_uri,
        user_pt,
        audio_uri,
    )

    ok = probe.ok and capture.level in ("good", "quiet")
    if probe.ok:
        if probe.reply_preview:
            message = tr("micTestSend.replyWithPreview").format(
                probe_message=probe.message, reply_preview=probe.reply_preview
            )
        else:
            message = probe.message
        if capture.level == "silent":
            message = tr("micTestSend.silentRecording").format(
                rms=capture.rms, probe_message=probe.message
            )
            ok = False
        elif capture.level == "quiet":
            message = tr("micTestSend.lowVolumeRecording").format(
                rms=capture.rms, probe_message=probe.message
            )
    else:
        message = probe.message

    return MicTestSendResult(
        ok=ok,
        message=message,
        pcm_bytes=len(pcm),
        rms=capture.rms,
        level=capture.level,
        audio_attached=True,
        input_tokens=probe.input_tokens,
        output_tokens=probe.output_tokens,
        reply_preview=probe.reply_preview,
        used_placeholder_image=True,
        active_input_device_id=capture.active_input_device_id,
        active_input_device_label=capture.active_input_device_label,
        default_input=capture.default_input,
        fallback_to_default=capture.fallback_to_default,
        error=probe.error,
    )
