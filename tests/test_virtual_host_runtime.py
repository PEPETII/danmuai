from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
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
from app.tts.audio import pcm_to_wav
from app.virtual_host.contracts import HostTurnResult, SceneContext
from app.virtual_host.model_config import (
    VISION_MODEL_KEY,
    apply_virtual_host_model_config,
    encode_tts_option_id,
    resolve_virtual_host_tts_binding,
    sanitize_virtual_host_model_config,
)
from app.virtual_host.playback import PlaybackQueue
from app.virtual_host.runtime_service import SceneVisionCoordinator, VirtualHostRuntimeService
from app.virtual_host.vision import SceneSummaryResult
from PyQt6.QtCore import QObject, QThreadPool, pyqtSlot

from tests.fakes import FakePixmap


class _FakeConfig:
    def __init__(self, data: dict | None = None, *, custom_models: list | None = None) -> None:
        self._data = dict(data or {})
        self._custom_models = list(custom_models or [])
        self._tts_secrets: dict[str, dict[str, str]] = {}

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def set_batch(self, items: dict[str, str]) -> None:
        self._data.update(items)

    def get_custom_models(self):
        return list(self._custom_models)

    def get_tts_api_key(self) -> str:
        return self._data.get("tts_api_key", "")

    def get_tts_secret(self, provider: str, field_id: str) -> str:
        return self._tts_secrets.get(provider, {}).get(field_id, "")

    def get_tts_secret_masked(self, provider: str, field_id: str) -> str:
        value = self.get_tts_secret(provider, field_id)
        return "********" if value else ""


def _vision_profile(model_id: str = "qwen3-vl-flash", *, api_key: str = "vision-secret") -> dict:
    return {
        "name": f"Vision {model_id}",
        "default_model_id": model_id,
        "model_ids": [model_id],
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "apiKey": api_key,
        "mode": "openai-compatible",
        "max_tokens": 512,
    }


def _danmu_profile(model_id: str = "danmu-model") -> dict:
    return {
        "name": "Danmu default",
        "default_model_id": model_id,
        "model_ids": [model_id],
        "endpoint": "https://api.openai.com/v1",
        "apiKey": "danmu-secret",
        "mode": "openai-compatible",
        "max_tokens": 512,
    }


class FakeTtsProvider(BaseTtsProvider):
    def __init__(self, descriptor: ProviderDescriptor, *, calls: list[str]) -> None:
        super().__init__(descriptor)
        self._calls = calls

    def synthesize(self, credentials, request, *, timeout_sec=60.0):
        del credentials, timeout_sec
        self._calls.append(request.model_id)
        return TtsResult(pcm_to_wav(b"\x00\x00" * 240), "wav")


def _tts_manager(*, calls: list[str] | None = None) -> TtsManager:
    recorded = calls if calls is not None else []
    voice = VoiceDescriptor("voice-1", "Voice 1")
    model = ModelDescriptor(
        id="vh-tts-model",
        label="VH TTS",
        capabilities=TtsCapabilities(),
        voices=(voice,),
    )
    descriptor = ProviderDescriptor(
        id="vh-tts-provider",
        label="VH TTS provider",
        auth=AuthDescriptor((AuthFieldDescriptor("api_key", "API key"),)),
        models=(model,),
    )
    provider = FakeTtsProvider(descriptor, calls=recorded)
    manager = TtsManager(ProviderRegistry([provider]), TtsCatalog([descriptor]))
    store = InMemoryCredentialStore()
    store.set("vh-tts-provider", {"api_key": "tts-secret"})
    manager.credentials = manager.credentials.__class__(store)
    return manager


def _fake_app(config: _FakeConfig) -> SimpleNamespace:
    return SimpleNamespace(config=config, personae=None, logger=SimpleNamespace(warning=lambda *a, **k: None))


class _FakePlayer:
    def __init__(self) -> None:
        self.current_callback = None

    def play(self, audio_bytes: bytes, on_complete):
        del audio_bytes
        self.current_callback = on_complete
        return object()

    def stop(self):
        pass

    def pause(self):
        pass


