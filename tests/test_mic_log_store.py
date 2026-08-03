from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

from app.mic_log_store import MicLogStore
from app.mic_transcription import (
    MicTranscriptionResult,
    _transcription_url,
    pcm_to_wav_bytes,
    transcribe_pcm,
)


def _sample_pcm(num_frames: int = 1600) -> bytes:
    return struct.pack(f"<{num_frames}h", *([100] * num_frames))


def test_mic_log_store_partial_finalize_and_discard():
    store = MicLogStore(max_entries=3)
    events: list[dict] = []
    store.entry_emitted.connect(events.append)

    partial = store.begin_partial(utterance_id="u1")
    assert partial.status == "partial"
    assert events[-1]["type"] == "upsert"

    store.finalize("u1", text="你好", status="success")
    items = store.list_recent()
    assert len(items) == 1
    assert items[0]["text"] == "你好"
    assert items[0]["status"] == "success"

    store.discard("u1")
    assert store.list_recent() == []
    assert events[-1]["type"] == "discard"


def test_mic_log_store_trim_oldest():
    store = MicLogStore(max_entries=2)
    store.begin_partial(utterance_id="a")
    store.finalize("a", text="one", status="success")
    store.begin_partial(utterance_id="b")
    store.finalize("b", text="two", status="success")
    store.begin_partial(utterance_id="c")
    store.finalize("c", text="three", status="success")
    texts = [item["text"] for item in store.list_recent()]
    assert texts == ["two", "three"]


def test_transcription_url_normalizes_chat_completions_suffix():
    assert _transcription_url("https://api.example.com/v1/chat/completions").endswith(
        "/audio/transcriptions"
    )


def test_transcribe_pcm_success():
    pcm = _sample_pcm()
    assert pcm_to_wav_bytes(pcm) is not None
    config = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"text": " hello "}
    client = MagicMock()
    client.post.return_value = response

    with patch(
        "app.mic_transcription.resolve_mic_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "whisper-1", "openai"),
    ):
        result = transcribe_pcm(config, pcm, http_client=client)

    assert result == MicTranscriptionResult(ok=True, text="hello")


def test_transcribe_pcm_empty_transcript_is_failed():
    pcm = _sample_pcm()
    config = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"text": "   "}
    client = MagicMock()
    client.post.return_value = response

    with patch(
        "app.mic_transcription.resolve_mic_request_credentials",
        return_value=("https://api.example.com/v1", "sk-test", "whisper-1", "openai"),
    ):
        result = transcribe_pcm(config, pcm, http_client=client)

    assert result.ok is False
    assert result.error == "empty_transcript"
