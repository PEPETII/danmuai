#!/usr/bin/env python3
"""
Local JPEG quality benchmark for DanmuAI screenshot compression.

Uses main.compress_screenshot() (production path). Does not call AI APIs.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).resolve().parent / "_bench_jpeg_worker.py"
_BENCH_QT_ARGV = ["bench_jpeg_quality"]

DEFAULT_MAX_WIDTH = 768
QUALITIES = (100, 90, 85, 80)
DATA_URI_PREFIX = "data:image/jpeg;base64,"

_qt_app = None


@dataclass
class QualityRow:
    quality: int
    orig_w: int
    orig_h: int
    out_w: int
    out_h: int
    jpeg_bytes: int
    base64_len: int
    data_uri_len: int
    compress_ms_median: float
    jpeg_vs_100_pct: float | None
    uri_vs_100_pct: float | None


def _init_qt_inline():
    """Create QApplication and import Qt / main only after success."""
    global _qt_app
    if _qt_app is not None:
        return _qt_app

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")

    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication

    existing = QGuiApplication.instance()
    if existing is not None:
        _qt_app = existing
        return _qt_app

    last_err: Exception | None = None
    for argv in (_BENCH_QT_ARGV, []):
        try:
            _qt_app = QApplication(list(argv))
            if QGuiApplication.instance() is not None:
                return _qt_app
        except Exception as exc:
            last_err = exc
            _qt_app = None

    hint = f" ({last_err})" if last_err else ""
    raise RuntimeError(f"Could not create QApplication{hint}")


def _import_compress_screenshot():
    from main import compress_screenshot

    return compress_screenshot


def _pil_rgba_to_qpixmap(pil_image, QImage, QPixmap):

    rgba = pil_image.convert("RGBA")
    w, h = rgba.size
    qimage = QImage(rgba.tobytes("raw", "RGBA"), w, h, QImage.Format.Format_RGBA8888)
    pixmap = QPixmap.fromImage(qimage)
    if pixmap.isNull():
        raise RuntimeError("Failed to convert PIL image to QPixmap.")
    return pixmap


def _load_pixmap_file(path: Path, QImage, QPixmap):
    from PIL import Image

    try:
        with Image.open(path) as im:
            return _pil_rgba_to_qpixmap(im, QImage, QPixmap)
    except OSError as exc:
        raise SystemExit(f"Failed to load image: {path} ({exc})") from exc


def _load_pixmap_screen(screen_index: int, QPixmap):
    from app.snipper import ScreenCapturer

    class _Cfg:
        def get_int(self, key: str, default: int = 0) -> int:
            if key == "screen_index":
                return screen_index
            return default

    pixmap = ScreenCapturer(_Cfg()).grab()
    if pixmap is None:
        raise SystemExit("Screen capture failed (no screens or grab returned None).")
    return pixmap


def _load_pixmap_synthetic(width: int, height: int, QColor, QImage, QPainter, QPixmap):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(32, 48, 72))
    block_h = max(24, height // 12)
    colors = (
        QColor(220, 90, 70),
        QColor(90, 180, 120),
        QColor(240, 200, 60),
        QColor(120, 140, 220),
    )
    painter = QPainter(image)
    for i, color in enumerate(colors):
        y = i * block_h
        if y >= height:
            break
        h = min(block_h, height - y)
        for x in range(0, width, max(80, width // 8)):
            w = min(160, width - x)
            painter.fillRect(x, y, w, h, color)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        raise SystemExit("Failed to build synthetic pixmap.")
    return pixmap


def _decode_jpeg_metrics(data_uri: str) -> tuple[int, int, int, int]:
    from PIL import Image

    if not data_uri.startswith(DATA_URI_PREFIX):
        raise ValueError("Unexpected data URI prefix from compress_screenshot")
    b64 = data_uri[len(DATA_URI_PREFIX) :]
    jpeg_bytes = base64.b64decode(b64, validate=True)
    with Image.open(io.BytesIO(jpeg_bytes)) as img:
        out_w, out_h = img.size
    return len(jpeg_bytes), len(b64), out_w, out_h


def _bench_quality(pixmap, quality: int, max_width: int, runs: int, compress_screenshot) -> tuple[str, float]:
    timings: list[float] = []
    data_uri = ""
    for _ in range(runs):
        t0 = time.perf_counter()
        data_uri = compress_screenshot(pixmap, max_width=max_width, quality=quality)
        timings.append((time.perf_counter() - t0) * 1000.0)
    return data_uri, float(statistics.median(timings))


def _run_benchmark_inline(pixmap, max_width: int, runs: int, compress_screenshot) -> list[QualityRow]:
    orig_w, orig_h = pixmap.width(), pixmap.height()
    rows: list[QualityRow] = []
    baseline_jpeg: int | None = None
    baseline_uri: int | None = None

    for quality in QUALITIES:
        data_uri, compress_ms_median = _bench_quality(pixmap, quality, max_width, runs, compress_screenshot)
        jpeg_bytes, base64_len, out_w, out_h = _decode_jpeg_metrics(data_uri)
        data_uri_len = len(data_uri)

        if quality == 100:
            baseline_jpeg = jpeg_bytes
            baseline_uri = data_uri_len
            jpeg_vs = uri_vs = None
        else:
            jpeg_vs = round((baseline_jpeg - jpeg_bytes) / baseline_jpeg * 100.0, 2) if baseline_jpeg else None
            uri_vs = round((baseline_uri - data_uri_len) / baseline_uri * 100.0, 2) if baseline_uri else None

        rows.append(
            QualityRow(
                quality=quality,
                orig_w=orig_w,
                orig_h=orig_h,
                out_w=out_w,
                out_h=out_h,
                jpeg_bytes=jpeg_bytes,
                base64_len=base64_len,
                data_uri_len=data_uri_len,
                compress_ms_median=round(compress_ms_median, 2),
                jpeg_vs_100_pct=jpeg_vs,
                uri_vs_100_pct=uri_vs,
            )
        )
    return rows


def _run_benchmark_subprocess(path: Path, max_width: int, runs: int) -> list[QualityRow]:
    cmd = [
        sys.executable,
        str(WORKER),
        str(path.resolve()),
        str(max_width),
        str(runs),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"Benchmark worker failed (exit {proc.returncode}):\n{err}")
    payload = json.loads(proc.stdout.strip())
    return [QualityRow(**row) for row in payload["rows"]]


def _format_table(rows: list[QualityRow], meta: dict) -> str:
    lines = [
        f"DanmuAI JPEG benchmark  max_width={meta['max_width']}  source={meta['source']}  "
        f"runs={meta['runs']}  engine={meta.get('engine', 'inline')}",
    ]
    if meta.get("path"):
        lines.append(f"  path={meta['path']}")
    if meta.get("screen_index") is not None:
        lines.append(f"  screen_index={meta['screen_index']}")
    if meta.get("synthetic_size"):
        lines.append(f"  synthetic_size={meta['synthetic_size']}")

    header = (
        f"{'q':>3}  {'orig':>11}  {'out':>11}  {'jpeg_kb':>8}  {'b64_kb':>8}  "
        f"{'uri_kb':>8}  {'ms':>8}  {'jpeg%-100':>10}  {'uri%-100':>10}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for r in rows:
        jpeg_pct = "" if r.jpeg_vs_100_pct is None else f"{r.jpeg_vs_100_pct:>9.2f}%"
        uri_pct = "" if r.uri_vs_100_pct is None else f"{r.uri_vs_100_pct:>9.2f}%"
        orig = f"{r.orig_w}x{r.orig_h}"
        out = f"{r.out_w}x{r.out_h}"
        lines.append(
            f"{r.quality:>3}  {orig:>11}  {out:>11}  "
            f"{r.jpeg_bytes / 1024:>8.1f}  {r.base64_len / 1024:>8.1f}  {r.data_uri_len / 1024:>8.1f}  "
            f"{r.compress_ms_median:>8.2f}  {jpeg_pct:>10}  {uri_pct:>10}"
        )
    return "\n".join(lines)


def _default_json_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.gettempdir()) / f"danmu_jpeg_bench_{stamp}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark main.compress_screenshot() JPEG quality settings (local only).",
    )
    parser.add_argument("--source", choices=("file", "screen", "synthetic"), default="file")
    parser.add_argument("--path", type=Path, help="Image path when --source file.")
    parser.add_argument("--screen-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--max-width", type=int, default=DEFAULT_MAX_WIDTH)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--no-json", action="store_true")
    parser.add_argument(
        "--subprocess",
        action="store_true",
        help="Force subprocess worker (fresh QApplication; recommended if inline Qt fails).",
    )
    parser.add_argument(
        "--inline-only",
        action="store_true",
        help="Do not fall back to subprocess worker.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.source == "file":
        if not args.path:
            raise SystemExit("--path is required when --source file")
        if not args.path.is_file():
            raise SystemExit(f"File not found: {args.path}")
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if args.subprocess and args.inline_only:
        raise SystemExit("Use only one of --subprocess or --inline-only.")

    path_str = str(args.path.resolve()) if args.source == "file" and args.path else None
    engine = "inline"

    if args.source == "file":
        use_subprocess = args.subprocess
        if not use_subprocess and not args.inline_only:
            try:
                _init_qt_inline()
            except RuntimeError:
                use_subprocess = True
        elif not use_subprocess:
            _init_qt_inline()

        if use_subprocess:
            rows = _run_benchmark_subprocess(args.path, args.max_width, args.runs)
            engine = "subprocess"
        else:
            from PyQt6.QtGui import QImage, QPixmap

            compress_screenshot = _import_compress_screenshot()
            pixmap = _load_pixmap_file(args.path, QImage, QPixmap)
            rows = _run_benchmark_inline(pixmap, args.max_width, args.runs, compress_screenshot)
    else:
        _init_qt_inline()
        from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap

        compress_screenshot = _import_compress_screenshot()
        if args.source == "screen":
            pixmap = _load_pixmap_screen(args.screen_index, QPixmap)
            path_str = None
        else:
            pixmap = _load_pixmap_synthetic(args.width, args.height, QColor, QImage, QPainter, QPixmap)
            path_str = None
        rows = _run_benchmark_inline(pixmap, args.max_width, args.runs, compress_screenshot)

    meta = {
        "source": args.source,
        "max_width": args.max_width,
        "runs": args.runs,
        "qualities": list(QUALITIES),
        "path": path_str,
        "screen_index": args.screen_index if args.source == "screen" else None,
        "synthetic_size": f"{args.width}x{args.height}" if args.source == "synthetic" else None,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "engine": engine,
    }

    print(_format_table(rows, meta))

    if not args.no_json:
        json_path = args.json_out or _default_json_path()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"meta": meta, "rows": [asdict(r) for r in rows]}
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON written to: {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
