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
 * zoom, the arrow keys turn, Home and a double-click reset.
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

    // Brightness = 0.45 + 0.55 × max(0, normal · light), § 4.5. The light is
    // in view space (y up, z towards the viewer): upper left, in front.
    const AMBIENT = 0.45;
    const DIFFUSE = 0.55;
    const LIGHT = unit([-0.35, 0.5, 1]);

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
    // ring: [[inset, height] on the lip sides, [inset, height] on the spine
    // side, how far the finger recess's cut reaches each way from the middle
    // at that height, or null where the ring runs above or below the slot].
    function profiles(s, d) {
        const r = s.edge_radius_mm, sw = s.seam_width_mm;
        const lip = s.lip_height_mm > 0;
        const t = lip ? s.lip_height_mm : 0;
        const front = [];
        if (lip) {
            // The lip's inner wall, bottom then top; on the spine side the
            // sheet runs straight to the rounding, so these sit where it starts.
            front.push([[s.lip_width_mm, d - t], [r, d - t]]);
            front.push([[s.lip_width_mm, d], [r, d - t]]);
        }
        const steps = r > 0 ? EDGE_SEGMENTS : 0;
        for (let k = steps; k >= 0; k--) {
            const theta = steps ? Math.PI / 2 * k / steps : 0;
            const inset = k !== steps ? r * (1 - Math.cos(theta)) : r;
            const rise = k !== steps ? r * Math.sin(theta) : r;
            front.push([[inset, d - r + rise], [inset, d - t - r + rise]]);
        }
        const back = front.slice().reverse().map(([[li, lz], [si, sz]]) => [[li, -lz], [si, -sz]]);
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
            const [ix, zx] = sx < 0 ? spineSide : lipSide;
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
            const x = w - lipSide[0], z = lipSide[1];
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

    // --- Drawing ----------------------------------------------------------

    const VERTEX = `#version 300 es
        in vec3 a_pos; in vec3 a_normal; in vec2 a_uv;
        uniform mat3 u_rot; uniform float u_scale, u_persp, u_near, u_far;
        uniform vec2 u_half; uniform vec3 u_light;
        out vec2 v_uv; out float v_bright;
        void main() {
            vec3 v = u_rot * a_pos * u_scale;
            float w = u_persp - v.z;
            float z = w * (u_far + u_near) / (u_far - u_near) - 2.0 * u_far * u_near / (u_far - u_near);
            gl_Position = vec4(v.x * u_persp / u_half.x, v.y * u_persp / u_half.y, z, w);
            v_uv = a_uv;
            v_bright = ${AMBIENT} + ${DIFFUSE} * max(0.0, dot(normalize(u_rot * a_normal), u_light));
        }`;
    const FRAGMENT = `#version 300 es
        precision mediump float;
        in vec2 v_uv; in float v_bright;
        uniform sampler2D u_tex; uniform bool u_use_tex; uniform vec3 u_colour;
        out vec4 colour;
        void main() {
            vec3 base = u_use_tex ? texture(u_tex, v_uv).rgb : u_colour;
            colour = vec4(base * v_bright, 1.0);
        }`;

    let root, stage, canvas, gl = null, prog = null, loc = {};
    let record = null;
    let groups = [];            // [{face, colour, first, count}], one draw each
    let buffer = null, vao = null;
    const textures = {};        // url → {tex, ready}
    let fit = 1, persp = 1, radius = 1;
    let yaw = START_YAW, pitch = START_PITCH, zoom = 1;

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
        for (const name of ['u_rot', 'u_scale', 'u_persp', 'u_near', 'u_far', 'u_half',
            'u_light', 'u_tex', 'u_use_tex', 'u_colour']) {
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
        gl.enable(gl.CULL_FACE);
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

    // Triangles for every patch, grouped by what fills them.
    function buildMesh() {
        const shape = record.shape && typeof record.shape === 'object' ? record.shape : null;
        const byKey = new Map();
        for (const p of boxPatches(record.case, shape)) {
            const key = `${p.face}|${p.colour}`;
            if (!byKey.has(key)) byKey.set(key, {face: p.face, colour: p.colour, data: []});
            const out = byKey.get(key).data;
            const normal = patchNormal(p.corners);
            const uv = p.source || p.corners.map(() => [0, 0]);
            // A fan: every patch is convex.
            for (let i = 1; i < p.corners.length - 1; i++) {
                for (const j of [0, i, i + 1]) out.push(...p.corners[j], ...normal, ...uv[j]);
            }
        }
        const all = [];
        groups = [];
        for (const g of byKey.values()) {
            groups.push({face: g.face, colour: g.colour, first: all.length / 8, count: g.data.length / 8});
            for (const x of g.data) all.push(x);
        }
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(all), gl.STATIC_DRAW);
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
        const scale = fit * zoom, reach = radius * scale * 1.05;
        gl.uniformMatrix3fv(loc.u_rot, false, rotation());
        gl.uniform1f(loc.u_scale, scale);
        gl.uniform1f(loc.u_persp, persp);
        gl.uniform1f(loc.u_near, Math.max(1, persp - reach));
        gl.uniform1f(loc.u_far, persp + reach);
        gl.uniform2f(loc.u_half, canvas.clientWidth / 2, canvas.clientHeight / 2);
        gl.uniform3fv(loc.u_light, LIGHT);
        gl.uniform1i(loc.u_tex, 0);
        for (const g of groups) {
            const url = g.face && record.urls && record.urls[g.face];
            const tex = url ? texture(`/static/${encodeURI(url)}`) : null;
            gl.uniform1i(loc.u_use_tex, tex && tex.ready ? 1 : 0);
            if (tex && tex.ready) gl.bindTexture(gl.TEXTURE_2D, tex.tex);
            gl.uniform3fv(loc.u_colour, hexColour(record.colours[g.colour]));
            gl.drawArrays(gl.TRIANGLES, g.first, g.count);
        }
    }

    function reset() {
        yaw = START_YAW;
        pitch = START_PITCH;
        zoom = 1;
        draw();
    }

    // Sizes the box so its height, and its widest turn (the diagonal of
    // front and spine), each fill most of the stage.
    function build() {
        const {width_mm: wmm, height_mm: hmm, depth_mm: dmm} = record.case;
        const rect = stage.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
        fit = Math.min(rect.height * 0.8 / hmm, rect.width * 0.8 / Math.hypot(wmm, dmm));
        persp = hmm * fit * 4;
        radius = Math.hypot(wmm, hmm, dmm) / 2;
        buildMesh();
    }

    // Shows the box in place of the zoomed picture; call it once the zoom is
    // open, so the stage has its size. False when the game has no faces or
    // the browser has no WebGL2, and the caller zooms the picture instead.
    function show() {
        if (!root) return false;
        root.hidden = true;
        if (!record || !initGl()) return false;
        root.hidden = false;
        build();
        reset();
        stage.focus({preventScroll: true});
        return true;
    }

    // game-box-faces.js hands over the record after an import, null after
    // a removal, so the zoom follows without a reload.
    function setRecord(value) {
        record = value || null;
    }

    function onResize() {
        if (root && !root.hidden && record && gl) {
            build();
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
            switch (e.key) {
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
        wireControls();
        window.addEventListener('resize', debounce(onResize, 150));
    }

    window.BoxViewer = {show, setRecord, boxPatches};

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
