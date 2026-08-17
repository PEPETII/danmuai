from __future__ import annotations

import inspect
import json
import threading
from pathlib import Path

import pytest
from app.live2d import (
    Live2DHostFacade,
    Live2DModelLoader,
    Live2DParameterController,
    Live2DRenderer,
    ParameterSpec,
    QtOpenGLLive2DBackend,
)


class FakeTimer:
    def __init__(self, callback, events):
        self.callback = callback
        self.events = events

    def start(self, interval_ms: int) -> None:
        self.events.append(("timer_start", interval_ms))

    def stop(self) -> None:
        self.events.append(("timer_stop",))


class FakeSink:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get_parameter_value(self, parameter_id: str) -> float:
        return self.values[parameter_id]

    def set_parameter_value(self, parameter_id: str, value: float) -> None:
        self.values[parameter_id] = value


class FakeBackend:
    def __init__(self, *, fail_create: bool = False):
        self.fail_create = fail_create
        self.events = []
        self.sink = FakeSink({"ParamMouthOpenY": 0.0})

    def create_model(self, model_path: Path, capabilities):
        self.events.append(("create", model_path, capabilities))
        if self.fail_create:
            raise RuntimeError("injected backend load failure")
        return object()

    def get_parameter_sink(self, model):
        self.events.append(("parameter_sink",))
        return self.sink

    def update(self, model, delta_sec: float) -> None:
        self.events.append(("update", delta_sec))

    def render(self, model) -> None:
        self.events.append(("render",))

    def show(self) -> None:
        self.events.append(("show",))

    def hide(self) -> None:
        self.events.append(("hide",))

    def close_window(self) -> None:
        self.events.append(("close_window",))

    def destroy_model(self, model) -> None:
        self.events.append(("destroy",))

    def dispose(self) -> None:
        self.events.append(("dispose",))


class FakeWindow:
    def __init__(self):
        self.events = []

    def show(self):
        self.events.append("show")

    def hide(self):
        self.events.append("hide")

    def close(self):
        self.events.append("close")


class FakeSdk:
    def __init__(self):
        self.events = []

    def load_model(self, model_path, capabilities):
        self.events.append("load")
        return object()

    def parameter_sink(self, model):
        return FakeSink()

    def update(self, model, delta_sec):
        self.events.append("update")

    def render(self, model):
        self.events.append("render")

    def destroy_model(self, model):
        self.events.append("destroy")

    def dispose(self):
        self.events.append("dispose")


def _write_model(tmp_path, *, missing: bool = False) -> Path:
    model_dir = tmp_path / "外部模型 with spaces"
    model_dir.mkdir()
    references = {
        "Moc": "avatar.moc3",
        "Textures": ["texture 00.png"],
        "Physics": "avatar.physics3.json",
        "Motions": {"Idle": ["idle.motion3.json"]},
        "Expressions": [{"Name": "smile", "File": "smile.exp3.json"}],
    }
    model_path = model_dir / "avatar.model3.json"
    model_path.write_text(json.dumps({"FileReferences": references}), encoding="utf-8")
    if not missing:
        for name in (
            "avatar.moc3",
            "texture 00.png",
            "avatar.physics3.json",
            "idle.motion3.json",
            "smile.exp3.json",
        ):
            (model_dir / name).write_bytes(b"test")
    return model_path


def _loader(model_path: Path) -> Live2DModelLoader:
    return Live2DModelLoader(
        parameter_discoverer=lambda _path: [
            {
                "parameter_id": "ParamMouthOpenY",
                "minimum": 0,
                "maximum": 1,
                "default": 0,
                "current": 0,
            }
        ]
    )


def _renderer_factory(backend: FakeBackend) -> Live2DRenderer:
    return Live2DRenderer(
        backend,
        timer_factory=lambda callback: FakeTimer(callback, backend.events),
    )


