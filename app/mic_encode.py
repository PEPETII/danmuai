"""Encode in-memory PCM to Responses API audio data URIs."""

from __future__ import annotations

import base64
import io
import wave

from app.mic_buffer import BYTES_PER_SAMPLE, DEFAULT_MIC_SAMPLE_RATE

MIN_PCM_BYTES = DEFAULT_MIC_SAMPLE_RATE * BYTES_PER_SAMPLE // 10  # ~100 ms


def pcm_to_wav_data_uri(
    pcm: bytes,
    *,
    sample_rate: int = DEFAULT_MIC_SAMPLE_RATE,
    channels: int = 1,
) -> str | None:
    """Return ``data:audio/wav;base64,...`` or None when PCM is too short."""
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
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:audio/wav;base64,{encoded}"
