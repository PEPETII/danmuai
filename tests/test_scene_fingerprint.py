"""Scene fingerprint helpers."""

import pytest
from app.scene_fingerprint import (
    DEFAULT_SCENE_PROBE_SIZE,
    HAMMING_THRESHOLD,
    MAX_SCENE_PROBE_SIZE,
    MIN_SCENE_PROBE_SIZE,
    clamp_scene_probe_size,
    fingerprint_from_pixmap,
    hamming_distance,
    is_scene_change,
    scene_debug_enabled,
    scene_probe_size_from_config,
)
from PIL import Image
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _solid_pixmap_via_pil(rgb: tuple[int, int, int]):
    from PyQt6.QtGui import QImage, QPixmap

    img = Image.new("RGB", (64, 64), rgb)
    buf = img.tobytes("raw", "RGB")
    qimg = QImage(buf, 64, 64, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


def test_scene_debug_env(monkeypatch):
    monkeypatch.delenv("DANMU_SCENE_DEBUG", raising=False)
    assert scene_debug_enabled() is False
    monkeypatch.setenv("DANMU_SCENE_DEBUG", "1")
    assert scene_debug_enabled() is True


def test_first_baseline_not_scene_change():
    assert is_scene_change(None, 0xFFFF) is False


def test_small_drift_not_scene_change():
    a = 0xAAAAAAAAAAAAAAAA
    b = a ^ (1 << 3)
    assert hamming_distance(a, b) == 1
    assert is_scene_change(a, b) is False


def test_large_change_is_scene_change():
    a = 0xAAAAAAAAAAAAAAAA
    b = 0x5555555555555555
    assert hamming_distance(a, b) == 64
    assert is_scene_change(a, b) is True


def test_fingerprint_stable_for_same_frame(qapp):
    px = _solid_pixmap_via_pil((40, 40, 40))
    assert fingerprint_from_pixmap(px) == fingerprint_from_pixmap(px)


def _pattern_pixmap_via_pil(left_rgb: tuple[int, int, int], right_rgb: tuple[int, int, int], size: int = 64):
    from PyQt6.QtGui import QImage, QPixmap

    img = Image.new("RGB", (size, size), left_rgb)
    for x in range(size // 2, size):
        for y in range(size):
            img.putpixel((x, y), right_rgb)
    buf = img.tobytes("raw", "RGB")
    qimg = QImage(buf, size, size, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


def test_different_colors_differ(qapp):
    # Uniform solids hash to all-1s (every pixel equals the average); use spatial contrast.
    dark = fingerprint_from_pixmap(_solid_pixmap_via_pil((20, 20, 20)))
    light = fingerprint_from_pixmap(_solid_pixmap_via_pil((200, 200, 200)))
    split = fingerprint_from_pixmap(_pattern_pixmap_via_pil((20, 20, 20), (200, 200, 200)))
    assert hamming_distance(dark, light) == 0
    assert hamming_distance(dark, split) >= HAMMING_THRESHOLD
    assert hamming_distance(light, split) >= HAMMING_THRESHOLD


def test_default_scene_probe_size():
    assert DEFAULT_SCENE_PROBE_SIZE == 256


def test_clamp_scene_probe_size():
    assert clamp_scene_probe_size(16) == MIN_SCENE_PROBE_SIZE
    assert clamp_scene_probe_size(256) == 256
    assert clamp_scene_probe_size(999) == MAX_SCENE_PROBE_SIZE


def test_scene_probe_size_from_config_defaults():
    class _Cfg:
        def get_int(self, key, default=0):
            return default

    assert scene_probe_size_from_config(_Cfg()) == DEFAULT_SCENE_PROBE_SIZE


def test_larger_probe_reduces_localized_drift(qapp):
    base = _solid_pixmap_via_pil((40, 40, 40))
    from PyQt6.QtGui import QImage, QPixmap

    img = Image.new("RGB", (64, 64), (40, 40, 40))
    for x in range(8):
        for y in range(4):
            img.putpixel((x, y), (220, 220, 220))
    buf = img.tobytes("raw", "RGB")
    qimg = QImage(buf, 64, 64, QImage.Format.Format_RGB888)
    patched = QPixmap.fromImage(qimg)
    small_dist = hamming_distance(
        fingerprint_from_pixmap(base, probe_size=32),
        fingerprint_from_pixmap(patched, probe_size=32),
    )
    large_dist = hamming_distance(
        fingerprint_from_pixmap(base, probe_size=256),
        fingerprint_from_pixmap(patched, probe_size=256),
    )
    assert large_dist <= small_dist
