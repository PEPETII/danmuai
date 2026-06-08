import struct
import threading
import time
from types import SimpleNamespace

from app.mic_buffer import DEFAULT_MIC_SAMPLE_RATE, MicRingBuffer
from app.mic_capture import MicCaptureService
from app.mic_test import pcm_metrics
from app.mic_utterance import MicUtteranceConfig, MicUtteranceDetector, UtteranceState


def _pcm_with_rms(rms: int, duration_ms: int = 200) -> bytes:
    samples = max(1, duration_ms * DEFAULT_MIC_SAMPLE_RATE // 1000)
    amp = max(1, min(rms, 30_000))
    raw = struct.pack(f"<{samples}h", *([amp] * samples))
    actual_rms, _ = pcm_metrics(raw)
    if actual_rms < rms and rms > 0:
        amp = min(32_000, amp * max(2, rms // max(actual_rms, 1)))
        raw = struct.pack(f"<{samples}h", *([amp] * samples))
    return raw


def _silent_pcm(duration_ms: int = 200) -> bytes:
    samples = max(1, duration_ms * DEFAULT_MIC_SAMPLE_RATE // 1000)
    return struct.pack(f"<{samples}h", *([0] * samples))


def _finish_utterance(
    detector: MicUtteranceDetector,
    *,
    t0: float,
    speech_sec: float,
    silence_sec: float,
    loud_rms: int = 800,
) -> None:
    """Drive detector through speak → silence_pending → end (needs 2+ silence polls)."""
    detector.poll(_pcm_with_rms(loud_rms, int(speech_sec * 1000)), now=t0)
    silence_start = t0 + speech_sec
    detector.poll(_silent_pcm(100), now=silence_start)
    detector.poll(_silent_pcm(100), now=silence_start + silence_sec)


def test_utterance_detector_fires_after_speech_and_silence():
    fired = []

    detector = MicUtteranceDetector(
        on_utterance_end=lambda: fired.append(True),
        config=MicUtteranceConfig(
            speech_rms=200,
            silence_ms=300,
            min_speech_ms=200,
            cooldown_sec=10.0,
        ),
    )

    t0 = 1000.0
    _finish_utterance(detector, t0=t0, speech_sec=0.3, silence_sec=0.35)

    assert detector.state == UtteranceState.COOLDOWN
    assert fired == [True]


def test_utterance_detector_ignores_short_noise():
    fired = []

    detector = MicUtteranceDetector(
        on_utterance_end=lambda: fired.append(True),
        config=MicUtteranceConfig(
            speech_rms=200,
            silence_ms=200,
            min_speech_ms=400,
            cooldown_sec=10.0,
        ),
    )

    t0 = 2000.0
    _finish_utterance(detector, t0=t0, speech_sec=0.1, silence_sec=0.25, loud_rms=900)

    assert fired == []
    assert detector.state == UtteranceState.IDLE


def test_utterance_detector_cooldown_blocks_repeat():
    fired = []

    detector = MicUtteranceDetector(
        on_utterance_end=lambda: fired.append(True),
        config=MicUtteranceConfig(
            speech_rms=200,
            silence_ms=200,
            min_speech_ms=200,
            cooldown_sec=5.0,
        ),
    )

    t0 = 3000.0
    _finish_utterance(detector, t0=t0, speech_sec=0.25, silence_sec=0.25)
    assert len(fired) == 1

    _finish_utterance(detector, t0=t0 + 1.0, speech_sec=0.25, silence_sec=0.25)
    assert len(fired) == 1

    _finish_utterance(detector, t0=t0 + 6.0, speech_sec=0.25, silence_sec=0.25)
    assert len(fired) == 2


def test_utterance_with_high_noise_floor():
    fired = []

    detector = MicUtteranceDetector(
        on_utterance_end=lambda: fired.append(True),
        config=MicUtteranceConfig(
            speech_rms=400,
            silence_ms=300,
            min_speech_ms=250,
            cooldown_sec=10.0,
        ),
    )
    detector.set_noise_floor(350)

    t0 = 5000.0
    detector.poll(_pcm_with_rms(360), now=t0)
    assert detector.state == UtteranceState.IDLE

    _finish_utterance(detector, t0=t0 + 0.1, speech_sec=0.35, silence_sec=0.35, loud_rms=900)

    assert fired == [True]


def test_utterance_poll_does_not_block_audio_callback():
    cap = MicCaptureService()
    stop = threading.Event()
    chunk = b"\x00\x01" * 400

    def append_loop() -> None:
        while not stop.is_set():
            cap._buffer.append(chunk)

    worker = threading.Thread(target=append_loop, daemon=True)
    worker.start()
    try:
        for _ in range(50):
            start = time.perf_counter()
            cap.try_snapshot_pcm_ms(600)
            assert time.perf_counter() - start < 0.05
    finally:
        stop.set()
        worker.join(timeout=2.0)


_POLL_STRESS_ITERATIONS = 500
_POLL_LATENCY_BUDGET_SEC = 0.05


def test_mic_poll_stress_try_snapshot_bounded_under_contention():
    """BUG-018: high-frequency poll vs concurrent append must not block the callback path."""
    cap = MicCaptureService()
    stop = threading.Event()
    chunk = b"\x00\x01" * 400

    def append_loop() -> None:
        while not stop.is_set():
            cap._buffer.append(chunk)
            time.sleep(0)  # yield GIL — real callbacks are periodic, not a tight spin

    worker = threading.Thread(target=append_loop, daemon=True)
    worker.start()
    try:
        time.sleep(0.05)
        start_bytes = cap._buffer.filled_bytes
        assert start_bytes > 0
        none_count = 0
        for _ in range(_POLL_STRESS_ITERATIONS):
            t0 = time.perf_counter()
            pcm = cap.try_snapshot_pcm_ms(600)
            assert time.perf_counter() - t0 < _POLL_LATENCY_BUDGET_SEC
            if pcm is None:
                none_count += 1
        assert cap._buffer.filled_bytes >= start_bytes
        assert none_count < _POLL_STRESS_ITERATIONS // 10
    finally:
        stop.set()
        worker.join(timeout=2.0)


def test_on_audio_sounddevice_status_records_last_error():
    """RISK-017: sounddevice status in callback is observable via last_error (dropout proxy)."""
    cap = MicCaptureService()
    indata = SimpleNamespace(tobytes=lambda: b"\x00\x01" * 200)
    cap._on_audio(indata, 100, None, "input overflow")
    assert "overflow" in cap.last_error.lower()
    assert cap._buffer.filled_bytes > 0


def test_take_recent_ms():
    buf = MicRingBuffer(sample_rate=16_000, capacity_sec=2)
    chunk = _pcm_with_rms(500, 500)
    buf.append(chunk)
    recent = buf.take_recent_ms(200)
    assert len(recent) <= 16_000 * 2 * 200 // 1000 + 4
    assert len(recent) > 0
