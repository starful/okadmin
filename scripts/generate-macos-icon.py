#!/usr/bin/env python3
"""Generate macOS .icns for OK Admin apps (dark + accent, readable at small sizes)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow required: pip install Pillow", file=sys.stderr)
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
MAC_DIR = ROOT / "mac"
ICONSET = MAC_DIR / "AppIcon.iconset"
DEV_ICONSET = MAC_DIR / "AppIconDev.iconset"
STOP_ICONSET = MAC_DIR / "AppIconStop.iconset"


def _font(size: int, *, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    )
    for path in candidates:
        p = Path(path)
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_icon(size: int, *, dev: bool = False, stop: bool = False) -> Image.Image:
    if stop:
        accent = (248, 113, 113, 255)
    elif dev:
        accent = (96, 165, 250, 255)
    else:
        accent = (232, 255, 71, 255)
    bg = (10, 10, 10, 255)
    img = Image.new("RGBA", (size, size), bg)
    draw = ImageDraw.Draw(img)
    pad = max(2, size // 10)
    radius = max(4, size // 5)
    draw.rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=radius,
        fill=(18, 18, 18, 255),
        outline=accent,
        width=max(2, size // 32),
    )

    main = "OK" if size >= 48 else "O"
    if stop:
        sub = "STOP" if size >= 64 else ""
        main = "■" if size >= 48 else "·"
    else:
        sub = "DEV" if dev else "AD"
    f_main = _font(max(10, int(size * 0.38)))
    f_sub = _font(max(7, int(size * 0.14)))

    bbox_m = draw.textbbox((0, 0), main, font=f_main)
    w_m = bbox_m[2] - bbox_m[0]
    h_m = bbox_m[3] - bbox_m[1]
    y_main = size * 0.28 - h_m / 2
    draw.text(((size - w_m) / 2, y_main), main, fill=accent, font=f_main)

    if size >= 64 and sub:
        bbox_s = draw.textbbox((0, 0), sub, font=f_sub)
        w_s = bbox_s[2] - bbox_s[0]
        sub_color = (180, 180, 180, 255)
        if dev:
            sub_color = (147, 197, 253, 255)
        if stop:
            sub_color = (252, 165, 165, 255)
        draw.text(
            ((size - w_s) / 2, size * 0.62),
            sub,
            fill=sub_color,
            font=f_sub,
        )
    return img


def write_iconset(iconset: Path, *, dev: bool = False, stop: bool = False) -> None:
    iconset.mkdir(parents=True, exist_ok=True)
    specs = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for px, name in specs:
        draw_icon(px, dev=dev, stop=stop).save(iconset / name, format="PNG")


def to_icns(iconset: Path, out: Path) -> None:
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(out)],
        check=True,
    )


def main() -> None:
    MAC_DIR.mkdir(parents=True, exist_ok=True)
    write_iconset(ICONSET, dev=False)
    write_iconset(DEV_ICONSET, dev=True)
    write_iconset(STOP_ICONSET, stop=True)
    to_icns(ICONSET, MAC_DIR / "AppIcon.icns")
    to_icns(DEV_ICONSET, MAC_DIR / "AppIconDev.icns")
    to_icns(STOP_ICONSET, MAC_DIR / "AppIconStop.icns")
    print(f"✅ {MAC_DIR / 'AppIcon.icns'}")
    print(f"✅ {MAC_DIR / 'AppIconDev.icns'}")
    print(f"✅ {MAC_DIR / 'AppIconStop.icns'}")


if __name__ == "__main__":
    main()
