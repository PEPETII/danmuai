"""Lightweight scene change detection (PIL only, no OpenCV)."""

from __future__ import annotations

import os

from PIL import Image
from PyQt6.QtGui import QPixmap

# 8x8 average hash on configurable grayscale probe (square side length in px)
DEFAULT_SCENE_PROBE_SIZE = 256
MIN_SCENE_PROBE_SIZE = 32
MAX_SCENE_PROBE_SIZE = 512
PROBE_SIZE = (DEFAULT_SCENE_PROBE_SIZE, DEFAULT_SCENE_PROBE_SIZE)
AHASH_SIZE = (8, 8)
HAMMING_THRESHOLD = 10


def clamp_scene_probe_size(size: int) -> int:
    return max(MIN_SCENE_PROBE_SIZE, min(MAX_SCENE_PROBE_SIZE, int(size)))


def scene_probe_size_from_config(config) -> int:
    """Read square probe side length from ConfigStore-like object."""
    raw = config.get_int("scene_probe_size", DEFAULT_SCENE_PROBE_SIZE)
    if raw <= 0:
        return DEFAULT_SCENE_PROBE_SIZE
    return clamp_scene_probe_size(raw)


def scene_debug_enabled() -> bool:
    value = os.environ.get("DANMU_SCENE_DEBUG", "").strip().lower()
    return value in ("1", "true", "yes", "on")


def _pixmap_to_gray_probe(pixmap: QPixmap, probe_size: int = DEFAULT_SCENE_PROBE_SIZE) -> Image.Image:
    side = clamp_scene_probe_size(probe_size)
    qimage = pixmap.toImage()
    width, height = qimage.width(), qimage.height()
    bits = qimage.bits()
    bits.setsize(height * qimage.bytesPerLine())
    rgba = Image.frombuffer(
        "RGBA",
        (width, height),
        bits,
        "raw",
        "BGRA",
        qimage.bytesPerLine(),
        1,
    )
    return rgba.convert("L").resize((side, side), Image.Resampling.LANCZOS)


def fingerprint_from_pixmap(pixmap: QPixmap, *, probe_size: int = DEFAULT_SCENE_PROBE_SIZE) -> int:
    """64-bit average hash from downscaled grayscale frame."""
    gray = _pixmap_to_gray_probe(pixmap, probe_size)
    small = gray.resize(AHASH_SIZE, Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    fingerprint = 0
    for index, value in enumerate(pixels):
        if value >= avg:
            fingerprint |= 1 << index
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def is_scene_change(previous: int | None, current: int, *, threshold: int = HAMMING_THRESHOLD) -> bool:
    if previous is None:
        return False
    return hamming_distance(previous, current) >= threshold
