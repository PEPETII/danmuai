from __future__ import annotations

from types import SimpleNamespace

from app.floating_panel_geometry import compute_panel_geometry


class _Rect:
    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self._x, self._y, self._width, self._height = x, y, width, height

    def x(self) -> int:
        return self._x

    def y(self) -> int:
        return self._y

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height


def _screen(x: int, y: int, width: int, height: int, *, available=None):
    rect = _Rect(x, y, width, height)
    available_rect = _Rect(*(available or (x, y, width, height)))
    return SimpleNamespace(geometry=lambda: rect, availableGeometry=lambda: available_rect)


def _config(**values):
    return SimpleNamespace(get=lambda key, default="": values.get(key, default))


def test_saved_negative_position_selects_left_monitor_and_preserves_origin():
    screens = [_screen(0, 0, 1920, 1080), _screen(-1280, 0, 1280, 1024)]
    geometry = compute_panel_geometry(
        screens,
        config=_config(floating_panel_x="-1100", floating_panel_y="40"),
        width=360,
        x_offset=20,
        y_offset=80,
        preferred_screen_index=0,
        use_available_geometry=True,
    )
    assert geometry == (360, 864, -1100, 40)


def test_saved_position_is_clamped_when_monitor_bounds_changed():
    geometry = compute_panel_geometry(
        [_screen(0, 0, 1280, 720)],
        config=_config(floating_panel_x="5000", floating_panel_y="-5000"),
        width=360,
        x_offset=20,
        y_offset=80,
        preferred_screen_index=0,
        use_available_geometry=True,
    )
    assert geometry == (360, 560, 920, 0)


def test_blank_saved_position_keeps_legacy_offset_layout_and_taskbar_bounds():
    geometry = compute_panel_geometry(
        [_screen(0, 0, 1920, 1080, available=(0, 0, 1920, 1040))],
        config=_config(),
        width=360,
        x_offset=20,
        y_offset=80,
        preferred_screen_index=0,
        use_available_geometry=True,
    )
    assert geometry == (360, 880, 1540, 80)
