/**
 * PASS-59-143 — the turnable 3D box in the cover zoom.
 *
 * A game with Slipcase faces (PASS-59-142, services/box_faces.py::faces_for)
 * zooms to a box built from CSS 3D transforms instead of a flat picture.
 * The faces are shown as imported: the case details are already in them, so
 * only lighting is added here. Nothing is painted around the box.
 * A face without a picture is filled with its colour from the record.
 *
 * Controls: drag turns (pitch held to -89..89 degrees), the wheel and + / -
 * zoom, the arrow keys turn, Home and a double-click reset.
 *
 * Contract: Slipcase docs/specs/SLIP-0104-turnable-3d-box.md § 4.1 (format,
 * orientation), § 4.5 (lighting, controls), INV-11, INV-12.
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

    // Towards the light, in view space (CSS axes: y points down): upper left,
    // in front. Brightness = 0.45 + 0.55 × max(0, normal · light), § 4.5.
    const LIGHT = (() => {
        const v = [-0.35, -0.5, 1];
        const len = Math.hypot(...v);
        return v.map(c => c / len);
    })();

    // Each face's outward normal before the box turns, its size from the
    // box's width, height and depth, and how it is placed around the centre.
    // Seen from outside the spine is on the front's left; the top's picture
    // has the back at its top edge, the bottom's the front (§ 4.1, Orientation).
    const FACES = {
        front:  {normal: [0, 0, 1],  size: (w, h, d) => [w, h], place: (w, h, d) => `translateZ(${d / 2}px)`},
        back:   {normal: [0, 0, -1], size: (w, h, d) => [w, h], place: (w, h, d) => `rotateY(180deg) translateZ(${d / 2}px)`},
        spine:  {normal: [-1, 0, 0], size: (w, h, d) => [d, h], place: (w, h, d) => `rotateY(-90deg) translateZ(${w / 2}px)`},
        edge:   {normal: [1, 0, 0],  size: (w, h, d) => [d, h], place: (w, h, d) => `rotateY(90deg) translateZ(${w / 2}px)`},
        top:    {normal: [0, -1, 0], size: (w, h, d) => [w, d], place: (w, h, d) => `rotateX(90deg) translateZ(${h / 2}px)`},
        bottom: {normal: [0, 1, 0],  size: (w, h, d) => [w, d], place: (w, h, d) => `rotateX(-90deg) translateZ(${h / 2}px)`},
    };

    // The colour a face without a picture takes from the record (§ 4.1).
    // Front and spine always have one; faces_for drops a record without.
    const FILL = {back: 'edge', edge: 'edge', top: 'top', bottom: 'bottom'};

    let root, stage, box;
    let record = null;
    let faceEls = {};
    let yaw = START_YAW, pitch = START_PITCH, zoom = 1;

    const rad = deg => deg * Math.PI / 180;

    // A normal after the box's own transform, rotateX(-pitch) rotateY(yaw).
    function turned([x, y, z]) {
        const cy = Math.cos(rad(yaw)), sy = Math.sin(rad(yaw));
        const x1 = x * cy + z * sy;
        const z1 = -x * sy + z * cy;
        const ca = Math.cos(rad(-pitch)), sa = Math.sin(rad(-pitch));
        return [x1, y * ca - z1 * sa, y * sa + z1 * ca];
    }

    function draw() {
        box.style.transform = `scale(${zoom}) rotateX(${-pitch}deg) rotateY(${yaw}deg)`;
        for (const [name, el] of Object.entries(faceEls)) {
            const n = turned(FACES[name].normal);
            const lit = n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2];
            el.style.setProperty('--box-shade', String(1 - (0.45 + 0.55 * Math.max(0, lit))));
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
        box.textContent = '';
        faceEls = {};
        const {width_mm: wmm, height_mm: hmm, depth_mm: dmm} = record.case;
        const rect = stage.getBoundingClientRect();
        const scale = Math.min(rect.height * 0.8 / hmm, rect.width * 0.8 / Math.hypot(wmm, dmm));
        const w = wmm * scale, h = hmm * scale, d = dmm * scale;
        stage.style.perspective = `${Math.round(h * 4)}px`;
        for (const [name, face] of Object.entries(FACES)) {
            const [fw, fh] = face.size(w, h, d);
            const el = document.createElement('div');
            el.className = 'box-viewer-face';
            el.style.width = `${fw}px`;
            el.style.height = `${fh}px`;
            el.style.marginLeft = `${-fw / 2}px`;
            el.style.marginTop = `${-fh / 2}px`;
            el.style.transform = face.place(w, h, d);
            const url = record.urls && record.urls[name];
            if (url) {
                el.style.backgroundImage = `url("/static/${encodeURI(url)}")`;
            } else {
                el.style.backgroundColor = record.colours[FILL[name]];
            }
            box.appendChild(el);
            faceEls[name] = el;
        }
    }

    // Shows the box in place of the zoomed picture; call it once the zoom is
    // open, so the stage has its size. False when the game has no faces, and
    // the caller zooms the picture instead.
    function show() {
        if (!root) return false;
        root.hidden = !record;
        if (!record) return false;
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
        if (root && !root.hidden && record) {
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
        box = root.querySelector('.box-viewer-box');
        try {
            record = JSON.parse(root.dataset.record || 'null');
        } catch (e) {
            record = null;
        }
        wireControls();
        window.addEventListener('resize', debounce(onResize, 150));
    }

    window.BoxViewer = {show, setRecord};

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
