"""Regression and micro-benchmark tests for Qt screenshot compression."""

from __future__ import annotations

import base64
import statistics
import time

from PyQt6.QtGui import QColor, QImage, QPixmap

from app.screenshot_compress import (
    IMAGE_JPEG_QUALITY,
    IMAGE_MAX_WIDTH,
    compress_screenshot,
)

_DATA_URI_PREFIX = "data:image/jpeg;base64,"


def _make_pixmap(width: int, height: int, *, color: QColor | None = None) -> QPixmap:
    pixmap = QPixmap(width, height)
    pixmap.fill(color or QColor(255, 100, 100))
    return pixmap


def _jpeg_bytes_from_uri(data_uri: str) -> bytes:
    assert data_uri.startswith(_DATA_URI_PREFIX)
    return base64.b64decode(data_uri[len(_DATA_URI_PREFIX) :], validate=True)


def _decoded_size(data_uri: str) -> tuple[int, int]:
    jpeg_bytes = _jpeg_bytes_from_uri(data_uri)
    image = QImage.fromData(jpeg_bytes)
    assert not image.isNull()
    return image.width(), image.height()


def test_compress_screenshot_constants():
    assert IMAGE_MAX_WIDTH == 768
    assert IMAGE_JPEG_QUALITY == 85


def test_compress_screenshot_data_uri_prefix(qapp):
    uri = compress_screenshot(_make_pixmap(640, 480))
    assert uri.startswith(_DATA_URI_PREFIX)


def test_compress_screenshot_non_empty_payload(qapp):
    uri = compress_screenshot(_make_pixmap(640, 480))
    payload = uri[len(_DATA_URI_PREFIX) :]
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
        assert uri.startswith(_DATA_URI_PREFIX)
        assert _jpeg_bytes_from_uri(uri)

    median_ms = statistics.median(timings_ms)
    assert median_ms < 500.0
