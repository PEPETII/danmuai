from __future__ import annotations

from app.tts import (
    AuthDescriptor,
    AuthFieldDescriptor,
    BaseTtsProvider,
    InMemoryCredentialStore,
    ModelDescriptor,
    ProviderDescriptor,
    ProviderRegistry,
    TtsCapabilities,
    TtsCatalog,
    TtsManager,
    TtsResult,
    VoiceDescriptor,
)
from app.virtual_host.audio import (
    AsrResult,
    TtsBinding,
    TtsSynthesizer,
    VirtualHostAudioOrchestrator,
    resolve_tts_binding,
    segment_text,
)
from app.virtual_host.playback import PlaybackQueue
from app.virtual_host.session import VirtualHostSession


class FakeProvider(BaseTtsProvider):
    def synthesize(self, credentials, request, *, timeout_sec=60.0):
        del credentials, timeout_sec
        return TtsResult(request.text.encode(), "wav", provider_request_id="request-1")


class FakeAsr:
    def transcribe(self, pcm: bytes, *, turn_id: int):
        assert pcm == b"pcm"
        return AsrResult(
            "ok",
            text=f"用户第{turn_id}轮",
            safe_summary=f"第{turn_id}轮用户输入",
            provider_id="asr-provider",
            model_id="asr-model",
        )


class FakeChat:
    def __init__(self) -> None:
        self.prompts = []

    def generate(self, prompt, *, turn_id: int):
        self.prompts.append(prompt)
        return f"主播回复{turn_id}第一句。主播回复{turn_id}第二句。"


class FakePlayer:
    def __init__(self) -> None:
        self.current_callback = None
        self.started: list[bytes] = []

    def play(self, audio_bytes: bytes, on_complete):
        self.started.append(audio_bytes)
        self.current_callback = on_complete
        return object()

    def stop(self):
        pass

    def pause(self):
        pass

    def complete(self) -> None:
        callback = self.current_callback
        self.current_callback = None
        if callback is not None:
            callback()


def _manager():
    voice = VoiceDescriptor("voice-1", "Voice 1")
    model = ModelDescriptor(
        id="tts-model",
        label="TTS model",
        capabilities=TtsCapabilities(),
        voices=(voice,),
    )
    descriptor = ProviderDescriptor(
        id="tts-provider",
        label="TTS provider",
        auth=AuthDescriptor((AuthFieldDescriptor("api_key", "API key"),)),
        models=(model,),
    )
    provider = FakeProvider(descriptor)
    manager = TtsManager(ProviderRegistry([provider]), TtsCatalog([descriptor]))
    store = InMemoryCredentialStore()
    store.set("tts-provider", {"api_key": "secret"})
    manager.credentials = manager.credentials.__class__(store)
    return manager


def _binding() -> TtsBinding:
    return TtsBinding(
        provider_id="tts-provider",
        model_id="tts-model",
        voice_id="voice-1",
        source="virtual_host",
        voice_source="static_catalog",
        credential_source="injected",
        credential_fields=("api_key",),
        credentials={"api_key": "secret"},
    )


def test_segment_text_prefers_sentences_and_caps_long_text():
    assert segment_text("你好！再见？") == ("你好！", "再见？")
    assert segment_text("abcdefgh", max_chars=3) == ("abc", "def", "gh")


def test_tts_binding_uses_manager_catalog_registry_and_credential_semantics():
    binding = resolve_tts_binding(
        _manager(),
        provider_id="tts-provider",
        model_id="tts-model",
        voice_id="voice-1",
    )

    assert binding.provider_id == "tts-provider"
    assert binding.model_id == "tts-model"
    assert binding.voice_id == "voice-1"
    assert binding.voice_source == "static_catalog"
    assert binding.credential_source == "manager"
    assert binding.credential_fields == ("api_key",)