def test_loader_accepts_valid_model_and_path_with_spaces(tmp_path):
    model_path = _write_model(tmp_path)
    result = _loader(model_path).load(str(model_path))

    assert result.ok
    assert result.status == "ready"
    assert result.model_path == "<external-model>/avatar.model3.json"
    assert result.capabilities.motion_groups == ("Idle",)
    assert result.capabilities.expression_ids == ("smile",)
    assert result.capabilities.parameter_ids == ("ParamMouthOpenY",)
    assert "外部模型" not in result.as_dict()["model_path"]


def test_loader_rejects_empty_missing_and_wrong_extension(tmp_path):
    loader = Live2DModelLoader()
    missing = tmp_path / "missing.model3.json"
    wrong = tmp_path / "avatar.json"
    wrong.write_text("{}", encoding="utf-8")

    assert loader.load(" ").reason == "empty_model_path"
    assert loader.load(missing).reason == "model_not_found"
    assert loader.load(wrong).reason == "invalid_model_extension"


def test_loader_rejects_model_without_file_references(tmp_path):
    model_path = tmp_path / "avatar.model3.json"
    model_path.write_text("{}", encoding="utf-8")

    result = Live2DModelLoader().load(model_path)

    assert not result.ok
    assert result.status == "invalid"
    assert result.reason == "model_references_invalid"


def test_loader_reports_missing_dependencies_without_leaking_path(tmp_path):
    model_path = _write_model(tmp_path, missing=True)
    result = Live2DModelLoader().load(model_path)

    assert not result.ok
    assert result.status == "blocked"
    assert result.reason == "dependency_missing"
    assert set(result.capabilities.missing_dependencies) == {
        "avatar.moc3",
        "texture 00.png",
        "avatar.physics3.json",
        "idle.motion3.json",
        "smile.exp3.json",
    }
    assert str(tmp_path) not in json.dumps(result.as_dict(), ensure_ascii=False)


def test_parameter_controller_clamps_interpolates_and_recovers():
    sink = FakeSink({"mouth": 0.2})
    spec = ParameterSpec("mouth", 0.0, 1.0, 0.1, 0.2)
    controller = Live2DParameterController((spec,), sink)

    scheduled = controller.animate("mouth", 3.0, 1.0, now=10.0)
    assert scheduled.status == "scheduled"
    assert scheduled.clamped
    controller.tick(10.5)
    assert sink.values["mouth"] == pytest.approx(0.6)
    assert controller.active_parameter_ids == ("mouth",)
    completed = controller.tick(11.0)
    assert sink.values["mouth"] == pytest.approx(1.0)
    assert completed == ()
    completed = controller.tick(12.0)
    assert sink.values["mouth"] == pytest.approx(0.1)
    assert completed[0].status == "recovered"
    assert controller.active_parameter_ids == ()

    assert controller.animate("unknown", 1, 1).status == "unsupported"
    assert controller.animate("mouth", 1, 0).reason == "duration_must_be_positive"


def test_renderer_does_not_touch_backend_before_load_and_tears_down_in_order(tmp_path):
    backend = FakeBackend()
    renderer = _renderer_factory(backend)
    renderer.tick()
    assert backend.events == []

    model_path = _write_model(tmp_path)
    capabilities = Live2DModelLoader().load(model_path).capabilities
    assert renderer.load_and_start(model_path, capabilities)
    renderer.tick()
    renderer.close()
    renderer.close()

    assert [event[0] for event in backend.events] == [
        "create",
        "timer_start",
        "update",
        "render",
        "timer_stop",
        "destroy",
        "close_window",
        "dispose",
    ]


def test_renderer_load_failure_is_observable_and_disposed_once(tmp_path):
    backend = FakeBackend(fail_create=True)
    renderer = _renderer_factory(backend)
    model_path = _write_model(tmp_path)
    capabilities = Live2DModelLoader().load(model_path).capabilities

    assert not renderer.load_and_start(model_path, capabilities)
    assert renderer.state.phase == "failed"
    assert "injected backend load failure" in renderer.state.error
    renderer.close()
    assert [event[0] for event in backend.events] == ["create", "dispose", "close_window"]


