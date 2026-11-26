/**
 * PASS-59-345 — a turnable 3D console or controller in the museum.
 *
 * Reads a GLB file (binary glTF 2.0) and draws it with WebGL2. The models in
 * static/models/hardware/ are prepared for this reader
 * (services/hardware_models.py): triangles, float attributes, 8-, 16- or
 * 32-bit indices, pictures as PNG, JPEG or WebP, and no compressed geometry,
 * whose decoders need 'wasm-unsafe-eval', which the CSP does not grant. A
 * file needing anything else is refused, and the museum says so.
 *
 * Materials: base colour (picture × factor), normal map, metal and
 * roughness, emission, alpha cut-out; each picture may use any of the first
 * three UV sets. Occlusion maps and optional extensions are ignored. The
 * normal map's tangent frame comes from screen derivatives, so the files
 * need no tangents.
 *
 * Light is fixed to the viewer, as the 3D box's: a key light upper left in
 * front, a softer fill from the right, and a sky-to-floor ambient.
 *
 * Controls, as box-viewer.js: drag turns (pitch held to -89..89 degrees),
 * the wheel and + / - zoom, the arrow keys turn, Home and a double-click
 * reset. It draws only when something changes.
 */
(function () {
    'use strict';

    const START_YAW = 35;
    const START_PITCH = 25;
    const PITCH_LIMIT = 89;
    const ZOOM_MIN = 0.5;
    const ZOOM_MAX = 4;
    const KEY_STEP = 10;
    const DRAG_SLOP = 3;
    const MAX_DPR = 2;
    const FOV = 30 * Math.PI / 180;   // vertical, or horizontal on a tall stage
    const FILL = 1;                   // share of the stage the model's bounding sphere fills

    const GLB_MAGIC = 0x46546C67;
    const CHUNK_JSON = 0x4E4F534A;
    const CHUNK_BIN = 0x004E4942;
    const READABLE = new Set(['EXT_texture_webp']);
    const COMPONENTS = {SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4};
    const ARRAYS = {5121: Uint8Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array};
    const GETTERS = {5121: 'getUint8', 5123: 'getUint16', 5125: 'getUint32', 5126: 'getFloat32'};
    const ATTRIBUTES = [['POSITION', 'a_pos'], ['NORMAL', 'a_normal'],
        ['TEXCOORD_0', 'a_uv0'], ['TEXCOORD_1', 'a_uv1'], ['TEXCOORD_2', 'a_uv2']];

    const VERTEX = `#version 300 es
        in vec3 a_pos; in vec3 a_normal; in vec2 a_uv0, a_uv1, a_uv2;
        uniform mat4 u_model_view, u_proj; uniform mat3 u_normal;
        out vec3 v_pos, v_normal; out vec2 v_uv0, v_uv1, v_uv2;
        void main() {
            vec4 p = u_model_view * vec4(a_pos, 1.0);
            v_pos = p.xyz;
            v_normal = u_normal * a_normal;
            v_uv0 = a_uv0; v_uv1 = a_uv1; v_uv2 = a_uv2;
            gl_Position = u_proj * p;
        }`;
    // View space throughout: the eye at the origin looking down -z.
    const FRAGMENT = `#version 300 es
        precision highp float;
        in vec3 v_pos, v_normal; in vec2 v_uv0, v_uv1, v_uv2;
        uniform sampler2D u_base, u_bump, u_mr, u_glow;
        uniform ivec4 u_set;            // UV set of base, normal, metal-rough, emission; -1 none
        uniform vec4 u_base_factor; uniform vec3 u_glow_factor;
        uniform float u_metal, u_rough, u_bump_scale, u_cutoff;
        uniform bool u_has_normal, u_two_sided;
        out vec4 colour;
        const float PI = 3.14159265;
        vec2 uvOf(int s) { return s == 1 ? v_uv1 : (s == 2 ? v_uv2 : v_uv0); }
        // Tangent frame from screen derivatives (Schüler, "Normal mapping
        // without precomputed tangents").
        mat3 frame(vec3 n, vec3 p, vec2 uv) {
            vec3 dp1 = dFdx(p), dp2 = dFdy(p);
            vec2 duv1 = dFdx(uv), duv2 = dFdy(uv);
            vec3 a = cross(dp2, n), b = cross(n, dp1);
            vec3 t = a * duv1.x + b * duv2.x, s = a * duv1.y + b * duv2.y;
            float k = inversesqrt(max(1e-12, max(dot(t, t), dot(s, s))));
            return mat3(t * k, s * k, n);
        }
        vec3 shade(vec3 l, vec3 n, vec3 v, vec3 diffuse, vec3 f0, float a) {
            float nl = max(dot(n, l), 0.0);
            if (nl <= 0.0) return vec3(0.0);
            vec3 h = normalize(l + v);
            float nh = max(dot(n, h), 0.0), nv = max(dot(n, v), 1e-3), vh = max(dot(v, h), 0.0);
            float a2 = a * a, d = nh * nh * (a2 - 1.0) + 1.0;
            float k = a / 2.0;
            float g = nl / (nl * (1.0 - k) + k) * nv / (nv * (1.0 - k) + k);
            vec3 f = f0 + (1.0 - f0) * pow(1.0 - vh, 5.0);
            vec3 spec = f * (a2 / (PI * d * d)) * g / (4.0 * nl * nv);
            return ((1.0 - f) * diffuse / PI + spec) * nl;
        }
        void main() {
            vec4 base = u_base_factor;
            if (u_set.x >= 0) base *= texture(u_base, uvOf(u_set.x));
            if (base.a < u_cutoff) discard;
            vec3 n;
            if (u_has_normal) {
                n = normalize(v_normal);
                if (u_two_sided && !gl_FrontFacing) n = -n;
            } else {
                n = normalize(cross(dFdx(v_pos), dFdy(v_pos)));
            }
            if (u_set.y >= 0) {
                vec2 uv = uvOf(u_set.y);
                vec3 t = texture(u_bump, uv).xyz * 2.0 - 1.0;
                // glTF's v runs down the picture; the map's green points up it.
                t.xy *= vec2(u_bump_scale, -u_bump_scale);
                n = normalize(frame(n, v_pos, uv) * t);
            }
            float rough = u_rough, metal = u_metal;
            if (u_set.z >= 0) {
                vec4 mr = texture(u_mr, uvOf(u_set.z));
                rough *= mr.g;
                metal *= mr.b;
            }
            float a = max(0.03, rough * rough);
            vec3 v = normalize(-v_pos);
            vec3 diffuse = base.rgb * (1.0 - metal);
            vec3 f0 = mix(vec3(0.04), base.rgb, metal);
            vec3 c = 3.2 * shade(normalize(vec3(-0.4, 0.6, 0.7)), n, v, diffuse, f0, a)
                   + 1.3 * shade(normalize(vec3(0.7, 0.1, 0.4)), n, v, diffuse, f0, a);
            vec3 sky = mix(vec3(0.22, 0.21, 0.2), vec3(0.42, 0.44, 0.48), 0.5 + 0.5 * n.y);
            c += sky * (diffuse + f0 * (1.0 - 0.6 * rough));
            vec3 glow = u_glow_factor;
            if (u_set.w >= 0) glow *= texture(u_glow, uvOf(u_set.w)).rgb;
            c += glow;
            colour = vec4(pow(clamp(c, 0.0, 1.0), vec3(1.0 / 2.2)), 1.0);
        }`;

    let root, stage, canvas, statusEl, gl = null, prog = null, loc = {};
    let model = null;           // {draws, centre, radius, textures, buffers, vaos}
    let loading = null;         // the url being fetched; a newer show() wins
    let yaw = START_YAW, pitch = START_PITCH, zoom = 1;

    // --- The file ----------------------------------------------------------

    function parseGlb(buf) {
        const dv = new DataView(buf);
        if (buf.byteLength < 20 || dv.getUint32(0, true) !== GLB_MAGIC || dv.getUint32(4, true) !== 2) {
            throw new Error('not a binary glTF 2.0 file');
        }
        let json = null, bin = null;
        for (let at = 12; at + 8 <= buf.byteLength;) {
            const length = dv.getUint32(at, true), type = dv.getUint32(at + 4, true);
            const body = new Uint8Array(buf, at + 8, length);
            if (type === CHUNK_JSON) json = JSON.parse(new TextDecoder().decode(body));
            else if (type === CHUNK_BIN && !bin) bin = body;
            at += 8 + length;
        }
        if (!json || !bin) throw new Error('the file has no JSON or binary chunk');
        for (const ext of json.extensionsRequired || []) {
            if (!READABLE.has(ext)) throw new Error(`the file needs ${ext}`);
        }
        if ((json.buffers || []).some(b => b.uri)) throw new Error('the file names an outside buffer');
        return {json, bin};
    }

    function viewBytes(file, index) {
        const view = file.json.bufferViews[index];
        return new Uint8Array(file.bin.buffer, file.bin.byteOffset + (view.byteOffset || 0), view.byteLength);
    }

    function readAccessor(file, index) {
        const a = file.json.accessors[index];
        const Type = ARRAYS[a.componentType], n = COMPONENTS[a.type];
        if (a.sparse || a.bufferView === undefined || !Type || !n || a.normalized) {
            throw new Error(`accessor ${index} is in a form this reader does not take`);
        }
        const view = file.json.bufferViews[a.bufferView];
        const start = file.bin.byteOffset + (view.byteOffset || 0) + (a.byteOffset || 0);
        const size = Type.BYTES_PER_ELEMENT, stride = view.byteStride || n * size;
        if (stride === n * size && start % size === 0) {
            return new Type(file.bin.buffer, start, a.count * n);
        }
        // Interleaved or unaligned: copy it out.
        const out = new Type(a.count * n), dv = new DataView(file.bin.buffer), get = GETTERS[a.componentType];
        for (let i = 0; i < a.count; i++) {
            for (let k = 0; k < n; k++) out[i * n + k] = dv[get](start + i * stride + k * size, true);
        }
        return out;
    }

    // --- Matrices (column-major, as WebGL takes them) ----------------------

    function nodeMatrix(node) {
        if (node.matrix) return node.matrix.slice();
        const [x, y, z, w] = node.rotation || [0, 0, 0, 1];
        const [sx, sy, sz] = node.scale || [1, 1, 1];
        const [tx, ty, tz] = node.translation || [0, 0, 0];
        return [
            (1 - 2 * (y * y + z * z)) * sx, 2 * (x * y + z * w) * sx, 2 * (x * z - y * w) * sx, 0,
            2 * (x * y - z * w) * sy, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z + x * w) * sy, 0,
            2 * (x * z + y * w) * sz, 2 * (y * z - x * w) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
            tx, ty, tz, 1];
    }

    function multiply(a, b) {
        const out = new Array(16);
        for (let c = 0; c < 4; c++) {
            for (let r = 0; r < 4; r++) {
                out[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1]
                    + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
            }
        }
        return out;
    }

    const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

    // The inverse transpose of the upper 3×3, which carries normals, and
    // its determinant: below zero the transform mirrors, and the winding with it.
    function normalMatrix(m) {
        const c0 = [m[0], m[1], m[2]], c1 = [m[4], m[5], m[6]], c2 = [m[8], m[9], m[10]];
        const x = cross(c1, c2), y = cross(c2, c0), z = cross(c0, c1);
        const det = c0[0] * x[0] + c0[1] * x[1] + c0[2] * x[2];
        const k = det ? 1 / det : 0;
        return {matrix: [...x, ...y, ...z].map(v => v * k), det};
    }

    function transformPoint(m, p) {
        return [0, 1, 2].map(r => m[r] * p[0] + m[4 + r] * p[1] + m[8 + r] * p[2] + m[12 + r]);
    }

    // --- Loading ------------------------------------------------------------

    async function makeTexture(file, index, srgb, cache) {
        const key = `${index}|${srgb}`;
        if (cache.has(key)) return cache.get(key);
        const promise = (async () => {
            const tex = file.json.textures[index];
            const source = tex.extensions && tex.extensions.EXT_texture_webp
                ? tex.extensions.EXT_texture_webp.source : tex.source;
            const image = file.json.images[source];
            if (image.bufferView === undefined) throw new Error('a picture outside the file');
            const blob = new Blob([viewBytes(file, image.bufferView)], {type: image.mimeType});
            const bitmap = await createImageBitmap(blob, {premultiplyAlpha: 'none', colorSpaceConversion: 'none'});
            const sampler = (file.json.samplers || [])[tex.sampler] || {};
            const t = gl.createTexture();
            gl.bindTexture(gl.TEXTURE_2D, t);
            gl.texImage2D(gl.TEXTURE_2D, 0, srgb ? gl.SRGB8_ALPHA8 : gl.RGBA8, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
            bitmap.close();
            gl.generateMipmap(gl.TEXTURE_2D);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, sampler.magFilter || gl.LINEAR);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, sampler.wrapS || gl.REPEAT);
            gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, sampler.wrapT || gl.REPEAT);
            const aniso = gl.getExtension('EXT_texture_filter_anisotropic');
            if (aniso) {
                gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT,
                    Math.min(8, gl.getParameter(aniso.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
            }
            return t;
        })();
        cache.set(key, promise);
        return promise;
    }

    async function makeMaterial(file, index, cache) {
        const m = (file.json.materials || [])[index] || {};
        const pbr = m.pbrMetallicRoughness || {};
        const slot = async (info, srgb) => (info
            ? {tex: await makeTexture(file, info.index, srgb, cache), set: info.texCoord || 0} : null);
        const [base, bump, mr, glow] = await Promise.all([
            slot(pbr.baseColorTexture, true), slot(m.normalTexture, false),
            slot(pbr.metallicRoughnessTexture, false), slot(m.emissiveTexture, true)]);
        return {
            base, bump, mr, glow,
            baseFactor: pbr.baseColorFactor || [1, 1, 1, 1],
            metal: pbr.metallicFactor ?? 1,
            rough: pbr.roughnessFactor ?? 1,
            bumpScale: (m.normalTexture && m.normalTexture.scale) ?? 1,
            glowFactor: m.emissiveFactor || [0, 0, 0],
            cutoff: m.alphaMode === 'MASK' ? (m.alphaCutoff ?? 0.5) : -1,
            twoSided: !!m.doubleSided,
        };
    }

    function makePrimitive(file, p, made) {
        if ((p.mode ?? 4) !== 4) return null;   // points and lines are not drawn
        const vao = gl.createVertexArray();
        gl.bindVertexArray(vao);
        made.vaos.push(vao);
        for (const [name, attribute] of ATTRIBUTES) {
            const at = gl.getAttribLocation(prog, attribute);
            if (at < 0) continue;
            if (p.attributes[name] === undefined) {
                gl.disableVertexAttribArray(at);
                continue;
            }
            const data = readAccessor(file, p.attributes[name]);
            const buffer = gl.createBuffer();
            made.buffers.push(buffer);
            gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
            gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
            gl.enableVertexAttribArray(at);
            gl.vertexAttribPointer(at, COMPONENTS[file.json.accessors[p.attributes[name]].type], gl.FLOAT, false, 0, 0);
        }
        const positions = file.json.accessors[p.attributes.POSITION];
        let count = positions.count, type = null;
        if (p.indices !== undefined) {
            const indices = readAccessor(file, p.indices);
            const buffer = gl.createBuffer();
            made.buffers.push(buffer);
            gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buffer);
            gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);
            count = indices.length;
            type = file.json.accessors[p.indices].componentType;
        }
        gl.bindVertexArray(null);
        return {vao, count, type, hasNormal: p.attributes.NORMAL !== undefined, bounds: [positions.min, positions.max]};
    }

    async function build(file) {
        const json = file.json;
        const made = {buffers: [], vaos: [], textures: new Map()};
        const materials = new Map();
        const draws = [];
        const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
        const scene = json.scenes[json.scene || 0];
        const visit = (index, parent) => {
            const node = json.nodes[index];
            const world = multiply(parent, nodeMatrix(node));
            if (node.mesh !== undefined) {
                const normal = normalMatrix(world);
                for (const p of json.meshes[node.mesh].primitives) {
                    if (p.attributes.POSITION === undefined) continue;
                    const prim = makePrimitive(file, p, made);
                    if (!prim) continue;
                    if (!materials.has(p.material)) materials.set(p.material, makeMaterial(file, p.material, made.textures));
                    draws.push({...prim, world, normal: normal.matrix, mirrored: normal.det < 0, material: p.material});
                    const [min, max] = prim.bounds;
                    if (!min || !max) continue;
                    for (let corner = 0; corner < 8; corner++) {
                        const q = transformPoint(world, [0, 1, 2].map(k => (corner >> k & 1 ? max[k] : min[k])));
                        for (let k = 0; k < 3; k++) {
                            low[k] = Math.min(low[k], q[k]);
                            high[k] = Math.max(high[k], q[k]);
                        }
                    }
                }
            }
            for (const child of node.children || []) visit(child, world);
        };
        for (const index of scene.nodes) visit(index, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
        if (!draws.length || low[0] === Infinity) throw new Error('the file has nothing to draw');
        for (const d of draws) d.material = await materials.get(d.material);
        const centre = low.map((v, k) => (v + high[k]) / 2);
        const radius = Math.hypot(...high.map((v, k) => v - low[k])) / 2;
        return {draws, centre, radius, made};
    }

    function free(m) {
        if (!m || !gl) return;
        m.made.vaos.forEach(v => gl.deleteVertexArray(v));
        m.made.buffers.forEach(b => gl.deleteBuffer(b));
        Promise.all(m.made.textures.values()).then(ts => ts.forEach(t => gl && gl.deleteTexture(t)), () => {});
    }

    // --- Drawing ----------------------------------------------------------

    function setUpGl() {
        gl = canvas.getContext('webgl2', {antialias: true, alpha: true, premultipliedAlpha: true});
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
        for (const name of ['u_model_view', 'u_proj', 'u_normal', 'u_base', 'u_bump', 'u_mr', 'u_glow',
            'u_set', 'u_base_factor', 'u_glow_factor', 'u_metal', 'u_rough', 'u_bump_scale', 'u_cutoff',
            'u_has_normal', 'u_two_sided']) {
            loc[name] = gl.getUniformLocation(prog, name);
        }
        gl.useProgram(prog);
        ['u_base', 'u_bump', 'u_mr', 'u_glow'].forEach((name, unit) => gl.uniform1i(loc[name], unit));
        gl.enable(gl.DEPTH_TEST);
        return true;
    }

    function initGl() {
        if (gl) return true;
        try {
            return setUpGl();
        } catch (e) {
            console.error('3D model viewer could not start:', e);
            gl = null;
            return false;
        }
    }

    // The eye looks at the model's centre from far enough back that its
    // bounding sphere fills FILL of the stage's shorter side.
    function camera() {
        const aspect = canvas.width / canvas.height;
        const tanY = Math.tan(FOV / 2), tanX = tanY * aspect;
        const fitTan = Math.min(tanX, tanY) * FILL;
        const distance = model.radius / Math.sin(Math.atan(fitTan)) / zoom;
        const near = Math.max(model.radius * 0.01, distance - model.radius * 1.2);
        const far = distance + model.radius * 1.2;
        const proj = [1 / tanX, 0, 0, 0, 0, 1 / tanY, 0, 0,
            0, 0, (far + near) / (near - far), -1, 0, 0, 2 * far * near / (near - far), 0];
        const cy = Math.cos(yaw * Math.PI / 180), sy = Math.sin(yaw * Math.PI / 180);
        const cp = Math.cos(pitch * Math.PI / 180), sp = Math.sin(pitch * Math.PI / 180);
        // Rx(pitch) · Ry(yaw), then back by the distance; the model's centre to the origin first.
        const turn = [cy, sp * sy, -cp * sy, 0, 0, cp, sp, 0, sy, -sp * cy, cp * cy, 0, 0, 0, -distance, 1];
        const [x, y, z] = model.centre;
        const view = multiply(turn, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1]);
        return {proj, view, turn: [cy, sp * sy, -cp * sy, 0, cp, sp, sy, -sp * cy, cp * cy]};
    }

    function mat3Multiply(a, b) {
        const out = new Array(9);
        for (let c = 0; c < 3; c++) {
            for (let r = 0; r < 3; r++) {
                out[c * 3 + r] = a[r] * b[c * 3] + a[3 + r] * b[c * 3 + 1] + a[6 + r] * b[c * 3 + 2];
            }
        }
        return out;
    }

    function bindSlot(unit, s) {
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, s ? s.tex : null);
        return s ? s.set : -1;
    }

    function draw() {
        if (!gl || !model || root.hidden) return;
        gl.viewport(0, 0, canvas.width, canvas.height);
        gl.clearColor(0, 0, 0, 0);
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        gl.useProgram(prog);
        const {proj, view, turn} = camera();
        gl.uniformMatrix4fv(loc.u_proj, false, proj);
        for (const d of model.draws) {
            const m = d.material;
            gl.uniformMatrix4fv(loc.u_model_view, false, multiply(view, d.world));
            gl.uniformMatrix3fv(loc.u_normal, false, mat3Multiply(turn, d.normal));
            gl.uniform4i(loc.u_set, bindSlot(0, m.base), bindSlot(1, m.bump), bindSlot(2, m.mr), bindSlot(3, m.glow));
            gl.uniform4fv(loc.u_base_factor, m.baseFactor);
            gl.uniform3fv(loc.u_glow_factor, m.glowFactor);
            gl.uniform1f(loc.u_metal, m.metal);
            gl.uniform1f(loc.u_rough, m.rough);
            gl.uniform1f(loc.u_bump_scale, m.bumpScale);
            gl.uniform1f(loc.u_cutoff, m.cutoff);
            gl.uniform1i(loc.u_has_normal, d.hasNormal ? 1 : 0);
            gl.uniform1i(loc.u_two_sided, m.twoSided ? 1 : 0);
            if (m.twoSided) gl.disable(gl.CULL_FACE);
            else gl.enable(gl.CULL_FACE);
            gl.frontFace(d.mirrored ? gl.CW : gl.CCW);
            gl.bindVertexArray(d.vao);
            if (d.type) gl.drawElements(gl.TRIANGLES, d.count, d.type, 0);
            else gl.drawArrays(gl.TRIANGLES, 0, d.count);
        }
        gl.bindVertexArray(null);
    }

    function sizeToStage() {
        const rect = stage.getBoundingClientRect();
        const dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
        canvas.width = Math.max(1, Math.round(rect.width * dpr));
        canvas.height = Math.max(1, Math.round(rect.height * dpr));
    }

    function reset() {
        yaw = START_YAW;
        pitch = START_PITCH;
        zoom = 1;
        draw();
    }

    function setStatus(text) {
        statusEl.textContent = text || '';
        statusEl.hidden = !text;
    }

    // Shows the model at `url` once the stage is on screen. Resolves true
    // when it is drawn, false when the browser or the file cannot be shown;
    // the status line then says so.
    async function show(url) {
        if (!root) return false;
        root.hidden = false;
        free(model);
        model = null;
        if (!initGl()) {
            setStatus(root.dataset.noWebgl);
            return false;
        }
        sizeToStage();
        gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
        setStatus(root.dataset.loading);
        loading = url;
        try {
            const reply = await fetch(url, {credentials: 'same-origin'});
            if (!reply.ok) throw new Error(`HTTP ${reply.status}`);
            const file = parseGlb(await reply.arrayBuffer());
            if (loading !== url) return false;
            const built = await build(file);
            if (loading !== url) {
                free(built);
                return false;
            }
            model = built;
        } catch (e) {
            if (loading === url) {
                console.error('3D model could not be shown:', url, e);
                setStatus(root.dataset.failed);
            }
            return false;
        }
        setStatus('');
        reset();
        stage.focus({preventScroll: true});
        return true;
    }

    function hide() {
        loading = null;
        free(model);
        model = null;
        if (root) root.hidden = true;
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
            // A drag let go over the backdrop must not close the dialog.
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
        root = document.getElementById('hardwareModel');
        if (!root) return;
        stage = root.querySelector('.hardware-model-stage');
        canvas = root.querySelector('.hardware-model-canvas');
        statusEl = root.querySelector('.hardware-model-status');
        // A lost context (driver reset) leaves gl and every buffer dead:
        // drop them, so the next show() builds afresh.
        canvas.addEventListener('webglcontextlost', () => {
            gl = null;
            model = null;
        });
        wireControls();
        window.addEventListener('resize', () => {
            if (!root.hidden && model) {
                sizeToStage();
                draw();
            }
        });
    }

    window.HardwareModel = {show, hide};

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
