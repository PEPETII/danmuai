#!/usr/bin/env python3
"""Copy feedback QR assets into web/static/image for packaging."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "image"
DST_DIR = ROOT / "web" / "static" / "image"

FILES = (
    "qrcode_1779738450536.jpg",
    "mm_reward_qrcode_1779738306814.png",
)

LIVE2D_PREVIEW_IMAGE_NAMES = (
    "httpsbooth.pmenitems4862237.png",
    "httpsbooth.pmenitems5247208.png",
    "httpsbooth.pmenitems5323958.png",
    "httpsbooth.pmzh-cnitems6499774.png",
    "httpsbooth.pmzh-cnitems7159191.png",
    "httpsbooth.pmzh-cnitems7641846.png",
    "1.png",
)


def main() -> int:
    DST_DIR.mkdir(parents=True, exist_ok=True)
    for name in (*FILES, *LIVE2D_PREVIEW_IMAGE_NAMES):
        src = SRC_DIR / name
        dst = DST_DIR / name
        if not src.is_file():
            print(f"missing source: {src}")
            return 1
        shutil.copy2(src, dst)
        print(f"copied {dst} ({dst.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