def test_runtime_vision_disabled_makes_zero_http_calls(monkeypatch):
    config = _FakeConfig(custom_models=[_vision_profile("vision-b")])
    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_scene_summary",
        lambda *_args, **_kwargs: pytest.fail("vision HTTP must not run"),
    )
    result = service.update_scene_from_image_data_uri(
        "data:image/jpeg;base64,ZmFrZQ==",
        screenshot_id=1,
        scene_generation=1,
    )
    assert result is None
    assert service.vision_request_count == 0


def test_runtime_vision_uses_virtual_host_model_not_danmu_default(monkeypatch):
    vision_model = "qwen3-vl-flash"
    config = _FakeConfig(
        {
            VISION_MODEL_KEY: vision_model,
            "default_model_id": "danmu-model",
        },
        custom_models=[_danmu_profile("danmu-model"), _vision_profile(vision_model)],
    )
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    seen: dict[str, str] = {}

    def _fake_request(image_data_uri, resolved, *, http_client=None):
        del image_data_uri, http_client
        seen["model_id"] = resolved[2]
        return SceneSummaryResult(ok=True, text="桌面浏览器窗口", model_id=resolved[2])

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _fake_request)
    result = service.update_scene_from_image_data_uri(
        "data:image/jpeg;base64,ZmFrZQ==",
        screenshot_id=7,
        scene_generation=3,
    )
    assert result is not None and result.ok is True
    assert seen["model_id"] == vision_model
    assert service.vision_request_count == 1
    context = service.session.current_scene_context()
    assert isinstance(context, SceneContext)
    assert context.summary == "桌面浏览器窗口"
    assert context.scene_generation == 3


def test_runtime_tts_binding_uses_virtual_host_provider(monkeypatch):
    tts_calls: list[str] = []
    manager = _tts_manager(calls=tts_calls)
    option_id = encode_tts_option_id("vh-tts-provider", "vh-tts-model")
    config = _FakeConfig(
        {
            "virtual_host_tts_provider": "vh-tts-provider",
            "virtual_host_tts_model_id": "vh-tts-model",
            "tts_provider": "vh-tts-provider",
            "tts_model_id": "danmu-read-model",
        }
    )
    config._tts_secrets["vh-tts-provider"] = {"api_key": "tts-secret"}
    monkeypatch.setattr(
        "app.virtual_host.model_config.list_tts_model_options",
        lambda _config: [
            {
                "id": option_id,
                "label": "VH",
                "provider_id": "vh-tts-provider",
                "model_id": "vh-tts-model",
            }
        ],
    )
    monkeypatch.setattr("app.virtual_host.runtime_service.get_tts_manager", lambda: manager)
    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    service.audio.playback = PlaybackQueue(_FakePlayer())
    binding = resolve_virtual_host_tts_binding(config, manager)
    assert binding is not None
    assert binding.model_id == "vh-tts-model"
    orchestrator = service.audio
    turn = orchestrator.begin_mic_turn(scene_generation=1)
    orchestrator.accept_transcript(turn.turn_id, "你好")
    orchestrator.submit_chat_result(turn.turn_id, HostTurnResult(session_id=service.session.session_id, turn_id=turn.turn_id, text="欢迎回来。"))
    state = orchestrator.synthesize_turn(turn.turn_id)
    assert state.tts_status == "completed"
    assert tts_calls == ["vh-tts-model"]
    assert service.tts_synthesize_count == 1


def test_runtime_tts_none_skips_synthesis(monkeypatch):
    config = _FakeConfig()
    monkeypatch.setattr("app.virtual_host.model_config.list_tts_model_options", lambda _config: [])
    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    orchestrator = service.audio
    turn = orchestrator.begin_mic_turn(scene_generation=1)
    orchestrator.accept_transcript(turn.turn_id, "你好")
    orchestrator.submit_chat_result(
        turn.turn_id,
        HostTurnResult(session_id=service.session.session_id, turn_id=turn.turn_id, text="欢迎回来。"),
    )
    state = orchestrator.synthesize_turn(turn.turn_id)
    assert state.tts_status == "skipped"
    assert service.tts_synthesize_count == 0


