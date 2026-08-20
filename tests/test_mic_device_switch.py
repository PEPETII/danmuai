"""Runtime microphone input device switching and stream cleanup."""

from types import SimpleNamespace

import pytest
from app.mic_capture import MicCaptureService
from app.mic_service import MicService


class _TrackingStream:
    instances: list["_TrackingStream"] = []
    closed: list["_TrackingStream"] = []

    def __init__(self, *, device):
        self.device = device
        self.started = False
        _TrackingStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        return None

    def close(self):
        _TrackingStream.closed.append(self)


class _FakeSd:
    def __init__(self, *, default_device=4):
        self.default = SimpleNamespace(device=(default_device, 7))

    def query_devices(self, device_id=None):
        if device_id is None:
            return [
                {"name": "Mic A", "max_input_channels": 1},
                {"name": "Mic B", "max_input_channels": 1},
                {"name": "Mic C", "max_input_channels": 0},
                {"name": "Default Mic", "max_input_channels": 1},
            ]
        if device_id in (0, 1, 4):
            names = {0: "Mic A", 1: "Mic B", 4: "Default Mic"}
            return {"name": names[device_id], "max_input_channels": 1}
        raise RuntimeError(f"missing device {device_id}")

    def InputStream(self, **kwargs):
        return _TrackingStream(device=kwargs.get("device"))


@pytest.fixture
def fake_sd(monkeypatch):
    _TrackingStream.instances.clear()
    _TrackingStream.closed.clear()
    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", True)
    monkeypatch.setattr("app.mic_capture.sd", _FakeSd())
    return _FakeSd


def test_mic_capture_restarts_stream_when_running_device_changes(fake_sd):
    cap = MicCaptureService()
    assert cap.start(preferred_device_id=0) is True
    first = _TrackingStream.instances[0]
    assert cap.active_device_id == 0

    assert cap.start(preferred_device_id=1) is True
    assert first in _TrackingStream.closed
    assert len(_TrackingStream.instances) == 2
    assert _TrackingStream.instances[-1].device == 1
    assert cap.active_device_id == 1
    assert cap.is_running()


def test_mic_capture_start_noop_when_same_device_requested(fake_sd):
    cap = MicCaptureService()
    assert cap.start(preferred_device_id=0) is True
    assert len(_TrackingStream.instances) == 1

    assert cap.start(preferred_device_id=0) is True
    assert len(_TrackingStream.instances) == 1
    assert len(_TrackingStream.closed) == 0


def test_mic_capture_start_failure_closes_partial_stream(monkeypatch):
    class _FailOnStartStream:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("device busy")

        def stop(self):
            return None

        def close(self):
            _FailOnStartStream.closed = True

    _FailOnStartStream.closed = False

    class _FailSd(_FakeSd):
        def InputStream(self, **kwargs):
            return _FailOnStartStream()

    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", True)
    monkeypatch.setattr("app.mic_capture.sd", _FailSd())

    cap = MicCaptureService()
    assert cap.start(preferred_device_id=0) is False
    assert cap.last_error == "device busy"
    assert cap.is_running() is False
    assert _FailOnStartStream.closed is True


def test_mic_capture_stop_closes_stream_when_not_marked_running(monkeypatch):
    class _BareStream:
        closed = False

        def stop(self):
            return None

        def close(self):
            _BareStream.closed = True

    cap = MicCaptureService()
    cap._stream = _BareStream()
    cap._running = False

    cap.stop()
    assert _BareStream.closed is True
    assert cap._stream is None


def test_mic_capture_rapid_device_switch_closes_all_old_streams(fake_sd):
    cap = MicCaptureService()
    for device_id in (0, 1, 0, 1):
        assert cap.start(preferred_device_id=device_id) is True

    assert len(_TrackingStream.instances) == 4
    closed = _TrackingStream.closed
    assert closed == _TrackingStream.instances[:3]
    assert cap.active_device_id == 1
    assert cap.is_running()


def test_mic_capture_switch_to_missing_device_falls_back_and_stays_consistent(fake_sd):
    cap = MicCaptureService()
    assert cap.start(preferred_device_id=0) is True
    first = _TrackingStream.instances[0]

    assert cap.start(preferred_device_id=99) is True
    assert first in _TrackingStream.closed
    assert cap.active_device_id == 4
    assert cap.fallback_to_default is True
    assert cap.is_running()


def test_mic_service_sync_applies_device_while_running(fake_sd):
    svc = MicService()
    svc.sync(enabled=True, preferred_device_id=0)
    assert svc.is_running()
    assert svc.active_input_device_id() == 0

    svc.sync(enabled=True, preferred_device_id=1)
    assert svc.is_running()
    assert svc.active_input_device_id() == 1
    assert len(_TrackingStream.instances) == 2
    assert _TrackingStream.instances[0] in _TrackingStream.closed


def test_mic_service_sync_stop_start_cycle_no_dual_streams(fake_sd):
    svc = MicService()
    svc.sync(enabled=True, preferred_device_id=0)
    svc.sync(enabled=True, preferred_device_id=1)
    svc.sync(enabled=False)
    assert not svc.is_running()
    assert len(_TrackingStream.closed) == 2

    svc.sync(enabled=True, preferred_device_id=0)
    assert svc.is_running()
    assert svc.active_input_device_id() == 0
    assert len(_TrackingStream.instances) == 3
