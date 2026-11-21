# Ported from Slipcase (MIT, the same author) core/jewel.py at a08a2a4 for
# PASS-59-326. Keep names and figures as Slipcase has them, so a fix there can
# be copied across; RetroDB changes are marked "RetroDB:".
"""A jewel case's faces, built from its booklet and back card (SLIP-0106 § 4.4).

A jewel case has no wrap. The front shows the booklet beside a strip of bare
tray plastic at the hinge. The back card is folded at both ends, so its
middle is the back and its two end strips show on the case's two sides.
BoxRenderer.render and build_box_model both build their faces here, so the
still render and the box file cannot differ.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw

from services.box3d.cases import CASE_TYPES, CaseType, TrayPrint, case_for
from services.box3d.image_ops import _fold_band_means, _nudge, is_full_cover, split_full_cover
from services.box3d.cases import NTSC_J, NTSC_U, PAL
from services.box3d.spine import _get_font, generate_spine

_log = logging.getLogger(__name__)

# Most pixels per mm a face is built at. LaunchBox's 1200 px at 2x
# supersampling needs about 15.5 px/mm on a PAL case at 30 degrees.
# RetroDB: 7.6, so a 142 mm jewel front is built about 1080 px wide, the
# size faces.FACE_MAX_EDGE keeps (PASS-59-326 §4.1).
JEWEL_PX_PER_MM_MAX = 7.6

# The widest end strip, as a share of its card's width: PAL PS1's.
_WIDEST_STRIP_SHARE = max(case.jewel.strip / case.jewel.back_card[0]
                          for case in CASE_TYPES.values() if case.layout == "jewel")


@dataclass
class JewelFaces:
    """A jewel case's pictured faces, each as seen from outside, upright."""
    front: Image.Image          # RGBA, case W x H: hinge strip + booklet
    back: Image.Image | None    # RGBA, case W x H: card middle on plastic
    hinge: Image.Image          # RGBA, case D x H: the spine on the front's left
    opening: Image.Image        # RGBA, case D x H: the side opposite


def back_has_strips(image: Image.Image, case_type: CaseType) -> bool:
    """Whether a back scan is the whole card, end strips included.

    The scan's width/height is compared with the card's ratio with strips
    and without them, relatively, and the nearer wins. A 15% band, as
    is_full_cover uses, cannot tell the standard card's two ratios apart:
    they are 8.7% apart.
    """
    card_w, card_h = case_type.jewel.back_card
    with_strips = card_w / card_h
    without = (card_w - 2 * case_type.jewel.strip) / card_h
    ratio = image.width / image.height
    return abs(ratio - with_strips) / with_strips < abs(ratio - without) / without


def _card_misfit(image: Image.Image, case_type: CaseType) -> float:
    """How far a back scan's width/height is from `case_type`'s card, with
    strips or without, whichever is nearer, relatively."""
    card_w, card_h = case_type.jewel.back_card
    ratio = image.width / image.height
    return min(abs(ratio - r) / r
               for r in (card_w / card_h, (card_w - 2 * case_type.jewel.strip) / card_h))


def card_case(image: Image.Image, platform: str, current: CaseType) -> CaseType:
    """`current`, or `platform`'s regional case whose back card fits the back
    scan `image` better than `current`'s does (SLIP-0111).

    A PAL PS1 card is wider than the standard card, so a PAL scan cut with
    the standard card's folds keeps most of each end strip on the back.
    Cases sharing `current`'s card fit equally and never replace it.
    """
    if current.layout != "jewel":
        return current
    candidates = [case for region in (NTSC_U, PAL, NTSC_J)
                  if (case := case_for(platform, region)) is not None
                  and case.layout == "jewel"]
    best = min(candidates, key=lambda case: _card_misfit(image, case), default=current)
    return best if _card_misfit(image, best) < _card_misfit(image, current) else current


def fold_reach(image: Image.Image) -> int:
    """How far, in px, the sliders may move a fold of the back scan `image`:
    the widest end strip any jewel card has, so a fold can cross a whole
    strip whichever case is shown (SLIP-0111)."""
    return max(40, math.ceil(image.width * _WIDEST_STRIP_SHARE))


def detect_strip_folds(image: Image.Image, case_type: CaseType) -> tuple[int, int]:
    """The x of a back card scan's two folds: the card's geometry, each fold
    then moved by the same edge search spine detection uses.

    No 85-115% width check: the folds bound the middle, not a spine.
    """
    w = image.width
    strip_px = round(w * case_type.jewel.strip / case_type.jewel.back_card[0])
    geo_left, geo_right = strip_px, w - strip_px
    try:
        band_means = _fold_band_means(image, strip_px)
        return (_nudge(band_means, geo_left, strip_px),
                _nudge(band_means, geo_right, strip_px))
    except (ValueError, IndexError) as e:
        _log.warning("fold refinement failed, using the geometric estimate: %s", e)
        return geo_left, geo_right


