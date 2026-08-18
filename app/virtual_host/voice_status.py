"""虚拟主播语音会话 UI 状态投影（无 Qt 依赖）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from main import DanmuApp

    from app.virtual_host.runtime_service import VirtualHostRuntimeService

VoiceUiPhase = str

_PHASE_LISTENING = frozenset({"input"})
_PHASE_RECOGNIZING = frozenset({"transcribing"})
_PHASE_THINKING = frozenset({"transcribed", "chatting", "chat_completed"})
_PHASE_SPEAKING = frozenset({"synthesizing", "queued", "playing", "paused"})


def derive_ui_phase(
    *,
    armed: bool,
    turn_status: str,
    mic_error: str = "",
) -> VoiceUiPhase:
    status = str(turn_status or "").strip()
    if status == "failed":
        return "failed"
    if status == "cancelled":
        return "idle" if armed else "idle"
    if status == "completed":
        return "completed" if armed else "idle"
    if status in _PHASE_SPEAKING:
        return "speaking"
    if status in _PHASE_THINKING:
        return "thinking"
    if status in _PHASE_RECOGNIZING:
        return "recognizing"
    if status in _PHASE_LISTENING:
        return "listening"
    if armed:
        return "listening"
    if mic_error:
        return "failed"
    return "idle"


def _safe_error(*values: object) -> str:
    for value in values:
        text = " ".join(str(value or "").split())
        if text:
            return text[:240]
    return ""


def _active_user_turn(runtime: VirtualHostRuntimeService | None):
    if runtime is None:
        return None
    active_id = int(getattr(runtime._mic_route, "active_turn_id", 0) or 0)
    if active_id:
        try:
            return runtime.audio.get_turn(active_id)
        except KeyError:
            pass
    latest = None
    for state in runtime.audio.turns:
        if state.source != "user_mic":
            continue
        if latest is None or state.turn_id > latest.turn_id:
            latest = state
    return latest


def _mic_snapshot(app: DanmuApp) -> dict[str, object]:
    from app.mic_service import mic_mode_enabled

    orchestrator = getattr(app, "_mic_orchestrator", None)
    service = getattr(orchestrator, "_mic_service", None) if orchestrator is not None else None
    engine_running = bool(getattr(getattr(app, "engine", None), "running", False))
    mic_mode_on = mic_mode_enabled(app.config)
    capture_running = bool(service.is_running()) if service is not None else False
    last_error = str(service.last_error()) if service is not None else ""
    return {
        "mic_mode_enabled": mic_mode_on,
        "mic_capture_running": capture_running,
        "mic_capture_ready": mic_mode_on and engine_running and capture_running and not last_error,
        "mic_error": _safe_error(last_error),
    }


def export_voice_status(
    runtime: VirtualHostRuntimeService | None,
    app: DanmuApp,
) -> dict[str, Any]:
    mic = _mic_snapshot(app)
    dialogue_enabled = False
    danmu_adapter_enabled = False
    runtime_status = "stopped"
    runtime_generation = 0
    armed = False
    turn_id: int | None = None
    turn_status = ""
    failure_reason = ""
    cancel_reason = ""
    asr_status = ""
    llm_status = ""
    tts_status = ""
    playback_status = ""

    if runtime is not None:
        dialogue_enabled = bool(runtime.dialogue_enabled)
        danmu_adapter_enabled = bool(runtime.danmu_adapter_enabled)
        runtime_status = "running" if runtime.running else "stopped"
        runtime_generation = int(runtime.runtime_generation)
        armed = bool(getattr(runtime, "voice_session_armed", False))
        active = _active_user_turn(runtime)
        if active is not None:
            turn_id = int(active.turn_id)
            turn_status = str(active.status)
            failure_reason = _safe_error(active.failure_reason)
            cancel_reason = _safe_error(active.cancel_reason)
            asr_status = str(active.asr_status or "")
            llm_status = str(active.llm_status or "")
            tts_status = str(active.tts_status or "")
            playback_status = str(active.playback_status or "")

    phase = derive_ui_phase(
        armed=armed,
        turn_status=turn_status,
        mic_error=str(mic.get("mic_error") or ""),
    )
    blocking_error = ""
    if not dialogue_enabled:
        blocking_error = "dialogue_mode_disabled"
    elif danmu_adapter_enabled:
        blocking_error = "adapter_mode_active"
    elif runtime_status != "running":
        blocking_error = "runtime_stopped"
    elif not mic.get("mic_mode_enabled"):
        blocking_error = "mic_mode_disabled"
    elif not mic.get("mic_capture_ready") and armed:
        blocking_error = _safe_error(mic.get("mic_error"), "mic_capture_unavailable") or "mic_capture_unavailable"

    return {
        "dialogue_enabled": dialogue_enabled,
        "danmu_adapter_enabled": danmu_adapter_enabled,
        "runtime_status": runtime_status,
        "runtime_generation": runtime_generation,
        "armed": armed,
        "phase": phase,
        "turn_id": turn_id,
        "turn_status": turn_status or None,
        "asr_status": asr_status or None,
        "llm_status": llm_status or None,
        "tts_status": tts_status or None,
        "playback_status": playback_status or None,
        "failure_reason": failure_reason or None,
        "cancel_reason": cancel_reason or None,
        "blocking_error": blocking_error or None,
        "mic_mode_enabled": mic["mic_mode_enabled"],
        "mic_capture_running": mic["mic_capture_running"],
        "mic_capture_ready": mic["mic_capture_ready"],
        "mic_error": mic["mic_error"] or None,
    }


__all__ = [
    "derive_ui_phase",
    "export_voice_status",
]
