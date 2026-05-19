#!/usr/bin/env python3
"""Build icon.icns, icon.ico, and app_icon_512.png from source/main_icon-v2.png.

Artwork is inset (~18% margin) on a square canvas so macOS can apply the
squircle mask without looking oversized or square-cornered in the Dock.
Each output size is resized from that composed master (LANCZOS).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
DEFAULT_SRC = HERE / "source" / "main_icon-v2.png"
ICONSET = HERE / "icon.iconset"

# macOS iconset: (filename, pixel size)
ICONSET_SIZES: tuple[tuple[str, int], ...] = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)

ICO_SIZES = (16, 32, 48, 256)
CANVAS = 1024
# Inset artwork so it matches other Dock icons after the squircle mask.
ART_FILL = 0.74
# ~macOS Big Sur app-icon corner radius (1024 → ~226px).
SQUIRCLE_RADIUS_RATIO = 0.221


def _sample_bg(img: Image.Image) -> tuple[int, int, int]:
    w, h = img.size
    pts = ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))
    rs = [img.getpixel(p)[0] for p in pts]
    gs = [img.getpixel(p)[1] for p in pts]
    bs = [img.getpixel(p)[2] for p in pts]
    return (sum(rs) // 4, sum(gs) // 4, sum(bs) // 4)


def _compose_master(src: Image.Image, *, canvas: int = CANVAS, fill: float = ART_FILL) -> Image.Image:
    """Center artwork on square canvas with safe margin for macOS icon mask."""
    src = src.convert("RGB")
    bg = _sample_bg(src)
    inner = max(1, round(canvas * fill))
    fitted = src.resize((inner, inner), Image.Resampling.LANCZOS)
    out = Image.new("RGB", (canvas, canvas), bg)
    offset = (canvas - inner) // 2
    out.paste(fitted, (offset, offset))
    return out


def _squircle_mask(size: int) -> Image.Image:
    radius = max(1, int(size * SQUIRCLE_RADIUS_RATIO))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255,
    )
    return mask


def _resize(master: Image.Image, size: int, *, sharpen: bool) -> Image.Image:
    out = master.resize((size, size), Image.Resampling.LANCZOS)
    if sharpen and size >= 64:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=2))
    return out


def _dock_png(master_rgb: Image.Image, size: int = 512) -> Image.Image:
    """RGBA PNG with transparent corners — Qt Dock uses this in dev (`python -m`)."""
    rgb = _resize(master_rgb, size, sharpen=True)
    r, g, b = rgb.split()
    return Image.merge("RGBA", (r, g, b, _squircle_mask(size)))


def build(src: Path, *, out_dir: Path) -> None:
    raw = Image.open(src).convert("RGB")
    master = _compose_master(raw)
    out_dir.mkdir(parents=True, exist_ok=True)

    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir()

    for name, px in ICONSET_SIZES:
        sharpen = px >= 128
        _resize(master, px, sharpen=sharpen).save(ICONSET / name, optimize=True)

    icns_path = out_dir / "icon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET), "-o", str(icns_path)],
        check=True,
    )
    shutil.rmtree(ICONSET)

    ico_images = [_resize(master, s, sharpen=s >= 64) for s in ICO_SIZES]
    ico_path = out_dir / "icon.ico"
    ico_images[-1].save(
        ico_path,
        format="ICO",
        sizes=[(im.width, im.height) for im in ico_images],
        append_images=ico_images[:-1],
    )

    app_png = out_dir / "app_icon_512.png"
    _dock_png(master, 512).save(app_png, optimize=True)
    print(f"Wrote {icns_path}, {ico_path}, {app_png} (RGBA + squircle)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=DEFAULT_SRC)
    p.add_argument("--out-dir", type=Path, default=HERE)
    args = p.parse_args(argv)
    if not args.src.is_file():
        print(f"Missing source: {args.src}", file=sys.stderr)
        return 1
    if sys.platform != "darwin":
        print("icon.icns requires macOS iconutil; .ico and PNG still build.", file=sys.stderr)
    build(args.src, out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
