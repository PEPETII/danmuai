"""Regression for BUG-004: MicRingBuffer concurrent read/write safety."""

import threading

from app.mic_buffer import MicRingBuffer


def test_mic_ring_buffer_concurrent_read_write():
    buf = MicRingBuffer(sample_rate=16000, capacity_sec=1)
    errors = []
    read_results = []

    chunk = b'\x00\x01' * 160  # 320 bytes = 10ms at 16kHz 16-bit mono

    def writer():
        for _ in range(2000):
            try:
                buf.append(chunk)
            except Exception as exc:
                errors.append(("write", exc))

    def reader():
        for _ in range(2000):
            try:
                result = buf.try_take_recent_ms(50)
                if result is not None:
                    read_results.append(len(result))
            except Exception as exc:
                errors.append(("read", exc))

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=reader)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Concurrent operations raised exceptions: {errors[:5]}"
    expected_max = 50 * 16000 * 2 // 1000  # 1600 bytes
    for length in read_results:
        assert length <= expected_max
    assert buf.filled_bytes > 0
