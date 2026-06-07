#!/usr/bin/env python3
"""Subprocess worker: Qt + main.compress_screenshot (clean QApplication lifecycle)."""

from __future__ import annotations

import base64
import io
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from main import compress_screenshot  # noqa: E402
from PIL import Image  # noqa: E402
from PyQt6.QtGui import QImage, QPixmap  # noqa: E402

DATA_URI_PREFIX = "data:image/jpeg;base64,"
QUALITIES = (100, 90, 85, 80)


def _pil_to_qpixmap(path: Path) -> QPixmap:
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
    w, h = rgba.size
    qimage = QImage(rgba.tobytes("raw", "RGBA"), w, h, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(qimage)
    if pixmap.isNull():
        raise RuntimeError(f"QPixmap.fromImage failed for {path}")
    return pixmap


def _decode_metrics(data_uri: str) -> tuple[int, int, int, int]:
    b64 = data_uri[len(DATA_URI_PREFIX) :]
    jpeg_bytes = base64.b64decode(b64, validate=True)
    with Image.open(io.BytesIO(jpeg_bytes)) as img:
        out_w, out_h = img.size
    return len(jpeg_bytes), len(b64), len(data_uri), out_w, out_h


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: _bench_jpeg_worker.py <image_path> <max_width> <runs>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    max_width = int(sys.argv[2])
    runs = max(1, int(sys.argv[3]))
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 2

    pixmap = _pil_to_qpixmap(path)
    orig_w, orig_h = pixmap.width(), pixmap.height()
    rows = []
    baseline_jpeg = baseline_uri = None

    for quality in QUALITIES:
        timings: list[float] = []
        data_uri = ""
        for _ in range(runs):
            t0 = time.perf_counter()
            data_uri = compress_screenshot(pixmap, max_width=max_width, quality=quality)
            timings.append((time.perf_counter() - t0) * 1000.0)
        jpeg_bytes, base64_len, data_uri_len, out_w, out_h = _decode_metrics(data_uri)
        row = {
            "quality": quality,
            "orig_w": orig_w,
            "orig_h": orig_h,
            "out_w": out_w,
            "out_h": out_h,
            "jpeg_bytes": jpeg_bytes,
            "base64_len": base64_len,
            "data_uri_len": data_uri_len,
            "compress_ms_median": round(float(statistics.median(timings)), 2),
            "jpeg_vs_100_pct": None,
            "uri_vs_100_pct": None,
        }
        if quality == 100:
            baseline_jpeg = jpeg_bytes
            baseline_uri = data_uri_len
        else:
            row["jpeg_vs_100_pct"] = round((baseline_jpeg - jpeg_bytes) / baseline_jpeg * 100.0, 2)
            row["uri_vs_100_pct"] = round((baseline_uri - data_uri_len) / baseline_uri * 100.0, 2)
        rows.append(row)

    print(json.dumps({"rows": rows, "mode": "subprocess"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