def split_back_card(
    image: Image.Image, case_type: CaseType,
    left_offset: int = 0, right_offset: int = 0,
    folds: tuple[int, int] | None = None,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """(left strip, middle, right strip) of a back card scan, as RGBA.

    The offsets move each fold, positive to the right. Each fold is then
    clamped to at least one pixel from either edge and from the other, so
    any scan at least 3 px wide and any offsets give three non-empty parts.
    `folds` is detect_strip_folds' result, if the caller already has it.
    """
    w, h = image.size
    left_x, right_x = folds or detect_strip_folds(image, case_type)
    left_x = max(1, min(left_x + left_offset, w - 2))
    right_x = max(left_x + 1, min(right_x + right_offset, w - 1))
    return (image.crop((0, 0, left_x, h)).convert("RGBA"),
            image.crop((left_x, 0, right_x, h)).convert("RGBA"),
            image.crop((right_x, 0, w, h)).convert("RGBA"))


def _on_plastic(image: Image.Image, size_mm: tuple[float, float],
                face_mm: tuple[float, float], p: float,
                plastic: tuple[int, int, int]) -> Image.Image:
    """`image` resized to `size_mm` and centred on a `face_mm` face of plastic."""
    face = Image.new("RGBA", (max(1, round(face_mm[0] * p)), max(1, round(face_mm[1] * p))),
                     (*plastic, 255))
    w, h = max(1, round(size_mm[0] * p)), max(1, round(size_mm[1] * p))
    face.alpha_composite(image.convert("RGBA").resize((w, h), Image.Resampling.LANCZOS),
                         ((face.width - w) // 2, (face.height - h) // 2))
    return face


# Dreamcast's swirl: its colour, and its size as a share of the font size.
# Judged by eye against the user's photos.
_SWIRL_COLOUR = (0xE8, 0x5A, 0x1E)
_SWIRL_SHARE = 0.75


def tray_print_panel(tray: TrayPrint, size_mm: tuple[float, float], p: float) -> Image.Image:
    """A clear tray's printed panel, `size_mm` across and down at `p` px/mm:
    `tray.paper` with `tray.text` in `tray.ink`, `tray.length` mm long and
    centred, running along the strip. A swirl goes after the first word.
    `tray.ribs` adds a band of printed ribs. `tray.across` places the text."""
    w, h = max(1, round(size_mm[0] * p)), max(1, round(size_mm[1] * p))
    panel = Image.new("RGBA", (w, h), (*tray.paper, 255))
    if tray.ribs is not None:
        panel = _printed_ribs(panel, tray, p)
    if not tray.text:
        return panel
    words = tray.text.split(" ", 1) if tray.swirl else [tray.text]

    def widths(font):
        space = font.getlength(" ")
        swirl = font.size * _SWIRL_SHARE + space if tray.swirl else 0
        return [font.getlength(word) for word in words], swirl

    # Size the font at 100 px, then scale it to the length.
    word_w, swirl_w = widths(_get_font(100, bold=False))
    font = _get_font(max(4, round(100 * tray.length * p / (sum(word_w) + swirl_w))), bold=False)
    word_w, swirl_w = widths(font)

    # Drawn lying down, then turned to run along the strip.
    lying = Image.new("RGBA", (h, w), (0, 0, 0, 0))
    draw = ImageDraw.Draw(lying)
    x = (h - sum(word_w) - swirl_w) / 2
    across = w / 2 if tray.across is None else tray.across * p
    y = across if tray.reads_up else w - across
    draw.text((x, y), words[0], font=font, fill=(*tray.ink, 255), anchor="lm")
    if tray.swirl:
        radius = font.size * _SWIRL_SHARE / 2
        cx = x + word_w[0] + swirl_w / 2
        turns = 2.5
        points = []
        for i in range(81):
            t = i / 80
            angle = t * turns * 2 * math.pi
            r = radius * (1 - 0.8 * t)
            points.append((cx + r * math.cos(angle), y + r * math.sin(angle)))
        draw.line(points, fill=(*_SWIRL_COLOUR, 255), width=max(1, round(radius / 4)))
        draw.text((x + word_w[0] + swirl_w, y), words[1], font=font,
                  fill=(*tray.ink, 255), anchor="lm")

    panel.alpha_composite(lying.rotate(90 if tray.reads_up else -90, expand=True))
    return panel


# The ribs printed on a US PS1 back card's inside (Crash Bandicoot's scan):
# dark oval lobes down a grey band that fades to black. Lobe pitch measured
# from the scan; lobe size and strength judged by eye.
_RIB_PITCH = 6.8      # mm
_RIB_LOBE_HEIGHT = 0.27  # share of the pitch, each side of the lobe's centre


def _printed_ribs(panel: Image.Image, tray: TrayPrint, p: float) -> Image.Image:
    """`panel` with `tray.ribs`' band printed across it."""
    a, b = tray.ribs
    x = (np.arange(panel.width) + 0.5)[None, :] / p
    y = (np.arange(panel.height) + 0.5)[:, None] / p
    t = (x - a) / (b - a)
    shade = np.where((t >= 0) & (t <= 1), np.clip(1 - t, 0, 1) ** 1.3, 0.0)
    across = (x - (a + 0.55 * (b - a))) / (0.5 * (b - a) + 0.5)
    down = ((y % _RIB_PITCH) - _RIB_PITCH / 2) / (_RIB_LOBE_HEIGHT * _RIB_PITCH)
    lobe = np.clip((1.2 - across ** 2 - down ** 2) / 0.4, 0, 1)
    shade = shade * (1 - 0.9 * lobe)
    paper, ink = np.array(tray.paper, float), np.array(tray.ink, float)
    rgb = paper + (ink - paper) * shade[..., None]
    out = Image.fromarray(np.round(rgb).astype(np.uint8), "RGB").convert("RGBA")
    out.putalpha(panel.getchannel("A"))
    return out


# A clear tray's front hinge strip is a window into a hollow compartment, with
# the back card's paper flat against its far wall (the user's drawing and
# comments, 2026-10-30). A case's true depth read as "just a little bit in",
# so the depth is deepened; this and all the shading are judged by eye.
_WINDOW_DEPTH_SCALE = 1.3
# A box file's front is one flat picture, so its window is drawn from here.
DEFAULT_VIEW_ANGLE = 30.0
_FLOOR_SHARE = 0.35           # the floor's height, as a share of the depth
_BEHIND_DIM = 0.97
_CORNER_SHADOW = (3.0, 0.5)   # mm wide, darkest multiplier where the paper meets a wall
_WALL_DARK = 0.5              # the inner wall's multiplier at the back card
_FLOOR_DARK = 0.65            # the floor's; it catches more light


def _through_window(panel: Image.Image, tray: TrayPrint, depth: float, angle: float,
                    p: float) -> Image.Image:
    """The compartment behind the window, its far wall carrying `panel`,
    `depth` mm back and seen at `angle` degrees from the spine's side and
    from above. The paper slides towards the spine and up; the inner wall by
    the booklet and the floor fill the room it leaves, meeting in a mitre."""
    w, h = panel.size
    wall_w = min(w, round(depth * math.tan(math.radians(angle)) * p))
    floor_h = min(h, round(depth * _FLOOR_SHARE * p))
    far_w, far_h = w - wall_w, h - floor_h

    x = (np.arange(w) + 0.5)[None, :]
    y = (np.arange(h) + 0.5)[:, None]
    along_wall = np.clip((x - far_w) / max(wall_w, 1), 0, 1)    # 0 at the paper, 1 at the lid
    along_floor = np.clip((y - far_h) / max(floor_h, 1), 0, 1)
    on_floor = (along_floor > along_wall) & (along_floor > 0)
    on_wall = (along_wall > 0) & ~on_floor

    colour = np.array(tray.wall, dtype=float)
    rgb = np.empty((h, w, 3))
    rgb[on_wall] = colour * (_WALL_DARK + (1 - _WALL_DARK) * np.broadcast_to(
        along_wall, (h, w))[on_wall])[:, None]
    rgb[on_floor] = colour * (_FLOOR_DARK + (1 - _FLOOR_DARK) * np.broadcast_to(
        along_floor, (h, w))[on_floor])[:, None]

    # The paper, flat on the far wall, darkest in the corners it makes.
    shadow_w, shadow_dark = _CORNER_SHADOW
    to_corner = np.minimum.reduce(
        np.broadcast_arrays(x / p, y / p, (far_w - x) / p, (far_h - y) / p))
    light = _BEHIND_DIM * (shadow_dark + (1 - shadow_dark) * np.clip(to_corner / shadow_w, 0, 1))
    paper = np.asarray(panel.convert("RGB"), dtype=float)[floor_h:, wall_w:]
    far = ~(on_wall | on_floor)
    rgb[far] = (paper * light[:far_h, :far_w, None]).reshape(-1, 3)
    return Image.fromarray(np.round(rgb).astype(np.uint8), "RGB").convert("RGBA")


def jewel_faces(
    front_image: Image.Image,
    back_image: Image.Image | None,
    case_type: CaseType,
    *,
    title: str,
    serial: str,
    platform: str,
    spine_color: tuple[int, int, int] | None,
    spine_left_offset: int,
    spine_right_offset: int,
    full_cover: bool | None,
    back_strips: bool | None,
    view_angle: float = DEFAULT_VIEW_ANGLE,
) -> JewelFaces:
    """Build a jewel case's faces from the loaded front and back.

    `full_cover` says whether the front is a wrap (None detects it), and
    `back_strips` whether the back is the whole card (None detects it). The
    offsets move the wrap's spine bounds when the front is a wrap, and the
    back card's folds otherwise. Each face takes the first source it has:
    back from the card's middle, else the wrap's back; hinge from the card's
    right strip, else the wrap's spine, else a generated spine; opening from
    the card's left strip, else a generated spine. A scan is seen from
    behind, where the hinge is on the right, so its right strip is the hinge.
    `view_angle` is the render's, for what a clear tray's window shows.
    """
    jewel = case_type.jewel
    plastic = case_type.plastic or (0, 0, 0)
    W, H, D = case_type.width, case_type.height, case_type.depth
    card_w, card_h = jewel.back_card
    middle_mm = (card_w - 2 * jewel.strip, card_h)
    strip_mm = (jewel.strip, card_h)

    wrap_back = wrap_spine = None
    booklet = front_image
    if full_cover is None:
        full_cover = is_full_cover(front_image, case_type)
    if full_cover:
        wrap_back, wrap_spine, booklet = split_full_cover(
            front_image, case_type,
            left_offset=spine_left_offset, right_offset=spine_right_offset,
        )

    booklet_w, booklet_h = jewel.booklet
    p = min(booklet.height / booklet_h, JEWEL_PX_PER_MM_MAX)

    # Front: the booklet with equal top, bottom and right margins; the strip
    # left of it is the hinge strip, bare tray seen through the lid.
    front = Image.new("RGBA", (max(1, round(W * p)), max(1, round(H * p))), (*plastic, 255))
    margin = (H - booklet_h) / 2
    front.alpha_composite(
        booklet.convert("RGBA").resize(
            (max(1, round(booklet_w * p)), max(1, round(booklet_h * p))),
            Image.Resampling.LANCZOS),
        (round((W - margin - booklet_w) * p), round(margin * p)),
    )

    left_strip = right_strip = middle = None
    if back_image is not None:
        if back_strips is None:
            back_strips = back_has_strips(back_image, case_type)
        # Three parts need three pixels.
        if back_strips and back_image.width >= 3:
            # With a wrap loaded the sliders belong to the wrap.
            offsets = (0, 0) if full_cover else (spine_left_offset, spine_right_offset)
            left_strip, middle, right_strip = split_back_card(
                back_image, case_type, left_offset=offsets[0], right_offset=offsets[1])
        else:
            middle = back_image

    def generated() -> Image.Image:
        return generate_spine(
            title=title or "Game",
            spine_width=max(round(D * p), 4),
            spine_height=front.height,
            platform=platform,
            serial=serial,
            bg_color=spine_color,
        ).convert("RGBA")

    back_src = middle if middle is not None else wrap_back
    hinge_src = right_strip if right_strip is not None else wrap_spine
    if case_type.tray_print is not None:
        # A clear tray shows the back card's printed panel through the
        # front's hinge strip. Scans do not carry it, so it is drawn.
        panel = tray_print_panel(case_type.tray_print, (W - margin - booklet_w, card_h), p)
        front.alpha_composite(
            _through_window(panel, case_type.tray_print, D * _WINDOW_DEPTH_SCALE, view_angle, p),
            (0, round((H - card_h) / 2 * p)),
        )
    return JewelFaces(
        front=front,
        back=_on_plastic(back_src, middle_mm, (W, H), p, plastic)
        if back_src is not None else None,
        hinge=_on_plastic(hinge_src, strip_mm, (D, H), p, plastic)
        if hinge_src is not None else generated(),
        opening=_on_plastic(left_strip, strip_mm, (D, H), p, plastic)
        if left_strip is not None else generated(),
    )
