# Ported from Slipcase (MIT, the same author) core/case_texture.py at a08a2a4 for
# PASS-59-326. Keep names and figures as Slipcase has them, so a fix there can
# be copied across; RetroDB changes are marked "RetroDB:".
"""Procedural case texture overlays for realistic physical case features.

Generates semi-transparent RGBA overlays that simulate embossed/debossed
details found on real game cases: DVD ridge lines, Blu-ray logo indents,
cartridge box fold lines, etc.
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from services.box3d.cases import CaseType
from services.box3d.spine import _get_font

# Strongest alpha of a jewel case lid's shine, at its top-left corner. Judged
# by eye at build (SLIP-0106 § 4.7).
SHINE_ALPHA = 48


def generate_front_texture(case_type: CaseType, width: int, height: int,
                           back: bool = False) -> Image.Image:
    """Generate a front face texture overlay for the given case type.

    Returns an RGBA image with subtle emboss/deboss features drawn as
    semi-transparent highlight/shadow pairs. `back` says the overlay is for
    a jewel case's back, whose clear base is glossy all over and has no lid
    ridges.
    """
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    texture = case_type.texture

    # Every jewel entry, whatever its name, is the same moulding (SLIP-0106).
    if case_type.layout == "jewel":
        _draw_jewel_front(draw, case_type, width, height, ridges=not back)
        if case_type.strip_logo and not back:
            overlay.alpha_composite(_strip_logo(case_type, width, height))
        gloss = generate_lid_shine(width, height)
        gloss.alpha_composite(_lid_streak(width, height))
        if case_type.matte_hinge_strip and not back:
            p = width / case_type.width
            window_x = _booklet_x(case_type, p) - (2 * JEWEL_RIDGE_MM + JEWEL_RIDGE_GAP_MM) * p
            gloss.paste((0, 0, 0, 0), (0, 0, max(0, round(window_x)), height))
        overlay.alpha_composite(gloss)
    elif texture == "dvd":
        _draw_dvd_front(draw, width, height)
    elif texture == "bluray":
        _draw_bluray_front(draw, width, height, _band_edge(case_type, height))
    elif texture == "cardboard":
        _draw_cardboard_front(draw, width, height)
    elif texture == "switch":
        _draw_switch_front(draw, width, height)
    elif texture == "ds":
        _draw_ds_front(draw, width, height)
    elif texture == "psp":
        _draw_psp_front(draw, width, height)
    elif texture == "clamshell":
        # The cover sits under a clear sleeve (SLIP-0108).
        overlay.alpha_composite(generate_lid_shine(width, height))

    # A clear keep case shines as a jewel lid does (SLIP-0107 § 4.3).
    if case_type.clear and case_type.layout == "wrap":
        overlay.alpha_composite(generate_lid_shine(width, height))
        overlay.alpha_composite(_lid_streak(width, height))
    if case_type.front_logo and case_type.layout == "wrap" and not back:
        overlay.alpha_composite(_front_logo(case_type, width, height))
    if case_type.band_logo and case_type.layout == "wrap" and not back:
        overlay.alpha_composite(_band_logo(case_type, width, height))

    return overlay


# RetroDB (PASS-59-329): a logo embossed in a keep case's clear front, as on
# early Xbox One and Series X cases. Its width and place are judged from
# photos; the alphas by eye.
FRONT_LOGO_MM = 40          # the text's width
FRONT_LOGO_CENTRE_MM = 7    # its middle, below the top edge
_EMBOSS_FACE = 26           # white over the letters' face
_EMBOSS_HIGHLIGHT = 110     # white along their upper edges
_EMBOSS_SHADOW = 70         # black along their lower edges


def _front_logo(case_type: CaseType, w: int, h: int) -> Image.Image:
    """An RGBA overlay with `case_type.front_logo` embossed in clear plastic,
    centred across the front near its top."""
    p = w / case_type.width
    font = _get_font(max(4, round(10 * p)), bold=True)
    left, top, right, bottom = font.getbbox(case_type.front_logo)
    font = _get_font(max(4, round(font.size * FRONT_LOGO_MM * p / max(1, right - left))),
                     bold=True)
    left, top, right, bottom = font.getbbox(case_type.front_logo)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text(
        ((w - (right - left)) / 2 - left,
         FRONT_LOGO_CENTRE_MM * p - (bottom - top) / 2 - top),
        case_type.front_logo, font=font, fill=255)
    return _emboss(mask, p)


def _emboss(mask: Image.Image, p: float, strength: float = 1.0) -> Image.Image:
    """An RGBA overlay raising the white of `mask` out of clear plastic:
    a faint face, lit upper edges, shaded lower ones. `p` is pixels per mm;
    `strength` scales all three."""
    w, h = mask.size
    m = np.asarray(mask, dtype=np.float32) / 255
    step = max(1, round(0.2 * p))
    above = np.zeros_like(m)
    above[step:] = m[:-step]
    below = np.zeros_like(m)
    below[:-step] = m[step:]
    light = np.clip(strength * (_EMBOSS_FACE * m + _EMBOSS_HIGHLIGHT * np.clip(m - above, 0, 1)),
                    0, 255)
    dark = np.clip(strength * _EMBOSS_SHADOW * np.clip(m - below, 0, 1), 0, 255)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    lit = light >= dark
    rgba[..., :3] = np.where(lit[..., None], 255, 0).astype(np.uint8)
    rgba[..., 3] = np.round(np.where(lit, light, dark)).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


# RetroDB (PASS-59-329): the marks moulded in a PS3 case's clear top strip,
# placed from the user's photo 001 against the case's 135 mm width: boxes in
# mm from the spine edge and the top edge. Their shapes are the logos the
# user supplied (2026-11-25), as grey masks in marks/.
_MARKS = Path(__file__).parent / "marks"
BAND_MARKS = {
    "PLAYSTATION 3": ("playstation3.png", (54.0, 7.2, 130.0, 9.8)),
    "Blu-ray": ("bluray.png", (6.5, 3.3, 22.5, 11.6)),
}
# The viewer draws the strip mostly see-through (box-viewer.js STRIP_ALPHA),
# which fades the moulding with it; judged by eye.
BAND_STRENGTH = 2.5


def _band_logo(case_type: CaseType, w: int, h: int) -> Image.Image:
    """An RGBA overlay of `case_type.band_logo` and the Blu-ray mark moulded
    in the front's clear top strip."""
    p = w / case_type.width
    mask = Image.new("L", (w, h), 0)
    for name in (case_type.band_logo, "Blu-ray"):
        if name in BAND_MARKS:
            _mark_in_box(mask, *BAND_MARKS[name], p)
    return _emboss(mask, p, BAND_STRENGTH)


