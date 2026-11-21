# Ported from Slipcase (MIT, the same author) core/box_model.py at a08a2a4 for
# PASS-59-326. Keep names and figures as Slipcase has them, so a fix there can
# be copied across; RetroDB changes are marked "RetroDB:".
"""The six faces of a game box, for the turnable 3D viewer and the box file.

build_box_model decides the faces the way BoxRenderer.render does, but keeps
them flat and unshaded: a viewer turns the box, so it applies the lighting
(SLIP-0104 § 4.2).
"""

from dataclasses import dataclass

from PIL import Image, ImageOps

from services.box3d.overlays import (
    generate_front_texture, generate_moulded_edge, generate_spine_texture,
)
from services.box3d.cases import CaseType
from services.box3d.image_ops import (
    case_edge_colours, inset_in_rim, is_full_cover, split_full_cover, upright_spine,
)
from services.box3d.jewel import DEFAULT_VIEW_ANGLE, jewel_faces
from services.box3d.spine import generate_spine

# Longest edge of any face picture. A 1600 x 1600 noise picture saves to
# about 6.7 MB, under RetroDB's 10 MB import limit (SLIP-0104 § 4.1).
# RetroDB: 1080, the size box_faces keeps, so no face is drawn larger than
# it is stored (PASS-59-326 §4.1).
FACE_MAX_EDGE = 1080


@dataclass
class BoxModel:
    """A box's real size, its plain-face colours and its pictured faces.

    Each picture shows its face from outside the box, standing upright, as
    RGB. The spine is on the front's left as seen from the front, and the
    edge on its right. `edge_face` is the edge's picture, which only a jewel
    case has; without it a viewer fills the edge with `edge`. `top_face`
    and `bottom_face` are the top and bottom's pictures, which only a case
    with moulded text has; without them a viewer fills those with `top` and
    `bottom`. The top's picture has the back at its top edge, the bottom's
    the front.
    """
    case_type: CaseType
    top: tuple[int, int, int]
    bottom: tuple[int, int, int]
    edge: tuple[int, int, int]
    front: Image.Image
    spine: Image.Image
    back: Image.Image | None
    edge_face: Image.Image | None = None
    top_face: Image.Image | None = None
    bottom_face: Image.Image | None = None


def _scaled(image: Image.Image, aspect: float) -> Image.Image:
    """`image` resized to width/height `aspect`, as large as the source allows
    on both axes and no larger than FACE_MAX_EDGE, as RGBA."""
    src_w, src_h = image.size
    h = max(1, int(min(src_h, src_w / aspect, FACE_MAX_EDGE, FACE_MAX_EDGE / aspect)))
    w = max(1, min(src_w, FACE_MAX_EDGE, round(h * aspect)))
    return image.convert("RGBA").resize((w, h), Image.Resampling.LANCZOS)


