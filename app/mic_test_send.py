"""Record microphone audio and send one probe request (Doubao Responses or MiMo Chat)."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image

from app.mic_encode import pcm_to_wav_data_uri
from app.model_providers import model_supports_mic_audio, resolve_api_transport
from app.translations import tr

_TEST_USER_PT = "听得见吗？跟我打个招呼"
_PREVIEW_MAX_LEN = 200
_AUDIO_MODEL_HINT = "请确认当前模型支持音频理解（纯视觉 flash 模型可能无法处理 input_audio）。"
_MIC_UNSUPPORTED_MSG = (
    "当前配置不支持麦克风音频。"
    "开麦请使用火山方舟豆包全模态模型（如 doubao-seed-2-0-mini-260428）"
    "或小米 MiMo 的 mimo-v2.5。"
)


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
    error: str = ""


def placeholder_image_data_uri() -> str:
    image = Image.new("RGB", (64, 64), (128, 128, 128))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=85)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def send_mic_probe(
    config,
    ai_worker,
    image_data_uri: str,
    user_pt: str,
    audio_data_uri: str,
) -> MicSendProbeResult:
    resolved = ai_worker._resolve_request_credentials()
    if resolved is None:
        return MicSendProbeResult(
            ok=False,
            message=tr("custom_model.error_incomplete"),
            error="incomplete_credentials",
        )

    endpoint, _, model_id, api_mode = resolved
    if not model_supports_mic_audio(model_id, endpoint=endpoint, api_mode=api_mode):
        return MicSendProbeResult(
            ok=False,
            message=(
                f"当前模型「{model_id}」可能不支持 input_audio。"
                f"开麦建议改用 doubao-seed-2-0-mini-260428 或 mimo-v2.5。{_AUDIO_MODEL_HINT}"
            ),
            error="unsupported_model",
        )

    captured = {
        "signal": "",
        "message": "",
        "input_tokens": 0,
        "output_tokens": 0,
    }
    original_emit = ai_worker._emit_result

    def capture_emit(
        signal_name: str,
        message: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        captured["signal"] = signal_name
        captured["message"] = message
        captured["input_tokens"] = input_tokens
        captured["output_tokens"] = output_tokens

    ai_worker._emit_result = capture_emit
    try:
        if resolve_api_transport(endpoint, api_mode) == "doubao":
            ai_worker._request_doubao(
                image_data_uri,
                "",
                user_pt,
                "mic_probe",
                0,
                0,
                0.0,
                0,
                audio_data_uri=audio_data_uri,
                resolved=resolved,
            )
        else:
            ai_worker._request(
                image_data_uri,
                "",
                user_pt,
                "mic_probe",
                0,
                0,
                0.0,
                0,
                audio_data_uri=audio_data_uri,
            )
    finally:
        ai_worker._emit_result = original_emit

    if captured["signal"] == "finished" and captured["message"].strip():
        preview = captured["message"].strip()
        if len(preview) > _PREVIEW_MAX_LEN:
            preview = preview[:_PREVIEW_MAX_LEN] + "…"
        return MicSendProbeResult(
            ok=True,
            message=(
                f"发送成功（input={captured['input_tokens']} · "
                f"output={captured['output_tokens']}）"
            ),
            input_tokens=captured["input_tokens"],
            output_tokens=captured["output_tokens"],
            reply_preview=preview,
        )

    message = captured["message"] or tr("ai.error_empty_response")
    if captured["signal"] != "finished":
        if message == tr("ai.error_empty_response"):
            message = f"{message} {_AUDIO_MODEL_HINT}"
        error = "api_error"
    else:
        error = "empty_response"

    return MicSendProbeResult(
        ok=False,
        message=message,
        input_tokens=captured["input_tokens"],
        output_tokens=captured["output_tokens"],
        error=error,
    )


def run_mic_test_send(danmu_app, duration_sec: float = 3.0) -> MicTestSendResult:
    if not danmu_app.mic_audio_supported():
        return MicTestSendResult(
            ok=False,
            message=_MIC_UNSUPPORTED_MSG,
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
            error=capture.error or "capture_failed",
        )

    audio_uri = pcm_to_wav_data_uri(pcm)
    if not audio_uri:
        return MicTestSendResult(
            ok=False,
            message="音频编码失败，请重试",
            pcm_bytes=len(pcm),
            rms=capture.rms,
            level=capture.level,
            error="encode_failed",
        )

    user_pt = _TEST_USER_PT
    image_uri = placeholder_image_data_uri()
    probe = danmu_app.send_mic_test_probe(
        image_uri,
        user_pt,
        audio_uri,
    )

    ok = probe.ok and capture.level in ("good", "quiet")
    if probe.ok:
        message = (
            f"{probe.message}；模型回复：{probe.reply_preview}"
            if probe.reply_preview
            else probe.message
        )
        if capture.level == "silent":
            message = f"API 已收到请求，但本地录音几乎无声（rms={capture.rms}）。{probe.message}"
            ok = False
        elif capture.level == "quiet":
            message = f"API 已收到请求，但本地音量偏低（rms={capture.rms}）。{probe.message}"
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
        error=probe.error,
    )
