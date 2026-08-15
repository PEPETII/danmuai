"""Safe WAV/PCM normalization for provider-neutral playback."""

from __future__ import annotations

import io
import wave

from app.tts.types import TtsAudioDecodeError, TtsResult


def _validate_pcm_shape(
    data: bytes,
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> None:
    if not data:
        raise TtsAudioDecodeError("TTS PCM audio is empty")
    if sample_rate <= 0:
        raise TtsAudioDecodeError("TTS PCM sample rate must be positive")
    if channels <= 0:
        raise TtsAudioDecodeError("TTS PCM channel count must be positive")
    if sample_width not in (1, 2, 3, 4):
        raise TtsAudioDecodeError("TTS PCM sample width is unsupported")
    frame_width = channels * sample_width
    if len(data) % frame_width:
        raise TtsAudioDecodeError("TTS PCM bytes do not contain complete frames")


def pcm_to_wav(
    pcm: bytes,
    *,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Wrap validated little-endian PCM in a canonical WAV container."""

    try:
        data = bytes(pcm)
    except (TypeError, ValueError) as exc:
        raise TtsAudioDecodeError("TTS PCM audio must be bytes-like") from exc
    _validate_pcm_shape(
        data,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(data)
    return output.getvalue()


def _validate_wav(data: bytes) -> tuple[int, int, int]:
    if not data:
        raise TtsAudioDecodeError("TTS WAV audio is empty")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise TtsAudioDecodeError("Compressed TTS WAV audio is unsupported")
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            if channels <= 0 or sample_rate <= 0 or sample_width not in (1, 2, 3, 4):
                raise TtsAudioDecodeError("TTS WAV metadata is invalid")
            if frame_count <= 0:
                raise TtsAudioDecodeError("TTS WAV audio has no frames")
            return sample_rate, channels, sample_width
    except TtsAudioDecodeError:
        raise
    except (EOFError, OSError, ValueError, wave.Error) as exc:
        raise TtsAudioDecodeError("TTS WAV container is invalid") from exc


def normalize_audio(
    audio_bytes: bytes,
    audio_format: str,
    *,
    sample_rate: int | None = None,
    channels: int = 1,
    sample_width: int = 2,
) -> tuple[bytes, int]:
    """Return validated WAV bytes and the effective sample rate."""

    try:
        data = bytes(audio_bytes)
    except (TypeError, ValueError) as exc:
        raise TtsAudioDecodeError("TTS audio must be bytes-like") from exc
    fmt = (audio_format or "").strip().lower().replace("audio/", "")
    if fmt in {"wav", "x-wav"}:
        rate, _channels, _sample_width = _validate_wav(data)
        if sample_rate is not None and sample_rate <= 0:
            raise TtsAudioDecodeError("TTS sample rate must be positive")
        if sample_rate is not None and sample_rate != rate:
            raise TtsAudioDecodeError("TTS WAV sample rate metadata does not match its header")
        return data, rate
    if fmt in {"pcm", "raw", "pcm_s16le", "pcm_s24le", "pcm_s32le"}:
        rate = sample_rate or 24000
        wav_data = pcm_to_wav(
            data,
            sample_rate=rate,
            channels=channels,
            sample_width=sample_width,
        )
        return wav_data, rate
    raise TtsAudioDecodeError(f"Unsupported TTS audio format: {audio_format}")


def normalize_tts_result(result: TtsResult) -> TtsResult:
    wav_data, sample_rate = normalize_audio(
        result.audio_bytes,
        result.audio_format,
        sample_rate=result.sample_rate,
    )
    return TtsResult(
        audio_bytes=wav_data,
        audio_format="wav",
        sample_rate=sample_rate,
        provider_request_id=result.provider_request_id,
    )


class AudioNormalizer:
    def normalize(self, result: TtsResult) -> TtsResult:
        return normalize_tts_result(result)


__all__ = ["AudioNormalizer", "normalize_audio", "normalize_tts_result", "pcm_to_wav"]
