"""Microphone capture test (metrics only, no audio logging)."""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

from app.mic_buffer import DEFAULT_MIC_SAMPLE_RATE, clamp_mic_window_sec
from app.mic_capture import MicCaptureService, default_input_device_label
from app.mic_encode import pcm_to_wav_data_uri
from app.mic_service import MicService

try:
    import sounddevice as sd

    _HAS_SOUNDDEVICE = True
except ImportError:  # pragma: no cover
    _HAS_SOUNDDEVICE = False
    sd = None  # type: ignore

MIN_TEST_SEC = 2
MAX_TEST_SEC = 8
SILENT_RMS = 80
QUIET_RMS = 400


@dataclass(frozen=True)
class MicTestResult:
    ok: bool
    message: str
    pcm_bytes: int = 0
    duration_sec: float = 0.0
    rms: int = 0
    peak: int = 0
    level: str = "error"
    wav_ok: bool = False
    capture_running: bool = False
    default_input: str = ""
    error: str = ""


def clamp_test_duration(seconds: float) -> float:
    return float(max(MIN_TEST_SEC, min(MAX_TEST_SEC, seconds)))


def pcm_metrics(pcm: bytes) -> tuple[int, int]:
    """Return (rms, peak) for int16 mono PCM."""
    if not pcm or len(pcm) < 4:
        return 0, 0
    count = len(pcm) // 2
    samples = struct.unpack(f"<{count}h", pcm[: count * 2])
    if not samples:
        return 0, 0
    peak = max(abs(s) for s in samples)
    mean_sq = sum(s * s for s in samples) / len(samples)
    rms = int(mean_sq**0.5)
    return rms, peak


def _level_label(rms: int, pcm_bytes: int) -> str:
    if pcm_bytes < DEFAULT_MIC_SAMPLE_RATE * 2 // 10:
        return "error"
    if rms < SILENT_RMS:
        return "silent"
    if rms < QUIET_RMS:
        return "quiet"
    return "good"


def _message_for(level: str, *, rms: int, wav_ok: bool, device: str) -> str:
    device_bit = f"（{device}）" if device else ""
    if level == "good" and wav_ok:
        return f"麦克风正常{device_bit}，已收到语音输入（电平 rms={rms}）"
    if level == "quiet" and wav_ok:
        return f"已录到音频但音量偏低{device_bit}，请靠近麦克风或提高系统输入音量（rms={rms}）"
    if level == "silent":
        return f"几乎未检测到声音{device_bit}，请检查系统默认录音设备与权限（rms={rms}）"
    if not wav_ok:
        return f"录音缓冲过短{device_bit}，请重试并多讲几句"
    return f"测试完成{device_bit}（rms={rms}）"


def capture_mic_sample(
    mic_service: MicService,
    duration_sec: float = 3.0,
    *,
    keep_running: bool = False,
) -> tuple[bytes, MicTestResult]:
    """Record a short PCM sample and return metrics (no AI call)."""
    duration = clamp_test_duration(duration_sec)
    device = default_input_device_label()

    if not MicCaptureService.is_available():
        result = MicTestResult(
            ok=False,
            message="未安装 sounddevice，无法测试麦克风",
            error="sounddevice_unavailable",
            default_input=device,
        )
        return b"", result

    temp_start = not mic_service.is_running()
    if temp_start and not mic_service.ensure_capture():
        err = mic_service.last_error() or "capture_start_failed"
        result = MicTestResult(
            ok=False,
            message=f"无法打开麦克风：{err}",
            error=err,
            default_input=device,
        )
        return b"", result

    mic_service.clear_buffer()
    time.sleep(duration)

    window = clamp_mic_window_sec(int(duration) + 1, maximum=MAX_TEST_SEC + 2)
    pcm = mic_service.snapshot_pcm(window)
    rms, peak = pcm_metrics(pcm)
    wav_ok = pcm_to_wav_data_uri(pcm) is not None
    level = _level_label(rms, len(pcm))
    ok = wav_ok and level in ("good", "quiet")
    message = _message_for(level, rms=rms, wav_ok=wav_ok, device=device)

    if temp_start and not keep_running:
        mic_service.stop()

    result = MicTestResult(
        ok=ok,
        message=message,
        pcm_bytes=len(pcm),
        duration_sec=duration,
        rms=rms,
        peak=peak,
        level=level,
        wav_ok=wav_ok,
        capture_running=mic_service.is_running(),
        default_input=device,
    )
    return pcm, result


def run_mic_test(
    mic_service: MicService,
    duration_sec: float = 3.0,
    *,
    keep_running: bool = False,
) -> MicTestResult:
    _, result = capture_mic_sample(
        mic_service,
        duration_sec,
        keep_running=keep_running,
    )
    return result
