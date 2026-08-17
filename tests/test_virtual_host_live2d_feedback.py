from __future__ import annotations

from types import SimpleNamespace

from app.virtual_host.contracts import ActionDraft, EmotionDraft, HostTurnResult
from app.virtual_host.live2d_feedback import Live2DFeedbackController
from app.virtual_host.playback import PlaybackEvent, PlaybackItem


class FakeRuntime:
    def __init__(self, *, mouth: bool = True, reset_expression_supported: bool = True) -> None:
        specs = [
            {
                "parameter_id": "ParamMouthOpenY",
                "minimum": 0,
                "maximum": 1,
                "default": 0,
                "current": 0,
            },
            {"parameter_id": "ParamMouthForm", "minimum": -1, "maximum": 1, "default": 0},
            {"parameter_id": "ParamEyeBallX", "minimum": -1, "maximum": 1, "default": 0},
            {"parameter_id": "ParamAngleY", "minimum": -30, "maximum": 30, "default": 0},
        ]
        if not mouth:
            specs.pop(0)
        self.snapshot_data = {
            "runtime_status": "running",
            "capabilities": {
                "parameter_specs": specs,
                "expression_entries": [{"id": "smile", "file": "expressions/smile.exp3.json"}],
                "motion_entries": [{"group": "nod", "index": 0, "file": "motions/nod.motion3.json"}],
            },
        }
        self.callback = None
        self.calls: list[tuple[str, object]] = []
        self._expression_active = False
        self._reset_expression_supported = reset_expression_supported

    def snapshot(self):
        return self.snapshot_data

    def set_parameter(self, parameter_id: str, value: float):
        self.calls.append(("parameter", (parameter_id, value)))
        return {"parameter_id": parameter_id, "value": value}

    def set_expression(self, file_name: str):
        self._expression_active = True
        self.calls.append(("expression", file_name))
        return {"file": file_name}

    def reset_expression(self):
        self._expression_active = False
        if self._reset_expression_supported:
            self.calls.append(("reset_expression", None))
            return {"status": "reset"}
        return {"status": "degraded", "reason": "reset_expression_unavailable"}

    def start_motion(self, file_name: str):
        self.calls.append(("motion", file_name))
        return {"file": file_name}

    def restore_idle(self):
        self.calls.append(("idle", None))
        return {"status": "idle"}

    def set_frame_callback(self, callback):
        self.callback = callback

    def simulate_model_update(self):
        if self._expression_active:
            self.calls.append(("expression_reapplied", None))


def _item(item_id: str, generation: int = 1) -> PlaybackItem:
    return PlaybackItem("session", 1, 0, b"audio", runtime_generation=generation, item_id=item_id)


def _event(kind: str, item_id: str, generation: int = 1) -> PlaybackEvent:
    return PlaybackEvent(kind, _item(item_id, generation))


def _named_action(kind: str, name: str, *, intensity: float = 0.5) -> ActionDraft:
    return ActionDraft(kind, intensity=intensity, name=name)


def _controller(runtime: FakeRuntime | None = None) -> tuple[Live2DFeedbackController, FakeRuntime]:
    runtime = runtime or FakeRuntime()
    controller = Live2DFeedbackController()
    controller.bind_runtime(runtime, 1)
    controller.activate()
    return controller, runtime


def test_bind_runtime_uses_callback_and_handles_malformed_capabilities():
    runtime = FakeRuntime()
    runtime.snapshot_data["capabilities"] = {
        "parameter_specs": [None, {"parameter_id": "bad", "minimum": "no"}],
        "expression_entries": object(),
        "motion_entries": "bad",
    }
    controller = Live2DFeedbackController()

    controller.bind_runtime(runtime, 3)

    assert runtime.callback == controller.tick
    assert controller.runtime_generation == 3
    assert controller.tick() == ()
    controller.unbind_runtime()
    assert runtime.callback is None


def test_playback_start_and_end_drive_smooth_fallback_lip_sync():
    controller, runtime = _controller()

    controller.handle_playback_event(_event("start", "a"))
    controller.tick()
    assert controller.speech_lip_sync_active
    assert any(kind == "parameter" and args[0] == "ParamMouthOpenY" for kind, args in runtime.calls)

    runtime.calls.clear()
    controller.handle_playback_event(_event("end", "a"))
    controller.tick()
    assert not controller.speech_lip_sync_active
    assert any(kind == "parameter" for kind, _args in runtime.calls)


def test_missing_mouth_open_y_keeps_playback_safe_without_parameter_write():
    controller, runtime = _controller(FakeRuntime(mouth=False))

    controller.handle_playback_event(_event("start", "a"))
    controller.tick()
    assert not any(
        kind == "parameter" and args[0] == "ParamMouthOpenY"
        for kind, args in runtime.calls
    )


