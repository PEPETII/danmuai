from unittest.mock import MagicMock, patch

from app.snipper import (
    ScreenCapturer,
    grab_rect_screen_local,
    resolve_capture_rect,
    resolve_screen_index,
)


class FakeGeometry:
    def __init__(self, x=10, y=20, width=800, height=600):
        self._x = x
        self._y = y
        self._width = width
        self._height = height

    def x(self):
        return self._x

    def y(self):
        return self._y

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeScreen:
    def __init__(self, geometry=None):
        self._geometry = geometry or FakeGeometry()
        self.grab_args = None

    def geometry(self):
        return self._geometry

    def grabWindow(self, *args):
        self.grab_args = args
        return "pixmap"


class FakeNullPixmap:
    def isNull(self):
        return True


def test_resolve_screen_index_clamps_to_available_screens():
    screens = [object(), object(), object()]
    config = MagicMock()
    config.get_int.return_value = 5

    with patch("app.snipper.QApplication.screens", return_value=screens):
        assert resolve_screen_index(config) == 2


def test_resolve_screen_index_defaults_to_zero_without_config():
    screens = [object()]

    with patch("app.snipper.QApplication.screens", return_value=screens):
        assert resolve_screen_index(None) == 0


def test_resolve_screen_index_returns_zero_when_no_screens():
    config = MagicMock()
    config.get_int.return_value = 1

    with patch("app.snipper.QApplication.screens", return_value=[]):
        assert resolve_screen_index(config) == 0


def test_resolve_capture_rect_full_screen_without_config():
    assert resolve_capture_rect(None, FakeGeometry()) == (10, 20, 800, 600)


def test_resolve_capture_rect_uses_screen_relative_region():
    config = MagicMock()
    config.get_region.return_value = (100, 50, 320, 180)

    assert resolve_capture_rect(config, FakeGeometry()) == (110, 70, 320, 180)


def test_resolve_capture_rect_invalid_region_falls_back_to_full_screen():
    config = MagicMock()
    config.get_region.return_value = (100, 50, 0, 180)

    assert resolve_capture_rect(config, FakeGeometry()) == (10, 20, 800, 600)


def test_resolve_capture_rect_clamps_out_of_bounds_region():
    config = MagicMock()
    config.get_region.return_value = (-20, 500, 1000, 200)

    assert resolve_capture_rect(config, FakeGeometry()) == (10, 520, 800, 100)


def test_resolve_capture_rect_falls_back_when_clamped_region_is_empty():
    config = MagicMock()
    config.get_region.return_value = (900, 100, 50, 50)

    assert resolve_capture_rect(config, FakeGeometry()) == (10, 20, 800, 600)


def test_grab_rect_screen_local_offsets_secondary_monitor_origin():
    geo = FakeGeometry(x=1920, y=0, width=2560, height=1440)
    assert grab_rect_screen_local(None, geo) == (0, 0, 2560, 1440)


def test_screen_capturer_passes_region_to_qscreen_grab():
    config = MagicMock()
    config.get_int.return_value = 0
    config.get_region.return_value = (100, 50, 320, 180)
    screen = FakeScreen()

    with patch("app.snipper.QApplication.screens", return_value=[screen]):
        assert ScreenCapturer(config).grab() == "pixmap"

    assert screen.grab_args == (0, 100, 50, 320, 180)


def test_screen_capturer_treats_null_pixmap_as_failed_capture():
    screen = FakeScreen()
    screen.grabWindow = MagicMock(return_value=FakeNullPixmap())

    with patch("app.snipper.QApplication.screens", return_value=[screen]):
        assert ScreenCapturer(None).grab() is None
