from __future__ import annotations

import inspect
import threading

import pytest
from app.live2d.actions import Live2DActionAdapter
from app.live2d.model_loader import ParameterSpec
from app.live2d.parameters import Live2DParameterController


class FakeSink:
    def __init__(self, values: dict[str, float]) -> None:
        self.values = dict(values)

    def get_parameter_value(self, parameter_id: str) -> float:
        return self.values[parameter_id]

    def set_parameter_value(self, parameter_id: str, value: float) -> None:
        self.values[parameter_id] = value


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _adapter(
    clock: FakeClock | None = None,
    *,
    controller_present: bool = True,
    emotion_map=None,
    reaction_map=None,
):
    specs = (
        ParameterSpec("ParamMouthOpenY", 0.0, 1.0, 0.0, 0.0),
        ParameterSpec("ParamMouthForm", -1.0, 1.0, 0.0, 0.0),
        ParameterSpec("ParamAngleX", -30.0, 30.0, 0.0, 0.0),
        ParameterSpec("ParamEyeLOpen", 0.0, 1.0, 1.0, 1.0),
    )
    sink = FakeSink({spec.parameter_id: spec.current for spec in specs})
    controller = Live2DParameterController(specs, sink) if controller_present else None
    return (
        Live2DActionAdapter(
            controller,
            specs,
            emotion_map=emotion_map,
            reaction_map=reaction_map,
            clock=clock or FakeClock(),
        ),
        sink,
        specs,
    )


def test_dispatch_uses_real_parameter_specs_and_clamps_values_and_duration():
    clock = FakeClock()
    adapter, sink, _specs = _adapter(clock)

    assert adapter.managed_parameter_ids["mouth_open"] == "ParamMouthOpenY"
    result = adapter.dispatch(
        {
            "type": "set_parameter",
            "logical_name": "mouth_open",
            "value": 4,
            "duration": 99,
            "restore": False,
        }
    )

    assert result.ok
    assert result.status == "scheduled"
    assert result.clamped
    adapter.tick(0.0)
    assert sink.values["ParamMouthOpenY"] == pytest.approx(1.0)


def test_layers_prioritize_reaction_then_restore_emotion_then_idle_default():
    clock = FakeClock()
    adapter, sink, _specs = _adapter(
        clock,
        emotion_map={"happy": {"angle_x": 1.0}},
        reaction_map={"nod": {"angle_x": -1.0}},
    )

    assert adapter.set_emotion("happy", intensity=1.0, duration=3).ok
    adapter.tick(0.0)
    assert sink.values["ParamAngleX"] == pytest.approx(30.0)

    reaction = adapter.play_reaction("nod", intensity=1.0, duration=1.0)
    assert reaction.ok
    adapter.tick(0.5)
    assert sink.values["ParamAngleX"] == pytest.approx(-30.0)

    adapter.tick(1.1)
    assert sink.values["ParamAngleX"] == pytest.approx(30.0)
    adapter.tick(3.1)
    assert sink.values["ParamAngleX"] == pytest.approx(0.0)


def test_unknown_missing_unloaded_and_cancelled_actions_are_structured():
    unloaded, _sink, _specs = _adapter(controller_present=False)
    assert unloaded.set_parameter("mouth_open", 0.5).reason == "model_not_loaded"
    assert unloaded.dispatch({"type": "set_emotion", "name": "unknown"}).status == "unsupported"

    adapter, sink, _specs = _adapter()
    missing = adapter.set_parameter("not_managed", 0.5)
    assert missing.status == "unsupported"
    assert missing.reason == "logical_name_not_allowed"

    scheduled = adapter.set_parameter("mouth_open", 0.8, duration=5)
    assert scheduled.ok
    cancelled = adapter.cancel(scheduled.action_id)
    assert cancelled.status == "cancelled"
    adapter.tick(0.0)
    assert sink.values["ParamMouthOpenY"] == pytest.approx(0.0)
    assert adapter.cancel("stale-action").reason == "action_not_found"


def test_dispatch_rejects_untrusted_shapes_without_passing_strings_to_native():
    adapter, _sink, _specs = _adapter()

    assert adapter.dispatch("set_parameter").reason == "action_must_be_object"
    assert adapter.dispatch({"type": "run_native", "name": "ParamMouthOpenY"}).status == "unsupported"
    assert adapter.dispatch({"type": []}).status == "unsupported"
    assert adapter.dispatch({"type": "set_parameter", "logical_name": "mouth_open", "value": True}).status == "rejected"
    assert adapter.dispatch({"type": "set_parameter", "logical_name": "mouth_open", "value": 0.5, "restore": "yes"}).status == "rejected"


def test_cross_thread_tick_requires_dispatcher_and_does_not_touch_sink():
    adapter, sink, _specs = _adapter()
    scheduled = adapter.set_parameter("mouth_open", 1.0, duration=3, restore=False)
    assert scheduled.ok
    result_holder = {}

    worker = threading.Thread(
        target=lambda: result_holder.setdefault("updates", adapter.tick(0.0))
    )
    worker.start()
    worker.join()

    updates = result_holder["updates"]
    assert updates
    assert all(update.reason == "thread_violation" for update in updates)
    assert sink.values["ParamMouthOpenY"] == pytest.approx(0.0)


def test_idle_is_deterministic_low_frequency_and_runtime_isolated_from_pet():
    import app.live2d.actions as actions_module

    adapter, sink, _specs = _adapter()
    assert adapter.configure_idle("angle_x", amplitude=0.2, period_seconds=8).ok
    adapter.tick(0.0)
    first = sink.values["ParamAngleX"]
    adapter.tick(0.05)
    assert sink.values["ParamAngleX"] == pytest.approx(first)
    adapter.tick(0.2)
    assert sink.values["ParamAngleX"] != pytest.approx(first)

    source = inspect.getsource(actions_module)
    assert "app.pet" not in source
    assert "pet_animation_mapper" not in source
    assert "app.overlay" not in source
