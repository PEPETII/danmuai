"""Optional compress metrics (DANMU_IMAGE_METRICS=1). Never logs Base64 payload."""

from __future__ import annotations

import base64
import io

from PIL import Image

from app.env_config import get as get_env

_DATA_URI_PREFIX = "data:image/jpeg;base64,"


def image_metrics_enabled() -> bool:
    value = get_env("DANMU_IMAGE_METRICS").strip().lower()
    return value in ("1", "true", "yes", "on")


def jpeg_output_size(data_uri: str) -> tuple[int, int, int]:
    """Return (out_w, out_h, jpeg_bytes) from a JPEG data URI."""
    if not data_uri.startswith(_DATA_URI_PREFIX):
        return 0, 0, len(data_uri)
    jpeg_bytes = base64.b64decode(data_uri[len(_DATA_URI_PREFIX) :], validate=True)
    with Image.open(io.BytesIO(jpeg_bytes)) as img:
        out_w, out_h = img.size
    return out_w, out_h, len(jpeg_bytes)


def log_compress_metrics(
    logger,
    *,
    orig_w: int,
    orig_h: int,
    quality: int,
    compress_ms: float,
    data_uri: str,
) -> None:
    if not image_metrics_enabled():
        return
    out_w, out_h, jpeg_bytes = jpeg_output_size(data_uri)
    logger.debug(
        "image_metrics "
        f"orig={orig_w}x{orig_h} out={out_w}x{out_h} quality={quality} "
        f"jpeg_bytes={jpeg_bytes} data_uri_len={len(data_uri)} compress_ms={compress_ms:.1f}"
    )
