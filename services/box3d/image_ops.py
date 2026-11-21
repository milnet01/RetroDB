# Ported from Slipcase (MIT, the same author) core/image_utils.py at a08a2a4
# for PASS-59-326: only the parts the face builders call. Keep names and
# figures as Slipcase has them; RetroDB changes are marked "RetroDB:".
"""Image utility functions the box face builders use."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from services.box3d.cases import CaseType

_log = logging.getLogger(__name__)


# Smallest colour step, as the RGB distance _refine_spine_bounds scores in
# (0 to ~441), that may count as a fold. The 20% test alone is met by ANY
# edge when the estimate itself scores 0 -- a region with no detail -- so a
# faint gradient or compression noise could move the boundary (SLIP-0058).
_MIN_FOLD_STEP = 10.0


def uniform_filter1d(values: np.ndarray, size: int, axis: int = 0) -> np.ndarray:
    """RetroDB: SciPy's `scipy.ndimage.uniform_filter1d` in its default
    `reflect` mode (numpy's `symmetric`), so the port needs no SciPy. The
    window of an even `size` reaches one further back than forward, as
    SciPy's does."""
    values = np.asarray(values, dtype=np.float64)
    before, after = size // 2, size - 1 - size // 2
    pad = [(0, 0)] * values.ndim
    pad[axis] = (before, after)
    padded = np.pad(values, pad, mode='symmetric')
    total = np.cumsum(padded, axis=axis)
    zero = np.zeros_like(np.take(total, [0], axis=axis))
    total = np.concatenate([zero, total], axis=axis)
    n = values.shape[axis]
    upper = np.take(total, np.arange(size, size + n), axis=axis)
    lower = np.take(total, np.arange(0, n), axis=axis)
    return ((upper - lower) / size).astype(np.float32)

def extract_dominant_edge_color(
    image: Image.Image,
    edge: str = "left",
    sample_width: int = 5,
) -> tuple[int, int, int]:
    """Extract the dominant color from an edge of the image.

    Args:
        image: Input image.
        edge: Which edge to sample ('left', 'right', 'top', 'bottom').
        sample_width: Number of pixels to sample from the edge.

    Returns:
        (R, G, B) tuple of the dominant color.
    """
    img = image.convert("RGB")
    w, h = img.size

    if edge == "left":
        region = img.crop((0, 0, min(sample_width, w), h))
    elif edge == "right":
        region = img.crop((max(0, w - sample_width), 0, w, h))
    elif edge == "top":
        region = img.crop((0, 0, w, min(sample_width, h)))
    elif edge == "bottom":
        region = img.crop((0, max(0, h - sample_width), w, h))
    else:
        region = img.crop((0, 0, min(sample_width, w), h))

    # Quantize to find dominant color
    small = region.resize((1, 1), Image.Resampling.LANCZOS)
    r, g, b = small.getpixel((0, 0))
    return (int(r), int(g), int(b))


# Clear plastic with no tint of its own, as LaunchBox's Switch and PSP boxes
# show it. Judged by eye (2026-10-30).
CLEAR_RIM = (0xD8, 0xDC, 0xE0)
# How much the lip's inner wall darkens the plastic, and its share of the lip.
_RIM_WALL_SHADE = 0.6
_RIM_WALL_SHARE = 0.25


def _case_plastic(
    case_type: CaseType,
    case_color: tuple[int, int, int] | None,
) -> tuple[int, int, int] | None:
    """The colour a case's bare plastic shows; None for a printed box."""
    if case_color is not None:
        return case_color
    if case_type.plastic is not None:
        return case_type.plastic
    return CLEAR_RIM if case_type.clear else None


def case_edge_colours(
    front_image: Image.Image,
    case_type: CaseType,
    case_color: tuple[int, int, int] | None,
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """A case's top, bottom and opening-edge colours (SLIP-0107 § 4.2).

    A case with plastic is that plastic all round, clear or not; a clear one
    no longer takes the cover's colour (the user, 2026-10-30). A printed box
    has no plastic: its top and bottom are sampled from the front at those
    edges, and its opening edge takes the top's colour.
    """
    plastic = _case_plastic(case_type, case_color)
    if plastic is not None:
        return plastic, plastic, plastic
    top = extract_dominant_edge_color(front_image, edge="top")
    return top, extract_dominant_edge_color(front_image, edge="bottom"), top


def inset_in_rim(
    face: Image.Image,
    case_type: CaseType,
    case_color: tuple[int, int, int] | None,
    opening: str | None,
    wall: bool = True,
) -> Image.Image:
    """Shrink a printed face into its case's plastic lip; RGBA.

    The lip runs along the top and bottom, and down the side named by
    `opening` ("left" or "right"; None for a spine, which has neither). The
    hinge side has none, so the art runs on to the spine. The art is shrunk,
    not cropped, as a logo often sits at its very edge. A case with no rim
    returns `face` untouched. With `wall` clear, the lip's inner wall is not
    painted: a 3D viewer drawing a real lip casts it (SLIP-0125 § 4.3).
    """
    if not case_type.rim_mm:
        return face
    width, height = face.size
    rim = max(1, round(case_type.rim_mm * height / case_type.height))
    side = max(1, round(case_type.side_rim_mm * height / case_type.height))
    if height <= 2 * rim or width <= side:
        return face
    plastic = _case_plastic(case_type, case_color)
    framed = Image.new("RGBA", face.size, (*plastic, 255))

    left = side if opening == "left" else 0
    right = width - side if opening == "right" else width
    # The lip's inner wall, in shade, so the sheet reads as sunk below it. A
    # one-pixel lip has no room for one and must still read as the plastic.
    band = round(rim * _RIM_WALL_SHARE) if wall and rim > 1 else 0
    if band:
        shade = tuple(round(c * _RIM_WALL_SHADE) for c in plastic)
        framed.paste((*shade, 255), (
            max(0, left - band), rim - band,
            min(width, right + band), height - rim + band,
        ))
    art = face if face.mode == "RGBA" else face.convert("RGBA")
    art = art.resize((max(1, right - left), height - 2 * rim), Image.Resampling.LANCZOS)
    # Over the frame, not pasted: a transparent corner must not punch a hole.
    framed.alpha_composite(art, (left, rim))
    return framed


def wrap_panels_mm(case_type: CaseType) -> tuple[float, float, float, float]:
    """A full cover's panels in mm: (back, spine, front, height).

    The wrap layout's panels are the case's own faces. A jewel case's wrap is
    its paper: the back card's middle, one end strip at the hinge, and the
    booklet, at the back card's height (SLIP-0106 § 4.4).
    """
    jewel = case_type.jewel
    if jewel is None:
        return case_type.width, case_type.depth, case_type.width, case_type.height
    card_w, card_h = jewel.back_card
    return card_w - 2 * jewel.strip, jewel.strip, jewel.booklet[0], card_h


def upright_spine(image: Image.Image) -> Image.Image:
    """A spine picture the user loaded, standing upright as RGBA.

    A spine scan lying on its side, wider than tall, is turned a quarter
    clockwise, so its left end goes to the top: a spine's title reads top
    to bottom.
    """
    if image.width > image.height:
        image = image.transpose(Image.Transpose.ROTATE_270)
    return image.convert("RGBA")


def is_full_cover(image: Image.Image, case_type: CaseType, tolerance: float = 0.15) -> bool:
    """Detect whether an image is a full cover (back + spine + front) based on aspect ratio.

    A full cover has aspect ratio ~= (back + spine + front) / height, from
    wrap_panels_mm. A front-only cover has aspect ratio ~= width / height.

    Args:
        image: Input image to test.
        case_type: Case type with real-world dimensions.
        tolerance: How much deviation from expected AR is allowed (0.15 = 15%).

    Returns:
        True if image appears to be a full cover.
    """
    img_ar = image.size[0] / image.size[1]
    back, spine, front, height = wrap_panels_mm(case_type)
    full_ar = (back + spine + front) / height
    return abs(img_ar - full_ar) / full_ar <= tolerance


def detect_spine_bounds(
    image: Image.Image, case_type: CaseType,
) -> tuple[int, int]:
    """Detect the left and right x-coordinates of the spine in a full cover.

    Uses a two-stage approach:
    1. Geometric baseline from case dimensions and image height.
    2. Image-based refinement using multi-band vertical edge analysis to
       find physical fold lines near the geometric estimate.

    Returns:
        (left_x, right_x) spine boundary positions in image coordinates.
    """
    w, h = image.size

    # Stage 1: geometric baseline
    geo_left, geo_right, spine_px = _geometric_spine_bounds(w, h, case_type)

    # Stage 2: refine using image analysis. Only the errors numpy raises on
    # unexpected data fall back, and they are logged; anything else is a bug
    # and propagates (SLIP-0054).
    try:
        return _refine_spine_bounds(image, geo_left, geo_right, spine_px)
    except (ValueError, IndexError) as e:
        _log.warning("spine refinement failed, using the geometric estimate: %s", e)
        return geo_left, geo_right


def _geometric_spine_bounds(
    w: int, h: int, case_type: CaseType,
) -> tuple[int, int, int]:
    """Pure geometric spine detection from case dimensions.

    Returns:
        (left_x, right_x, spine_width_px)
    """
    back_mm, spine_mm, front_mm, height_mm = wrap_panels_mm(case_type)
    px_per_mm = h / height_mm
    back_px = round(back_mm * px_per_mm)
    spine_px = round(spine_mm * px_per_mm)
    front_px = round(front_mm * px_per_mm)

    total_panels = back_px + spine_px + front_px
    offset = max(0, w - total_panels) // 2

    spine_left = offset + back_px
    spine_right = spine_left + spine_px

    spine_left = max(0, min(spine_left, w - 1))
    spine_right = max(spine_left + 1, min(spine_right, w))

    return spine_left, spine_right, spine_px


def _fold_band_means(image: Image.Image, expected_sw: int) -> np.ndarray:
    """Per-band running-mean colour of each column, shape (bands, width, 3).

    The edge search's input for one image; _nudge reads it once per fold.
    """
    arr = np.array(image.convert("RGB"), dtype=np.float32)
    h = arr.shape[0]

    n_bands = 16
    strip_w = _fold_strip_width(expected_sw)
    y_margin = int(h * 0.03)
    band_h = max(1, (h - 2 * y_margin) // n_bands)

    band_means = []
    for i in range(n_bands):
        y0 = y_margin + i * band_h
        y1 = y0 + band_h
        col_mean = arr[y0:y1, :, :].mean(axis=0)  # (w, 3)
        rm = uniform_filter1d(col_mean, size=strip_w, axis=0)  # (w, 3)
        band_means.append(rm)
    return np.array(band_means)  # (n_bands, w, 3)


def _fold_strip_width(expected_sw: int) -> int:
    """Width of the strip compared either side of a candidate fold."""
    return max(4, min(8, expected_sw // 10))


def _nudge(band_means: np.ndarray, geo_x: int, expected_sw: int) -> int:
    """Move one fold from its geometric estimate `geo_x` to the strongest
    consistent edge within reach, or leave it.

    It moves up to 15% of `expected_sw`, clamped to 8-30 px, and only when
    that edge beats the estimate by more than 20% and is at least
    _MIN_FOLD_STEP strong. Both spine bounds and a back card's folds use it
    (SLIP-0106 § 4.4).
    """
    w = band_means.shape[1]
    half = _fold_strip_width(expected_sw) // 2
    nudge_max = max(8, min(30, int(expected_sw * 0.15)))

    # Boundary score for each x in [geo_x - nudge_max, geo_x + nudge_max]:
    # the 30th percentile, across bands, of the colour step there. Empty
    # when the image is too narrow to hold a strip either side.
    lo = max(half + 1, geo_x - nudge_max)
    hi = min(w - half - 1, geo_x + nudge_max + 1)
    if hi <= lo:
        return geo_x
    left_m = band_means[:, lo - half:hi - half, :]
    right_m = band_means[:, lo + half:hi + half, :]
    diffs = np.sqrt(np.sum((right_m - left_m) ** 2, axis=2))
    scores = np.percentile(diffs, 30, axis=0)

    geo_idx = geo_x - lo
    if geo_idx < 0 or geo_idx >= len(scores):
        return geo_x
    geo_score = scores[geo_idx]
    best_idx = int(np.argmax(scores))
    best_score = scores[best_idx]
    # Only nudge to a real edge that is meaningfully better
    if best_score > geo_score * 1.2 and best_score >= _MIN_FOLD_STEP:
        return lo + best_idx
    return geo_x


def _refine_spine_bounds(
    image: Image.Image,
    geo_left: int,
    geo_right: int,
    expected_sw: int,
) -> tuple[int, int]:
    """Refine spine boundaries using multi-band colour discontinuity.

    At a physical fold line the colours on the left and right sides come
    from different panels, producing a consistent colour jump across most
    of the image height.  Artwork edges, by contrast, only appear in
    specific rows.

    For each candidate boundary position near the geometric estimate, we
    measure the colour difference between thin strips on each side across
    multiple horizontal bands.  The 30th percentile across bands gives a
    robust "consistency" measure.

    Each boundary is independently nudged (_nudge) to the STRONGEST
    consistent edge near its geometric estimate, or kept there.
    """
    band_means = _fold_band_means(image, expected_sw)
    ref_left = _nudge(band_means, geo_left, expected_sw)
    ref_right = _nudge(band_means, geo_right, expected_sw)

    # Ensure spine width stays within 85-115% of expected
    ref_sw = ref_right - ref_left
    if ref_sw < expected_sw * 0.85 or ref_sw > expected_sw * 1.15:
        return geo_left, geo_right

    return ref_left, ref_right


def split_full_cover(
    image: Image.Image, case_type: CaseType,
    left_offset: int = 0,
    right_offset: int = 0,
    bounds: tuple[int, int] | None = None,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """Split a full cover image into back, spine, and front portions.

    Calculates spine boundaries from the case dimensions and image analysis,
    then applies a small inward trim on the front and back crops so that
    their edges contain only their own panel content (no spine bleed).
    The spine absorbs the trimmed pixels on each side; since it is resized
    to the target width by the renderer, the extra few pixels are negligible.

    Args:
        image: Full cover image (back + spine + front, left to right).
        case_type: Case type with real-world dimensions.
        left_offset: Pixel offset for the left spine boundary (start).
            Positive moves the boundary right (wider spine, narrower back).
        right_offset: Pixel offset for the right spine boundary (end).
            Positive moves the boundary right (narrower spine, wider front).
        bounds: detect_spine_bounds' result, if the caller already has it.
            It does not depend on the offsets, so a caller splitting one
            image repeatedly need not re-run the detector (SLIP-0067).

    Returns:
        (back, spine, front) as three separate RGBA images.
    """
    w, h = image.size
    left_x, right_x = bounds or detect_spine_bounds(image, case_type)

    left_x = max(0, min(left_x + left_offset, w - 2))
    right_x = max(left_x + 1, min(right_x + right_offset, w))

    # Trim a few pixels inward on front/back so the perspective-transform
    # edge padding never samples spine content.  The spine widens slightly
    # to absorb the trimmed area (resized to target width anyway).
    trim = max(1, round(w * 0.001))
    back_end = max(0, left_x - trim)
    front_start = min(w, right_x + trim)

    back = image.crop((0, 0, back_end, h)).convert("RGBA")
    spine = image.crop((back_end, 0, front_start, h)).convert("RGBA")
    front = image.crop((front_start, 0, w, h)).convert("RGBA")

    return back, spine, front
