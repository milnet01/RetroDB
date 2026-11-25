/**
 * PASS-59-143, PASS-59-231 — the turnable 3D box in the cover zoom.
 *
 * A game with Slipcase faces (PASS-59-142, services/box_faces.py::faces_for)
 * zooms to a box drawn with WebGL instead of a flat picture. The faces are
 * shown as imported: the case details are already in them, so only lighting
 * is added here. Nothing is painted around the box. A face without a
 * picture is filled with its colour from the record.
 *
 * A record with a `shape` (Slipcase SLIP-0125 § 4.1) draws the case's real
 * shape: rounded corners and edges, the raised lip, the seam and the finger
 * recess. boxPatches below is Slipcase's core/box_shape.py::box_patches,
 * step for step, so both apps draw the same solid. The solid is concave;
 * the depth buffer decides what hides what, so no patch is sorted.
 *
 * No WebGL2 → show() returns false and the zoom shows the picture.
 *
 * Controls: drag turns (pitch held to -89..89 degrees), the wheel and + / -
 * zoom, the arrow keys turn, Home and a double-click reset, O opens.
 *
 * Opening (PASS-59-325). The case name picks one of three kinds. A keep case
 * or clamshell opens like a book: the shell is cut at the seam and the front
 * half turns on the spine. A jewel case is cut just under its lid. A cardboard
 * carton swings its top flap back and lifts what it holds. Inside, built here
 * from simple solids: a disc on its hub with a ridge round it, or a cartridge
 * or card in its holder; the manual under two clips in the lid, or with no
 * manual a PS2 case's memory-card holder. A GameCube case has its own tray,
 * holder, mouldings and latch hole (gamecubeBase, gamecubeLatch), and a
 * two-disc flap when the record's `discs` says so. A PS5 case has its own
 * ring, hub, booklet clips and rails, and edge marks (ps5Base, ps5Lid, ps5Edges). Pictures come from the game's box scans
 * (services/box_scans.py::scans_for): the first `media` scan on the disc or
 * cartridge, the first `manual` on the booklet, the first `inside` as the
 * paper inside (a wide scan spread over both halves). The inside of the shell
 * is drawn in the case's plastic, cardboard for a carton.
 *
 * Cost: it draws only when something changes, the opening runs frames only
 * while it moves, the scans load the first time the box opens, and the canvas
 * stops at twice the screen's pixel size.
 *
 * Contract: Slipcase docs/specs/SLIP-0104-turnable-3d-box.md § 4.1 (format,
 * orientation), § 4.5 (lighting, controls), INV-11, INV-12;
 * SLIP-0125-keep-case-shape.md § 4.1 (shape), § 4.4 (drawing it).
 */
