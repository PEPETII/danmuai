"""Tests for in-memory image compression."""

import io

from app.image_compress import compress_image_bytes
from main import IMAGE_JPEG_QUALITY
from PIL import Image


def _make_jpeg_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_runtime_default_jpeg_quality_is_85():
    assert IMAGE_JPEG_QUALITY == 85


def test_compress_image_bytes_default_quality_matches_85():
    data = _make_jpeg_bytes(1200, 800)
    default_result = compress_image_bytes(data, max_width=768)
    explicit_85 = compress_image_bytes(data, max_width=768, quality=85)
    at_100 = compress_image_bytes(data, max_width=768, quality=100)
    assert default_result["jpeg_bytes"] == explicit_85["jpeg_bytes"]
    assert default_result["jpeg_bytes"] < at_100["jpeg_bytes"]


def test_compress_image_bytes_scales_down():
    data = _make_jpeg_bytes(1200, 800)
    result = compress_image_bytes(data, max_width=768, quality=90)
    assert result["orig_w"] == 1200
    assert result["out_w"] <= 768
    assert result["preview_data_url"].startswith("data:image/jpeg;base64,")
    assert result["jpeg_bytes"] > 0


def test_config_image_quality_override():
    """Explicit image_quality in config must override runtime default."""
    from tests.test_p0_main_flow import FakeConfig

    cfg = FakeConfig({"image_quality": "100"})
    assert cfg.get_int("image_quality", IMAGE_JPEG_QUALITY) == 100
    assert cfg.get_int("image_quality", IMAGE_JPEG_QUALITY) != 85
    empty = FakeConfig({})
    assert empty.get_int("image_quality", IMAGE_JPEG_QUALITY) == 85