def test_stale_virtual_host_model_sanitized_without_fallback(monkeypatch):
    vision_model = "qwen3-vl-flash"
    config = _FakeConfig(
        {
            VISION_MODEL_KEY: "deleted-model",
            "virtual_host_tts_provider": "vh-tts-provider",
            "virtual_host_tts_model_id": "missing-model",
        },
        custom_models=[_vision_profile(vision_model)],
    )
    monkeypatch.setattr("app.virtual_host.model_config.list_tts_model_options", lambda _config: [])
    normalized = sanitize_virtual_host_model_config(config, persist=True)
    assert normalized[VISION_MODEL_KEY] == ""
    assert normalized["virtual_host_tts_provider"] == ""
    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    assert service.update_scene_from_image_data_uri(
        "data:image/jpeg;base64,ZmFrZQ==",
        screenshot_id=1,
        scene_generation=1,
    ) is None
    assert service.vision_request_count == 0
    assert service.audio.tts_binding is None


def test_request_scene_summary_posts_expected_model(monkeypatch):
    vision_model = "qwen3-vl-flash"
    config = _FakeConfig(custom_models=[_vision_profile(vision_model)])
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "游戏画面"}}]}

    class _FakeClient:
        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr("app.virtual_host.vision.httpx.Client", lambda **kwargs: _FakeClient())
    from app.virtual_host.model_config import resolve_virtual_host_vision_credentials
    from app.virtual_host.vision import request_scene_summary

    resolved = resolve_virtual_host_vision_credentials(config)
    assert resolved is not None
    result = request_scene_summary("data:image/jpeg;base64,ZmFrZQ==", resolved)
    assert result.ok is True
    assert result.model_id == vision_model
    assert vision_model in str(captured.get("json"))


def _vision_config(
    vision_model: str = "qwen3-vl-flash",
    *,
    extra_models: list | None = None,
) -> _FakeConfig:
    models = list(extra_models or [])
    if not any(
        isinstance(m, dict) and m.get("default_model_id") == vision_model for m in models
    ):
        models.append(_vision_profile(vision_model))
    config = _FakeConfig({VISION_MODEL_KEY: vision_model}, custom_models=models)
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    return config


def _vision_service(monkeypatch, config: _FakeConfig) -> VirtualHostRuntimeService:
    pool = QThreadPool()
    monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: pool)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.compress_screenshot",
        lambda _pixmap: "data:image/jpeg;base64,ZmFrZQ==",
    )
    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    return service


class _SceneVisionCompleteReceiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.thread_ids: list[int] = []

    @pyqtSlot(object, int, int, float, int, str)
    def on_completed(
        self,
        _result: object,
        _screenshot_id: int,
        _scene_generation: int,
        _captured_at: float,
        _runtime_generation: int,
        _vision_model_id: str,
    ) -> None:
        self.thread_ids.append(threading.get_ident())


def test_scene_vision_worker_result_delivered_on_main_thread_via_signal(qapp, monkeypatch):
    config = _vision_config()
    service = _vision_service(monkeypatch, config)
    coordinator = SceneVisionCoordinator()
    receiver = _SceneVisionCompleteReceiver()
    coordinator.completed.connect(receiver.on_completed)
    main_thread_id = threading.get_ident()

    def _fake_request(_image_data_uri, resolved, *, http_client=None):
        del http_client
        return SceneSummaryResult(ok=True, text="主线程信号", model_id=resolved[2])

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _fake_request)

    from app.virtual_host.runtime_service import _SceneVisionRunnable

    resolved = service._active_vision_model_id
    runnable = _SceneVisionRunnable(
        coordinator,
        image_data_uri="data:image/jpeg;base64,ZmFrZQ==",
        resolved=(
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "vision-secret",
            resolved,
            "openai-compatible",
        ),
        screenshot_id=1,
        scene_generation=1,
        captured_at=1.0,
        runtime_generation=service.runtime_generation,
        vision_model_id=resolved,
    )

    worker = threading.Thread(target=runnable.run)
    worker.start()
    worker.join(timeout=2.0)
    assert not worker.is_alive()

    deadline = time.monotonic() + 1.0
    while not receiver.thread_ids and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert receiver.thread_ids == [main_thread_id]