def _mark_in_box(mask: Image.Image, file: str,
                 box_mm: tuple[float, float, float, float], p: float) -> None:
    """Lay the grey mark `file` on `mask`, as large as fits `box_mm` keeping
    its shape, centred in it."""
    mark = Image.open(_MARKS / file).convert("L")
    x0, y0, x1, y1 = (v * p for v in box_mm)
    scale = min((x1 - x0) / mark.width, (y1 - y0) / mark.height)
    size = (max(1, round(mark.width * scale)), max(1, round(mark.height * scale)))
    mark = mark.resize(size, Image.Resampling.LANCZOS)
    at = (round((x0 + x1 - size[0]) / 2), round((y0 + y1 - size[1]) / 2))
    region = (*at, at[0] + size[0], at[1] + size[1])
    mask.paste(ImageChops.lighter(mask.crop(region), mark), at)


def generate_spine_texture(case_type: CaseType, width: int, height: int) -> Image.Image:
    """Generate a spine texture overlay for the given case type."""
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    texture = case_type.texture

    if case_type.layout == "jewel":
        _draw_jewel_spine(draw, case_type, width, height)
    elif texture == "dvd":
        _draw_dvd_spine(draw, width, height)
    elif texture == "bluray":
        _draw_bluray_spine(draw, width, height)
    elif texture == "cardboard":
        _draw_cardboard_spine(draw, width, height)
    elif texture in ("switch", "ds", "psp", "clamshell"):
        _draw_keepcase_spine(draw, width, height)

    return overlay


# --- DVD Case ---

