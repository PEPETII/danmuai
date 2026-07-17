"""Mic input device enumeration semantics (Host API dedup, role classification)."""

from types import SimpleNamespace

import pytest

from app.mic_capture import (
    MicInputDeviceInfo,
    _classify_input_role,
    _iter_input_candidates,
    _select_mic_picker_candidates,
    list_input_devices,
)


def _windows_realtek_fixture_devices():
    """Synthetic PortAudio layout mirroring a Realtek quad-Host-API Windows machine."""
    return [
        {"name": "Microsoft 声音映射器 - Input", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
        {"name": "麦克风阵列 (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Microsoft 声音映射器 - Output", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
        {"name": "扬声器 (Realtek(R) Audio)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 8},
        {"name": "主声音捕获驱动程序", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
        {"name": "麦克风阵列 (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
        {"name": "主声音驱动程序", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
        {"name": "扬声器 (Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 8},
        {"name": "扬声器 (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 0, "max_output_channels": 2},
        {"name": "麦克风阵列 (Realtek(R) Audio)", "hostapi": 2, "max_input_channels": 2, "max_output_channels": 0},
        {"name": "Speakers 1 (Realtek HD Audio output with SST)", "hostapi": 3, "max_input_channels": 0, "max_output_channels": 2},
        {"name": "Speakers 2 (Realtek HD Audio output with SST)", "hostapi": 3, "max_input_channels": 0, "max_output_channels": 8},
        {
            "name": "电脑扬声器 (Realtek HD Audio output with SST)",
            "hostapi": 3,
            "max_input_channels": 2,
            "max_output_channels": 0,
        },
        {"name": "麦克风 (Realtek HD Audio Mic input)", "hostapi": 3, "max_input_channels": 2, "max_output_channels": 0},
        {
            "name": "立体声混音 (Realtek HD Audio Stereo input)",
            "hostapi": 3,
            "max_input_channels": 2,
            "max_output_channels": 0,
        },
        {
            "name": "麦克风阵列 (Realtek HD Audio Mic Array input)",
            "hostapi": 3,
            "max_input_channels": 2,
            "max_output_channels": 0,
        },
    ]


def _hostapi_names():
    return {
        0: "MME",
        1: "Windows DirectSound",
        2: "Windows WASAPI",
        3: "Windows WDM-KS",
    }


def test_classify_render_loopback_from_wdm_ks_output_suffix():
    role, is_loopback = _classify_input_role(
        name="电脑扬声器 (Realtek HD Audio output with SST)",
        hostapi_slug="wdm-ks",
        output_names_on_hostapi=set(),
    )
    assert role == "render_loopback"
    assert is_loopback is True


def test_classify_stereo_mix_from_wdm_ks_suffix():
    role, is_loopback = _classify_input_role(
        name="立体声混音 (Realtek HD Audio Stereo input)",
        hostapi_slug="wdm-ks",
        output_names_on_hostapi=set(),
    )
    assert role == "stereo_mix"
    assert is_loopback is True


def test_classify_physical_mic_from_wdm_ks_suffix():
    role, is_loopback = _classify_input_role(
        name="麦克风 (Realtek HD Audio Mic input)",
        hostapi_slug="wdm-ks",
        output_names_on_hostapi=set(),
    )
    assert role == "microphone"
    assert is_loopback is False


def test_classify_virtual_mapper_alias():
    role, is_loopback = _classify_input_role(
        name="Microsoft 声音映射器 - Input",
        hostapi_slug="mme",
        output_names_on_hostapi=set(),
    )
    assert role == "virtual_mapper"
    assert is_loopback is False


def test_select_prefers_wasapi_and_dedupes_cross_hostapi(monkeypatch):
    monkeypatch.setattr("app.mic_capture.platform.system", lambda: "Windows")
    candidates = _iter_input_candidates(_windows_realtek_fixture_devices(), _hostapi_names())
    selected = _select_mic_picker_candidates(candidates)

    assert len(selected) == 1
    assert selected[0]["id"] == 9
    assert selected[0]["hostapi"] == "wasapi"
    assert selected[0]["role"] == "microphone"
    assert selected[0]["name"] == "麦克风阵列 (Realtek(R) Audio)"


def test_fixture_excludes_render_loopback_and_stereo_mix(monkeypatch):
    monkeypatch.setattr("app.mic_capture.platform.system", lambda: "Windows")
    candidates = _iter_input_candidates(_windows_realtek_fixture_devices(), _hostapi_names())
    by_name = {item["name"]: item for item in candidates}

    assert by_name["电脑扬声器 (Realtek HD Audio output with SST)"]["role"] == "render_loopback"
    assert by_name["立体声混音 (Realtek HD Audio Stereo input)"]["role"] == "stereo_mix"
    selected_names = {item["name"] for item in _select_mic_picker_candidates(candidates)}
    assert "电脑扬声器 (Realtek HD Audio output with SST)" not in selected_names
    assert "立体声混音 (Realtek HD Audio Stereo input)" not in selected_names


def test_non_windows_falls_back_to_hostapi_priority_dedupe(monkeypatch):
    monkeypatch.setattr("app.mic_capture.platform.system", lambda: "Linux")
    devices = [
        {"name": "USB Mic", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
        {"name": "USB Mic", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0},
    ]
    hostapi_names = {0: "ALSA", 1: "JACK Audio Connection Kit"}
    candidates = _iter_input_candidates(devices, hostapi_names)
    selected = _select_mic_picker_candidates(candidates)
    assert len(selected) == 1
    assert selected[0]["id"] == 0


def test_wasapi_absent_keeps_best_available_physical_mic(monkeypatch):
    monkeypatch.setattr("app.mic_capture.platform.system", lambda: "Windows")
    devices = [
        {"name": "USB Headset", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0},
        {"name": "USB Headset", "hostapi": 1, "max_input_channels": 1, "max_output_channels": 0},
    ]
    hostapi_names = {0: "MME", 1: "Windows DirectSound"}
    candidates = _iter_input_candidates(devices, hostapi_names)
    selected = _select_mic_picker_candidates(candidates)
    assert len(selected) == 1
    assert selected[0]["hostapi"] == "directsound"


class _FakeSd:
    def __init__(self, devices, default_input=1):
        self._devices = devices
        self.default = SimpleNamespace(device=(default_input, 3))

    def query_devices(self, device_id=None):
        if device_id is None:
            return self._devices
        return self._devices[device_id]

    def query_hostapis(self):
        return tuple({"name": name} for name in _hostapi_names().values())


def test_list_input_devices_marks_default_by_normalized_name(monkeypatch):
    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", True)
    monkeypatch.setattr("app.mic_capture.platform.system", lambda: "Windows")
    monkeypatch.setattr(
        "app.mic_capture.sd",
        _FakeSd(_windows_realtek_fixture_devices(), default_input=1),
    )

    items = list_input_devices()
    assert len(items) == 1
    assert items[0] == MicInputDeviceInfo(
        id=9,
        name="麦克风阵列 (Realtek(R) Audio)",
        is_default=True,
        max_input_channels=2,
        hostapi="wasapi",
        role="microphone",
        is_loopback=False,
    )


def test_list_input_devices_returns_empty_when_sounddevice_missing(monkeypatch):
    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", False)
    assert list_input_devices() == []


def test_list_input_devices_swallows_query_errors(monkeypatch):
    class _BrokenSd:
        default = SimpleNamespace(device=(0, 0))

        def query_devices(self, device_id=None):
            raise RuntimeError("driver unavailable")

        def query_hostapis(self):
            raise RuntimeError("driver unavailable")

    monkeypatch.setattr("app.mic_capture._HAS_SOUNDDEVICE", True)
    monkeypatch.setattr("app.mic_capture.sd", _BrokenSd())
    assert list_input_devices() == []