def test_scene_vision_stale_result_after_stop_does_not_update_scene_context(qapp, monkeypatch):
    config = _vision_config()
    service = _vision_service(monkeypatch, config)

    def _slow_request(_image_data_uri, resolved, *, http_client=None):
        del http_client
        time.sleep(0.05)
        return SceneSummaryResult(ok=True, text="stop 后过期", model_id=resolved[2])

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _slow_request)

    service.on_capture_completed(
        FakePixmap(1),
        screenshot_id=9,
        scene_generation=2,
    )
    assert service.vision_in_flight
    service.stop()

    deadline = time.monotonic() + 2.0
    while service.vision_in_flight and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert not service.vision_in_flight
    context = service.session.current_scene_context()
    assert context is None or context.summary != "stop 后过期"


def test_scene_vision_stale_result_after_stop_start_does_not_update_scene_context(qapp, monkeypatch):
    config = _vision_config()
    service = _vision_service(monkeypatch, config)

    def _slow_request(_image_data_uri, resolved, *, http_client=None):
        del http_client
        time.sleep(0.05)
        return SceneSummaryResult(ok=True, text="上一周期", model_id=resolved[2])

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _slow_request)

    service.on_capture_completed(
        FakePixmap(1),
        screenshot_id=3,
        scene_generation=1,
    )
    service.stop()
    service.start()

    deadline = time.monotonic() + 2.0
    while service.vision_in_flight and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    context = service.session.current_scene_context()
    assert context is None or context.summary != "上一周期"


def test_scene_vision_stale_model_result_does_not_update_scene_context(qapp, monkeypatch):
    model_a = "qwen3-vl-flash"
    model_b = "vision-model-b"
    config = _vision_config(
        model_a,
        extra_models=[_vision_profile(model_b, api_key="vision-b")],
    )
    service = _vision_service(monkeypatch, config)

    def _slow_request(_image_data_uri, resolved, *, http_client=None):
        del http_client
        time.sleep(0.05)
        return SceneSummaryResult(ok=True, text="旧模型 A", model_id=resolved[2])

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _slow_request)

    service.on_capture_completed(
        FakePixmap(1),
        screenshot_id=5,
        scene_generation=4,
    )
    config.set_batch({VISION_MODEL_KEY: model_b})
    service.refresh_model_bindings()

    deadline = time.monotonic() + 2.0
    while service.vision_in_flight and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    context = service.session.current_scene_context()
    assert context is None or context.summary != "旧模型 A"


def test_scene_vision_success_clears_vision_in_flight(qapp, monkeypatch):
    config = _vision_config()
    service = _vision_service(monkeypatch, config)

    def _fake_request(_image_data_uri, resolved, *, http_client=None):
        del http_client
        return SceneSummaryResult(ok=True, text="正常完成", model_id=resolved[2])

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _fake_request)

    service.on_capture_completed(
        FakePixmap(1),
        screenshot_id=11,
        scene_generation=6,
    )
    assert service.vision_in_flight

    deadline = time.monotonic() + 2.0
    while service.vision_in_flight and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert not service.vision_in_flight
    context = service.session.current_scene_context()
    assert context is not None
    assert context.summary == "正常完成"


def test_scene_vision_http_failure_clears_vision_in_flight(qapp, monkeypatch):
    config = _vision_config()
    service = _vision_service(monkeypatch, config)

    def _failed_request(_image_data_uri, resolved, *, http_client=None):
        del resolved, http_client
        return SceneSummaryResult(ok=False, error="http_error")

    monkeypatch.setattr("app.virtual_host.runtime_service.request_scene_summary", _failed_request)

    service.on_capture_completed(
        FakePixmap(1),
        screenshot_id=12,
        scene_generation=7,
    )
    assert service.vision_in_flight

    deadline = time.monotonic() + 2.0
    while service.vision_in_flight and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert not service.vision_in_flight
    assert service.session.current_scene_context() is None
