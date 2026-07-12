"""JPEG compression shared contract: data URI assembly + PIL resize/encode.

``resize_rgb_to_jpeg_bytes`` is **PIL-only** (Web preview / bytes input via
``image_compress.compress_image_bytes``).

``jpeg_bytes_to_data_uri`` is shared by both pipelines:
- PIL path: ``image_compress.py`` (uvicorn HTTP thread; no Qt dependency)
- Qt path: ``screenshot_compress.py`` (QThreadPool; native QPixmap resize/encode)

We keep two resize/encode backends because:
- Web preview cannot require QApplication on the HTTP thread.
- Main capture already holds QPixmap; copying RGB888 into Pillow adds hot-path
  overhead without matching Qt encoder output byte-for-byte anyway.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from app.config_defaults import DEFAULT_IMAGE_MAX_WIDTH

JPEG_DATA_URI_PREFIX = "data:image/jpeg;base64,"


def jpeg_bytes_to_data_uri(jpeg_bytes: bytes) -> str:
    """Encode JPEG bytes as a data URI (single assembly point for both pipelines)."""
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
    return f"{JPEG_DATA_URI_PREFIX}{b64}"


def resize_rgb_to_jpeg_bytes(
    pil_image: Image.Image,
    *,
    max_width: int = DEFAULT_IMAGE_MAX_WIDTH,
    quality: int = 85,
) -> tuple[Image.Image, bytes, int, int]:
    """Resize RGB image if wider than max_width; return (final PIL, jpeg bytes, out_w, out_h)."""
    pil_image = pil_image.convert("RGB")
    orig_width, orig_height = pil_image.size
    if orig_width > max_width:
        ratio = max_width / orig_width
        new_height = int(orig_height * ratio)
        pil_image = pil_image.resize((max_width, new_height), Image.Resampling.LANCZOS)
    final_width, final_height = pil_image.size
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=quality)
    return pil_image, buf.getvalue(), final_width, final_height
