from __future__ import annotations

from unittest.mock import MagicMock

from app.live2d.window_interaction import compute_window_drag_target
from PyQt6.QtCore import QPoint


def test_compute_window_drag_target_uses_global_delta_only():
    origin_global = QPoint(500, 600)
    origin_window = QPoint(100, 200)

    first = compute_window_drag_target(origin_global, origin_window, QPoint(520, 640))
    second = compute_window_drag_target(origin_global, origin_window, QPoint(510, 630))

    assert (first.x(), first.y()) == (120, 240)
    assert (second.x(), second.y()) == (110, 230)


def test_apply_live2d_settings_patch_persists_click_through(qapp, monkeypatch):
    from main import DanmuApp

    from tests.conftest import bind_minimal_danmu_app
    from tests.fakes import FakeConfig

    config = FakeConfig({"live2d_click_through": "0"})
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=config)
    runtime = MagicMock()
    runtime.snapshot.return_value = {"runtime_status": "running", "click_through": True}
    app.__dict__["_live2d_desktop_runtime"] = runtime
    monkeypatch.setattr(
        app,
        "_get_live2d_model_registry",
        lambda: MagicMock(snapshot=lambda: {"configured": True, "status": "ready", "capabilities": {}}),
    )
    emitted: list[str] = []
    app.config_changed = MagicMock()
    app.config_changed.emit = lambda: emitted.append("changed")

    snapshot = app.apply_live2d_settings_patch({"click_through": True})

    assert config.get("live2d_click_through") == "1"
    runtime.set_click_through.assert_called_once_with(True)
    assert snapshot["click_through"] is True
    assert emitted == ["changed"]