def test_two_mic_turns_keep_history_and_trace_tts_source():
    player = FakePlayer()
    chat = FakeChat()
    session = VirtualHostSession(session_id="host-session", persona_name="host")
    orchestrator = VirtualHostAudioOrchestrator(
        session,
        asr=FakeAsr(),
        chat=chat,
        tts=TtsSynthesizer(synthesize_fn=lambda text, binding: text.encode()),
        tts_binding=_binding(),
        playback=PlaybackQueue(player),
        max_segment_chars=40,
    )

    first = orchestrator.begin_mic_turn(scene_generation=3, input_started_at=1.0)
    orchestrator.end_input(first.turn_id, input_ended_at=2.0)
    orchestrator.transcribe(first.turn_id, b"pcm")
    orchestrator.run_chat(first.turn_id)
    orchestrator.synthesize_turn(first.turn_id)
    assert first.input_ended_at == 2.0
    assert first.transcript_summary == "第1轮用户输入"
    assert first.tts_provider_id == "tts-provider"
    assert first.tts_model_id == "tts-model"
    assert first.tts_voice_source == "static_catalog"
    assert first.segments == ("主播回复1第一句。", "主播回复1第二句。")

    player.complete()
    player.complete()
    assert first.status == "completed"

    second = orchestrator.begin_mic_turn(scene_generation=3, input_started_at=3.0)
    orchestrator.end_input(second.turn_id, input_ended_at=4.0)
    orchestrator.transcribe(second.turn_id, b"pcm")
    orchestrator.run_chat(second.turn_id)
    assert "turn 1:" in chat.prompts[1].user_prompt
    assert second.turn_id == 2


def test_cancelled_turn_rejects_late_speech_and_tts_failure_isolated():
    player = FakePlayer()
    session = VirtualHostSession(session_id="host-session")
    calls = []

    def synthesize(text, binding):
        del binding
        calls.append(text)
        if "失败" in text:
            raise RuntimeError("provider unavailable")
        return text.encode()

    orchestrator = VirtualHostAudioOrchestrator(
        session,
        tts=TtsSynthesizer(synthesize_fn=synthesize),
        tts_binding=_binding(),
        playback=PlaybackQueue(player),
        max_segment_chars=40,
    )
    turn = orchestrator.begin_mic_turn()
    orchestrator.accept_transcript(turn.turn_id, "用户输入")
    orchestrator.submit_chat_result(turn.turn_id, "好的。失败。")
    orchestrator.synthesize_turn(turn.turn_id)
    assert turn.status == "failed"
    assert turn.tts_status == "failed"
    assert turn.failure_reason.startswith("RuntimeError")
    assert orchestrator.playback.active_item is None

    cancelled = orchestrator.begin_mic_turn()
    orchestrator.cancel_turn(cancelled.turn_id, reason="user_cancelled")
    assert orchestrator.synthesize_turn(cancelled.turn_id).status == "cancelled"
    assert cancelled.cancel_reason == "user_cancelled"


def test_missing_binding_skips_tts_and_keeps_text_result():
    session = VirtualHostSession(session_id="host-session")
    orchestrator = VirtualHostAudioOrchestrator(
        session,
        tts=TtsSynthesizer(synthesize_fn=lambda text, binding: text.encode()),
        playback=PlaybackQueue(),
    )
    turn = orchestrator.begin_mic_turn()
    orchestrator.accept_transcript(turn.turn_id, "用户输入")
    orchestrator.submit_chat_result(turn.turn_id, "仅文本回复")

    state = orchestrator.synthesize_turn(turn.turn_id)
    assert state.status == "completed"
    assert state.tts_status == "skipped"
    assert state.playback_status == "skipped"


def test_missing_manager_is_unavailable_not_fake_success():
    session = VirtualHostSession(session_id="host-session")
    orchestrator = VirtualHostAudioOrchestrator(
        session,
        tts=TtsSynthesizer(),
        tts_binding=_binding(),
        playback=PlaybackQueue(),
    )
    turn = orchestrator.begin_mic_turn()
    orchestrator.accept_transcript(turn.turn_id, "用户输入")
    orchestrator.submit_chat_result(turn.turn_id, "需要播报")

    state = orchestrator.synthesize_turn(turn.turn_id)
    assert state.status == "failed"
    assert state.tts_status == "unavailable"
    assert state.failure_reason == "tts_manager_unavailable"