def test_stale_playback_item_and_generation_cannot_stop_new_playback():
    controller, _runtime = _controller()

    controller.handle_playback_event(_event("start", "new"))
    stale = controller.handle_playback_event(_event("end", "old"))
    assert stale.status == "ignored"
    assert controller.speech_lip_sync_active

    controller.set_runtime_generation(2)
    stale_generation = controller.handle_playback_event(_event("end", "new", 1))
    assert stale_generation.status == "ignored"
    controller.handle_playback_event(_event("start", "current", 2))
    assert controller.speech_lip_sync_active


def test_stale_turn_and_session_cannot_start_new_model_feedback():
    controller, _runtime = _controller()
    controller.apply_turn_result(HostTurnResult("session", 2, "new"), 1)

    stale_turn = PlaybackEvent("start", PlaybackItem("session", 1, 0, b"audio", runtime_generation=1))
    stale_session = PlaybackEvent("start", PlaybackItem("old", 2, 0, b"audio", runtime_generation=1))

    assert controller.handle_playback_event(stale_turn).status == "ignored"
    assert controller.handle_playback_event(stale_session).status == "ignored"
    assert not controller.speech_lip_sync_active


def test_generation_reset_writes_mouth_back_to_default_immediately():
    controller, runtime = _controller()
    controller.handle_playback_event(_event("start", "a"))
    controller.tick()
    runtime.calls.clear()

    controller.set_runtime_generation(2)

    assert ("parameter", ("ParamMouthOpenY", 0.0)) in runtime.calls
    assert ("reset_expression", None) in runtime.calls
    assert not controller.speech_lip_sync_active


def test_expression_reset_survives_model_update_after_generation_bump():
    controller, runtime = _controller()
    controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", emotion=EmotionDraft("happy")),
        1,
    )
    runtime.calls.clear()

    controller.set_runtime_generation(2)
    runtime.simulate_model_update()

    assert ("reset_expression", None) in runtime.calls
    assert ("expression_reapplied", None) not in runtime.calls


def test_deactivate_and_unbind_clear_expression_state():
    controller, runtime = _controller()
    controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", emotion=EmotionDraft("happy")),
        1,
    )
    runtime.calls.clear()

    controller.deactivate()
    assert ("reset_expression", None) in runtime.calls
    runtime.calls.clear()
    runtime._expression_active = True

    controller.activate()
    controller.unbind_runtime()
    assert ("reset_expression", None) in runtime.calls
    runtime.simulate_model_update()
    assert ("expression_reapplied", None) not in runtime.calls


def test_reset_expression_missing_api_degrades_without_crash():
    controller, runtime = _controller(FakeRuntime(reset_expression_supported=False))
    controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", emotion=EmotionDraft("happy")),
        1,
    )
    runtime.calls.clear()
    controller.set_runtime_generation(2)
    assert ("reset_expression", None) not in runtime.calls


def test_consecutive_start_events_do_not_create_a_lip_sync_gap():
    controller, _runtime = _controller()

    controller.handle_playback_event(_event("start", "first"))
    controller.tick()
    controller.handle_playback_event(_event("end", "first"))
    controller.handle_playback_event(_event("start", "second"))
    assert controller.speech_lip_sync_active
    controller.tick()
    assert controller.speech_lip_sync_active


def test_emotion_maps_to_actual_expression_and_ignores_missing_match():
    controller, runtime = _controller()
    matching = HostTurnResult("session", 1, "hi", emotion=EmotionDraft("happy"))
    mismatching = HostTurnResult("session", 2, "hi", emotion=EmotionDraft("made_up"))

    assert controller.apply_turn_result(matching, 1)[0].status == "expression_applied"
    assert controller.apply_turn_result(mismatching, 1)[0].status == "ignored"
    assert ("expression", "expressions/smile.exp3.json") in runtime.calls


def test_arbitrary_expression_name_is_not_guessed_as_happy():
    runtime = FakeRuntime()
    runtime.snapshot_data["capabilities"]["expression_entries"] = [
        {"id": "ku", "file": "expressions/exp01.exp3.json"},
    ]
    controller, _runtime = _controller(runtime)

    outcome = controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", emotion=EmotionDraft("exp01")),
        1,
    )[0]
    assert outcome.status == "ignored"
    assert not any(kind == "expression" for kind, _ in runtime.calls)


def test_explicit_semantic_mapping_hits_arbitrary_expression_name():
    runtime = FakeRuntime()
    runtime.snapshot_data["capabilities"]["expression_entries"] = [
        {"id": "ku", "file": "expressions/exp01.exp3.json"},
    ]
    runtime.snapshot_data["capabilities"]["semantic_mappings"] = {
        "emotions": {"happy": "ku"},
    }
    controller, runtime = _controller(runtime)

    outcome = controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", emotion=EmotionDraft("happy")),
        1,
    )[0]
    assert outcome.status == "expression_applied"
    assert ("expression", "expressions/exp01.exp3.json") in runtime.calls