(function () {
    'use strict';

    const START_YAW = 30;       // turned to show the spine
    const START_PITCH = 10;     // seen a little from above, as in § 4.5
    const PITCH_LIMIT = 89;
    const ZOOM_MIN = 0.5;
    const ZOOM_MAX = 3;
    const KEY_STEP = 10;        // degrees per arrow press
    const DRAG_SLOP = 3;        // px a press may move and still count as a click
    const MAX_DPR = 2;          // canvas pixels per CSS pixel, at most
    const OPEN_MS = 700;

    // Brightness = 0.45 + 0.55 × max(0, normal · light), § 4.5. The light is
    // in view space (y up, z towards the viewer): upper left, in front.
    const AMBIENT = 0.45;
    const DIFFUSE = 0.55;
    const LIGHT = unit([-0.35, 0.5, 1]);
    // RetroDB adds to § 4.5 for bare plastic only (PASS-59-325): a soft shine,
    // so rounded edges and the lips beside the seam catch the light, and a
    // shadow in the seam's groove. Without them a dark case's seam is lost.
    const SHEEN = 0.18;
    const SHININESS = 20;
    const GROOVE = 0.35;        // the groove's colour, as a share of the plastic's

    // --- The solid (Slipcase core/box_shape.py) ----------------------------
    // Millimetres, the box centred on the origin: x across the front, y up,
    // z out of the front. The spine is x = -width/2, the opening side
    // x = +width/2. Every patch is wound clockwise seen from outside.

    const CORNER_SEGMENTS = 8;
    const EDGE_SEGMENTS = 3;
    const RECESS_SEGMENTS = 4;  // per rounded corner of the slot's ends
    const SAME_MM = 1e-9;
    const FULL_PICTURE = [[0, 0], [1, 0], [1, 1], [0, 1]];
    const FACE_NORMALS = {
        front: [0, 0, 1], back: [0, 0, -1], spine: [-1, 0, 0],
        edge: [1, 0, 0], top: [0, 1, 0], bottom: [0, -1, 0],
    };

    function unit(v) {
        const len = Math.hypot(...v);
        return v.map(c => c / len);
    }
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    const same = (a, b) => Math.max(...a.map((x, i) => Math.abs(x - b[i]))) <= SAME_MM;
    const argmax = (names, score) => names.reduce((best, n) => (score(n) > score(best) ? n : best));

    // Each face's corners seen from outside: top left, top right, bottom
    // right, bottom left of its picture.
    function faceCorners(c) {
        const w = c.width_mm / 2, h = c.height_mm / 2, d = c.depth_mm / 2;
        return {
            front: [[-w, h, d], [w, h, d], [w, -h, d], [-w, -h, d]],
            back: [[w, h, -d], [-w, h, -d], [-w, -h, -d], [w, -h, -d]],
            spine: [[-w, h, -d], [-w, h, d], [-w, -h, d], [-w, -h, -d]],
            edge: [[w, h, d], [w, h, -d], [w, -h, -d], [w, -h, d]],
            top: [[-w, h, -d], [w, h, -d], [w, h, d], [-w, h, d]],
            bottom: [[-w, -h, d], [w, -h, d], [w, -h, -d], [-w, -h, -d]],
        };
    }

    // Outward unit normal by Newell's method; [0, 0, 0] for no area.
    function patchNormal(corners) {
        let nx = 0, ny = 0, nz = 0;
        corners.forEach(([x0, y0, z0], i) => {
            const [x1, y1, z1] = corners[(i + 1) % corners.length];
            nx += (y0 - y1) * (z0 + z1);
            ny += (z0 - z1) * (x0 + x1);
            nz += (x0 - x1) * (y0 + y1);
        });
        const len = Math.hypot(nx, ny, nz);
        // Newell's normal follows the right-hand rule; these patches run clockwise.
        return len < SAME_MM ? [0, 0, 0] : [-nx / len, -ny / len, -nz / len];
    }

    // The plain colour for a patch: its face's, else its side's.
    function plainColour(face, normal) {
        if (face === null) {
            face = argmax(['edge', 'top', 'bottom', 'spine'], f => dot(normal, FACE_NORMALS[f]));
        }
        return face === 'top' || face === 'bottom' ? face : 'edge';
    }

    // Each corner's place in `face`'s picture, straight below it on the
    // face's plane, held to the picture.
    function source(face, corners, faces) {
        const [tl, tr, , bl] = faces[face];
        const across = sub(tr, tl), down = sub(bl, tl);
        const clamp = x => Math.min(1, Math.max(0, x));
        return corners.map(p => {
            const rel = sub(p, tl);
            return [clamp(dot(rel, across) / dot(across, across)),
                clamp(dot(rel, down) / dot(down, down))];
        });
    }

    const hasRecess = s => s.recess_length_mm > 0 && s.recess_height_mm > 0 && s.recess_depth_mm > 0;
    // A record stored before PASS-59-252 has neither key: half-round ends,
    // the slot in the middle of the side.
    const recessEndRadius = s => s.recess_end_radius_mm ?? s.recess_height_mm / 2;
    const recessOffset = s => s.recess_offset_mm ?? 0;

    // The rings, front sheet to back sheet, `d` being half the depth. Each
    // ring: [[inset, height, inset on the opening side where it differs] on
    // the lip sides, [inset, height] on the spine side, how far the finger recess's cut reaches each way from the middle
    // at that height, or null where the ring runs above or below the slot].
    function profiles(s, d) {
        const r = s.edge_radius_mm, sw = s.seam_width_mm;
        const lip = s.lip_height_mm > 0;
        const t = lip ? s.lip_height_mm : 0;
        const front = [];
        if (lip) {
            // The lip's inner wall, bottom then top; on the spine side the
            // sheet runs straight to the rounding, so these sit where it starts.
            // A record stored before PASS-59-329 has no lip_side_width_mm.
            const side = s.lip_side_width_mm || s.lip_width_mm;
            front.push([[s.lip_width_mm, d - t, side], [r, d - t]]);
            front.push([[s.lip_width_mm, d, side], [r, d - t]]);
        }
        const steps = r > 0 ? EDGE_SEGMENTS : 0;
        for (let k = steps; k >= 0; k--) {
            const theta = steps ? Math.PI / 2 * k / steps : 0;
            const inset = k !== steps ? r * (1 - Math.cos(theta)) : r;
            const rise = k !== steps ? r * Math.sin(theta) : r;
            front.push([[inset, d - r + rise], [inset, d - t - r + rise]]);
        }
        const back = front.slice().reverse().map(([[li, lz, lx], [si, sz]]) => [[li, -lz, lx], [si, -sz]]);
        // The straight run between the two roundings: the seam, and the slot.
        const seam = sw > 0 ? [[[0, sw / 2], [0, sw / 2]], [[s.seam_depth_mm, 0], [0, 0]],
            [[0, -sw / 2], [0, -sw / 2]]] : [];
        let straight;
        if (!hasRecess(s)) {
            straight = seam.map(([lipSide, spineSide]) => [lipSide, spineSide, null]);
        } else {
            const end = s.recess_height_mm / 2, rho = recessEndRadius(s);
            const flat = end - rho;     // the slot's ends run straight up to here each way
            const reach = z => {
                const past = Math.max(0, Math.abs(z) - flat);
                return s.recess_length_mm / 2 - rho + Math.sqrt(Math.max(0, rho * rho - past * past));
            };
            // Rings round each end's two rounded corners, top then bottom; a
            // square end needs only its top and bottom rings.
            const quarter = [];
            for (let j = 0; j <= RECESS_SEGMENTS; j++) {
                quarter.push(flat + rho * Math.cos(Math.PI / 2 * j / RECESS_SEGMENTS));
            }
            const levels = [];
            for (const z of quarter.concat(quarter.slice().reverse().map(q => -q))) {
                if (!levels.length || levels[levels.length - 1] - z > SAME_MM) levels.push(z);
            }
            // Levels inside the seam would cut its V; the seam's own rings stand in.
            const cut = levels.filter(z => sw === 0 || Math.abs(z) > sw / 2 + SAME_MM)
                .map(z => [[0, z], [0, z]]);
            const inside = cut.concat(seam).sort((a, b) => b[0][1] - a[0][1]);
            straight = [[[0, end], [0, end], null]]
                .concat(inside.map(([lipSide, spineSide]) => [lipSide, spineSide, reach(lipSide[1])]),
                    [[[0, -end], [0, -end], null]]);
        }
        const plainRing = ([lipSide, spineSide]) => [lipSide, spineSide, null];
        return front.map(plainRing).concat(straight, back.map(plainRing));
    }

    // cos and sin of the j-th step through a quarter turn, exact at both ends.
    function arc(j) {
        if (j === 0) return [1, 0];
        if (j === CORNER_SEGMENTS) return [0, 1];
        const a = Math.PI / 2 * j / CORNER_SEGMENTS;
        return [Math.cos(a), Math.sin(a)];
    }

    // One ring, anticlockwise seen from the front, starting at the top of
    // the opening side; with a recess, its four points close the ring.
    function ring(c, s, [lipSide, spineSide, reach]) {
        const w = c.width_mm / 2, h = c.height_mm / 2, radius = s.corner_radius_mm;
        const points = [];
        // [x sign, y sign, does the arc run from the x side to the y side?]
        for (const [sx, sy, xFirst] of [[1, 1, true], [-1, 1, false], [-1, -1, true], [1, -1, false]]) {
            const [ix, zx] = sx < 0 ? spineSide : [lipSide[2] ?? lipSide[0], lipSide[1]];
            const [iy, zy] = lipSide;
            const cx = sx * (w - Math.max(radius, ix));
            const cy = sy * (h - Math.max(radius, iy));
            const rx = Math.max(0, radius - ix), ry = Math.max(0, radius - iy);
            for (let j = 0; j <= CORNER_SEGMENTS; j++) {
                const [co, si] = arc(xFirst ? j : CORNER_SEGMENTS - j);
                // co is 1 on the x side and 0 on the y side; co*co eases between.
                const z = zx === zy ? zx : zx * co * co + zy * (1 - co * co);
                points.push([cx + sx * rx * co, cy + sy * ry * si, z]);
            }
        }
        if (hasRecess(s)) {
            const x = w - (lipSide[2] ?? lipSide[0]), z = lipSide[1];
            let floor = x - s.recess_depth_mm;
            if (reach === null) {
                // Uncut: the points sit where the slot's straight edges end.
                reach = s.recess_length_mm / 2 - recessEndRadius(s);
                floor = x;
            }
            const mid = recessOffset(s);
            points.push([x, mid - reach, z], [floor, mid - reach, z],
                [floor, mid + reach, z], [x, mid + reach, z]);
        }
        return points;
    }

    // `corners` without a corner repeating the one before it.
    function clean(corners) {
        const kept = [];
        for (const p of corners) {
            if (!kept.length || !same(p, kept[kept.length - 1])) kept.push(p);
        }
        while (kept.length > 1 && same(kept[0], kept[kept.length - 1])) kept.pop();
        return kept;
    }

    // The patches to draw: six faces for a flat box, else the shaped surface.
    // Each is {corners, face (or null), source (or null), colour}.
    function boxPatches(c, s) {
        const faces = faceCorners(c);
        if (!s) {
            return Object.entries(faces).map(([face, corners]) => (
                {corners, face, source: FULL_PICTURE, colour: plainColour(face, [0, 0, 0])}));
        }
        const prof = profiles(s, c.depth_mm / 2);
        const rings = prof.map(p => ring(c, s, p));
        const n = rings[0].length;
        // The lips' inner walls and the seam's two faces show plain plastic,
        // but on the spine side, where the seam runs flat, the picture.
        const last = rings.length - 2;
        const plain = s.lip_height_mm > 0 ? new Set([0, last]) : new Set();
        let seam = new Set();
        if (s.seam_width_mm > 0) {
            const middle = prof.findIndex(([[li, lz]]) => li === s.seam_depth_mm && lz === 0);
            seam = new Set([middle - 1, middle]);
        }
        // The recess's walls and floor: the three quads between its four points.
        const recessQuads = hasRecess(s) ? new Set([n - 4, n - 3, n - 2]) : new Set();

        const pieces = [[rings[0].slice().reverse(), 'face']];
        for (let band = 0; band < rings.length - 1; band++) {
            const a = rings[band], b = rings[band + 1];
            const inRecess = prof[band][2] !== null || prof[band + 1][2] !== null;
            for (let k = 0; k < n; k++) {
                const quad = [a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]];
                let kind = 'face';
                if (plain.has(band) || (inRecess && recessQuads.has(k))) kind = 'plain';
                else if (seam.has(band)) kind = 'seam';
                pieces.push([quad, kind]);
            }
        }
        pieces.push([rings[rings.length - 1], 'face']);

        const patches = [];
        for (const [raw, kind] of pieces) {
            const corners = clean(raw);
            if (corners.length < 3) continue;
            const normal = patchNormal(corners);
            let face = null;
            if (kind !== 'plain' && normal.some(x => x !== 0)) {
                face = argmax(Object.keys(FACE_NORMALS), f => dot(normal, FACE_NORMALS[f]));
                if (kind === 'seam' && dot(normal, FACE_NORMALS[face]) < 1 - SAME_MM) face = null;
            }
            patches.push({corners, face, source: face !== null ? source(face, corners, faces) : null,
                colour: plainColour(face, normal)});
        }
        return patches;
    }

    // --- Opening (PASS-59-325) -----------------------------------------------
    // Every patch below is {corners, uv, tex, colour, inner, part, slide}:
    // `part` is 'base' (stays), 'lid' (turns on the hinge) or 'slide' (rises
    // `slide` mm as a carton opens); `inner` is the colour of its back side.

    const JEWEL_LID_MM = 3;     // a jewel case's lid, cut this far under the front
    const PAPER_MM = 0.4;       // paper and parts sit this far off the plastic
    const SILVER = [0.80, 0.82, 0.85];
    const CARDBOARD = [0.72, 0.66, 0.56];
    const CARTRIDGE = [0.12, 0.12, 0.13];   // a cartridge's bare plastic
    const DISC_CASES = /PS[2-5]|DVD|Blu-ray|Xbox|Wii|GameCube|Jewel|Long Box/;
    // Cards and small cartridges held in a keep case: [name, width, height, thickness] in mm.
    const CARDS = [[/Switch/, 21, 31, 3.3], [/3DS|DS Case/, 35, 33, 3.8], [/Vita/, 22, 30, 2],
        [/PSP/, 64, 65, 4.2], [/HuCard/, 54, 85, 1]];
    // Cartridges held by a clip at each end, not walled round: [name, long
    // side, short side, thickness] in mm. Its scan's shape says which way it
    // lies: on its side in a PAL case, across in others. The Mega Drive's:
    // ConsoleMods' "Dimensions for Game Cartridges" gives 109 x 70 x 17 mm,
    // one mould for Genesis and PAL; the user's ruler read 108 x 70 (2026-11-21).
    const CLIPPED_CARTRIDGES = [[/Genesis Clamshell/, 109, 70, 17]];

    function caseKind(name) {
        const n = String(name || '');
        if (/Jewel/.test(n)) return 'jewel';
        if (/Cartridge Box|Game Boy Box|GBA Box|Game Gear Box|Atari 2600 Box/.test(n)) return 'carton';
        return 'keep';
    }

    // Where the shell is cut and what turns: a book's lid on the spine (axis
    // y), a carton's flap on its top back edge (axis x). `max` is in degrees.
    function hingeOf(kind, c) {
        const w = c.width_mm / 2, h = c.height_mm / 2, d = c.depth_mm / 2;
        if (kind === 'carton') return {axis: 'x', pivot: [0, h, -d], at: h, max: 115};
        const at = kind === 'jewel' ? d - JEWEL_LID_MM : 0;
        return {axis: 'y', pivot: [-w, 0, at], at, max: 170};
    }

    // The part of a patch where side(p) >= 0, its picture places carried
    // along; null where none of it is.
    function clipPatch(p, side) {
        const corners = [], uv = [], n = p.corners.length;
        const uvOf = i => (p.uv ? p.uv[i] : [0, 0]);
        for (let i = 0; i < n; i++) {
            const j = (i + 1) % n, a = side(p.corners[i]), b = side(p.corners[j]);
            if (a >= 0) { corners.push(p.corners[i]); uv.push(uvOf(i)); }
            if ((a > 0 && b < 0) || (a < 0 && b > 0)) {
                const t = a / (a - b), mix = (x, y) => x.map((v, k) => v + (y[k] - v) * t);
                corners.push(mix(p.corners[i], p.corners[j]));
                uv.push(mix(uvOf(i), uvOf(j)));
            }
        }
        if (corners.length < 3 || patchNormal(corners).every(x => x === 0)) return null;
        return {...p, corners, uv: p.uv ? uv : null};
    }

    // The closed shell's patches, each given to the base or the lid.
    function splitShell(patches, hinge) {
        const out = [];
        for (const p of patches) {
            if (hinge.axis === 'x') {
                const top = p.corners.every(q => q[1] >= hinge.at - SAME_MM);
                out.push({...p, part: top ? 'lid' : 'base'});
                continue;
            }
            for (const [part, sign] of [['lid', 1], ['base', -1]]) {
                const piece = clipPatch(p, q => sign * (q[2] - hinge.at));
                if (piece) out.push({...piece, part});
            }
        }
        return out;
    }

    function part(corners, outward, name, colour, tex = null, uv = null, slide = 0) {
        if (dot(patchNormal(corners), outward) < 0) {
            corners = corners.slice().reverse();
            uv = uv && uv.slice().reverse();
        }
        return {corners, uv, tex, colour, inner: colour, part: name, slide};
    }

    // A box of the given centre and size; `tex` maps a face name to a picture.
    function cuboid(centre, size, name, colour, tex = {}, slide = 0) {
        const faces = faceCorners({width_mm: size[0], height_mm: size[1], depth_mm: size[2]});
        return Object.entries(faces).map(([face, cs]) => ({
            corners: cs.map(q => q.map((v, k) => v + centre[k])),
            uv: tex[face] ? FULL_PICTURE : null, tex: tex[face] || null,
            colour, inner: colour, part: name, slide,
        }));
    }

    // A flat ring (a disc when r0 is small) standing from z0 to z1 round
    // (cx, cy); `tex` covers its top, the picture's square fitted to r1.
    function annulus(cx, cy, z0, z1, r0, r1, name, colour, tex = null, segments = 48) {
        const out = [];
        const at = (r, a, z) => [cx + r * Math.cos(a), cy + r * Math.sin(a), z];
        const uvOf = q => [0.5 + (q[0] - cx) / (2 * r1), 0.5 - (q[1] - cy) / (2 * r1)];
        for (let i = 0; i < segments; i++) {
            const a0 = 2 * Math.PI * i / segments, a1 = 2 * Math.PI * (i + 1) / segments;
            const mid = (a0 + a1) / 2, radial = [Math.cos(mid), Math.sin(mid), 0];
            const top = [at(r0, a0, z1), at(r1, a0, z1), at(r1, a1, z1), at(r0, a1, z1)];
            out.push(part(top, [0, 0, 1], name, colour, tex, tex ? top.map(uvOf) : null));
            out.push(part([at(r0, a0, z0), at(r1, a0, z0), at(r1, a1, z0), at(r0, a1, z0)],
                [0, 0, -1], name, colour));
            out.push(part([at(r1, a0, z1), at(r1, a1, z1), at(r1, a1, z0), at(r1, a0, z0)],
                radial, name, colour));
            out.push(part([at(r0, a0, z1), at(r0, a1, z1), at(r0, a1, z0), at(r0, a0, z0)],
                radial.map(v => -v), name, colour));
        }
        return out;
    }

    // The disc hub: a ring of teeth round the centre, as on a real tray.
    function rosette(cx, cy, z0, z1, name, colour, teeth = 12) {
        const out = [], points = [];
        for (let i = 0; i < teeth * 2; i++) {
            const a = Math.PI * i / teeth, r = i % 2 ? 6.2 : 7.4;
            points.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
        }
        points.forEach(([x0, y0], i) => {
            const [x1, y1] = points[(i + 1) % points.length];
            out.push(part([[cx, cy, z1], [x0, y0, z1], [x1, y1, z1]], [0, 0, 1], name, colour));
            out.push(part([[x0, y0, z1], [x1, y1, z1], [x1, y1, z0], [x0, y0, z0]],
                [(x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy, 0], name, colour));
        });
        return out;
    }

    // A quad of paper facing `outward` at depth z, the picture's [u0, u1]
    // across it; `flip` mirrors it, for paper read from inside the lid.
    function paper(x0, x1, y0, y1, z, outward, name, tex, u0, u1, flip) {
        const [l, r] = flip ? [x1, x0] : [x0, x1];
        const corners = [[l, y1, z], [r, y1, z], [r, y0, z], [l, y0, z]];
        return part(corners, outward, name, [1, 1, 1], tex, [[u0, 0], [u1, 0], [u1, 1], [u0, 1]]);
    }

    const firstOf = (scans, kind) => scans.find(s => s.kind === kind) || null;
    const aspectOf = s => (s && s.width > 0 && s.height > 0 ? s.width / s.height : null);
    const scanUrl = s => (s ? `/static/${encodeURI(s.url)}` : null);

    // What sits inside the case, placed as it sits when the case is closed.
    // `game` is what the record says of the game: {discs, region}.
    function insideParts(kind, c, shape, plastic, scans, game = {}) {
        const out = [];
        const w = c.width_mm / 2, h = c.height_mm / 2, d = c.depth_mm / 2;
        const sheet = (shape && shape.lip_height_mm) || 0;
        const floor = -d + sheet + PAPER_MM;      // the tray's inside
        const media = firstOf(scans, 'media'), manual = firstOf(scans, 'manual');
        const inside = firstOf(scans, 'inside');

        if (kind === 'carton') {
            const ch = 0.75 * c.height_mm, ct = Math.min(0.6 * c.depth_mm, 22);
            const cw = Math.min(c.width_mm - 8, ch * (aspectOf(media) || 0.8));
            out.push(...cuboid([0, -h + ch / 2 + 1, d - ct / 2 - 2], [cw, ch, ct], 'slide', CARTRIDGE,
                {front: scanUrl(media)}, 0.45 * ch));
            if (manual) {
                out.push(...cuboid([0, 0, -d + 2], [c.width_mm - 6, c.height_mm - 6, 1.5], 'slide', [1, 1, 1],
                    {front: scanUrl(manual)}, 0.25 * c.height_mm));
            }
            return out;
        }

        const lidInside = d - sheet - PAPER_MM;   // the lid's inside, facing -z
        const spread = aspectOf(inside) > 1.2;
        if (inside) {
            out.push(paper(-w + 2, w - 2, -h + 2, h - 2, floor, [0, 0, 1], 'base', scanUrl(inside),
                spread ? 0.5 : 0, 1, false));
            if (spread) {
                out.push(paper(-w + 2, w - 2, -h + 2, h - 2, lidInside, [0, 0, -1], 'lid', scanUrl(inside),
                    0, 0.5, true));
            }
        }

        const name = c.name || '';
        const gamecube = GAMECUBE.test(name), ps5 = PS5_CASE.test(name);
        if (gamecube) {
            out.push(...gamecubeBase(c, floor, plastic, scans, game, !inside));
        } else if (ps5) {
            out.push(...ps5Base(c, floor, plastic, media));
        } else if (DISC_CASES.test(name)) {
            const r = Math.min(/GameCube/.test(name) ? 40 : 60, w - 3, h - 3);
            out.push(...annulus(0, 0, floor, floor + 1.2, r + 1, r + 2.5, 'base', plastic));
            out.push(...rosette(0, 0, floor, floor + 5, 'base', plastic));
            out.push(...annulus(0, 0, floor + 2, floor + 3.2, 7.5, r, 'base', SILVER, scanUrl(media)));
        } else if (CLIPPED_CARTRIDGES.some(([pattern]) => pattern.test(name))) {
            const [, long, short, ct] = CLIPPED_CARTRIDGES.find(([pattern]) => pattern.test(name));
            // No scan: on its side, as in the user's PAL case.
            const across = (aspectOf(media) || 0) > 1;
            const [cw, ch] = across ? [long, short] : [short, long];
            const high = Math.min(ct + 1, c.depth_mm - 2), clip = 3;
            out.push(...cuboid([0, 0, floor + ct / 2], [cw, ch, ct], 'base', CARTRIDGE,
                {front: scanUrl(media)}));
            for (const y of [ch / 2 + clip / 2, -ch / 2 - clip / 2]) {
                out.push(...cuboid([0, y, floor + high / 2], [14, clip, high], 'base', plastic));
            }
        } else {
            const card = CARDS.find(([pattern]) => pattern.test(name));
            let [cw, ch, ct] = card ? card.slice(1) : [0.75 * c.width_mm, 0.55 * c.height_mm,
                Math.min(c.depth_mm - 3, 18)];
            if (!card && aspectOf(media)) cw = Math.min(c.width_mm - 10, ch * aspectOf(media));
            const cy = card ? h * 0.25 : 0, wall = 1.5, high = Math.min(ct + 1, c.depth_mm - 2);
            out.push(...cuboid([0, cy, floor + ct / 2], [cw, ch, ct], 'base', CARTRIDGE,
                {front: scanUrl(media)}));
            for (const [x, y, sx, sy] of [[0, ch / 2 + wall, cw + 4 * wall, wall], [0, -ch / 2 - wall, cw + 4 * wall, wall],
                [cw / 2 + wall, 0, wall, ch], [-cw / 2 - wall, 0, wall, ch]]) {
                out.push(...cuboid([x, cy + y, floor + high / 2], [sx, sy, high], 'base', plastic));
            }
        }

        if (kind === 'jewel') {
            // Two tabs on the lid's opening side hold the booklet.
            for (const y of [h * 0.4, -h * 0.4]) {
                out.push(...cuboid([w - 3, y, lidInside - 1], [4, 10, 2], 'lid', plastic));
            }
            return out;
        }
        if (/PS2/.test(name) && !manual) {
            // The memory-card holder: a low frame. A manual lies over it, so
            // it is drawn only without one: its walls, edge-on under the
            // manual, would show through in streaks.
            const [mx, my, mw, mh] = [w - 40, -h + 35, 60, 44];
            for (const [x, y, sx, sy] of [[0, mh / 2, mw, 1.5], [0, -mh / 2, mw, 1.5],
                [mw / 2, 0, 1.5, mh], [-mw / 2, 0, 1.5, mh]]) {
                out.push(...cuboid([mx + x, my + y, lidInside - 1.5], [sx, sy, 3], 'lid', plastic));
            }
        }
        if (ps5) {
            out.push(...ps5Lid(c, lidInside, plastic, manual));
            return out;
        }
        if (manual) {
            const aspect = aspectOf(manual) || 0.7;
            let bh = c.height_mm - 16, bw = bh * aspect;
            if (bw > c.width_mm - 14) { bw = c.width_mm - 14; bh = bw / aspect; }
            const z = lidInside - 4;
            out.push(...cuboid([0, 0, z], [bw, bh, 1.5], 'lid', [1, 1, 1], {back: scanUrl(manual)}));
            // The clips at its top and bottom edges; a GameCube's are its own.
            for (const y of gamecube ? [] : [bh / 2 - 1, -bh / 2 + 1]) {
                out.push(...cuboid([0, y, z - 1.5], [14, 4, 1.5], 'lid', plastic));
            }
        }
        if (gamecube) out.push(...gamecubeLid(c, lidInside, plastic, !!manual, game.region, !inside));
        return out;
    }

    // --- The GameCube case (PASS-59-329) --------------------------------------
    // From the user's photos of two PAL cases, a single-disc Sonic Mega
    // Collection and a two-disc Resident Evil 4 (2026-11-24); every place and
    // size is read from those photos by eye. The tray is a raised hexagon,
    // points to the top and bottom; a memory card holder sits in the corner by
    // the spine at the bottom; two disc-handling pictures sit at the bottom by
    // the opening side; "NINTENDO GAMECUBE" and its cube are moulded across
    // the top. A two-disc case holds its first disc on a hinged hexagonal flap
    // over the second. Not drawn, being unreadable in the photos: the patent
    // line along the hinge, the model number and the CE mark.
    const GAMECUBE = /^GameCube (DVD|Player's Choice) Case/;
    const GC_TRAY = {x: 4, y: 1, halfW: 54, halfH: 53, flatH: 28, thick: 1.5};
    const GC_HOLE = {length: 18, tongue: 10};       // the latch hole in the finger groove
    const DARK = [0.04, 0.04, 0.045];
    const lift = (colour, t) => colour.map(v => v + (1 - v) * t);
    // Moulded along the hinge of the user's European cases (photos, 2026-11-24);
    // its length read from those photos against the disc.
    const GC_PATENTS = 'EP0789914B / EP0896719 / PCT/GB01/04553 / PCT/GB01/05000 / GB2105020';
    const GC_PATENTS_MM = 120;

    // A flat-topped solid: the convex outline `points` ([x, y], in order)
    // raised from z0 to z1.
    function prism(points, z0, z1, name, colour) {
        const out = [];
        const cx = points.reduce((s, p) => s + p[0], 0) / points.length;
        const cy = points.reduce((s, p) => s + p[1], 0) / points.length;
        out.push(part(points.map(([x, y]) => [x, y, z1]), [0, 0, 1], name, colour));
        out.push(part(points.map(([x, y]) => [x, y, z0]), [0, 0, -1], name, colour));
        points.forEach(([x0, y0], i) => {
            const [x1, y1] = points[(i + 1) % points.length];
            out.push(part([[x0, y0, z1], [x1, y1, z1], [x1, y1, z0], [x0, y0, z0]],
                [(x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy, 0], name, colour));
        });
        return out;
    }

    // A straight bar `width` wide from (x0, y0) to (x1, y1).
    function bar([x0, y0], [x1, y1], width, z0, z1, name, colour) {
        const len = Math.hypot(x1 - x0, y1 - y0), nx = -(y1 - y0) / len * width / 2,
            ny = (x1 - x0) / len * width / 2;
        return prism([[x0 + nx, y0 + ny], [x1 + nx, y1 + ny], [x1 - nx, y1 - ny], [x0 - nx, y0 - ny]],
            z0, z1, name, colour);
    }

    function hexagon(t) {
        return [[t.x, t.y + t.halfH], [t.x - t.halfW, t.y + t.flatH], [t.x - t.halfW, t.y - t.flatH],
            [t.x, t.y - t.halfH], [t.x + t.halfW, t.y - t.flatH], [t.x + t.halfW, t.y + t.flatH]];
    }

    // Moulded relief, as a picture in the plastic's own colour: `paint`
    // draws its shapes in mm, and each is drawn lit from the top left, in
    // shadow below right, as the viewer's light falls.
    const EMBOSS_PX = 16;       // picture pixels per mm
    function embossed(wMm, hMm, plastic, paint) {
        const cv = document.createElement('canvas');
        cv.width = Math.ceil(wMm * EMBOSS_PX);
        cv.height = Math.ceil(hMm * EMBOSS_PX);
        const ctx = cv.getContext('2d');
        const tone = (t, to) => `rgb(${plastic.map(v => Math.round(255 * (v + (to - v) * t))).join(',')})`;
        ctx.fillStyle = tone(0, 0);
        ctx.fillRect(0, 0, cv.width, cv.height);
        for (const [dx, style] of [[0.2, tone(0.55, 0)], [-0.2, tone(0.45, 1)], [0, tone(0.08, 1)]]) {
            ctx.save();
            ctx.scale(EMBOSS_PX, EMBOSS_PX);
            ctx.translate(dx, dx);
            ctx.fillStyle = ctx.strokeStyle = style;
            paint(ctx);
            ctx.restore();
        }
        return cv.toDataURL('image/png');
    }

    // A moulded picture lying on the base's floor over x0..x1, y0..y1.
    function moulding(x0, x1, y0, y1, z, plastic, paint) {
        const tex = embossed(x1 - x0, y1 - y0, plastic, paint);
        return part([[x0, y1, z], [x1, y1, z], [x1, y0, z], [x0, y0, z]], [0, 0, 1], 'base', plastic,
            tex, FULL_PICTURE);
    }

    // `text` filling `width` mm from (x, y), its letters `size` mm tall.
    function fitText(ctx, text, x, y, width, size, weight = 'bold') {
        ctx.font = `${weight} ${size}px sans-serif`;
        ctx.textBaseline = 'top';
        ctx.save();
        ctx.translate(x, y);
        ctx.scale(width / ctx.measureText(text).width, 1);
        ctx.fillText(text, 0, 0);
        ctx.restore();
    }

    // The cube mark: a hexagon ring opened on the right, a small cube inside.
    function paintCube(ctx, cx, cy, r) {
        const hex = rr => Array.from({length: 6}, (_, i) => {
            const a = Math.PI / 2 + i * Math.PI / 3;
            return [cx + rr * Math.cos(a), cy - rr * Math.sin(a)];
        });
        const path = (pts, p = new Path2D()) => {
            pts.forEach(([x, y], i) => (i ? p.lineTo(x, y) : p.moveTo(x, y)));
            p.closePath();
            return p;
        };
        const ring = path(hex(0.62 * r), path(hex(r)));
        ctx.save();
        ctx.beginPath();
        ctx.rect(cx - r, cy - r, 2 * r, 2 * r);
        ctx.rect(cx + 0.3 * r, cy - 0.1 * r, 0.8 * r, -0.6 * r);
        ctx.clip('evenodd');
        ctx.fill(ring, 'evenodd');
        ctx.restore();
        ctx.fill(path(hex(0.38 * r)));
    }

    // One disc-handling picture: a disc, and fingers on its rim (`right`)
    // or a thumb on its face.
    function paintHandling(ctx, x, y, size, right) {
        const cx = x + size / 2, cy = y + size / 2;
        ctx.lineWidth = 0.7;
        ctx.strokeRect(x, y, size, size);
        ctx.beginPath();
        ctx.arc(cx, cy, 0.3 * size, 0, 2 * Math.PI);
        ctx.moveTo(cx + 0.07 * size, cy);
        ctx.arc(cx, cy, 0.07 * size, 0, 2 * Math.PI);
        ctx.stroke();
        const fingers = right ? [[cx - 0.33 * size, cy, 0.06, 0.12], [cx + 0.33 * size, cy, 0.06, 0.12]]
            : [[cx + 0.08 * size, cy - 0.08 * size, 0.08, 0.14]];
        for (const [fx, fy, rx, ry] of fingers) {
            ctx.beginPath();
            ctx.ellipse(fx, fy, rx * size, ry * size, right ? 0 : -0.6, 0, 2 * Math.PI);
            ctx.fill();
        }
        // The tick or cross above its right side.
        const mx = x + size - 4, my = y - 5;
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        if (right) {
            ctx.moveTo(mx - 1.5, my + 0.3);
            ctx.lineTo(mx - 0.3, my + 1.8);
            ctx.lineTo(mx + 2, my - 1.5);
        } else {
            ctx.moveTo(mx - 1.5, my - 1.5);
            ctx.lineTo(mx + 1.5, my + 1.5);
            ctx.moveTo(mx + 1.5, my - 1.5);
            ctx.lineTo(mx - 1.5, my + 1.5);
        }
        ctx.stroke();
    }

    // The base half's tray, holder, mouldings and discs. `bare` is false
    // when an inside scan covers the floor, which hides the mouldings.
    function gamecubeBase(c, floor, plastic, scans, {discs = 1, region} = {}, bare = true) {
        const out = [], w = c.width_mm / 2, h = c.height_mm / 2, t = GC_TRAY;
        const media = scans.filter(s => s.kind === 'media');
        const r = Math.min(40, w - 3, h - 3);
        const top = floor + t.thick;
        // Raised parts a shade lighter: lit head-on, their walls cast no
        // shading, and in the photos their edges catch the light.
        const raised = lift(plastic, 0.1), flapColour = lift(plastic, 0.2);
        out.push(...prism(hexagon(t), floor, top, 'base', raised));
        // A disc on its hub at `z`.
        const disc = (z, scan) => {
            // The hub stands 2 mm proud: a flap's disc sits high, under the manual.
            out.push(...rosette(t.x, t.y, z - 2, z + 2, 'base', plastic));
            out.push(...annulus(t.x, t.y, z, z + 1.2, 7.5, r, 'base', SILVER, scanUrl(scan)));
        };
        if (discs >= 2) {
            // The flap: a hexagon like the tray's on two arms from a hinge
            // bar by the spine; the first disc rides on it, the second under it.
            disc(top + 0.5, media[1] || null);
            const flap = top + 3.2, flapTop = flap + 1;
            out.push(...prism(hexagon({...t, halfW: t.halfW - 2, halfH: t.halfH - 2, flatH: t.flatH - 1}),
                flap, flapTop, 'base', flapColour));
            out.push(...bar([-w + 3, -72], [-w + 3, 72], 4, flap, flapTop, 'base', flapColour));
            for (const s of [1, -1]) {
                out.push(...bar([-w + 4, s * 70], [t.x - t.halfW + 4, t.y + s * t.flatH], 6,
                    flap, flapTop, 'base', flapColour));
            }
            disc(flapTop + 0.4, media[0] || null);
        } else {
            disc(top + 0.5, media[0] || null);
        }
        // The memory card holder: a low frame.
        const [hx0, hx1, hy0, hy1] = [-w + 7, -w + 51, -h + 13, -h + 46];
        for (const [a, b] of [[[hx0, hy0], [hx1, hy0]], [[hx1, hy0], [hx1, hy1]],
            [[hx1, hy1], [hx0, hy1]], [[hx0, hy1], [hx0, hy0]]]) {
            out.push(...bar(a, b, 1.5, floor, floor + 3, 'base', raised));
        }
        if (!bare) return out;
        const z = floor + 0.05;
        if (region === 'PAL') {
            // The European patent line in the hinge's channel, reading down
            // the case with its letters' tops towards the tray.
            const size = 2, half = GC_PATENTS_MM / 2;
            out.push(moulding(-w + 1.5, -w + 1.5 + size + 0.6, -half, half, z, plastic, ctx => {
                ctx.translate(size + 0.3, 0);
                ctx.rotate(Math.PI / 2);
                fitText(ctx, GC_PATENTS, 0, 0, GC_PATENTS_MM, size, 'normal');
            }));
            // The case's model number, in the same channel near the bottom.
            out.push(moulding(-w + 1.5, -w + 1.5 + size + 0.6, -h + 8, -h + 26, z, plastic, ctx => {
                ctx.translate(size + 0.3, 0);
                ctx.rotate(Math.PI / 2);
                fitText(ctx, 'DOL-007(EUR)', 0, 0, 18, size, 'normal');
            }));
        }
        out.push(moulding(hx0 + 2, hx1 - 2, hy1 - 5, hy1 - 1.5, z, plastic,
            ctx => fitText(ctx, 'MEMORY CARD STORAGE', 0, 0.3, hx1 - hx0 - 4, 3)));
        out.push(moulding(-w + 15, w - 11, h - 31, h - 5, z, plastic, ctx => {
            paintCube(ctx, 12, 13, 11);
            fitText(ctx, 'N I N T E N D O', 28, 1, 76, 5, 'normal');
            fitText(ctx, 'GAMECUBE', 27, 8, 78, 16);
        }));
        out.push(moulding(w - 61, w - 5, -h + 8, -h + 45, z, plastic, ctx => {
            paintHandling(ctx, 1, 10, 25, true);
            paintHandling(ctx, 29, 10, 25, false);
        }));
        return out;
    }

    // The lid's inside: a hooked clip from the opening side near the top
    // and the bottom, which the booklet slides under; two short ridges by
    // the spine; and on a European case the CE mark and "D-63760" (Nintendo
    // of Europe's postcode) near the spine at the top. Read from the user's
    // photos; lid x runs the other way once open, so its mouldings are mirrored.
    function gamecubeLid(c, lidInside, plastic, manual, region, bare) {
        const out = [], w = c.width_mm / 2, h = c.height_mm / 2;
        const raised = lift(plastic, 0.1);
        // Over the manual where there is one (it lies 4 mm off the lid).
        const z = manual ? lidInside - 5.5 : lidInside - 3;
        for (const s of [1, -1]) {
            const y = s * (h - 20), outline = [[w - 1.5, y - 3.5], [w - 1.5, y + 3.5]];
            for (let k = 0; k <= 6; k++) {
                const a = Math.PI / 2 + Math.PI * k / 6;
                outline.push([w - 30 + 3.5 * Math.cos(a), y + 3.5 * Math.sin(a)]);
            }
            out.push(...prism(outline.reverse(), z - 0.6, z + 0.6, 'lid', raised));
        }
        for (const [x, y0, y1] of [[-w + 10, h - 38, h - 15], [-w + 16, -h + 10, -h + 35]]) {
            out.push(...bar([x, y0], [x, y1], 1, lidInside - 1.5, lidInside, 'lid', raised));
        }
        if (region === 'PAL' && bare) {
            const zl = lidInside - 0.05, [x0, x1, y0, y1] = [-w + 4, -w + 18, h - 32, h - 20];
            const tex = embossed(x1 - x0, y1 - y0, plastic, ctx => {
                fitText(ctx, 'CE', 3, 0.5, 6, 5, 'normal');
                fitText(ctx, 'D-63760', 1, 7.5, 12, 2, 'normal');
            });
            out.push(part([[x1, y1, zl], [x0, y1, zl], [x0, y0, zl], [x1, y0, zl]], [0, 0, -1], 'lid',
                plastic, tex, FULL_PICTURE));
        }
        return out;
    }

    // --- The PS5 case (PASS-59-329) -------------------------------------------
    // From the user's ruler photos of their own case (2026-11-25), read to
    // about 2 mm. The disc sits in a raised ring with four finger dips, about
    // 51 degrees either side of the spine and of the opening side; the hub is
    // a low round platform with five sprung tongues round a three-lobed
    // button that fits the disc's 15 mm hole. The booklet half has a clip near
    // each opening corner and a rail along its top and bottom edges. A wall
    // runs round each half just inside its edge. Its small notches are not
    // drawn: the photos do not show them clearly enough to place.
    const PS5_CASE = /^PS5 /;
    const PS5 = {
        ringIn: 60.5, ringOut: 65, ringHigh: 3.5,
        dips: [51, -51, 129, 231], dipHalf: 12.5, dipFloor: 0.8,  // degrees from the opening side
        platform: 21, platformHigh: 0.6, button: 7.2, buttonHigh: 5.5,
        tongues: 5, tongueIn: 7.6, tongueOut: 15, slitTo: 17.5,
        disc: 60, discHole: 7.5, discAt: 2,
        wallIn: 1.5, wallWidth: 1,
        // A booklet clip: a flat frame on a post by the opening side, a U slot through it,
        // and inside the U a tongue that springs down onto the booklet (photos, 2026-11-25).
        clip: {fromOpening: 22, fromEdge: 27.75, along: 25, across: 18.5, corner: 3, high: 4.5,
            slotFromOpening: 14.5, slotLength: 14.5, slotWidth: 8, line: 1.5, plate: 1, flat: 0.3, low: 0.8, tipLift: 0.7},
        rail: {fromEdge: 10.5, start: 12, end: 128, thin: 1, thick: 2.5, high: 2},
        bookletFromOpening: 14,
        latch: {fromEnd: 22.5, length: 6, reach: 2},        // hooks inside the disc half's opening wall
        hingeNotch: {width: 2, depth: 3},                   // cut in each half's rim by the spine
    };

    // The wall round a half's inside, from z0 to z1.
    function ps5Wall(c, z0, z1, name, colour) {
        const x = c.width_mm / 2 - PS5.wallIn, y = c.height_mm / 2 - PS5.wallIn, t = PS5.wallWidth;
        return [[[-x, y], [x, y]], [[x, y], [x, -y]], [[x, -y], [-x, -y]], [[-x, -y], [-x, y]]]
            .flatMap(([a, b]) => bar(a, b, t, z0, z1, name, colour));
    }

    // The disc ring: its top drops into a rounded dip at each of PS5.dips.
    function ps5Ring(z0, colour, segments = 120) {
        const out = [], r0 = PS5.ringIn, r1 = PS5.ringOut;
        const topAt = a => {
            let z = z0 + PS5.ringHigh;
            for (const dip of PS5.dips) {
                const off = Math.abs(((a * 180 / Math.PI - dip) % 360 + 540) % 360 - 180);
                if (off < PS5.dipHalf) {
                    const t = off / PS5.dipHalf;
                    z = Math.min(z, z0 + PS5.dipFloor + (PS5.ringHigh - PS5.dipFloor) * t * t);
                }
            }
            return z;
        };
        const at = (r, a, z) => [r * Math.cos(a), r * Math.sin(a), z];
        for (let i = 0; i < segments; i++) {
            const a0 = 2 * Math.PI * i / segments, a1 = 2 * Math.PI * (i + 1) / segments;
            const z1a = topAt(a0), z1b = topAt(a1), mid = (a0 + a1) / 2;
            const radial = [Math.cos(mid), Math.sin(mid), 0];
            out.push(part([at(r0, a0, z1a), at(r1, a0, z1a), at(r1, a1, z1b), at(r0, a1, z1b)],
                [0, 0, 1], 'base', colour));
            out.push(part([at(r1, a0, z1a), at(r1, a1, z1b), at(r1, a1, z0), at(r1, a0, z0)],
                radial, 'base', colour));
            out.push(part([at(r0, a0, z1a), at(r0, a1, z1b), at(r0, a1, z0), at(r0, a0, z0)],
                radial.map(v => -v), 'base', colour));
        }
        return out;
    }

    // The hub's platform top: ten straight slits out from the button, evenly
    // spaced, a tongue in every other gap, each ending in a small round hole;
    // drawn dark on the plastic, 1 mm to a picture unit, centred on the hub.
    function ps5HubPicture(plastic) {
        const size = 2 * PS5.platform, cv = document.createElement('canvas');
        cv.width = cv.height = Math.ceil(size * EMBOSS_PX);
        const ctx = cv.getContext('2d');
        ctx.fillStyle = `rgb(${plastic.map(v => Math.round(255 * v)).join(',')})`;
        ctx.fillRect(0, 0, cv.width, cv.height);
        ctx.scale(EMBOSS_PX, EMBOSS_PX);
        ctx.translate(PS5.platform, PS5.platform);
        ctx.strokeStyle = ctx.fillStyle = `rgb(${DARK.map(v => Math.round(255 * v)).join(',')})`;
        ctx.lineWidth = 0.5;
        for (let k = 0; k < 2 * PS5.tongues; k++) {
            const a = Math.PI / 2 + Math.PI * (2 * k + 1) / (2 * PS5.tongues);
            const [c, s] = [Math.cos(a), -Math.sin(a)];
            ctx.beginPath();
            ctx.moveTo(PS5.button * c, PS5.button * s);
            ctx.lineTo(PS5.slitTo * c, PS5.slitTo * s);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(PS5.slitTo * c, PS5.slitTo * s, 0.9, 0, 2 * Math.PI);
            ctx.fill();
        }
        // The button's three fingers.
        for (let k = 0; k < 3; k++) {
            const a = Math.PI / 6 + 2 * Math.PI * k / 3;
            ctx.beginPath();
            ctx.moveTo(1.2 * Math.cos(a), -1.2 * Math.sin(a));
            ctx.lineTo(PS5.button * Math.cos(a), -PS5.button * Math.sin(a));
            ctx.stroke();
        }
        return cv.toDataURL('image/png');
    }

    // The disc half: wall, ring, hub and the disc on it.
    function ps5Base(c, floor, plastic, media) {
        const out = [], raised = lift(plastic, 0.1), p = PS5;
        out.push(...ps5Wall(c, floor, -0.5, 'base', raised));
        // The hooks that keep the case shut, on the opening wall's inside near
        // each end; they reach up past the seam into the lid when it closes.
        const hx = c.width_mm / 2 - p.wallIn - p.wallWidth / 2 - p.latch.reach / 2;
        for (const s of [1, -1]) {
            out.push(...cuboid([hx, s * (c.height_mm / 2 - p.latch.fromEnd), (floor + 1 + 0.8) / 2],
                [p.latch.reach, p.latch.length, 0.8 - floor - 1], 'base', raised));
        }
        out.push(...ps5Ring(floor, raised));
        const top = floor + p.platformHigh, hub = ps5HubPicture(raised);
        out.push(...annulus(0, 0, floor, top, p.button, p.platform, 'base', raised, hub));
        for (let k = 0; k < p.tongues; k++) {
            const a = Math.PI / 2 + 2 * Math.PI * k / p.tongues;
            // A wedge filling its gap between two slits, a little short of each.
            const half = Math.PI / (2 * p.tongues) - 0.05, at = (r, da) => [r * Math.cos(a + da), r * Math.sin(a + da)];
            out.push(...prism([at(p.tongueIn, -half), at(p.tongueOut, -half), at(p.tongueOut, half),
                at(p.tongueIn, half)], top, floor + p.discAt, 'base', lift(plastic, 0.25)));
        }
        out.push(...annulus(0, 0, floor, floor + p.buttonHigh, 0.01, p.button, 'base', raised, hub, 24)
            .map(q => (q.tex ? {...q, uv: q.corners.map(([x, y]) =>
                [0.5 + x / (2 * p.platform), 0.5 - y / (2 * p.platform)])} : q)));
        out.push(...annulus(0, 0, floor + p.discAt, floor + p.discAt + 1.2, p.discHole, p.disc, 'base',
            SILVER, scanUrl(media)));
        return out;
    }

    // The booklet half: wall, two clips by the opening corners, two rails,
    // and the booklet held between the rails, its corners under the clips.
    function ps5Lid(c, lidInside, plastic, manual) {
        const out = [], w = c.width_mm / 2, h = c.height_mm / 2, raised = lift(plastic, 0.1);
        const {clip, rail} = PS5;
        out.push(...ps5Wall(c, 0.5, lidInside, 'lid', raised));
        if (manual) {
            // Between the rails, its opening-side edge under the clips (photos, 2026-11-25).
            const aspect = aspectOf(manual) || 0.7, edge = w - PS5.bookletFromOpening;
            let bh = 2 * (h - rail.fromEdge) - 3, bw = Math.min(bh * aspect, edge + w - PS5.wallIn - 2);
            if (bw < bh * aspect) bh = bw / aspect;
            out.push(...cuboid([edge - bw / 2, 0, lidInside - 0.15 - 1.5 / 2], [bw, bh, 1.5], 'lid', [1, 1, 1],
                {back: scanUrl(manual)}));
        }
        const zc = lidInside - clip.high;   // the clips' face, over the booklet
        const bookletTop = 1.65;            // the booklet's face, above the lid's inside
        for (const s of [1, -1]) {
            // A clip: a flat frame with rounded corners on its spine side, held over the
            // booklet's corner by a post past the booklet's edge. A U slot runs right
            // through it; the tongue inside joins the frame at the spine end, runs flat,
            // then curves down like a tick so its tip presses the booklet (user, 2026-11-25).
            const cx = w - clip.fromOpening, cy = s * (h - clip.fromEdge);
            const x0 = cx - clip.along / 2, x1 = cx + clip.along / 2, ay = clip.across / 2, r = clip.corner;
            const sx1 = w - clip.slotFromOpening, sx0 = sx1 - clip.slotLength;
            const sh = clip.slotWidth / 2, t = clip.line;
            const round = (k, sy) => [x0 + r - r * Math.sin(Math.PI / 8 * k), cy + sy * (ay - r + r * Math.cos(Math.PI / 8 * k))];
            // The frame in pieces round the slot: the rounded spine end, the strips
            // either side, the opening end, and the post under that end.
            const spineEnd = [[sx0, cy - ay], [sx0, cy + ay]];
            for (let k = 0; k <= 4; k++) spineEnd.push(round(k, 1));
            for (let k = 4; k >= 0; k--) spineEnd.push(round(k, -1));
            const box = (a, b, c2, d2) => [[a, c2], [b, c2], [b, d2], [a, d2]];
            for (const piece of [spineEnd, box(sx0, x1, cy + sh, cy + ay), box(sx0, x1, cy - ay, cy - sh),
                box(sx1, x1, cy - sh, cy + sh)]) {
                out.push(...prism(piece, zc, zc + clip.plate, 'lid', raised));
            }
            // The post is a wall as thin as the frame (user's photos, 2026-11-25).
            out.push(...prism(box(x1 - clip.plate, x1, cy - ay, cy + ay), zc, lidInside, 'lid', raised));
            // The tongue: flat from its root, bending down until its underside meets
            // the booklet's face, then curving up a little at the tip so a booklet
            // slides in and out without catching (user, 2026-11-25).
            const ty0 = cy - sh + t, ty1 = cy + sh - t, tx1 = sx1 - t, steps = 12;
            const drop = clip.high - clip.plate - bookletTop;
            const at = i => {
                const u = i / steps;
                const z = u <= clip.low
                    ? drop * Math.max(0, (u - clip.flat) / (clip.low - clip.flat)) ** 1.6
                    : drop - clip.tipLift * ((u - clip.low) / (1 - clip.low)) ** 2;
                return [sx0 + (tx1 - sx0) * u, zc + z];
            };
            for (let i = 0; i < steps; i++) {
                const [xa, za] = at(i), [xb, zb] = at(i + 1), za1 = za + clip.plate, zb1 = zb + clip.plate;
                out.push(part([[xa, ty0, za], [xb, ty0, zb], [xb, ty1, zb], [xa, ty1, za]], [0, 0, -1], 'lid', raised));
                out.push(part([[xa, ty0, za1], [xb, ty0, zb1], [xb, ty1, zb1], [xa, ty1, za1]], [0, 0, 1], 'lid', raised));
                for (const [y, n] of [[ty0, -1], [ty1, 1]]) {
                    out.push(part([[xa, y, za], [xb, y, zb], [xb, y, zb1], [xa, y, za1]], [0, n, 0], 'lid', raised));
                }
                if (i === steps - 1) {
                    out.push(part([[xb, ty0, zb], [xb, ty1, zb], [xb, ty1, zb1], [xb, ty0, zb1]], [1, 0, 0], 'lid', raised));
                }
            }
            // A rail, thin by the clip and thicker towards the spine.
            const y = s * (h - rail.fromEdge), rx0 = w - rail.start, rx1 = w - rail.end;
            out.push(...prism([[rx0, y - rail.thin / 2], [rx0, y + rail.thin / 2],
                [rx1, y + rail.thick / 2], [rx1, y - rail.thick / 2]], lidInside - rail.high, lidInside,
            'lid', raised));
        }
        return out;
    }

    // Marks on the PS5 shell, from the user's photos (2026-11-25): a notch in
    // each half's top and bottom rim where it meets the spine.
    function ps5Edges(c, plastic) {
        const out = [], w = c.width_mm / 2, h = c.height_mm / 2, d = c.depth_mm / 2;
        const n = PS5.hingeNotch, dark = plastic.map(v => v * 0.3);
        for (const s of [1, -1]) {
            const yy = s * (h + 0.02), x0 = -w + 0.5, x1 = x0 + n.width;
            for (const [name, z0, z1] of [['lid', d - n.depth, d], ['base', -d, -d + n.depth]]) {
                out.push(part([[x0, yy, z1], [x1, yy, z1], [x1, yy, z0], [x0, yy, z0]], [0, s, 0], name, dark));
            }
        }
        return out.map(p => ({...p, shell: true}));
    }

    // The square latch hole in the middle of the finger groove, seen shut:
    // dark, with the base's latch tongue standing in it.
    function gamecubeLatch(c, s) {
        const x = c.width_mm / 2 - s.recess_depth_mm + 0.02, half = GC_HOLE.length / 2;
        const z = s.recess_height_mm / 2 - 0.3, out = [];
        for (const [name, z0, z1] of [['lid', 0, z], ['base', -z, 0]]) {
            out.push(part([[x, half, z1], [x, -half, z1], [x, -half, z0], [x, half, z0]],
                [1, 0, 0], name, DARK));
        }
        out.push(...cuboid([x - 0.2, 0, -z / 2], [0.8, GC_HOLE.tongue, z], 'base', [0.3, 0.3, 0.32]));
        return out.map(p => ({...p, shell: true}));
    }

    // A shop's hanging tab (RetroDB, PASS-59-329): a thin plate with rounded
    // corners standing above the top edge, flush with the back half, centred.
    // Its slot is the shop-peg kind: a long rounded slot with a round bump up
    // its middle. Width and height are the user's reading of a PAL Mega Drive
    // case by eye (2026-11-21); the rest is judged from their photos.
    const TAB = {width: 50, height: 20, thick: 2, corner: 3, sink: 2,
        slotMid: 9, slotLength: 27, slotHeight: 5.3, bump: 4.5, bumpRise: 3.7, steps: 128};

    function hangingTab(c, plastic) {
        const h = c.height_mm / 2, d = c.depth_mm / 2, t = TAB;
        // The plate runs `sink` mm down into the case, so no gap shows
        // where the top edge rounds off.
        const bottom = h - t.sink, plateMid = (bottom + h + t.height) / 2;
        const halfW = t.width / 2, halfH = (t.height + t.sink) / 2;
        const cy = h + t.slotMid, slotR = t.slotHeight / 2;
        const bumpY = cy + slotR + t.bumpRise - t.bump;
        // Inside tests for the plate and the hole; both are star-shaped
        // round (0, cy), so one ray per step meets each edge once.
        const inPlate = (x, y) => {
            const qx = Math.max(Math.abs(x) - (halfW - t.corner), 0);
            const qy = Math.max(Math.abs(y - plateMid) - (halfH - t.corner), 0);
            return qx * qx + qy * qy <= t.corner * t.corner;
        };
        const inHole = (x, y) => {
            const qx = Math.max(Math.abs(x) - (t.slotLength / 2 - slotR), 0);
            return qx * qx + (y - cy) ** 2 <= slotR * slotR
                || x * x + (y - bumpY) ** 2 <= t.bump * t.bump;
        };
        const edge = (inside, a) => {
            let lo = 0, hi = t.width;
            for (let k = 0; k < 30; k++) {
                const mid = (lo + hi) / 2;
                if (inside(mid * Math.cos(a), cy + mid * Math.sin(a))) lo = mid; else hi = mid;
            }
            return [lo * Math.cos(a), cy + lo * Math.sin(a)];
        };
        const zf = -d + t.thick, zb = -d, out = [];
        const outer = [], inner = [];
        for (let i = 0; i < t.steps; i++) {
            const a = 2 * Math.PI * i / t.steps;
            outer.push(edge(inPlate, a));
            inner.push(edge(inHole, a));
        }
        for (let i = 0; i < t.steps; i++) {
            const j = (i + 1) % t.steps;
            const [o0, o1, n0, n1] = [outer[i], outer[j], inner[i], inner[j]];
            const at = (p, z) => [p[0], p[1], z];
            const mid = Math.PI * 2 * (i + 0.5) / t.steps;
            const radial = [Math.cos(mid), Math.sin(mid), 0];
            out.push(part([at(o0, zf), at(o1, zf), at(n1, zf), at(n0, zf)], [0, 0, 1], 'base', plastic));
            out.push(part([at(o0, zb), at(o1, zb), at(n1, zb), at(n0, zb)], [0, 0, -1], 'base', plastic));
            out.push(part([at(o0, zf), at(o1, zf), at(o1, zb), at(o0, zb)], radial, 'base', plastic));
            out.push(part([at(n0, zf), at(n1, zf), at(n1, zb), at(n0, zb)], radial.map(v => -v), 'base', plastic));
        }
        return out.map(p => ({...p, shell: true}));
    }

    // The lid's turn and a slide's rise at `open` (0 shut, 1 open), as
    // {rot: column-major mat3, shift}. Turning about y takes +z towards -x.
    function partTransform(name, hinge, open, slide) {
        if (name !== 'lid') return {rot: [1, 0, 0, 0, 1, 0, 0, 0, 1], shift: [0, slide * open, 0]};
        const a = -rad(hinge.max * open), c = Math.cos(a), s = Math.sin(a);
        const rot = hinge.axis === 'y' ? [c, 0, -s, 0, 1, 0, s, 0, c] : [1, 0, 0, 0, c, s, 0, -s, c];
        return {rot, shift: [0, 0, 0]};
    }

    // --- Drawing ----------------------------------------------------------

    // u_part turns a part about u_pivot (the lid on its hinge), then u_shift
    // moves it. A back side is seen only inside an opened shell: it shows
    // u_inner, lit from its own side.
    const VERTEX = `#version 300 es
        in vec3 a_pos; in vec3 a_normal; in vec2 a_uv;
        uniform mat3 u_rot, u_part; uniform vec3 u_pivot, u_shift;
        uniform float u_scale, u_persp, u_near, u_far; uniform vec2 u_half;
        out vec2 v_uv; out vec3 v_normal;
        void main() {
            vec3 p = u_part * (a_pos - u_pivot) + u_pivot + u_shift;
            vec3 v = u_rot * p * u_scale;
            float w = u_persp - v.z;
            float z = w * (u_far + u_near) / (u_far - u_near) - 2.0 * u_far * u_near / (u_far - u_near);
            gl_Position = vec4(v.x * u_persp / u_half.x, v.y * u_persp / u_half.y, z, w);
            v_uv = a_uv;
            v_normal = u_rot * (u_part * a_normal);
        }`;
    const FRAGMENT = `#version 300 es
        precision mediump float;
        in vec2 v_uv; in vec3 v_normal;
        uniform sampler2D u_tex; uniform bool u_use_tex; uniform vec3 u_colour, u_inner, u_light;
        uniform float u_shine;
        out vec4 colour;
        void main() {
            vec3 n = normalize(v_normal);
            vec3 base = u_inner;
            if (gl_FrontFacing && u_use_tex) {
                // A disc or cartridge scan is cut off its backdrop
                // (services/box_scans.py::cut_out): what is see-through is not there.
                vec4 texel = texture(u_tex, v_uv);
                if (texel.a < 0.5) discard;
                base = texel.rgb;
            } else if (gl_FrontFacing) base = u_colour;
            else n = -n;
            float lit = ${AMBIENT} + ${DIFFUSE} * max(0.0, dot(n, u_light));
            vec3 half_way = normalize(u_light + vec3(0.0, 0.0, 1.0));
            float shine = u_shine * ${SHEEN} * pow(max(0.0, dot(n, half_way)), ${SHININESS}.0);
            colour = vec4(base * lit + shine, 1.0);
        }`;

    let root, stage, canvas, gl = null, prog = null, loc = {};
    let openButton = null, strip = null, scanView = null;
    let record = null;
    let scans = [];             // services/box_scans.py::scans_for
    let groups = [];            // [{tex, colour, inner, part, slide, first, count}], one draw each
    let buffer = null, vao = null;
    const textures = {};        // url → {tex, ready}
    let fitShut = 1, fitOpen = 1, radius = 1, hinge = null, kind = 'keep';
    let yaw = START_YAW, pitch = START_PITCH, zoom = 1;
    let open = 0, tween = null; // 0 shut .. 1 open; tween runs frames while it moves

    const rad = deg => deg * Math.PI / 180;

    function hexColour(hex) {
        const v = parseInt(String(hex || '#000000').slice(1), 16);
        return [(v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255];
    }

    // A shader that will not compile or link means no 3D box: the zoom
    // shows the plain cover, and the next open tries again (PASS-59-283).
    function initGl() {
        if (gl) return true;
        try {
            return setUpGl();
        } catch (e) {
            console.error('3D box viewer could not start:', e);
            gl = null;
            return false;
        }
    }

    function setUpGl() {
        gl = canvas.getContext('webgl2', {antialias: true, premultipliedAlpha: true, alpha: true});
        if (!gl) return false;
        const shader = (type, src) => {
            const sh = gl.createShader(type);
            gl.shaderSource(sh, src);
            gl.compileShader(sh);
            if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
            return sh;
        };
        prog = gl.createProgram();
        gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERTEX));
        gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAGMENT));
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
        for (const name of ['u_rot', 'u_part', 'u_pivot', 'u_shift', 'u_scale', 'u_persp', 'u_near',
            'u_far', 'u_half', 'u_light', 'u_tex', 'u_use_tex', 'u_colour', 'u_inner', 'u_shine']) {
            loc[name] = gl.getUniformLocation(prog, name);
        }
        buffer = gl.createBuffer();
        vao = gl.createVertexArray();
        gl.bindVertexArray(vao);
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        const stride = 8 * 4;
        [['a_pos', 3, 0], ['a_normal', 3, 12], ['a_uv', 2, 24]].forEach(([name, size, offset]) => {
            const at = gl.getAttribLocation(prog, name);
            gl.enableVertexAttribArray(at);
            gl.vertexAttribPointer(at, size, gl.FLOAT, false, stride, offset);
        });
        gl.enable(gl.DEPTH_TEST);
        gl.frontFace(gl.CW);
        return true;
    }

    function texture(url) {
        if (textures[url]) return textures[url];
        const entry = {tex: gl.createTexture(), ready: false};
        textures[url] = entry;
        const img = new Image();
        img.onload = () => {
            gl.bindTexture(gl.TEXTURE_2D, entry.tex);
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
            gl.generateMipmap(gl.TEXTURE_2D);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
            // The rounded strips are seen edge-on; this keeps them sharp.
            const aniso = gl.getExtension('EXT_texture_filter_anisotropic');
            if (aniso) {
                gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT,
                    Math.min(8, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
            }
            entry.ready = true;
            draw();
        };
        img.src = url;
        return entry;
    }

    // Triangles for the shell, cut for opening, and the parts inside,
    // grouped by what fills them and how they move.
    function buildMesh() {
        const shape = record.shape && typeof record.shape === 'object' ? record.shape : null;
        kind = caseKind(record.case.name);
        hinge = hingeOf(kind, record.case);
        const plastic = hexColour(record.colours.edge);
        const inner = kind === 'carton' ? CARDBOARD : plastic;
        const faceUrl = face => {
            const url = face && record.urls && record.urls[face];
            return url ? `/static/${encodeURI(url)}` : null;
        };
        // The seam's groove: plastic within its width of the middle.
        const groove = shape && shape.seam_width_mm > 0 ? shape.seam_width_mm / 2 + SAME_MM : -1;
        const shell = boxPatches(record.case, shape).map(p => {
            let colour = hexColour(record.colours[p.colour]);
            if (p.face === null && p.corners.every(q => Math.abs(q[2]) <= groove)) {
                colour = colour.map(v => v * GROOVE);
            }
            return {corners: p.corners, uv: p.source, tex: faceUrl(p.face), colour, inner,
                slide: 0, shell: true};
        });
        // Bare plastic shines; pictures, paper and cardboard do not.
        const shines = p => !p.tex && !(p.shell && kind === 'carton');
        const patches = splitShell(shell, hinge)
            .concat(insideParts(kind, record.case, shape, plastic, scans,
                {discs: record.discs || 1, region: record.region}));
        if (record.hanging_tab) patches.push(...hangingTab(record.case, plastic));
        if (shape && hasRecess(shape) && GAMECUBE.test(record.case.name)) {
            patches.push(...gamecubeLatch(record.case, shape));
        }
        if (PS5_CASE.test(record.case.name || '')) patches.push(...ps5Edges(record.case, plastic));

        const byKey = new Map();
        let floats = 0;
        for (const p of patches) {
            const key = [p.tex, p.colour, p.inner, p.part, p.slide, !!p.shell].join('|');
            if (!byKey.has(key)) {
                byKey.set(key, {tex: p.tex, colour: p.colour, inner: p.inner, part: p.part,
                    slide: p.slide, shell: !!p.shell, shine: shines(p), patches: []});
            }
            byKey.get(key).patches.push(p);
            floats += (p.corners.length - 2) * 3 * 8;
        }
        // One typed array, filled in place: no per-vertex garbage.
        const all = new Float32Array(floats);
        let at = 0;
        groups = [];
        for (const g of byKey.values()) {
            const first = at / 8;
            for (const p of g.patches) {
                const normal = patchNormal(p.corners);
                // A fan: every patch is convex.
                for (let i = 1; i < p.corners.length - 1; i++) {
                    for (const j of [0, i, i + 1]) {
                        const q = p.corners[j], uv = p.uv ? p.uv[j] : [0, 0];
                        all.set([q[0], q[1], q[2], normal[0], normal[1], normal[2], uv[0], uv[1]], at);
                        at += 8;
                    }
                }
            }
            groups.push({tex: g.tex, colour: g.colour, inner: g.inner, part: g.part, slide: g.slide,
                shell: g.shell, shine: g.shine ? 1 : 0, first, count: at / 8 - first});
        }
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, all, gl.STATIC_DRAW);
    }

    // The box's rotation: pitch about x after yaw about y (column-major).
    function rotation() {
        const cy = Math.cos(rad(yaw)), sy = Math.sin(rad(yaw));
        const cp = Math.cos(rad(pitch)), sp = Math.sin(rad(pitch));
        // Rx(pitch) · Ry(yaw)
        return [cy, sp * sy, -cp * sy,
            0, cp, sp,
            sy, -sp * cy, cp * cy];
    }

    function draw() {
        if (!gl || !record || root.hidden) return;
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.useProgram(prog);
        gl.bindVertexArray(vao);
        // Shut, the inside cannot be seen: cull the back sides and skip the
        // parts, so their pictures are not even fetched until it opens.
        if (open > 0) gl.disable(gl.CULL_FACE);
        else gl.enable(gl.CULL_FACE);
        const fit = fitShut + (fitOpen - fitShut) * open;
        const scale = fit * zoom, reach = radius * scale * 1.05;
        const persp = record.case.height_mm * fit * 4;
        // The opened box, kept in the middle of the stage.
        const centre = hinge.axis === 'y' ? [record.case.width_mm / 2 * open, 0, 0]
            : [0, -0.2 * record.case.height_mm * open, 0];
        gl.uniformMatrix3fv(loc.u_rot, false, rotation());
        gl.uniform1f(loc.u_scale, scale);
        gl.uniform1f(loc.u_persp, persp);
        gl.uniform1f(loc.u_near, Math.max(1, persp - reach));
        gl.uniform1f(loc.u_far, persp + reach);
        gl.uniform2f(loc.u_half, canvas.clientWidth / 2, canvas.clientHeight / 2);
        gl.uniform3fv(loc.u_light, LIGHT);
        gl.uniform3fv(loc.u_pivot, hinge.pivot);
        gl.uniform1i(loc.u_tex, 0);
        for (const g of groups) {
            if (!g.shell && open === 0) continue;
            const tex = g.tex ? texture(g.tex) : null;
            const move = partTransform(g.part, hinge, open, g.slide);
            gl.uniformMatrix3fv(loc.u_part, false, move.rot);
            gl.uniform3fv(loc.u_shift, move.shift.map((v, k) => v + centre[k]));
            gl.uniform1i(loc.u_use_tex, tex && tex.ready ? 1 : 0);
            if (tex && tex.ready) gl.bindTexture(gl.TEXTURE_2D, tex.tex);
            gl.uniform3fv(loc.u_colour, g.colour);
            gl.uniform3fv(loc.u_inner, g.inner);
            gl.uniform1f(loc.u_shine, g.shine);
            gl.drawArrays(gl.TRIANGLES, g.first, g.count);
        }
    }

    const ease = t => (t < 0.5 ? 2 * t * t : 1 - 2 * (1 - t) * (1 - t));

    // Opens (1) or shuts (0) the box, turning the view to face the inside
    // as it opens and back as it shuts. Frames run only until it arrives.
    function setOpen(target) {
        const view = target ? (hinge.axis === 'y' ? [0, 20] : [15, 40]) : [START_YAW, START_PITCH];
        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        yaw = ((yaw + 180) % 360 + 360) % 360 - 180;    // turn back the short way
        tween = {from: [open, yaw, pitch], to: [target, ...view], start: performance.now(),
            ms: reduce ? 0 : OPEN_MS * Math.abs(target - open), view: true};
        const step = now => {
            if (!tween) return;
            const t = tween.ms ? Math.min(1, (now - tween.start) / tween.ms) : 1, k = ease(t);
            const at = i => tween.from[i] + (tween.to[i] - tween.from[i]) * k;
            open = at(0);
            if (tween.view) { yaw = at(1); pitch = at(2); }
            draw();
            if (t < 1) requestAnimationFrame(step);
            else tween = null;
        };
        requestAnimationFrame(step);
        updateOpenControls(target);
    }

    // Back to the first view, the box still as open as it is.
    function reset() {
        tween = null;
        const shut = open < 0.5;
        yaw = shut ? START_YAW : (hinge.axis === 'y' ? 0 : 15);
        pitch = shut ? START_PITCH : (hinge.axis === 'y' ? 20 : 40);
        zoom = 1;
        draw();
    }

    // Sizes the box so its height, and its widest turn (the diagonal of
    // front and spine), each fill most of the stage; opened, so the open
    // book's two halves or the carton's lifted contents do.
    function sizeToStage() {
        const {width_mm: wmm, height_mm: hmm, depth_mm: dmm} = record.case;
        const rect = stage.getBoundingClientRect();
        const dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
        fitShut = Math.min(rect.height * 0.8 / hmm, rect.width * 0.8 / Math.hypot(wmm, dmm));
        fitOpen = caseKind(record.case.name) === 'carton'
            ? Math.min(rect.height * 0.8 / (hmm * 1.45), rect.width * 0.8 / Math.hypot(wmm, dmm))
            : Math.min(rect.height * 0.8 / hmm, rect.width * 0.85 / (2 * wmm + dmm));
        radius = Math.hypot(2 * wmm + dmm, 1.5 * hmm, wmm) / 2;
    }

    // Shows the box in place of the zoomed picture, shut; call it once the
    // zoom is open, so the stage has its size. False when the game has no
    // faces or the browser has no WebGL2, and the caller zooms the picture.
    function show() {
        if (!root) return false;
        root.hidden = true;
        if (!record || !initGl()) return false;
        root.hidden = false;
        closeScan();
        open = 0;
        sizeToStage();
        buildMesh();
        updateOpenControls(0);
        reset();
        stage.focus({preventScroll: true});
        return true;
    }

    // --- The Open button and the scans strip --------------------------------

    function updateOpenControls(target) {
        if (!openButton) return;
        openButton.textContent = target ? openButton.dataset.closeLabel : openButton.dataset.openLabel;
        openButton.setAttribute('aria-pressed', target ? 'true' : 'false');
        strip.hidden = !target || !scans.length;
    }

    function toggleOpen() {
        if (!gl || !record || root.hidden) return;
        setOpen(open < 0.5 || (tween && tween.to[0] === 0) ? 1 : 0);
    }

    // The strip of the inside's scans, built once per page; thumbnails load
    // only when the strip first shows.
    function buildStrip() {
        strip.replaceChildren();
        let labels = {};
        try { labels = JSON.parse(strip.dataset.kindLabels || '{}'); } catch (e) { labels = {}; }
        for (const scan of scans) {
            const label = [labels[scan.kind] || scan.kind, scan.caption].filter(Boolean).join(' — ');
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'box-viewer-thumb';
            button.title = label;
            const img = document.createElement('img');
            img.src = scanUrl(scan);
            img.alt = label;
            img.loading = 'lazy';
            img.decoding = 'async';
            button.append(img);
            button.addEventListener('click', () => openScan(scan, label));
            strip.append(button);
        }
    }

    function openScan(scan, label) {
        scanView.querySelector('img').src = scanUrl(scan);
        scanView.querySelector('img').alt = label;
        scanView.querySelector('figcaption').textContent = label;
        stage.hidden = true;
        strip.hidden = true;
        scanView.hidden = false;
        scanView.querySelector('button').focus({preventScroll: true});
    }

    function closeScan() {
        if (!scanView || scanView.hidden) return;
        scanView.hidden = true;
        scanView.querySelector('img').removeAttribute('src');   // let the browser drop it
        stage.hidden = false;
        updateOpenControls(open >= 0.5 ? 1 : 0);
        stage.focus({preventScroll: true});
        draw();
    }

    // game-box-faces.js hands over the record after an import, null after
    // a removal, so the zoom follows without a reload.
    function setRecord(value) {
        record = value || null;
    }

    function onResize() {
        if (root && !root.hidden && record && gl) {
            sizeToStage();
            draw();
        }
    }

    function wireControls() {
        let drag = null;
        stage.addEventListener('pointerdown', e => {
            if (e.button !== 0) return;
            drag = {x: e.clientX, y: e.clientY, moved: false};
            stage.setPointerCapture(e.pointerId);
        });
        stage.addEventListener('pointermove', e => {
            if (!drag) return;
            const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
            if (!drag.moved && Math.hypot(dx, dy) < DRAG_SLOP) return;
            drag.moved = true;
            if (tween) tween.view = false;   // the hand takes the view; the lid keeps moving
            yaw += dx * 0.5;
            pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, pitch + dy * 0.5));
            drag.x = e.clientX;
            drag.y = e.clientY;
            draw();
        });
        const endDrag = () => {
            // A drag let go over the backdrop must not close the zoom.
            if (drag && drag.moved) {
                const swallow = ev => { ev.stopPropagation(); ev.preventDefault(); };
                window.addEventListener('click', swallow, {capture: true, once: true});
                setTimeout(() => window.removeEventListener('click', swallow, {capture: true}), 0);
            }
            drag = null;
        };
        stage.addEventListener('pointerup', endDrag);
        stage.addEventListener('pointercancel', endDrag);
        stage.addEventListener('dblclick', reset);
        stage.addEventListener('wheel', e => {
            e.preventDefault();
            zoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, zoom * Math.exp(-e.deltaY * 0.001)));
            draw();
        }, {passive: false});
        stage.addEventListener('keydown', e => {
            if (tween && e.key.startsWith('Arrow')) tween.view = false;
            switch (e.key) {
                case 'o': case 'O': toggleOpen(); return e.preventDefault();
                case 'ArrowLeft': yaw -= KEY_STEP; break;
                case 'ArrowRight': yaw += KEY_STEP; break;
                case 'ArrowUp': pitch = Math.max(-PITCH_LIMIT, pitch - KEY_STEP); break;
                case 'ArrowDown': pitch = Math.min(PITCH_LIMIT, pitch + KEY_STEP); break;
                case '+': case '=': zoom = Math.min(ZOOM_MAX, zoom * 1.2); break;
                case '-': zoom = Math.max(ZOOM_MIN, zoom / 1.2); break;
                case 'Home': reset(); return e.preventDefault();
                default: return;
            }
            e.preventDefault();
            draw();
        });
    }

    function init() {
        root = document.getElementById('boxViewer');
        if (!root) return;
        stage = root.querySelector('.box-viewer-stage');
        canvas = root.querySelector('.box-viewer-canvas');
        // A lost context (driver reset) leaves gl and every texture dead:
        // drop them so the next show() builds afresh.
        canvas.addEventListener('webglcontextlost', () => {
            gl = null;
            for (const url of Object.keys(textures)) delete textures[url];
        });
        try {
            record = JSON.parse(root.dataset.record || 'null');
        } catch (e) {
            record = null;
        }
        try {
            scans = JSON.parse(root.dataset.scans || '[]') || [];
        } catch (e) {
            scans = [];
        }
        openButton = root.querySelector('.box-viewer-open');
        strip = root.querySelector('.box-viewer-scans');
        scanView = root.querySelector('.box-viewer-scan');
        if (openButton) {
            openButton.addEventListener('click', toggleOpen);
            scanView.querySelector('button').addEventListener('click', closeScan);
            buildStrip();
        }
        wireControls();
        window.addEventListener('resize', debounce(onResize, 150));
    }

    window.BoxViewer = {show, setRecord, boxPatches, caseKind, splitShell, insideParts};

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