def test_host_lifecycle_is_idempotent_and_parameter_entry_is_model_opaque(tmp_path):
    model_path = _write_model(tmp_path)
    backend = FakeBackend()
    host = Live2DHostFacade(_loader(model_path), lambda: _renderer_factory(backend))

    assert host.set_parameter("mouth", 1).status == "unavailable"
    assert host.start(model_path).status == "started"
    assert host.start(model_path).status == "already_running"
    assert host.show().status == "shown"
    assert host.show().status == "already_visible"
    assert host.hide().status == "hidden"
    assert host.hide().status == "already_hidden"
    assert host.animate_parameter("ParamMouthOpenY", 2, 1).clamped
    assert host.stop().status == "stopped"
    assert host.stop().status == "already_stopped"
    assert host.close().status == "already_closed"
    assert host.quit().status == "already_closed"
    assert [event[0] for event in backend.events].count("create") == 1
    assert [event[0] for event in backend.events].count("dispose") == 1


def test_host_load_failure_and_early_window_close_are_safe(tmp_path):
    model_path = _write_model(tmp_path)
    failing_backend = FakeBackend(fail_create=True)
    failing_host = Live2DHostFacade(
        _loader(model_path), lambda: _renderer_factory(failing_backend)
    )
    failed = failing_host.start(model_path)
    assert not failed.ok
    assert failed.status == "renderer_failed"
    assert failed.state.reason == "renderer_load_failed"

    backend = FakeBackend()
    host = Live2DHostFacade(_loader(model_path), lambda: _renderer_factory(backend))
    assert host.start(model_path).ok
    closed = host.handle_window_closed()
    assert closed.status == "window_closed"
    assert host.state.phase == "closed"
    assert host.stop().status == "already_stopped"
    assert [event[0] for event in backend.events].count("destroy") == 1


def test_host_rejects_worker_thread_without_touching_renderer(tmp_path):
    model_path = _write_model(tmp_path)
    backend = FakeBackend()
    host = Live2DHostFacade(_loader(model_path), lambda: _renderer_factory(backend))
    result_holder = {}

    worker = threading.Thread(
        target=lambda: result_holder.setdefault("result", host.start(model_path))
    )
    worker.start()
    worker.join()

    result = result_holder["result"]
    assert result.status == "thread_violation"
    assert host.state.phase == "idle"
    assert backend.events == []


def test_host_routes_worker_call_through_injected_main_thread_invoker(tmp_path):
    model_path = _write_model(tmp_path)
    backend = FakeBackend()
    pending = {}
    operation_ready = threading.Event()
    operation_done = threading.Event()

    def invoker(operation):
        pending["operation"] = operation
        operation_ready.set()
        operation_done.wait(timeout=2)
        return pending["result"]

    host = Live2DHostFacade(
        _loader(model_path),
        lambda: _renderer_factory(backend),
        main_thread_invoker=invoker,
    )
    result_holder = {}
    worker = threading.Thread(
        target=lambda: result_holder.setdefault("result", host.start(model_path))
    )
    worker.start()
    assert operation_ready.wait(timeout=2)
    pending["result"] = pending["operation"]()
    operation_done.set()
    worker.join()

    assert result_holder["result"].status == "started"
    assert host.state.phase == "running"
    assert [event[0] for event in backend.events].count("create") == 1


def test_qt_backend_is_only_an_injected_adapter():
    sdk = FakeSdk()
    window = FakeWindow()
    backend = QtOpenGLLive2DBackend(sdk, window)

    model = backend.create_model(Path("avatar.model3.json"), capabilities=object())
    backend.show()
    backend.hide()
    backend.destroy_model(model)
    backend.dispose()
    backend.close_window()

    assert sdk.events == ["load", "destroy", "dispose"]
    assert window.events == ["show", "hide", "close"]


def test_live2d_runtime_is_structurally_isolated_from_pet_and_overlay():
    import app.live2d.host as host_module
    import app.live2d.model_loader as loader_module
    import app.live2d.parameters as parameters_module
    import app.live2d.renderer as renderer_module

    for module in (host_module, loader_module, parameters_module, renderer_module):
        source = inspect.getsource(module)
        assert "app.pet" not in source
        assert "pet_animation_mapper" not in source
        assert "app.overlay" not in source
