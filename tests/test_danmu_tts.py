import base64
import io
import wave

import numpy as np
import pytest
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, DanmuItem
from app.danmu_read_service import (
    danmu_read_enabled,
)
from app.danmu_tts_playback import DanmuTtsPlayback
from app.tts_providers import (
    MIMO_TTS_ENDPOINT,
    MIMO_TTS_MODEL,
    TTS_PROVIDER_DASHSCOPE_QWEN,
    TTS_PROVIDER_MIMO,
    DanmuTtsError,
    ResolvedTtsConfig,
    clamp_read_interval_sec,
    normalize_tts_voice,
    resolve_tts_config,
    synthesize_tts,
)

from tests.fakes import FakeConfig


@pytest.fixture()
def engine(workspace_tmp):
    db_path = workspace_tmp / "config.db"
    store = ConfigStore(db_path=db_path)
    eng = DanmuEngine(store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    eng.screen_width = 1000.0
    eng._visibility_counts_seeded = True
    return eng


def _fake_wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(b"\x00\x00" * 240)
    return buf.getvalue()


def test_visible_display_texts_only_on_screen(engine):
    track = engine.tracks[0]
    on = DanmuItem("可见甲", x=100.0, width=80.0)
    on._vis_on_screen = True
    off = DanmuItem("屏外乙", x=1200.0, width=80.0)
    off._vis_on_screen = False
    dup = DanmuItem("可见甲", x=200.0, width=80.0)
    dup._vis_on_screen = True
    track.items.extend([on, off, dup])
    assert engine.visible_display_texts() == ["可见甲"]


def test_clamp_read_interval_sec():
    assert clamp_read_interval_sec(2) == 3
    assert clamp_read_interval_sec(999) == 120
    assert clamp_read_interval_sec("x", default=10) == 10


def test_normalize_tts_voice():
    assert normalize_tts_voice("Chloe") == "Chloe"
    assert normalize_tts_voice("invalid") == "冰糖"


def test_synthesize_mimo_tts_parses_audio(monkeypatch):
    wav = _fake_wav_bytes()
    payload = {
        "choices": [
            {"message": {"audio": {"data": base64.b64encode(wav).decode("ascii")}}}
        ]
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            assert json["model"] == "mimo-v2.5-tts"
            assert json["messages"][-1]["role"] == "assistant"
            return FakeResponse()

    monkeypatch.setattr("app.tts_providers.httpx.Client", FakeClient)
    resolved = ResolvedTtsConfig(
        provider=TTS_PROVIDER_MIMO,
        endpoint=MIMO_TTS_ENDPOINT,
        model=MIMO_TTS_MODEL,
        is_custom=False,
        stored_provider="",
        stored_endpoint="",
        stored_model_id="",
    )
    out = synthesize_tts(
        "sk-test", "你好", resolved=resolved, style_prompt="轻快", voice="冰糖"
    )
    assert out == wav


def test_resolve_tts_config_defaults():
    cfg = FakeConfig({})
    resolved = resolve_tts_config(cfg)
    assert resolved.model == MIMO_TTS_MODEL
    assert resolved.endpoint == MIMO_TTS_ENDPOINT
    assert resolved.is_custom is False


def test_resolve_tts_config_rejects_doubao():
    cfg = FakeConfig(
        {
            "tts_provider": "doubao",
            "tts_model_id": "seed-tts-2.0",
        }
    )
    with pytest.raises(ValueError, match="火山豆包"):
        resolve_tts_config(cfg)


def test_resolve_tts_config_dashscope():
    cfg = FakeConfig(
        {
            "tts_provider": TTS_PROVIDER_DASHSCOPE_QWEN,
            "tts_model_id": "qwen3-tts-flash-2025-11-27",
        }
    )
    resolved = resolve_tts_config(cfg)
    assert resolved.provider == TTS_PROVIDER_DASHSCOPE_QWEN
    assert resolved.model == "qwen3-tts-flash-2025-11-27"


def test_resolve_tts_config_rejects_custom_openai():
    cfg = FakeConfig(
        {
            "tts_provider": "custom_openai",
            "tts_endpoint": "https://tts.example.com/v1",
            "tts_model_id": "my-tts-model",
        }
    )
    with pytest.raises(ValueError, match="不再支持自定义 OpenAI 兼容 TTS"):
        resolve_tts_config(cfg)


def test_synthesize_mimo_tts_missing_key():
    resolved = ResolvedTtsConfig(
        provider=TTS_PROVIDER_MIMO,
        endpoint=MIMO_TTS_ENDPOINT,
        model=MIMO_TTS_MODEL,
        is_custom=False,
        stored_provider="",
        stored_endpoint="",
        stored_model_id="",
    )
    with pytest.raises(DanmuTtsError, match="API Key"):
        synthesize_tts("", "hi", resolved=resolved)


def test_synthesize_mimo_tts_text_only_response(monkeypatch):
    """普通 chat 模型返回文本无 audio.data 时应提示 TTS 能力不匹配。"""
    payload = {
        "model": "openrouter/chat-model",
        "choices": [{"message": {"content": "Hello, I am a text model."}}],
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr("app.tts_providers.httpx.Client", FakeClient)
    resolved = ResolvedTtsConfig(
        provider=TTS_PROVIDER_MIMO,
        endpoint=MIMO_TTS_ENDPOINT,
        model="openrouter/chat-model",
        is_custom=False,
        stored_provider="",
        stored_endpoint="",
        stored_model_id="",
    )
    with pytest.raises(DanmuTtsError, match="不支持读弹幕 TTS 音频输出"):
        synthesize_tts("sk-test", "你好", resolved=resolved)


def test_config_tts_api_key_roundtrip(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "cfg.db")
    store.set_tts_api_key("tts-secret")
    assert store.get_tts_api_key() == "tts-secret"


def test_append_trailing_pause_adds_one_second():
    from app.danmu_tts_playback import _append_trailing_pause

    rate = 24000
    audio = np.zeros(1000, dtype=np.int16)
    audio[-1] = 16000
    out = _append_trailing_pause(audio, rate)
    assert out.size == 1000 + rate
    assert out[-rate:].max() == 0
    assert out[500] == 0


def test_service_alive_false_when_shutdown():
    from app.danmu_read_service import _service_alive

    class Stub:
        _shutdown = True

    assert not _service_alive(Stub())  # type: ignore[arg-type]


def test_danmu_read_enabled():
    cfg = FakeConfig({"danmu_read_enabled": "1"})
    assert danmu_read_enabled(cfg)


def test_playback_busy_flag(qtbot):
    from PyQt6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    playback = DanmuTtsPlayback()
    finished: list[int] = []
    playback.playback_finished.connect(lambda: finished.append(1))
    assert not playback.is_busy()
    wav = _fake_wav_bytes()
    assert playback.play_wav_bytes(wav) is True
    assert playback.is_busy()
    assert playback.play_wav_bytes(wav) is False
    qtbot.waitUntil(lambda: bool(finished), timeout=3000)
    assert not playback.is_busy()