def _flatten(image: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    """`image` laid on an opaque `colour`, as RGB."""
    background = Image.new("RGBA", image.size, (*colour, 255))
    return Image.alpha_composite(background, image).convert("RGB")


def build_box_model(
    front_image: Image.Image,
    back_image: Image.Image | None,
    case_type: CaseType,
    *,
    title: str,
    serial: str,
    platform: str,
    spine_color: tuple[int, int, int] | None,
    case_color: tuple[int, int, int] | None,
    spine_left_offset: int,
    spine_right_offset: int,
    full_cover: bool | None,
    show_texture: bool,
    back_strips: bool | None = None,
    spine_image: Image.Image | None = None,
) -> BoxModel:
    """Build the faces from BoxRenderer.render's face inputs.

    A full cover is split with the same offsets render uses, and a loaded
    back cover wins over the split one. A loaded `spine_image` wins over
    the split spine; with neither, the spine is generated at the front
    height's scale. With `show_texture` set, each face
    carries the case overlay at its own size; the back carries the front
    overlay mirrored, as render's back view lays it.

    A jewel case takes its faces from jewel_faces, as render does, and its
    plain faces are its bare plastic, never sampled from the art.
    """
    if case_type.layout == "jewel":
        return _jewel_model(
            front_image, back_image, case_type, title=title, serial=serial,
            platform=platform, spine_color=spine_color, case_color=case_color,
            spine_left_offset=spine_left_offset,
            spine_right_offset=spine_right_offset, full_cover=full_cover,
            show_texture=show_texture, back_strips=back_strips,
            spine_image=spine_image,
        )
    split_spine = None
    if full_cover is None:
        full_cover = is_full_cover(front_image, case_type)
    if full_cover:
        split_back, split_spine, front_image = split_full_cover(
            front_image, case_type,
            left_offset=spine_left_offset, right_offset=spine_right_offset,
        )
        if back_image is None:
            back_image = split_back
    if spine_image is not None:
        split_spine = upright_spine(spine_image)

    top, bottom, edge = case_edge_colours(front_image, case_type, case_color)

    face_aspect = case_type.width / case_type.height
    front = _scaled(front_image, face_aspect)
    back = _scaled(back_image, face_aspect) if back_image is not None else None
    if split_spine is not None:
        spine = _scaled(split_spine, case_type.depth / case_type.height)
    else:
        h = front.size[1]
        spine = generate_spine(
            title=title or "Game",
            spine_width=max(round(case_type.depth * h / case_type.height), 4),
            spine_height=h,
            platform=platform,
            serial=serial,
            bg_color=spine_color,
        ).convert("RGBA")

    # Seen from behind, the opening side is on the left. A real lip casts its
    # own inner wall in the viewer, so none is painted (SLIP-0125 § 4.3).
    wall = case_type.shape is None or case_type.shape.lip_height == 0
    front = inset_in_rim(front, case_type, case_color, opening="right", wall=wall)
    spine = inset_in_rim(spine, case_type, case_color, opening=None, wall=wall)
    if back is not None:
        back = inset_in_rim(back, case_type, case_color, opening="left", wall=wall)

    if show_texture:
        front = Image.alpha_composite(
            front, generate_front_texture(case_type, *front.size))
        spine = Image.alpha_composite(
            spine, generate_spine_texture(case_type, *spine.size))
        if back is not None:
            back = Image.alpha_composite(
                back, ImageOps.mirror(generate_front_texture(case_type, *back.size, back=True)))

    return BoxModel(
        case_type=case_type, top=top, bottom=bottom, edge=edge,
        front=_flatten(front, edge),
        spine=_flatten(spine, edge),
        back=_flatten(back, edge) if back is not None else None,
    )


def _jewel_model(
    front_image: Image.Image,
    back_image: Image.Image | None,
    case_type: CaseType,
    *,
    case_color: tuple[int, int, int] | None,
    show_texture: bool,
    spine_image: Image.Image | None,
    **face_args,
) -> BoxModel:
    """build_box_model for a jewel case (SLIP-0106 § 4.5). A loaded
    `spine_image` replaces the hinge, as render does."""
    faces = jewel_faces(front_image, back_image, case_type,
                        view_angle=DEFAULT_VIEW_ANGLE, **face_args)
    plastic = case_color or case_type.plastic

    face_aspect = case_type.width / case_type.height
    side_aspect = case_type.depth / case_type.height
    front = _scaled(faces.front, face_aspect)
    back = _scaled(faces.back, face_aspect) if faces.back is not None else None
    hinge = upright_spine(spine_image) if spine_image is not None else faces.hinge
    spine = _scaled(hinge, side_aspect)
    edge_face = _scaled(faces.opening, side_aspect)
    del faces

    # The opening side gets no overlay. Moulded text is a case detail too.
    moulded = None
    if show_texture and case_type.moulded_logo:
        p = front.width / case_type.width
        moulded = generate_moulded_edge(
            case_type, plastic, front.width, max(1, round(case_type.depth * p)))
    if show_texture:
        front = Image.alpha_composite(
            front, generate_front_texture(case_type, *front.size))
        spine = Image.alpha_composite(
            spine, generate_spine_texture(case_type, *spine.size))
        if back is not None:
            back = Image.alpha_composite(
                back, ImageOps.mirror(generate_front_texture(case_type, *back.size, back=True)))

    return BoxModel(
        case_type=case_type, top=plastic, bottom=plastic, edge=plastic,
        front=_flatten(front, plastic),
        spine=_flatten(spine, plastic),
        back=_flatten(back, plastic) if back is not None else None,
        edge_face=_flatten(edge_face, plastic),
        top_face=moulded, bottom_face=moulded,
    )
