"""虚拟主播对话开关与语音会话生命周期测试。"""

from __future__ import annotations

from app.virtual_host.mode_config import apply_virtual_host_mode_settings
from app.virtual_host.model_config import VISION_MODEL_KEY, apply_virtual_host_model_config
from app.virtual_host.runtime_service import VirtualHostRuntimeService

from tests.test_virtual_host_runtime import (
    _fake_app,
    _FakeConfig,
    _register_runtime_test,
    _vision_profile,
)


def _dialogue_config(*, dialogue: bool = True, adapter: bool = False) -> _FakeConfig:
    config = _FakeConfig(
        {
            "virtual_host_dialogue_enabled": "1" if dialogue else "0",
            "virtual_host_danmu_adapter_enabled": "1" if adapter else "0",
            VISION_MODEL_KEY: "qwen3-vl-flash",
        },
        custom_models=[_vision_profile()],
    )
    apply_virtual_host_model_config(config, {"vision_model_id": "qwen3-vl-flash"})
    return config


def _runtime(monkeypatch, config: _FakeConfig) -> VirtualHostRuntimeService:
    service = VirtualHostRuntimeService(_fake_app(config))
    _register_runtime_test(service)
    return service


def test_runtime_start_auto_arms_voice_when_dialogue_enabled(monkeypatch, qapp):
    service = _runtime(monkeypatch, _dialogue_config(dialogue=True))
    assert not service.voice_session_armed

    service.start()
    qapp.processEvents()

    assert service.running is True
    assert service.dialogue_enabled is True
    assert service.voice_session_armed is True
    assert service.mic_route_active() is True


def test_runtime_start_does_not_arm_voice_when_dialogue_disabled(monkeypatch, qapp):
    service = _runtime(monkeypatch, _dialogue_config(dialogue=False))
    service.start()
    qapp.processEvents()

    assert service.running is True
    assert service.voice_session_armed is False
    assert service.mic_route_active() is False


def test_runtime_stop_disarms_voice_and_resets_mic_route(monkeypatch, qapp):
    service = _runtime(monkeypatch, _dialogue_config(dialogue=True))
    service.start()
    assert service.voice_session_armed is True
    service.on_mic_speech_start()

    service.stop()
    qapp.processEvents()

    assert service.running is False
    assert service.voice_session_armed is False
    assert service.mic_route_active() is False
    assert not service.on_mic_speech_start()


def test_enable_dialogue_while_running_auto_arms_voice(monkeypatch, qapp):
    config = _dialogue_config(dialogue=False)
    service = _runtime(monkeypatch, config)
    service.start()
    assert service.voice_session_armed is False

    apply_virtual_host_mode_settings(config, {"dialogue_enabled": True})
    service.refresh_mode_settings()
    qapp.processEvents()

    assert service.dialogue_enabled is True
    assert service.voice_session_armed is True
    assert service.mic_route_active() is True


def test_disable_dialogue_while_running_disarms_voice(monkeypatch, qapp):
    config = _dialogue_config(dialogue=True)
    service = _runtime(monkeypatch, config)
    service.start()
    assert service.voice_session_armed is True

    apply_virtual_host_mode_settings(config, {"dialogue_enabled": False})
    service.refresh_mode_settings()
    qapp.processEvents()

    assert service.dialogue_enabled is False
    assert service.voice_session_armed is False
    assert not service.on_mic_speech_start()


def test_repeated_runtime_start_does_not_duplicate_voice_arm(monkeypatch, qapp):
    service = _runtime(monkeypatch, _dialogue_config(dialogue=True))
    service.start()
    first_generation = service.runtime_generation
    assert service.voice_session_armed is True

    service.stop()
    service.start()
    qapp.processEvents()

    assert service.voice_session_armed is True
    assert service.runtime_generation > first_generation
    assert service.mic_route_active() is True


def test_runtime_stop_cancels_in_flight_user_mic_turn(monkeypatch, qapp):
    service = _runtime(monkeypatch, _dialogue_config(dialogue=True))
    service.start()
    service.on_mic_speech_start()
    turn = service.audio.get_turn(1)
    assert turn.status != "cancelled"

    service.stop()
    qapp.processEvents()

    turn = service.audio.get_turn(1)
    assert turn.status == "cancelled"
