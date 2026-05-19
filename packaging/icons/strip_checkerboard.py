#!/usr/bin/env python3
"""Remove GPT fake checkerboard background → real PNG alpha.

Flood-fills from image borders through light neutral pixels only, so
internal whites (e.g. gap between ring and iris) are preserved.
"""
from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

from PIL import Image


def _is_bg_pixel(r: int, g: int, b: int, *, lum_min: int = 228, chroma_max: int = 14) -> bool:
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn > chroma_max:
        return False
    return (r + g + b) / 3 >= lum_min


def strip_checkerboard(src: Path, dst: Path, *, lum_min: int = 228) -> None:
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    px = im.load()
    visited = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()

    def push(x: int, y: int) -> None:
        i = y * w + x
        if visited[i]:
            return
        r, g, b, _a = px[x, y]
        if not _is_bg_pixel(r, g, b, lum_min=lum_min):
            return
        visited[i] = 1
        q.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)

    while q:
        x, y = q.popleft()
        px[x, y] = (px[x, y][0], px[x, y][1], px[x, y][2], 0)
        if x > 0:
            push(x - 1, y)
        if x + 1 < w:
            push(x + 1, y)
        if y > 0:
            push(x, y - 1)
        if y + 1 < h:
            push(x, y + 1)

    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, optimize=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("src", type=Path)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--lum-min", type=int, default=228, help="min mean RGB for bg flood (default 228)")
    args = p.parse_args(argv)
    strip_checkerboard(args.src, args.output, lum_min=args.lum_min)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
