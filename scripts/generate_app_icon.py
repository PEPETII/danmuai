#!/usr/bin/env python3
"""Generate resources/icon.png and resources/icon.ico for tray + PyInstaller exe."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "resources"
BG = (255, 183, 140)  # warm peach, aligned with web warm-tokens
FG = (255, 255, 255)
SIZES_ICO = (16, 24, 32, 48, 64, 128, 256)


def _draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(2, size // 16)
    radius = max(4, size // 5)
    draw.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=radius,
        fill=BG,
    )
    font_size = max(10, int(size * 0.52))
    try:
        font = ImageFont.truetype("segoeui.ttf", font_size)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()
    text = "D"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2, (size - th) / 2 - 1),
        text,
        fill=FG,
        font=font,
    )
    return img


def main() -> None:
    RES.mkdir(parents=True, exist_ok=True)
    master = _draw_icon(256)
    png_path = RES / "icon.png"
    ico_path = RES / "icon.ico"
    master.save(png_path, format="PNG")
    ico_images = [_draw_icon(s) for s in SIZES_ICO]
    ico_images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in SIZES_ICO],
        append_images=ico_images[1:],
    )
    print(f"Wrote {png_path}")
    print(f"Wrote {ico_path}")


if __name__ == "__main__":
    main()