def test_expression_requires_allowlisted_name_and_real_entry():
    controller, runtime = _controller()
    result = HostTurnResult(
        "session",
        1,
        "hi",
        actions=(_named_action("expression", "smile"), _named_action("expression", "missing")),
    )

    outcomes = controller.apply_turn_result(result, 1)

    assert [outcome.status for outcome in outcomes] == ["expression_applied", "ignored"]
    assert runtime.calls == [("expression", "expressions/smile.exp3.json")]


def test_gesture_requires_allowlisted_name_and_real_motion_entry():
    controller, runtime = _controller()
    result = HostTurnResult(
        "session",
        1,
        "hi",
        actions=(_named_action("gesture", "nod"), _named_action("gesture", "wave")),
    )

    outcomes = controller.apply_turn_result(result, 1)

    assert [outcome.status for outcome in outcomes] == ["motion_applied", "ignored"]
    assert runtime.calls == [("motion", "motions/nod.motion3.json")]


def test_nod_without_motion_uses_angle_y_parameter_fallback():
    runtime = FakeRuntime()
    runtime.snapshot_data["capabilities"]["motion_entries"] = [
        {"group": "daiji", "index": 0, "file": "motions/daiji.motion3.json"},
    ]
    controller, runtime = _controller(runtime)

    outcome = controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", actions=(_named_action("gesture", "nod"),)),
        1,
    )[0]
    controller.tick()
    assert outcome.status == "parameter_fallback"
    assert not any(kind == "motion" for kind, _ in runtime.calls)
    assert any(kind == "parameter" and args[0] == "ParamAngleY" for kind, args in runtime.calls)


def test_nod_does_not_auto_match_idle_daiji_motion():
    runtime = FakeRuntime()
    runtime.snapshot_data["capabilities"]["motion_entries"] = [
        {"group": "daiji", "index": 0, "file": "motions/daiji.motion3.json"},
        {"group": "nod", "index": 0, "file": "motions/nod.motion3.json"},
    ]
    controller, runtime = _controller(runtime)

    outcome = controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", actions=(_named_action("gesture", "nod"),)),
        1,
    )[0]
    assert outcome.status == "motion_applied"
    assert ("motion", "motions/nod.motion3.json") in runtime.calls


def test_missing_gesture_parameters_are_ignored_safely():
    runtime = FakeRuntime()
    runtime.snapshot_data["capabilities"]["parameter_specs"] = [
        {"parameter_id": "ParamMouthForm", "minimum": -1, "maximum": 1, "default": 0},
    ]
    runtime.snapshot_data["capabilities"]["motion_entries"] = []
    controller, _runtime = _controller(runtime)

    outcome = controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", actions=(_named_action("gesture", "nod"),)),
        1,
    )[0]
    assert outcome.status == "ignored"
    assert outcome.reason == "gesture_parameters_missing"


def test_happy_without_expression_uses_parameter_fallback():
    runtime = FakeRuntime()
    runtime.snapshot_data["capabilities"]["expression_entries"] = [
        {"id": "ku", "file": "expressions/exp01.exp3.json"},
    ]
    controller, runtime = _controller(runtime)

    outcome = controller.apply_turn_result(
        HostTurnResult("session", 1, "hi", emotion=EmotionDraft("happy")),
        1,
    )[0]
    controller.tick()
    assert outcome.status == "parameter_fallback"
    assert not any(kind == "expression" for kind, _ in runtime.calls)
    assert any(kind == "parameter" and args[0] == "ParamMouthForm" for kind, args in runtime.calls)


def test_look_at_and_idle_use_controlled_semantic_names():
    controller, runtime = _controller()
    result = HostTurnResult(
        "session",
        1,
        "hi",
        actions=(
            _named_action("look_at", "right"),
            ActionDraft("idle"),
            _named_action("look_at", "unknown"),
        ),
    )

    outcomes = controller.apply_turn_result(result, 1)
    controller.tick()

    assert [outcome.status for outcome in outcomes] == ["scheduled", "applied", "ignored"]
    assert ("idle", None) in runtime.calls
    assert any(kind == "parameter" and args[0] == "ParamEyeBallX" for kind, args in runtime.calls)


def test_activate_deactivate_and_unbind_clear_temporary_state():
    controller, runtime = _controller()
    controller.handle_playback_event(_event("start", "a"))
    controller.deactivate()
    assert not controller.active
    assert not controller.speech_lip_sync_active
    assert controller.handle_playback_event(_event("end", "a")).status == "ignored"

    controller.activate()
    controller.unbind_runtime()
    assert not controller.active
    assert runtime.callback is None
    assert controller.apply_turn_result(SimpleNamespace(actions=()), 1) == ()
