from app.mic_buffer import MicRingBuffer, clamp_mic_window_sec
from app.mic_encode import pcm_to_wav_data_uri
from app.mic_prompt import append_mic_context_to_user_pt, build_mic_insert_user_pt


def test_clamp_mic_window_sec():
    assert clamp_mic_window_sec(0) == 1
    assert clamp_mic_window_sec(5) == 5
    assert clamp_mic_window_sec(99) == 30


def test_ring_buffer_keeps_recent_only():
    buf = MicRingBuffer(sample_rate=1000, capacity_sec=2)
    buf.append(b"\x01" * 2000)
    buf.append(b"\x02" * 2000)
    recent = buf.take_recent(1)
    assert len(recent) == 1000 * 2
    assert recent[0] == 2


def test_pcm_to_wav_data_uri():
    pcm = b"\x00\x01" * 2000
    uri = pcm_to_wav_data_uri(pcm)
    assert uri is not None
    assert uri.startswith("data:audio/wav;base64,")


def test_pcm_to_wav_data_uri_rejects_short():
    assert pcm_to_wav_data_uri(b"\x00\x01") is None


def test_append_mic_context_to_user_pt():
    out = append_mic_context_to_user_pt("请生成弹幕：")
    assert "请生成弹幕：" in out
    assert "麦克风" in out
    assert "截图" in out


def test_build_mic_insert_user_pt():
    out = build_mic_insert_user_pt("base")
    assert "麦克风插入" in out
    assert out.startswith("base")
    assert "请生成 6条 JSON 数组弹幕" in out
    assert "前3条必须直接回应" in out
    assert "后 3 条可结合截图氛围" in out
    assert "仍要在前 2 条体现听到了用户说话" in out
