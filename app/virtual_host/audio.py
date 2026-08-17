"""虚拟主播麦克风、TTS 和播放之间的纯状态编排。

这里的适配器是能力边界，不是 provider 实现：ASR、聊天和 TTS 分别注入，
TTS 真实请求统一交给现有 ``TtsManager``。模块不创建线程、不拥有 Qt 对象，
调用方可以在已有 worker 中运行适配器，再把结构化结果交回本状态机。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.tts.types import (
    TtsAuthError,
    TtsConfigurationError,
    TtsInvalidVoiceError,
    TtsProviderNetworkError,
    TtsQuotaError,
    TtsRateLimitError,
    TtsRequest,
    TtsResult,
    TtsUnsupportedCapabilityError,
)
from app.virtual_host.contracts import HostPrompt, HostTurn, HostTurnResult
from app.virtual_host.playback import (
    PlaybackEvent,
    PlaybackItem,
    PlaybackPriority,
    PlaybackQueue,
)
from app.virtual_host.session import VirtualHostSession

TtsOutcomeStatus = Literal["ok", "unsupported", "unavailable", "failed"]
VoiceTurnStatus = Literal[
    "input",
    "transcribing",
    "transcribed",
    "chatting",
    "chat_completed",
    "synthesizing",
    "queued",
    "playing",
    "paused",
    "completed",
    "cancelled",
    "failed",
]


def segment_text(text: object, *, max_chars: int = 120) -> tuple[str, ...]:
    """按自然句优先、长度兜底切分文本。

    不做语言或 provider 特判；中英文常见句末标点都作为安全切分点，单个
    超长句再按字符上限拆开。
    """

    normalized = " ".join(str(text or "").split())
    limit = max(1, int(max_chars))
    if not normalized:
        return ()
    sentence_marks = set("。！？!?；;.!?\n")
    result: list[str] = []
    current: list[str] = []

    def flush() -> None:
        value = "".join(current).strip()
        if value:
            result.append(value)
        current.clear()

    for char in normalized:
        current.append(char)
        if char in sentence_marks or len(current) >= limit:
            flush()
    flush()
    return tuple(result)


@dataclass(frozen=True)
class AsrResult:
    status: Literal["ok", "unsupported", "unavailable", "failed"]
    text: str = ""
    safe_summary: str = ""
    reason: str = ""
    provider_id: str = ""
    model_id: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"ok", "unsupported", "unavailable", "failed"}:
            raise ValueError("unsupported ASR result status")
        object.__setattr__(self, "text", " ".join(str(self.text or "").split()))
        object.__setattr__(self, "safe_summary", " ".join(str(self.safe_summary or "").split())[:240])
        object.__setattr__(self, "reason", " ".join(str(self.reason or "").split())[:240])
        object.__setattr__(self, "provider_id", str(self.provider_id or "").strip())
        object.__setattr__(self, "model_id", str(self.model_id or "").strip())


class MicAsrAdapter(Protocol):
    """现有麦克风/ASR 能力的注入端口，不携带 provider 分支。"""

    def transcribe(self, pcm: bytes, *, turn_id: int) -> AsrResult | str:
        ...


class HostChatAdapter(Protocol):
    """主播聊天模型的注入端口，与 ASR/TTS 模型明确分离。"""

    def generate(self, prompt: HostPrompt, *, turn_id: int) -> HostTurnResult | str:
        ...


@dataclass(frozen=True)
class TtsBinding:
    """经过 ``TtsManager`` 验证的 provider/model/voice 绑定。

    ``credentials`` 只供本次注入式调用使用；不出现在状态摘要和事件中。
    ``source`` 标记绑定来源（例如 ``virtual_host``），与 AI 读弹幕配置解耦。
    """

    provider_id: str
    model_id: str
    voice_id: str = ""
    source: str = "virtual_host"
    voice_source: str = "model_default"
    credential_source: str = "manager"
    credential_fields: tuple[str, ...] = ()
    credentials: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        provider_id = str(self.provider_id or "").strip()
        model_id = str(self.model_id or "").strip()
        if not provider_id or not model_id:
            raise ValueError("TTS provider_id and model_id must not be empty")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "voice_id", str(self.voice_id or "").strip())
        object.__setattr__(self, "source", str(self.source or "virtual_host").strip())
        object.__setattr__(self, "voice_source", str(self.voice_source or "model_default"))
        object.__setattr__(self, "credential_source", str(self.credential_source or "manager"))
        object.__setattr__(self, "credential_fields", tuple(sorted(str(key) for key in self.credential_fields)))
        object.__setattr__(self, "credentials", dict(self.credentials or {}))


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def resolve_tts_binding(
    manager: Any,
    *,
    provider_id: str,
    model_id: str,
    voice_id: str = "",
    source: str = "virtual_host",
    credentials: Mapping[str, str] | None = None,
) -> TtsBinding:
    """通过现有 manager/catalog/registry/credential 语义解析 TTS 配置。

    这里只验证统一 ``TtsRequest``，不导入任何厂商模块，也不把该 model ID
    暴露给 ASR 或聊天适配器。
    """

    request = TtsRequest(
        text="virtual host binding validation",
        provider_id=str(provider_id).strip(),
        model_id=str(model_id).strip(),
        voice_id=str(voice_id or "").strip() or None,
    )
    _provider, model = manager.validate_request(request)
    supplied = dict(credentials) if credentials is not None else None
    resolved_credentials = supplied
    if resolved_credentials is None:
        resolved_credentials = dict(manager.credentials.resolve(request.provider_id))

    voice_source = "model_default"
    if request.voice_id:
        for voice in model.voices:
            if voice.id == request.voice_id:
                voice_source = _enum_value(voice.source)
                break
        else:
            cached = manager.voice_cache.get(
                request.provider_id,
                request.model_id,
                fresh_only=False,
            )
            if cached is not None:
                for voice in cached.voices:
                    if voice.id == request.voice_id:
                        voice_source = _enum_value(voice.source)
                        break
            if voice_source == "model_default" and model.capabilities.custom_voice_id:
                voice_source = "custom_id"
            elif voice_source == "model_default" and model.capabilities.voice_list:
                voice_source = "provider_authoritative"

    return TtsBinding(
        provider_id=request.provider_id,
        model_id=request.model_id,
        voice_id=request.voice_id or "",
        source=source,
        voice_source=voice_source,
        credential_source="injected" if supplied is not None else "manager",
        credential_fields=tuple(resolved_credentials),
        credentials=resolved_credentials,
    )


@dataclass(frozen=True)
class TtsSynthesisOutcome:
    status: TtsOutcomeStatus
    audio_bytes: bytes = b""
    reason: str = ""
    provider_request_id: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"ok", "unsupported", "unavailable", "failed"}:
            raise ValueError("unsupported TTS outcome status")
        object.__setattr__(self, "audio_bytes", bytes(self.audio_bytes))
        object.__setattr__(self, "reason", " ".join(str(self.reason or "").split())[:240])
        object.__setattr__(self, "provider_request_id", str(self.provider_request_id or "").strip())


class TtsSynthesizer:
    """通过 TtsManager 或测试注入函数合成一段音频。"""

    def __init__(
        self,
        manager: Any | None = None,
        *,
        synthesize_fn: Callable[[str, TtsBinding], TtsSynthesisOutcome | TtsResult | bytes]
        | None = None,
    ) -> None:
        self._manager = manager
        self._synthesize_fn = synthesize_fn

    @staticmethod
    def _error_outcome(error: BaseException) -> TtsSynthesisOutcome:
        if isinstance(error, (TtsUnsupportedCapabilityError, TtsConfigurationError, TtsInvalidVoiceError)):
            status: TtsOutcomeStatus = "unsupported"
        elif isinstance(error, (TtsAuthError, TtsRateLimitError, TtsQuotaError, TtsProviderNetworkError)):
            status = "unavailable"
        else:
            status = "failed"
        return TtsSynthesisOutcome(status, reason=f"{type(error).__name__}:{error}")

    def synthesize(self, text: str, binding: TtsBinding, *, timeout_sec: float = 60.0) -> TtsSynthesisOutcome:
        value = " ".join(str(text or "").split())
        if not value:
            return TtsSynthesisOutcome("failed", reason="empty_text")
        if self._synthesize_fn is not None:
            try:
                result = self._synthesize_fn(value, binding)
                if isinstance(result, TtsSynthesisOutcome):
                    return result
                if isinstance(result, TtsResult):
                    return TtsSynthesisOutcome("ok", result.audio_bytes, provider_request_id=result.provider_request_id or "")
                if isinstance(result, bytes) and result:
                    return TtsSynthesisOutcome("ok", result)
                return TtsSynthesisOutcome("failed", reason="empty_or_invalid_audio")
            except Exception as exc:
                return self._error_outcome(exc)
        if self._manager is None:
            return TtsSynthesisOutcome("unavailable", reason="tts_manager_unavailable")
        try:
            result = self._manager.synthesize(
                TtsRequest(
                    text=value,
                    provider_id=binding.provider_id,
                    model_id=binding.model_id,
                    voice_id=binding.voice_id or None,
                ),
                credentials=binding.credentials or None,
                timeout_sec=timeout_sec,
            )
            if not isinstance(result, TtsResult) or not result.audio_bytes:
                return TtsSynthesisOutcome("failed", reason="empty_or_invalid_audio")
            return TtsSynthesisOutcome(
                "ok",
                result.audio_bytes,
                provider_request_id=result.provider_request_id or "",
            )
        except Exception as exc:
            return self._error_outcome(exc)


@dataclass
class VoiceTurnState:
    """一个虚拟主播语音轮次的可诊断状态。"""

    session_id: str
    turn_id: int
    input_started_at: float
    scene_generation: int | None = None
    input_ended_at: float | None = None
    transcript: str = ""
    transcript_summary: str = ""
    asr_status: str = "pending"
    llm_status: str = "pending"
    tts_status: str = "pending"
    playback_status: str = "pending"
    status: VoiceTurnStatus = "input"
    cancel_reason: str = ""
    timeout_reason: str = ""
    failure_reason: str = ""
    segments: tuple[str, ...] = ()
    host_turn: HostTurn | None = None
    host_result: HostTurnResult | None = None
    prompt: HostPrompt | None = None
    tts_provider_id: str = ""
    tts_model_id: str = ""
    tts_voice_id: str = ""
    tts_source: str = ""
    tts_voice_source: str = ""
    tts_credential_source: str = ""
    played_segments: int = 0

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"


class VirtualHostAudioOrchestrator:
    """把现有主播会话、ASR/chat 适配器、TTS 和播放队列串成可测试状态机。"""

    _terminal = frozenset({"completed", "cancelled", "failed"})

    def __init__(
        self,
        session: VirtualHostSession,
        *,
        asr: MicAsrAdapter | None = None,
        chat: HostChatAdapter | None = None,
        tts: TtsSynthesizer | None = None,
        tts_binding: TtsBinding | None = None,
        playback: PlaybackQueue | None = None,
        clock: Callable[[], float] = time.time,
        max_segment_chars: int = 120,
    ) -> None:
        self.session = session
        self.asr = asr
        self.chat = chat
        self.tts = tts or TtsSynthesizer()
        self.tts_binding = tts_binding
        self.playback = playback or PlaybackQueue()
        self.playback.add_listener(self._on_playback_event)
        self._clock = clock
        self._max_segment_chars = max(1, int(max_segment_chars))
        self._next_turn_id = 1
        self._turns: dict[int, VoiceTurnState] = {}

    @property
    def turns(self) -> tuple[VoiceTurnState, ...]:
        return tuple(self._turns.values())

    def get_turn(self, turn_id: int) -> VoiceTurnState:
        try:
            return self._turns[int(turn_id)]
        except KeyError as exc:
            raise KeyError(f"unknown voice turn: {turn_id}") from exc

    def _usable(self, state: VoiceTurnState, current_scene_generation: int | None = None) -> bool:
        if state.status in self._terminal:
            return False
        if (
            current_scene_generation is not None
            and state.scene_generation is not None
            and int(current_scene_generation) != state.scene_generation
        ):
            self.cancel_turn(state.turn_id, reason="scene_generation_stale")
            return False
        return True

    def begin_mic_turn(
        self,
        *,
        scene_generation: int | None = None,
        input_started_at: float | None = None,
        supersede_previous: bool = True,
    ) -> VoiceTurnState:
        if supersede_previous:
            for previous in tuple(self._turns.values()):
                if previous.status not in self._terminal:
                    self.cancel_turn(previous.turn_id, reason="superseded_by_new_mic_turn")
        turn = VoiceTurnState(
            session_id=self.session.session_id,
            turn_id=self._next_turn_id,
            input_started_at=self._clock() if input_started_at is None else float(input_started_at),
            scene_generation=None if scene_generation is None else int(scene_generation),
        )
        self._next_turn_id += 1
        self._turns[turn.turn_id] = turn
        return turn

    def end_input(self, turn_id: int, *, input_ended_at: float | None = None) -> VoiceTurnState:
        state = self.get_turn(turn_id)
        if state.cancelled:
            return state
        state.input_ended_at = self._clock() if input_ended_at is None else float(input_ended_at)
        state.status = "transcribing"
        return state

    @staticmethod
    def _coerce_asr(value: AsrResult | str | None) -> AsrResult:
        if isinstance(value, AsrResult):
            return value
        if isinstance(value, str) and value.strip():
            return AsrResult("ok", text=value)
        return AsrResult("unavailable", reason="empty_or_missing_asr_result")

    def accept_transcript(
        self,
        turn_id: int,
        transcript: str,
        *,
        safe_summary: str = "",
        provider_id: str = "",
        model_id: str = "",
    ) -> VoiceTurnState:
        state = self.get_turn(turn_id)
        if state.cancelled:
            return state
        result = AsrResult("ok", transcript, safe_summary, provider_id=provider_id, model_id=model_id)
        if not result.text:
            return self._fail(state, "asr_empty_transcript", stage="asr")
        state.transcript = result.text
        state.transcript_summary = result.safe_summary or f"mic_transcript:{len(result.text)}chars"
        state.asr_status = "completed"
        state.status = "transcribed"
        return state

    def transcribe(self, turn_id: int, pcm: bytes) -> VoiceTurnState:
        state = self.get_turn(turn_id)
        if state.cancelled:
            return state
        if not self._usable(state):
            return state
        if not pcm:
            return self._fail(state, "empty_pcm", stage="asr")
        if self.asr is None:
            state.asr_status = "unsupported"
            return self._fail(state, "asr_adapter_unavailable", stage="asr")
        try:
            result = self.asr.transcribe(bytes(pcm), turn_id=state.turn_id)
        except Exception as exc:
            state.asr_status = "unavailable"
            return self._fail(state, f"asr_failed:{type(exc).__name__}", stage="asr")
        normalized = self._coerce_asr(result)
        if normalized.status != "ok":
            state.asr_status = normalized.status
            return self._fail(state, normalized.reason or f"asr_{normalized.status}", stage="asr")
        return self.accept_transcript(
            turn_id,
            normalized.text,
            safe_summary=normalized.safe_summary,
            provider_id=normalized.provider_id,
            model_id=normalized.model_id,
        )

    def prepare_chat(
        self,
        turn_id: int,
        *,
        current_scene_generation: int | None = None,
    ) -> HostPrompt | None:
        state = self.get_turn(turn_id)
        if not self._usable(state, current_scene_generation):
            return None
        if not state.transcript:
            self._fail(state, "transcript_required", stage="llm")
            return None
        state.status = "chatting"
        state.llm_status = "pending"
        try:
            host_turn = self.session.start_turn(
                state.transcript,
                mic_text=state.transcript,
                now=self._clock(),
            )
            prompt = self.session.compose_prompt(host_turn, now=self._clock())
        except Exception as exc:
            self._fail(state, f"prompt_failed:{type(exc).__name__}", stage="llm")
            return None
        state.host_turn = host_turn
        state.prompt = prompt
        return prompt

    @staticmethod
    def _coerce_chat_result(session_id: str, host_turn: HostTurn, value: HostTurnResult | str | None) -> HostTurnResult | None:
        if isinstance(value, HostTurnResult):
            return value
        if isinstance(value, str) and value.strip():
            return HostTurnResult(session_id=session_id, turn_id=host_turn.turn_id, text=value)
        return None

    def submit_chat_result(self, turn_id: int, result: HostTurnResult | str) -> VoiceTurnState:
        state = self.get_turn(turn_id)
        if state.cancelled:
            return state
        if state.host_turn is None:
            self.prepare_chat(turn_id)
        if state.host_turn is None:
            return state
        normalized = self._coerce_chat_result(state.session_id, state.host_turn, result)
        if normalized is None:
            return self._fail(state, "empty_chat_result", stage="llm")
        try:
            self.session.complete_turn(state.host_turn, normalized)
        except Exception as exc:
            return self._fail(state, f"chat_result_invalid:{type(exc).__name__}", stage="llm")
        state.host_result = normalized
        state.llm_status = "completed"
        state.status = "chat_completed"
        return state

    def run_chat(self, turn_id: int, *, current_scene_generation: int | None = None) -> VoiceTurnState:
        state = self.get_turn(turn_id)
        prompt = self.prepare_chat(turn_id, current_scene_generation=current_scene_generation)
        if prompt is None or state.cancelled:
            return state
        if self.chat is None:
            state.llm_status = "unsupported"
            return self._fail(state, "chat_adapter_unavailable", stage="llm")
        try:
            result = self.chat.generate(prompt, turn_id=state.turn_id)
        except Exception as exc:
            state.llm_status = "unavailable"
            return self._fail(state, f"chat_failed:{type(exc).__name__}", stage="llm")
        normalized = self._coerce_chat_result(state.session_id, state.host_turn, result)
        if normalized is None:
            return self._fail(state, "empty_chat_result", stage="llm")
        return self.submit_chat_result(turn_id, normalized)

    def synthesize_turn(
        self,
        turn_id: int,
        *,
        binding: TtsBinding | None = None,
        max_chars: int | None = None,
    ) -> VoiceTurnState:
        state = self.get_turn(turn_id)
        if not self._usable(state):
            return state
        result = state.host_result
        if result is None:
            return self._fail(state, "chat_result_required", stage="tts")
        if not result.speak:
            state.tts_status = "skipped"
            state.playback_status = "skipped"
            state.status = "completed"
            return state
        active_binding = binding or self.tts_binding
        if active_binding is None:
            state.tts_status = "skipped"
            state.playback_status = "skipped"
            state.status = "completed"
            return state
        state.tts_provider_id = active_binding.provider_id
        state.tts_model_id = active_binding.model_id
        state.tts_voice_id = active_binding.voice_id
        state.tts_source = active_binding.source
        state.tts_voice_source = active_binding.voice_source
        state.tts_credential_source = active_binding.credential_source
        segments = segment_text(result.text, max_chars=max_chars or self._max_segment_chars)
        if not segments:
            state.tts_status = "failed"
            return self._fail(state, "empty_speech_text", stage="tts")
        state.segments = segments
        state.status = "synthesizing"
        for index, segment in enumerate(segments):
            if not self._usable(state):
                return state
            outcome = self.tts.synthesize(segment, active_binding)
            if outcome.status != "ok" or not outcome.audio_bytes:
                state.tts_status = outcome.status
                self.playback.cancel_turn(state.session_id, state.turn_id, reason="tts_failed")
                return self._fail(state, outcome.reason or f"tts_{outcome.status}", stage="tts")
            playback_result = self.playback.enqueue(
                PlaybackItem(
                    session_id=state.session_id,
                    turn_id=state.turn_id,
                    segment_index=index,
                    audio_bytes=outcome.audio_bytes,
                    priority=PlaybackPriority.USER_MIC,
                    source="mic_reply",
                )
            )
            if playback_result.status in {"unavailable", "rejected"}:
                state.playback_status = playback_result.status
                return self._fail(state, playback_result.reason or "playback_unavailable", stage="playback")
        state.tts_status = "completed"
        if state.status not in self._terminal and state.playback_status != "completed":
            state.status = "queued"
            state.playback_status = "queued"
        return state

    def cancel_turn(self, turn_id: int, *, reason: str = "cancelled") -> VoiceTurnState:
        state = self.get_turn(turn_id)
        if state.status == "completed":
            return state
        state.cancel_reason = str(reason or "cancelled")
        state.status = "cancelled"
        state.playback_status = "interrupted"
        self.playback.cancel_turn(state.session_id, state.turn_id, reason=state.cancel_reason)
        return state

    def enqueue_spoken_result(
        self,
        result: HostTurnResult,
        *,
        binding: TtsBinding | None = None,
        max_chars: int | None = None,
    ) -> bool:
        """自主回应 TTS：speak=false 或缺绑定时不合成、不入队。"""

        if not result.speak or not result.text:
            return False
        active_binding = binding or self.tts_binding
        if active_binding is None:
            return False
        segments = segment_text(result.text, max_chars=max_chars or self._max_segment_chars)
        if not segments:
            return False
        for index, segment in enumerate(segments):
            outcome = self.tts.synthesize(segment, active_binding)
            if outcome.status != "ok" or not outcome.audio_bytes:
                self.playback.cancel_turn(result.session_id, result.turn_id, reason="tts_failed")
                return False
            playback_result = self.playback.enqueue(
                PlaybackItem(
                    session_id=result.session_id,
                    turn_id=result.turn_id,
                    segment_index=index,
                    audio_bytes=outcome.audio_bytes,
                    priority=PlaybackPriority.AUTO_SCENE,
                    source="auto_reply",
                )
            )
            if playback_result.status in {"unavailable", "rejected"}:
                return False
        return True

    def timeout_turn(self, turn_id: int, *, reason: str = "timeout") -> VoiceTurnState:
        state = self.get_turn(turn_id)
        state.timeout_reason = str(reason or "timeout")
        return self.cancel_turn(turn_id, reason=state.timeout_reason)

    def _fail(self, state: VoiceTurnState, reason: str, *, stage: str) -> VoiceTurnState:
        if state.cancelled:
            return state
        state.failure_reason = str(reason or f"{stage}_failed")[:240]
        state.status = "failed"
        if stage == "asr":
            state.asr_status = state.asr_status if state.asr_status != "pending" else "failed"
        elif stage == "llm":
            state.llm_status = state.llm_status if state.llm_status != "pending" else "failed"
        elif stage == "tts":
            state.tts_status = state.tts_status if state.tts_status != "pending" else "failed"
        elif stage == "playback":
            state.playback_status = state.playback_status if state.playback_status != "pending" else "failed"
        return state

    def _on_playback_event(self, event: PlaybackEvent) -> None:
        state = self._turns.get(event.item.turn_id)
        if state is None or state.session_id != event.item.session_id or state.cancelled:
            return
        if event.kind == "start":
            state.playback_status = "playing"
            state.status = "playing"
        elif event.kind == "pause":
            state.playback_status = "paused"
            state.status = "paused"
        elif event.kind == "interrupted":
            state.playback_status = "interrupted"
        elif event.kind == "end":
            if event.reason == "completed":
                state.played_segments += 1
                if not self.playback.has_pending_for_turn(state.session_id, state.turn_id):
                    state.playback_status = "completed"
                    state.status = "completed"
            elif event.reason == "audio_player_unavailable":
                state.playback_status = "unavailable"
                self._fail(state, event.reason, stage="playback")
            elif event.reason:
                state.playback_status = "failed"


__all__ = [
    "AsrResult",
    "HostChatAdapter",
    "MicAsrAdapter",
    "TtsBinding",
    "TtsSynthesisOutcome",
    "TtsSynthesizer",
    "VirtualHostAudioOrchestrator",
    "VoiceTurnState",
    "resolve_tts_binding",
    "segment_text",
]
