# RetroDB's own, not ported from Slipcase (PASS-59-331).
"""Faces cut out of a game's downloaded 3D box picture (`boxart_3d`).

The picture is the box drawn turned to the left: the spine on the left,
the front on the right, on a transparent background. The fold between them
is where the box's top outline is highest, because the fold is the edge
nearest the viewer. Each face is a four-sided shape whose top and bottom
edges are straight lines; it is straightened into a flat rectangle the
case's real shape.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from services.box3d.cases import CaseType

# A 3D picture whose spine is narrower or wider than this share of the
# picture's width is not a box turned the expected way.
_SPINE_SHARE = (0.03, 0.45)
# Most a fitted top or bottom edge may stray from the outline, as a share of
# the picture's height, before the picture counts as not a plain box.
_MAX_STRAY = 0.03
# Two fronts are compared as small grey pictures this size, each with this
# share trimmed off every side (a case's band or rim), the best of every
# shift up to _COMPARE_SHIFT pixels. Measured on 279 library games
# (PASS-59-331): the same artwork scores 0.86 at the median, two different
# games' never above 0.45, and nearly every same-game pair under SAME_ART is
# another release's box.
_COMPARE_SIZE = (24, 36)
_COMPARE_TRIM = 0.08
_COMPARE_SHIFT = 2
SAME_ART = 0.5


def _edge(xs: np.ndarray, ys: np.ndarray, height: int):
    """The straight line through the middle 80% of one edge's outline, as
    (slope, intercept), or None when the outline strays from it."""
    trim = len(xs) // 10
    xs, ys = xs[trim:len(xs) - trim], ys[trim:len(ys) - trim]
    if len(xs) < 2:
        return None
    slope, intercept = np.polyfit(xs, ys, 1)
    if np.abs(slope * xs + intercept - ys).max() > _MAX_STRAY * height:
        return None
    return slope, intercept


def _straighten(im: Image.Image, x_near: int, x_far: int, top, bottom,
                size: tuple[int, int]) -> Image.Image:
    """The face between columns x_near and x_far, as a flat `size` picture."""
    at = lambda line, x: line[0] * x + line[1]  # noqa: E731
    left, right = min(x_near, x_far), max(x_near, x_far)
    quad = (left, at(top, left), left, at(bottom, left),
            right, at(bottom, right), right, at(top, right))
    return im.transform(size, Image.Transform.QUAD, quad, Image.Resampling.BICUBIC)


def cut_faces(path: str, case: CaseType | None, max_height: int) -> tuple[Image.Image, Image.Image] | None:
    """(front, spine) as RGB, cut from the 3D picture at `path` and shaped
    as `case`'s front and spine (with no case, as wide as the picture shows
    them), no taller than `max_height` nor than the picture shows them;
    None when the picture is not a box turned to the left on a transparent
    background."""
    with Image.open(path) as im:
        if 'A' not in im.getbands() and 'transparency' not in im.info:
            return None
        im = im.convert('RGBA')
    solid = np.asarray(im.getchannel('A')) > 128
    if solid[0, 0] or solid[0, -1] or solid[-1, 0] or solid[-1, -1]:
        return None
    columns = np.flatnonzero(solid.any(axis=0))
    if len(columns) < 20:
        return None
    rows = solid[:, columns]
    tops = rows.argmax(axis=0)
    bottoms = rows.shape[0] - 1 - rows[::-1].argmax(axis=0)
    fold = int(tops.argmin())
    if not _SPINE_SHARE[0] <= fold / len(columns) <= _SPINE_SHARE[1]:
        return None

    lines = []
    for part in (slice(0, fold), slice(fold, None)):
        for outline in (tops, bottoms):
            line = _edge(columns[part], outline[part], im.height)
            if line is None:
                return None
            lines.append(line)
    spine_top, spine_bottom, front_top, front_bottom = lines

    x_left, x_fold, x_right = int(columns[0]), int(columns[fold]), int(columns[-1])
    # Edges are the first and last solid rows, so both rows count.
    near = (front_bottom[0] - front_top[0]) * x_fold + front_bottom[1] - front_top[1] + 1
    height = max(1, min(max_height, round(near)))
    if case is None:
        front_size, spine_size = (max(1, x_right - x_fold), height), (max(1, x_fold - x_left), height)
    else:
        front_size = (max(1, round(height * case.width / case.height)), height)
        spine_size = (max(1, round(height * case.depth / case.height)), height)
    flat = im.convert('RGB')
    front = _straighten(flat, x_fold, x_right, front_top, front_bottom, front_size)
    spine = _straighten(flat, x_left, x_fold, spine_top, spine_bottom, spine_size)
    return front, spine


def _small(im: Image.Image) -> np.ndarray:
    grey = im.convert('L')
    w, h = grey.size
    trim = (round(w * _COMPARE_TRIM), round(h * _COMPARE_TRIM))
    grey = grey.crop((trim[0], trim[1], w - trim[0], h - trim[1]))
    return np.asarray(grey.resize(_COMPARE_SIZE, Image.Resampling.BOX), dtype=np.float64)


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    spread = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / spread) if spread else 0.0


def same_art(a: Image.Image, b: Image.Image) -> float:
    """How alike two fronts look, from -1 to 1: their best correlation as
    small grey pictures, so scan colour, size, sharpness, a case's band and
    a slightly different crop barely count."""
    a, b = _small(a), _small(b)
    rows, cols = a.shape
    best = -1.0
    for dy in range(-_COMPARE_SHIFT, _COMPARE_SHIFT + 1):
        for dx in range(-_COMPARE_SHIFT, _COMPARE_SHIFT + 1):
            ys, yt = slice(max(0, dy), rows + min(0, dy)), slice(max(0, -dy), rows + min(0, -dy))
            xs, xt = slice(max(0, dx), cols + min(0, dx)), slice(max(0, -dx), cols + min(0, -dx))
            best = max(best, _correlation(a[ys, xs], b[yt, xt]))
    return best
