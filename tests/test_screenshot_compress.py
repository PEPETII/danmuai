"""Regression and micro-benchmark tests for Qt screenshot compression."""

from __future__ import annotations

import base64
import io
import statistics
import time

from app.image_compress import compress_image_bytes
from app.jpeg_resize import JPEG_DATA_URI_PREFIX
from app.screenshot_compress import (
    IMAGE_JPEG_QUALITY,
    IMAGE_MAX_WIDTH,
    compress_screenshot,
)
from PIL import Image
from PyQt6.QtGui import QColor, QImage, QPixmap
import pytest


def _make_pixmap(width: int, height: int, *, color: QColor | None = None) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(color or QColor(255, 100, 100))
    return pixmap


def _jpeg_bytes_from_uri(data_uri: str) -> bytes:
    assert data_uri.startswith(JPEG_DATA_URI_PREFIX)
    return base64.b64decode(data_uri[len(JPEG_DATA_URI_PREFIX) :], validate=True)


def _decoded_size(data_uri: str) -> tuple[int, int]:
    jpeg_bytes = _jpeg_bytes_from_uri(data_uri)
    image = QImage.fromData(jpeg_bytes)
    assert not image.isNull()
    return image.width(), image.height()


def test_compress_screenshot_constants():
    assert IMAGE_MAX_WIDTH == 1024
    assert IMAGE_JPEG_QUALITY == 85


def test_compress_screenshot_data_uri_prefix(qapp):
    uri = compress_screenshot(_make_pixmap(640, 480))
    assert uri.startswith(JPEG_DATA_URI_PREFIX)


def test_compress_screenshot_non_empty_payload(qapp):
    uri = compress_screenshot(_make_pixmap(640, 480))
    payload = uri[len(JPEG_DATA_URI_PREFIX) :]
    assert payload
    _jpeg_bytes_from_uri(uri)


def test_compress_screenshot_decodable_jpeg(qapp):
    uri = compress_screenshot(_make_pixmap(800, 600))
    out_w, out_h = _decoded_size(uri)
    assert out_w > 0
    assert out_h > 0


def test_compress_screenshot_scales_wide_image(qapp):
    uri = compress_screenshot(_make_pixmap(1200, 800), max_width=768)
    out_w, out_h = _decoded_size(uri)
    assert out_w <= 768
    assert out_h == round(800 * out_w / 1200)


def test_compress_screenshot_no_upscale(qapp):
    uri = compress_screenshot(_make_pixmap(400, 300), max_width=768)
    out_w, out_h = _decoded_size(uri)
    assert out_w == 400
    assert out_h == 300


def test_compress_screenshot_quality_affects_size(qapp):
    pixmap = _make_pixmap(900, 700)
    low = _jpeg_bytes_from_uri(compress_screenshot(pixmap, max_width=768, quality=50))
    high = _jpeg_bytes_from_uri(compress_screenshot(pixmap, max_width=768, quality=95))
    assert len(low) < len(high)


def test_compress_screenshot_benchmark_repeatable(qapp):
    pixmap = _make_pixmap(1920, 1080)
    timings_ms: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        uri = compress_screenshot(pixmap, max_width=768, quality=85)
        timings_ms.append((time.perf_counter() - started) * 1000.0)
        assert uri.startswith(JPEG_DATA_URI_PREFIX)
        assert _jpeg_bytes_from_uri(uri)

    median_ms = statistics.median(timings_ms)
    assert median_ms < 500.0


def _pil_rgb_to_qpixmap(pil_image: Image.Image) -> QPixmap:
    rgba = pil_image.convert("RGBA")
    w, h = rgba.size
    qimage = QImage(rgba.tobytes("raw", "RGBA"), w, h, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(qimage)
    if pixmap.isNull():
        raise RuntimeError("Failed to convert PIL image to QPixmap.")
    return pixmap


def _make_jpeg_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (1920, 1080),
        (1024, 768),
        (200, 200),
    ],
)
def test_both_pipelines_output_size_within_5_percent(qapp, width, height):
    """PIL bytes path vs Qt QPixmap path on the same synthetic image."""
    max_width = IMAGE_MAX_WIDTH
    quality = IMAGE_JPEG_QUALITY
    data = _make_jpeg_bytes(width, height)

    pil_result = compress_image_bytes(data, max_width=max_width, quality=quality)
    pil_bytes = pil_result["jpeg_bytes"]

    pixmap = _pil_rgb_to_qpixmap(Image.open(io.BytesIO(data)))
    qt_uri = compress_screenshot(pixmap, max_width=max_width, quality=quality)
    qt_bytes = len(_jpeg_bytes_from_uri(qt_uri))

    assert pil_bytes > 0
    assert abs(qt_bytes - pil_bytes) / pil_bytes < 0.05

    pil_out_w, pil_out_h = pil_result["out_w"], pil_result["out_h"]
    qt_out_w, qt_out_h = _decoded_size(qt_uri)
    assert pil_out_w == qt_out_w
    assert abs(pil_out_h - qt_out_h) <= 1
