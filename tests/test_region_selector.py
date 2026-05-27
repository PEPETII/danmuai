"""Tests for screen-relative region normalization (no Qt required)."""

import pytest
from app.region_selector import (
    MIN_REGION_SIZE,
    normalize_region_for_screen,
    rect_from_drag,
)
from app.web_api.capture_region import (
    apply_capture_region,
    capture_region_mode,
    clear_capture_region,
    read_capture_region_status,
)


class FakeConfig:
    def __init__(self, region=(0, 0, 0, 0)):
        self._region = region

    def get_region(self):
        return self._region

    def set_region(self, x, y, w, h):
        self._region = (x, y, w, h)


def test_rect_from_drag_normalizes_negative_drag():
    assert rect_from_drag(10, 20, 110, 220) == (10, 20, 100, 200)
    assert rect_from_drag(110, 220, 10, 20) == (10, 20, 100, 200)


def test_normalize_region_rejects_too_small():
    assert normalize_region_for_screen(0, 0, 5, 20, 800, 600) is None
    assert normalize_region_for_screen(0, 0, 20, 5, 800, 600) is None


def test_normalize_region_clamps_to_screen():
    assert normalize_region_for_screen(-20, 500, 1000, 200, 800, 600) == (
        0,
        500,
        800,
        100,
    )


def test_normalize_region_rejects_empty_after_clamp():
    assert normalize_region_for_screen(900, 100, 50, 50, 800, 600) is None


def test_capture_region_mode_full_and_custom():
    cfg = FakeConfig((0, 0, 0, 0))
    assert capture_region_mode(cfg) == "full"
    cfg.set_region(10, 20, 100, 80)
    assert capture_region_mode(cfg) == "custom"


def test_read_capture_region_status_shape():
    cfg = FakeConfig((12, 34, 320, 180))
    data = read_capture_region_status(cfg, selection_state="idle")
    assert data["mode"] == "custom"
    assert data["region"] == {"x": 12, "y": 34, "w": 320, "h": 180}
    assert data["selection_state"] == "idle"


def test_apply_capture_region_persists_normalized(tmp_path):
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "region.db")
    applied = apply_capture_region(
        store, -5, 10, 900, 400, screen_width=800, screen_height=600
    )
    assert applied == (0, 10, 800, 400)
    assert store.get_region() == (0, 10, 800, 400)


def test_clear_capture_region():
    cfg = FakeConfig((1, 2, 3, 4))
    clear_capture_region(cfg)
    assert cfg.get_region() == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "w,h",
    [(MIN_REGION_SIZE - 1, 50), (50, MIN_REGION_SIZE - 1)],
)
def test_apply_capture_region_rejects_below_min_size(w, h, tmp_path):
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "small.db")
    store.set_region(50, 50, 200, 200)
    result = apply_capture_region(
        store, 0, 0, w, h, screen_width=800, screen_height=600
    )
    assert result is None
    assert store.get_region() == (50, 50, 200, 200)
