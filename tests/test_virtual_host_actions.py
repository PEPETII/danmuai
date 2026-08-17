from __future__ import annotations

import pytest
from app.live2d.actions import Live2DActionAdapter
from app.live2d.model_loader import ParameterSpec
from app.live2d.parameters import Live2DParameterController
from app.virtual_host.playback import PlaybackItem, PlaybackQueue


class FakeSink:
    def __init__(self) -> None:
        self.values = {"ParamMouthOpenY": 0.0}

    def get_parameter_value(self, parameter_id: str) -> float:
        return self.values[parameter_id]

    def set_parameter_value(self, parameter_id: str, value: float) -> None:
        self.values[parameter_id] = value


class FakePlayer:
    def __init__(self) -> None:
        self.callback = None
        self.pause_count = 0
        self.stop_count = 0

    def play(self, audio_bytes: bytes, on_complete):
        del audio_bytes
        self.callback = on_complete
        return object()

    def pause(self):
        self.pause_count += 1

    def stop(self):
        self.stop_count += 1


def _make_adapter(clock):
    spec = ParameterSpec("ParamMouthOpenY", 0.0, 1.0, 0.0, 0.0)
    sink = FakeSink()
    controller = Live2DParameterController((spec,), sink)
    adapter = Live2DActionAdapter(controller, (spec,), clock=clock)
    return adapter, sink


def test_playback_start_pause_and_end_drive_controlled_lip_sync_fallback():
    now = [0.0]
    adapter, sink = _make_adapter(lambda: now[0])
    player = FakePlayer()
    queue = PlaybackQueue(player)
    adapter.attach_playback_queue(queue)
    item = PlaybackItem("session-1", 1, 0, b"audio")

    assert queue.enqueue(item).status == "queued"
    assert adapter.speech_lip_sync_active
    adapter.tick(0.0)
    assert 0.0 < sink.values["ParamMouthOpenY"] <= 1.0

    assert queue.pause()
    assert not adapter.speech_lip_sync_active
    now[0] = 0.1
    adapter.tick()
    releasing = sink.values["ParamMouthOpenY"]
    assert 0.0 < releasing < 1.0

    queue.interrupt(reason="test_interrupt")
    now[0] = 0.5
    adapter.tick()
    assert sink.values["ParamMouthOpenY"] == pytest.approx(0.0)
    assert player.pause_count == 1
    assert player.stop_count == 1


def test_playback_end_event_closes_lip_without_audio_analysis_or_randomness():
    now = [1.0]
    adapter, sink = _make_adapter(lambda: now[0])
    adapter.handle_playback_event(type("Event", (), {"kind": "start"})())
    adapter.tick()
    opened = sink.values["ParamMouthOpenY"]
    adapter.handle_playback_event(type("Event", (), {"kind": "end"})())
    now[0] = 1.25
    adapter.tick()
    assert sink.values["ParamMouthOpenY"] == pytest.approx(0.0)
    assert opened == pytest.approx(0.29)