def _draw_dvd_front(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """DVD case: border indent + subtle horizontal ridges."""
    # Border indent lines (~3% from edges)
    margin_x = int(w * 0.03)
    margin_y = int(h * 0.02)
    lw = max(1, w // 200)

    # Outer indent (shadow on outside, highlight on inside)
    _draw_indent_rect(draw, margin_x, margin_y,
                      w - margin_x, h - margin_y, lw)

    # Horizontal ridges near top and bottom (DVD latch area)
    ridge_y_top = int(h * 0.06)
    ridge_y_bot = int(h * 0.94)
    for ry in (ridge_y_top, ridge_y_bot):
        _draw_hline_emboss(draw, margin_x + lw, w - margin_x - lw, ry, lw)

    # Center hub circle indent (faint)
    cx, cy = w // 2, h // 2
    r = int(min(w, h) * 0.08)
    _draw_circle_indent(draw, cx, cy, r, lw)


def _draw_dvd_spine(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """DVD spine: vertical groove lines along edges."""
    lw = max(1, w // 10)
    # Left groove
    draw.line([(lw, 0), (lw, h)], fill=(0, 0, 0, 12), width=lw)
    draw.line([(lw + lw, 0), (lw + lw, h)], fill=(255, 255, 255, 8), width=lw)
    # Right groove
    draw.line([(w - lw * 2, 0), (w - lw * 2, h)], fill=(0, 0, 0, 12), width=lw)
    draw.line([(w - lw, 0), (w - lw, h)], fill=(255, 255, 255, 8), width=lw)


# --- Blu-ray Case ---

def _band_edge(case_type: CaseType, h: int) -> int | None:
    """RetroDB: the pixel row where a clear top strip ends, None for none."""
    if not case_type.top_band_mm:
        return None
    return round((case_type.rim_mm + case_type.top_band_mm) * h / case_type.height)


def _draw_bluray_front(draw: ImageDraw.ImageDraw, w: int, h: int,
                       ridge_y: int | None = None) -> None:
    """Blu-ray case: border indent + curved spine-edge groove. RetroDB:
    `ridge_y` moves the top ridge to where a clear top strip ends."""
    margin_x = int(w * 0.025)
    margin_y = int(h * 0.018)
    lw = max(1, w // 200)

    _draw_indent_rect(draw, margin_x, margin_y,
                      w - margin_x, h - margin_y, lw)

    # Spine-edge curved groove (left side, slight curve inward)
    groove_x = int(w * 0.04)
    for dy in range(0, h, max(1, h // 80)):
        curve = int(math.sin(dy / h * math.pi) * w * 0.005)
        x = groove_x + curve
        draw.line([(x, dy), (x, min(dy + max(1, h // 80), h))],
                  fill=(0, 0, 0, 10), width=lw)
        draw.line([(x + lw, dy), (x + lw, min(dy + max(1, h // 80), h))],
                  fill=(255, 255, 255, 6), width=lw)

    # Top latch ridge
    if ridge_y is None:
        ridge_y = int(h * 0.04)
    _draw_hline_emboss(draw, margin_x + lw, w - margin_x - lw, ridge_y, lw)


def _draw_bluray_spine(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Blu-ray spine: subtle vertical grooves."""
    lw = max(1, w // 8)
    draw.line([(lw, 0), (lw, h)], fill=(0, 0, 0, 10), width=lw)
    draw.line([(w - lw, 0), (w - lw, h)], fill=(255, 255, 255, 6), width=lw)


# --- CD Jewel Case ---

# Jewel case mouldings in mm, measured from the user's PAL Ridge Racer Type 4
# photos (2026-10-21) against its 120 mm booklet. Alphas judged by eye.
JEWEL_RIM_MM = 1.0          # the clear lid's edge, catching light all round
JEWEL_RIDGE_MM = 0.6        # each of the two lines where the lid meets the booklet
JEWEL_RIDGE_GAP_MM = 1.5    # between those two lines
JEWEL_CAP_MM = 3.0          # the tray's end caps over the hinge, top and bottom
_RIM_ALPHA = 70
_RIDGE_ALPHA = 55
_CLEAR_LINE_DARK = (0x30, 0x34, 0x3C)
_CLEAR_LINE_ALPHA = 130
_MARGIN_ALPHA = 110
# A PS1 lid's ribbed hinge strip, as in the downloaded Ridge Racer Type 4
# render the user chose (2026-10-21); sizes and alpha judged by eye.
JEWEL_RIB_MM = 0.4
JEWEL_RIB_PITCH_MM = 1.0
_RIB_ALPHA = 40
_CAP_ALPHA = 235
STREAK_ALPHA = 34           # the lid's diagonal reflection, at its centre line


def _draw_jewel_front(draw: ImageDraw.ImageDraw, case_type: CaseType,
                      w: int, h: int, ridges: bool = True) -> None:
    """Jewel case lid: a light rim round the outside, and two ridge lines
    down the hinge strip's booklet side, where the lid's hinge edge sits.
    The back has the rim only: the ridges mark where the lid opens."""
    p = w / case_type.width
    rim = max(1, round(JEWEL_RIM_MM * p))
    draw.rectangle([(0, 0), (w - 1, h - 1)], outline=(255, 255, 255, _RIM_ALPHA),
                   width=rim)
    if not ridges:
        return
    booklet_x = _booklet_x(case_type, p)
    # The clear lid's margin round the booklet, top, right and bottom, reads
    # lighter than the tray under it in the user's photo.
    lit = (255, 255, 255, _MARGIN_ALPHA)
    top = round((case_type.height - case_type.jewel.booklet[1]) / 2 * p)
    right = round(booklet_x + case_type.jewel.booklet[0] * p)
    x0 = round(booklet_x)
    draw.rectangle([(x0, rim), (w - 1 - rim, top - 1)], fill=lit)
    draw.rectangle([(x0, h - top), (w - 1 - rim, h - 1 - rim)], fill=lit)
    draw.rectangle([(right, top), (w - 1 - rim, h - top - 1)], fill=lit)
    ridge = max(1, round(JEWEL_RIDGE_MM * p))
    outer_ridge_x = booklet_x - ridge - JEWEL_RIDGE_GAP_MM * p
    if case_type.ridged_hinge_strip:
        # Vertical ribs across the strip, stopping a pitch short of the
        # outer ridge line so the two lines stay distinct.
        pitch = JEWEL_RIB_PITCH_MM * p
        rib = max(1, round(JEWEL_RIB_MM * p))
        x = rim + pitch / 2
        while x + rib <= outer_ridge_x - pitch:
            draw.rectangle([(round(x), rim), (round(x) + rib - 1, h - 1 - rim)],
                           fill=(255, 255, 255, _RIB_ALPHA))
            x += pitch
    # A clear lid's lines show dark over a white printed panel and light over
    # a black one; judged by eye against the user's references (2026-10-30).
    line = (255, 255, 255, _RIDGE_ALPHA)
    if case_type.tray_print is not None:
        light_paper = sum(case_type.tray_print.paper) > 3 * 128
        line = (*(_CLEAR_LINE_DARK if light_paper else (255, 255, 255)), _CLEAR_LINE_ALPHA)
    for x in (booklet_x - ridge, outer_ridge_x):
        draw.rectangle([(round(x), rim), (round(x) + ridge - 1, h - 1 - rim)], fill=line)


def _booklet_x(case_type: CaseType, p: float) -> float:
    """The booklet's left edge in px at `p` px/mm, as jewel_faces places it."""
    booklet_w, booklet_h = case_type.jewel.booklet
    margin = (case_type.height - booklet_h) / 2
    return (case_type.width - margin - booklet_w) * p


def _lid_streak(width: int, height: int) -> Image.Image:
    """A glossy lid's diagonal reflection: a soft white band along
    x/w + y/h = 0.7, STREAK_ALPHA at its centre line and gone 0.12 either
    side, so it misses both corners INV-11 reads."""
    x = np.arange(width, dtype=np.float32)[np.newaxis, :] / width
    y = np.arange(height, dtype=np.float32)[:, np.newaxis] / height
    falloff = np.maximum(0.0, 1.0 - np.abs(x + y - 0.7) / 0.12)
    streak = np.full((height, width, 4), 255, dtype=np.uint8)
    streak[:, :, 3] = np.round(STREAK_ALPHA * falloff).astype(np.uint8)
    return Image.fromarray(streak, "RGBA")


def generate_lid_shine(width: int, height: int) -> Image.Image:
    """A jewel case lid's soft shine: white, strongest at the top-left and
    gone past the diagonal. Alpha is SHINE_ALPHA * max(0, 1 - x/w - y/h)."""
    x = np.arange(width, dtype=np.float32)[np.newaxis, :] / width
    y = np.arange(height, dtype=np.float32)[:, np.newaxis] / height
    alpha = np.round(SHINE_ALPHA * np.maximum(0.0, 1.0 - x - y)).astype(np.uint8)
    shine = np.full((height, width, 4), 255, dtype=np.uint8)
    shine[:, :, 3] = alpha
    return Image.fromarray(shine, "RGBA")


def _draw_jewel_spine(draw: ImageDraw.ImageDraw, case_type: CaseType,
                      w: int, h: int) -> None:
    """Jewel case hinge side: the paper strip under clear plastic, with the
    tray's end caps over its top and bottom and a light lid edge on each
    long side."""
    p = h / case_type.height
    cap_h = max(2, round(JEWEL_CAP_MM * p))
    rim = max(1, round(JEWEL_RIM_MM * p))
    cap = (*(case_type.plastic or (0, 0, 0)), _CAP_ALPHA)
    for y in (0, h - cap_h):
        draw.rectangle([(0, y), (w - 1, y + cap_h - 1)], fill=cap)
    for x in (0, w - rim):
        draw.rectangle([(x, 0), (x + rim - 1, h - 1)], fill=(255, 255, 255, _RIM_ALPHA))


# A case's moulded text, measured from the user's PAL Ridge Racer Type 4
# photos (SLIP-0110): about 37 mm long, centred on the edge. Shades judged
# by eye at build.
MOULDED_TEXT_MM = 37
_MOULD_LIFT = 8         # letter face over the bare plastic
_MOULD_HIGHLIGHT = 40   # the letters' upper edges, catching the light
_MOULD_SHADOW = 12      # their lower edges


def generate_moulded_edge(case_type: CaseType, plastic: tuple[int, int, int],
                          width: int, height: int) -> Image.Image:
    """A top or bottom edge's picture: bare `plastic` with
    `case_type.moulded_logo` raised out of it, centred, as RGB.

    The text reads left to right, upright in the picture, on both edges, as
    on the real case: each edge seen from outside with the spine on the
    left. So one picture serves both.
    """
    p = width / case_type.width
    font = _get_font(max(4, round(height)), bold=False)
    left, top, right, bottom = font.getbbox(case_type.moulded_logo)
    size = max(4, round(font.size * MOULDED_TEXT_MM * p / max(1, right - left)))
    font = _get_font(size, bold=False)
    left, top, right, bottom = font.getbbox(case_type.moulded_logo)

    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).text(
        ((width - (right - left)) / 2 - left, (height - (bottom - top)) / 2 - top),
        case_type.moulded_logo, font=font, fill=255)
    m = np.asarray(mask, dtype=np.float32) / 255
    step = max(1, round(0.15 * p))
    above = np.zeros_like(m)
    above[step:] = m[:-step]
    below = np.zeros_like(m)
    below[:-step] = m[step:]
    shade = (_MOULD_LIFT * m + _MOULD_HIGHLIGHT * np.clip(m - above, 0, 1)
             - _MOULD_SHADOW * np.clip(m - below, 0, 1))
    pixels = np.asarray(plastic, dtype=np.float32) + shade[:, :, np.newaxis]
    return Image.fromarray(np.clip(np.round(pixels), 0, 255).astype(np.uint8), "RGB")


# A PAL Dreamcast tray's hinge strip, from photos of an empty case
# (SLIP-0112): raised text in a smooth, slightly recessed rounded panel,
# centred on the strip, on a stippled strip. Sizes estimated from one
# photo; alphas judged by eye.
STRIP_PANEL_MM = (40, 7)
STRIP_TEXT_MM = 30
_PANEL_EDGE = 50        # the panel's recessed rim, shadow above and light below
_STIPPLE = 8            # the strip's grain; under the steps a test reads as moulding


def _strip_logo(case_type: CaseType, w: int, h: int) -> Image.Image:
    """The front hinge strip's moulding as an RGBA overlay: stipple, the
    recessed panel and `case_type.strip_logo` raised in it, reading up the
    strip."""
    p = w / case_type.width
    strip_w = round(_booklet_x(case_type, p))
    rim = max(1, round(JEWEL_RIM_MM * p))
    rng = np.random.default_rng(0)
    grain = np.zeros((h, w, 4), dtype=np.uint8)
    grain[rim:h - rim, rim:strip_w, :3] = 255
    grain[rim:h - rim, rim:strip_w, 3] = rng.integers(
        0, _STIPPLE + 1, (h - 2 * rim, max(0, strip_w - rim)), dtype=np.uint8)
    out = Image.fromarray(grain, "RGBA")

    # The panel and its text, drawn lying down, then turned to run up the strip.
    pw, ph = round(STRIP_PANEL_MM[0] * p), round(STRIP_PANEL_MM[1] * p)
    panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(panel)
    edge = max(1, round(0.3 * p))
    d.rounded_rectangle([(0, 0), (pw - 1, ph - 1)], radius=ph // 3,
                        outline=(0, 0, 0, _PANEL_EDGE), width=edge)
    d.rounded_rectangle([(0, edge), (pw - 1, ph - 1)], radius=ph // 3,
                        outline=(255, 255, 255, _PANEL_EDGE // 2), width=edge)
    font = _get_font(max(4, ph), bold=False)
    left, top, right, bottom = font.getbbox(case_type.strip_logo)
    font = _get_font(max(4, round(font.size * STRIP_TEXT_MM * p / max(1, right - left))),
                     bold=False)
    left, top, right, bottom = font.getbbox(case_type.strip_logo)
    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).text(((pw - (right - left)) / 2 - left, (ph - (bottom - top)) / 2 - top),
                              case_type.strip_logo, font=font, fill=255)
    m = np.asarray(mask, dtype=np.float32) / 255
    step = max(1, round(0.15 * p))
    above = np.zeros_like(m)
    above[step:] = m[:-step]
    below = np.zeros_like(m)
    below[:-step] = m[step:]
    light = np.clip(_MOULD_HIGHLIGHT * 2 * np.clip(m - above, 0, 1) + 3 * _MOULD_LIFT * m, 0, 255)
    dark = np.clip(_MOULD_SHADOW * 3 * np.clip(m - below, 0, 1), 0, 255)
    letters = np.zeros((ph, pw, 4), dtype=np.uint8)
    lit = light >= dark
    letters[..., :3] = np.where(lit, 255, 0)[..., np.newaxis]
    letters[..., 3] = np.round(np.where(lit, light, dark)).astype(np.uint8)
    panel.alpha_composite(Image.fromarray(letters, "RGBA"))
    panel = panel.rotate(90, expand=True)
    out.alpha_composite(panel, (round((strip_w - panel.width) / 2), round((h - panel.height) / 2)))
    return out


# --- Small plastic keep cases (Switch, DS, 3DS, PSP, Vita) ---

def _draw_keepcase_spine(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Keep-case spine: a moulded groove along each edge."""
    lw = max(1, w // 10)
    draw.line([(lw, 0), (lw, h)], fill=(0, 0, 0, 12), width=lw)
    draw.line([(w - lw, 0), (w - lw, h)], fill=(255, 255, 255, 8), width=lw)


# --- Cartridge/Cardboard boxes ---

def _draw_cardboard_front(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Cardboard box: fold lines.

    No texture grain: the docstring promised it and the body never drew
    it (SLIP-0080). Whether the texture set should be richer is
    SLIP-0034's question, not a silent gap here.
    """
    lw = max(1, w // 200)

    # Top fold line
    fold_y = int(h * 0.02)
    _draw_hline_emboss(draw, 0, w, fold_y, lw)

    # Bottom fold line
    fold_y2 = int(h * 0.98)
    _draw_hline_emboss(draw, 0, w, fold_y2, lw)

    # Subtle vertical fold marks at edges
    fold_x = int(w * 0.015)
    draw.line([(fold_x, 0), (fold_x, h)], fill=(0, 0, 0, 8), width=lw)
    fold_x2 = int(w * 0.985)
    draw.line([(fold_x2, 0), (fold_x2, h)], fill=(0, 0, 0, 8), width=lw)


def _draw_cardboard_spine(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Cardboard spine: fold crease lines."""
    lw = max(1, w // 8)
    # Fold creases along both edges
    draw.line([(0, 0), (0, h)], fill=(0, 0, 0, 15), width=lw)
    draw.line([(w - 1, 0), (w - 1, h)], fill=(0, 0, 0, 15), width=lw)


# --- Switch Case ---

def _draw_switch_front(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Switch case: border indent + game card slot outline."""
    margin_x = int(w * 0.025)
    margin_y = int(h * 0.02)
    lw = max(1, w // 200)

    _draw_indent_rect(draw, margin_x, margin_y,
                      w - margin_x, h - margin_y, lw)

    # Game card slot (small rectangle, upper center)
    slot_w = int(w * 0.15)
    slot_h = int(h * 0.08)
    slot_x = (w - slot_w) // 2
    slot_y = int(h * 0.08)
    _draw_indent_rect(draw, slot_x, slot_y,
                      slot_x + slot_w, slot_y + slot_h, lw)


# --- DS / 3DS Case ---

def _draw_ds_front(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """DS/3DS case: border indent."""
    margin_x = int(w * 0.025)
    margin_y = int(h * 0.02)
    lw = max(1, w // 200)
    _draw_indent_rect(draw, margin_x, margin_y,
                      w - margin_x, h - margin_y, lw)

    # Latch ridge at top
    ridge_y = int(h * 0.05)
    _draw_hline_emboss(draw, margin_x, w - margin_x, ridge_y, lw)


# --- PSP / Vita ---

def _draw_psp_front(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """PSP/Vita case: border indent.

    No UMD or card slot is drawn; see SLIP-0080.
    """
    margin_x = int(w * 0.03)
    margin_y = int(h * 0.02)
    lw = max(1, w // 200)
    _draw_indent_rect(draw, margin_x, margin_y,
                      w - margin_x, h - margin_y, lw)


# --- Drawing primitives ---

def _draw_indent_rect(draw: ImageDraw.ImageDraw,
                      x1: int, y1: int, x2: int, y2: int,
                      lw: int) -> None:
    """Draw a rectangular indent (shadow on top-left, highlight on bottom-right)."""
    shadow = (0, 0, 0, 18)
    highlight = (255, 255, 255, 12)
    # Top and left edges (shadow - pressed in)
    draw.line([(x1, y1), (x2, y1)], fill=shadow, width=lw)
    draw.line([(x1, y1), (x1, y2)], fill=shadow, width=lw)
    # Bottom and right edges (highlight - raised lip)
    draw.line([(x1, y2), (x2, y2)], fill=highlight, width=lw)
    draw.line([(x2, y1), (x2, y2)], fill=highlight, width=lw)


def _draw_hline_emboss(draw: ImageDraw.ImageDraw,
                       x1: int, x2: int, y: int, lw: int) -> None:
    """Draw a horizontal embossed line (shadow + highlight pair)."""
    draw.line([(x1, y), (x2, y)], fill=(0, 0, 0, 15), width=lw)
    draw.line([(x1, y + lw), (x2, y + lw)], fill=(255, 255, 255, 10), width=lw)


def _draw_circle_indent(draw: ImageDraw.ImageDraw,
                        cx: int, cy: int, r: int, lw: int) -> None:
    """Draw a circular indent (ellipse with shadow/highlight effect)."""
    # Shadow arc (upper half)
    draw.arc([(cx - r, cy - r), (cx + r, cy + r)], 180, 360,
             fill=(0, 0, 0, 12), width=lw)
    # Highlight arc (lower half)
    draw.arc([(cx - r, cy - r), (cx + r, cy + r)], 0, 180,
             fill=(255, 255, 255, 8), width=lw)
