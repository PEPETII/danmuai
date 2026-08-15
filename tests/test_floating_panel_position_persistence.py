from __future__ import annotations

from app.main_floating_panel_mixin import DanmuAppFloatingPanelMixin


class _Config:
    def __init__(self):
        self.values = {"floating_panel_click_through": "0"}
        self.writes: list[dict[str, str]] = []

    def get(self, key, default=""):
        return self.values.get(key, default)

    def set_batch(self, items):
        self.values.update(items)
        self.writes.append(dict(items))


class _Process:
    def __init__(self, position=(100, 200)):
        self.position = position

    def current_position(self):
        return self.position


class _Timer:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1


def _app(config, process, timer):
    app = DanmuAppFloatingPanelMixin()
    app.config = config
    app._panel_process = process
    app._panel_web_active = True
    app._panel_position_timer = timer
    app._panel_position_candidate = process.position
    app._panel_position_last_changed_at = 0.0
    app._panel_position_last_saved = None
    return app


def test_position_tick_persists_settled_native_position():
    config = _Config()
    process = _Process((123, -45))
    app = _app(config, process, _Timer())

    app._on_panel_position_tick()

    assert config.values["floating_panel_x"] == "123"
    assert config.values["floating_panel_y"] == "-45"
    assert config.writes == [{"floating_panel_x": "123", "floating_panel_y": "-45"}]


def test_stopping_adjustment_forces_final_position_save():
    config = _Config()
    process = _Process((456, 789))
    app = _app(config, process, _Timer())

    app._stop_panel_position_tracking(force=True)

    assert config.values["floating_panel_x"] == "456"
    assert config.values["floating_panel_y"] == "789"
    assert app._panel_position_timer.stopped == 1
