#!/usr/bin/env python3
"""Rasterize packaging/icon.svg into all favicon / launcher / exe icons.

BUILD-TIME ONLY. Requires cairosvg (`pip install cairosvg`) which is NOT a
runtime dependency — it is deliberately absent from requirements.txt. The
maintainer runs this once when the icon changes and commits the outputs, so
end users never import it.

Usage:  python3 scripts/render_icons.py
"""
import io
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
# Master lives under packaging/ (a tracked location) — static/images/ is
# gitignored for scraped media, so the build source can't live there.
MASTER = ROOT / 'packaging' / 'icon.svg'


def _png(size: int) -> Image.Image:
    data = cairosvg.svg2png(url=str(MASTER), output_width=size, output_height=size)
    return Image.open(io.BytesIO(data)).convert('RGBA')


def main() -> None:
    static = ROOT / 'static'
    pkg = ROOT / 'packaging' / 'icons'
    pkg.mkdir(parents=True, exist_ok=True)

    # Favicon: keep the vector master + PNG fallbacks.
    (static / 'favicon.svg').write_bytes(MASTER.read_bytes())
    _png(32).save(static / 'favicon-32.png')
    _png(16).save(static / 'favicon-16.png')
    _png(180).save(static / 'apple-touch-icon.png')

    # Linux .desktop launcher icons.
    _png(256).save(pkg / 'retrodb-256.png')
    _png(512).save(pkg / 'retrodb-512.png')

    # Windows .ico (multi-size) + macOS .icns, assembled by Pillow.
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    _png(256).save(pkg / 'retrodb.ico', sizes=ico_sizes)
    # .icns: Pillow writes from a single high-res RGBA image.
    _png(512).save(pkg / 'retrodb.icns')

    print('Rendered favicon + launcher + exe icons from', MASTER.name)


if __name__ == '__main__':
    main()
