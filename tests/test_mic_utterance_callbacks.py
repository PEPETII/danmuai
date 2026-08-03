from __future__ import annotations

import struct

from app.mic_utterance import MicUtteranceConfig, MicUtteranceDetector


def test_speech_start_and_discarded_callbacks():
    starts: list[str] = []
    discards: list[str] = []
    ends: list[str] = []

    detector = MicUtteranceDetector(
        on_utterance_end=lambda: ends.append("end"),
        on_speech_start=lambda: starts.append("start"),
        on_utterance_discarded=lambda: discards.append("discard"),
        config=MicUtteranceConfig(
            speech_rms=10,
            silence_ms=50,
            min_speech_ms=1000,
            cooldown_sec=0.1,
        ),
    )
    detector.set_noise_floor(0)

    loud = struct.pack(f"<{800}h", *([5000] * 800))
    quiet = struct.pack(f"<{800}h", *([0] * 800))
    now = 1000.0

    detector.poll(loud, now=now)
    assert starts == ["start"]
    detector.poll(quiet, now=now + 0.05)
    detector.poll(quiet, now=now + 0.2)
    assert discards == ["discard"]
    assert ends == []
