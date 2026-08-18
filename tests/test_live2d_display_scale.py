from __future__ import annotations

import json

import pytest
from app.live2d.display_scale import (
    DEFAULT_DISPLAY_SCALE_PERCENT,
    compute_bottom_center_offset_y,
    get_model_display_scale_percent,
    set_model_display_scale_percent,
)

from tests.fakes import FakeConfig


def test_clamp_display_scale_percent_bounds():
    from app.live2d.display_scale import clamp_display_scale_percent

    assert clamp_display_scale_percent(10) == 25
    assert clamp_display_scale_percent(400) == 300
    assert clamp_display_scale_percent("150") == 150
    assert clamp_display_scale_percent("bad") == DEFAULT_DISPLAY_SCALE_PERCENT


def test_compute_bottom_center_offset_y_is_zero_at_default_scale():
    assert compute_bottom_center_offset_y(1.0) == 0.0


def test_resolve_uniform_scale_preserves_default_and_caps_upscale():
    from app.live2d.display_scale import (
        DISPLAY_SCALE_UNIFORM_MAX,
        DISPLAY_SCALE_UNIFORM_MID,
        DISPLAY_SCALE_UNIFORM_MIN,
        resolve_uniform_scale,
    )

    assert resolve_uniform_scale(25) == pytest.approx(DISPLAY_SCALE_UNIFORM_MIN)
    assert resolve_uniform_scale(100) == pytest.approx(DISPLAY_SCALE_UNIFORM_MID)
    assert resolve_uniform_scale(300) == pytest.approx(DISPLAY_SCALE_UNIFORM_MAX)
    assert resolve_uniform_scale(182) < DISPLAY_SCALE_UNIFORM_MAX
    assert resolve_uniform_scale(182) > DISPLAY_SCALE_UNIFORM_MID


def test_compute_bottom_center_offset_y_uses_normalized_scene_units():
    from app.live2d.display_scale import resolve_uniform_scale

    scale = resolve_uniform_scale(140)
    assert compute_bottom_center_offset_y(scale) == pytest.approx(-(scale - 1.0) * 0.5)


def test_display_scale_persists_per_model_id():
    config = FakeConfig({"live2d_model_display_scales": "{}"})

    assert get_model_display_scale_percent(config, "model-a") == 100
    saved = set_model_display_scale_percent(config, "model-a", 180)
    assert saved == 180
    assert get_model_display_scale_percent(config, "model-a") == 180

    set_model_display_scale_percent(config, "model-b", 60)
    assert get_model_display_scale_percent(config, "model-b") == 60
    assert get_model_display_scale_percent(config, "model-a") == 180

    stored = json.loads(config.get("live2d_model_display_scales"))
    assert stored == {"model-a": 180, "model-b": 60}


def test_apply_live2d_settings_patch_persists_display_scale(qapp, monkeypatch):
    from main import DanmuApp

    from tests.conftest import bind_minimal_danmu_app

    config = FakeConfig(
        {
            "live2d_model_id": "vtuber-1",
            "live2d_model_display_scales": "{}",
            "live2d_click_through": "0",
        }
    )
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=config)
    runtime = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    runtime.snapshot.return_value = {
        "runtime_status": "running",
        "click_through": False,
        "display_scale_percent": 150,
    }
    app.__dict__["_live2d_desktop_runtime"] = runtime
    monkeypatch.setattr(
        app,
        "_get_live2d_model_registry",
        lambda: __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(
            snapshot=lambda: {
                "configured": True,
                "status": "ready",
                "model_id": "vtuber-1",
                "capabilities": {},
            }
        ),
    )
    emitted: list[str] = []
    app.config_changed = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    app.config_changed.emit = lambda: emitted.append("changed")

    snapshot = app.apply_live2d_settings_patch({"display_scale_percent": 150})

    assert json.loads(config.get("live2d_model_display_scales")) == {"vtuber-1": 150}
    runtime.set_display_scale_percent.assert_called_once_with(150)
    assert snapshot["display_scale_percent"] == 150
    assert emitted == ["changed"]


def test_apply_live2d_settings_patch_requires_model_for_display_scale(qapp, monkeypatch):
    from main import DanmuApp

    from tests.conftest import bind_minimal_danmu_app

    config = FakeConfig({"live2d_model_id": "", "live2d_model_display_scales": "{}"})
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=config)
    monkeypatch.setattr(
        app,
        "_get_live2d_model_registry",
        lambda: __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(
            snapshot=lambda: {"configured": False, "status": "unconfigured", "capabilities": {}}
        ),
    )

    with pytest.raises(ValueError, match="live2d_model_not_configured"):
        app.apply_live2d_settings_patch({"display_scale_percent": 120})
