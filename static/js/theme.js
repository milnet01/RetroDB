/**
 * RetroDB Theme Manager
 * Handles theme switching, persistence, and canvas background effects
 * (Matrix digital rain, Ocean moon reflection, Cyberpunk smoke/mist)
 */

const ThemeManager = {
    THEMES: ['cyberpunk', 'matrix', 'amber', 'ocean', 'christian', 'bladerunner', 'elite'],
    STORAGE_KEY: 'retrodb-theme',
    _SMOKE_STATE_KEY: 'retrodb-smoke-state',
    // 'off' in this browser's storage keeps every background still.
    _MOTION_KEY: 'retrodb-background-motion',
    _FRAME_MS: 50,      // about 20 frames a second
    // The smoke drifts slowly, so 10 frames a second looks the same, and each
    // frame repaints the whole page: half the frames, half the graphics work.
    _SMOKE_FRAME_MS: 100,
    _IDLE_MS: 60000,    // a minute with no mouse, keys or scrolling pauses it
    _rafId: null,
    _timerId: null,
    _lastInput: Date.now(),
    _canvas: null,
    _ctx: null,
    _activeEffect: null,
    _boundResize: null,

    // Matrix-specific state
    _columns: [],

    // Ocean-specific state
    _oceanTime: 0,

    // Christian-specific state
    _dustParticles: null,
    _dustTime: 0,

    // Blade Runner-specific state
    _rainDrops: null,
    _rainTime: 0,

    // Cyberpunk smoke state
    _smokeFallbackBalls: null,
    _smokeCfg: null,
    _hardwareTier: null,
    _hardwareScore: null,

    // Noise-based smoke state (high/medium/low tiers), drawn by the graphics card
    _smokeTime: 0,
    _smokeGL: null,
    _smokeBufW: 0,
    _smokeBufH: 0,
    _smokeColorRegions: null,

    // Offscreen gradient cache (used by fallback blobs)
    _gradientCache: new Map(),

    // =========================================================================
    // Cyberpunk smoke shaders. The graphics card works out the smoke for each
    // dot of a small picture (a sixth to a tenth of the window), and the
    // browser stretches that picture over the window. Simplex noise: Ian
    // McEwan and Stefan Gustavson, webgl-noise (MIT licence).
    // =========================================================================

    _SMOKE_VERTEX: 'attribute vec2 p; void main() { gl_Position = vec4(p, 0.0, 1.0); }',

    _SMOKE_FRAGMENT: `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 u_res;
uniform float u_time;
uniform int u_octaves;
uniform float u_tint;
uniform sampler2D u_regions;

vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(
                i.z + vec4(0.0, i1.z, i2.z, 1.0))
              + i.y + vec4(0.0, i1.y, i2.y, 1.0))
              + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_res;
    float down = 1.0 - uv.y;                    // 0 = top of the window, 1 = bottom
    // Dense at the bottom, gone in the top 15%: skip the noise up there.
    float mask = smoothstep(0.15, 0.7, down);
    if (mask <= 0.0) { gl_FragColor = vec4(0.0); return; }

    float nx = uv.x * 3.0;
    float sy = down * 3.0 - u_time * 0.3;       // rises over time
    vec3 q = vec3(nx, sy, u_time * 0.15);
    float d = 0.0, amp = 0.5, freq = 1.0;
    for (int o = 0; o < 5; o++) {               // fBm; the tier sets how many layers
        if (o >= u_octaves) break;
        d += amp * snoise(q * freq);
        freq *= 2.0;
        amp *= 0.5;
    }
    d += snoise(vec3(nx * 2.5 + 100.0, sy * 2.5, u_time * 0.25)) * 0.15;
    d = clamp((d * 0.5 + 0.5) * mask, 0.0, 1.0);

    float a = d * 0.12;                         // subtle: at most 12% opaque
    vec3 c = vec3(140.0, 160.0, 180.0) / 255.0;
    if (u_tint > 0.5) {
        float k = d * 0.4;
        c = c * (1.0 - k) + texture2D(u_regions, vec2(uv.x, 0.5)).rgb * k;
    }
    gl_FragColor = vec4(c * a, a);              // the canvas expects premultiplied alpha
}`,

    /**
     * Initialize theme system
     */
    init() {
        // The signed-in user's saved theme first (PASS-59-89, set by
        // base.html's FOUC block), then this browser's, then the default.
        const saved = document.documentElement.getAttribute('data-user-theme')
            || localStorage.getItem(this.STORAGE_KEY)
            || document.documentElement.getAttribute('data-theme')
            || 'cyberpunk';
        this.apply(saved, false);

        // Guard against duplicate listeners on re-init
        if (!this._listenersSet) {
            this._listenersSet = true;

            // The background moves only while someone is using the page: the
            // tab is showing, the window is in front, and there was a mouse,
            // key or scroll in the last _IDLE_MS. Any of those wakes it.
            const wake = () => {
                this._lastInput = Date.now();
                if (this._canAnimate()) this._startEffectLoop();
            };
            for (const ev of ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll', 'focus']) {
                window.addEventListener(ev, wake, { passive: true, capture: true });
            }
            window.addEventListener('blur', () => this._pauseEffect());
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) this._pauseEffect();
                else wake();
            });

            // Save smoke state before page unload so it persists across navigations
            window.addEventListener('beforeunload', () => this._saveSmokeState());
        }

        const motionToggle = document.getElementById('backgroundMotionToggle');
        if (motionToggle) motionToggle.checked = this.motionEnabled();
    },

    /** Whether this browser shows moving backgrounds (Settings > Display). */
    motionEnabled() {
        return localStorage.getItem(this._MOTION_KEY) !== 'off';
    },

    /** Turn moving backgrounds on or off for this browser, at once. */
    setMotion(on) {
        localStorage.setItem(this._MOTION_KEY, on ? 'on' : 'off');
        this.apply(localStorage.getItem(this.STORAGE_KEY) || 'cyberpunk', false);
    },

    /**
     * Apply a theme
     * @param {string} theme - Theme name
     * @param {boolean} save - Whether to persist to server
     */
    apply(theme, save = true) {
        if (!this.THEMES.includes(theme)) theme = 'cyberpunk';

        // Set or remove data-theme attribute
        if (theme === 'cyberpunk') {
            document.documentElement.removeAttribute('data-theme');
        } else {
            document.documentElement.setAttribute('data-theme', theme);
        }

        // Persist to localStorage
        localStorage.setItem(this.STORAGE_KEY, theme);

        // Tear down any existing canvas effect
        this._destroyCanvas();

        // WCAG SC 2.3.3 Animation from Interactions: respect prefers-reduced-motion.
        // CSS @media query covers the rest of the app via reset.css; canvas-driven
        // animations ignore CSS so we gate them here.
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        // Start theme-specific canvas effect
        if (!reduceMotion && this.motionEnabled()) {
            if (theme === 'matrix') {
                this._initMatrixRain();
            } else if (theme === 'ocean') {
                this._initOceanEffect();
            } else if (theme === 'cyberpunk') {
                this._initCyberpunkSmoke();
            } else if (theme === 'christian') {
                this._initChristianDust();
            } else if (theme === 'bladerunner') {
                this._initBladeRunnerRain();
            } else if (theme === 'elite') {
                this._initEliteStarfield();
            }
        }

        // Update theme selector UI if present
        document.querySelectorAll('.theme-option').forEach(el => {
            el.classList.toggle('active', el.dataset.theme === theme);
            el.setAttribute('aria-checked', String(el.dataset.theme === theme));
        });

        // Save to server
        if (save) {
            this.save(theme);
        }
    },

    /**
     * Persist theme choice to the current user's settings, so it follows the
     * user to other devices (Pass 59.38).
     * @param {string} theme - Theme name
     */
    save(theme) {
        // keepalive: a theme picked just before leaving the page still saves.
        // A failure is said: the saved theme would come back on the next page.
        API.post('/api/users/settings', { theme_preference: theme }, { keepalive: true })
            .catch(err => {
                console.error('Failed to save theme:', err);
                if (typeof showNotification === 'function') {
                    showNotification(t('Could not save the theme; it will reset on the next page.'), 'error');
                }
            });
    },

    // =========================================================================
    // Shared Canvas Management
    // =========================================================================

    /**
     * @param {string} id - Element id
     * @param {boolean} [gl=false] - Leave the context to the caller (the smoke
     *   shader asks for WebGL; a canvas holds only one kind of context).
     */
    _createCanvas(id, gl = false) {
        const canvas = document.createElement('canvas');
        canvas.id = id;
        canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:-3;pointer-events:none;';
        document.body.appendChild(canvas);
        this._canvas = canvas;
        this._ctx = gl ? null : canvas.getContext('2d');
        let resizeTimer;
        this._boundResize = () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                // A resize clears the canvas: draw it again, paused or not.
                this._resizeCanvas();
                this._pauseEffect();
                this._startEffectLoop();
            }, 150);
        };
        window.addEventListener('resize', this._boundResize, { passive: true });
        this._resizeCanvas();
    },

    _destroyCanvas() {
        this._pauseEffect();
        // Hand the smoke shader's graphics memory back at once
        if (this._smokeGL) {
            const gl = this._smokeGL.gl;
            this._smokeGL = null;   // first, so the lost-context handler ignores this
            const lose = gl.getExtension('WEBGL_lose_context');
            if (lose && !gl.isContextLost()) lose.loseContext();
        }
        if (this._canvas) {
            // Zero dimensions to immediately release bitmap backing store
            this._canvas.width = 0;
            this._canvas.height = 0;
            this._canvas.remove();
            this._canvas = null;
            this._ctx = null;
        }
        if (this._boundResize) {
            window.removeEventListener('resize', this._boundResize);
            this._boundResize = null;
        }
        this._activeEffect = null;
        this._columns = [];
        this._dustParticles = null;
        this._dustTime = 0;
        this._rainDrops = null;
        this._rainTime = 0;
        this._smokeFallbackBalls = null;
        this._smokeCfg = null;
        this._smokeBufW = 0;
        this._smokeBufH = 0;
        this._smokeTime = 0;
        this._smokeColorRegions = null;
        // Release offscreen gradient canvas bitmaps before clearing references
        this._gradientCache.forEach(offCanvas => {
            offCanvas.width = 0;
            offCanvas.height = 0;
        });
        this._gradientCache.clear();
    },

    /**
     * Get a cached offscreen gradient image for a given color and size.
     * Avoids creating CanvasGradient objects every frame (primary memory leak fix).
     * @param {number[]} color - [r, g, b] array
     * @param {number} size - Particle diameter
     * @param {string} type - 'smoke' (3-stop) or 'blob' (2-stop)
     * @returns {HTMLCanvasElement} - Offscreen canvas with pre-rendered gradient
     */
    _getGradientImage(color, size, type) {
        // Round size to nearest 50px to limit cache entries (~30-40 entries max)
        const roundedSize = Math.max(50, Math.ceil(size / 50) * 50);
        const key = `${type}_${color[0]}_${color[1]}_${color[2]}_${roundedSize}`;

        let cached = this._gradientCache.get(key);
        if (cached) return cached;

        const offCanvas = document.createElement('canvas');
        offCanvas.width = roundedSize;
        offCanvas.height = roundedSize;
        const offCtx = offCanvas.getContext('2d');

        const half = roundedSize / 2;
        const grad = offCtx.createRadialGradient(half, half, 0, half, half, half);

        if (type === 'smoke') {
            // 3-stop gradient matching original smoke rendering
            grad.addColorStop(0, `rgba(${color[0]},${color[1]},${color[2]},1)`);
            grad.addColorStop(0.4, `rgba(${color[0]},${color[1]},${color[2]},0.5)`);
            grad.addColorStop(1, `rgba(${color[0]},${color[1]},${color[2]},0)`);
        } else {
            // 2-stop gradient for fallback blobs
            grad.addColorStop(0, `rgba(${color[0]},${color[1]},${color[2]},1)`);
            grad.addColorStop(1, `rgba(${color[0]},${color[1]},${color[2]},0)`);
        }

        offCtx.fillStyle = grad;
        offCtx.fillRect(0, 0, roundedSize, roundedSize);

        // Enforce max cache size to prevent unbounded growth during long sessions
        // (each fallback ball reset generates a random neon color = unique key)
        if (this._gradientCache.size >= 60) {
            const oldestKey = this._gradientCache.keys().next().value;
            const oldCanvas = this._gradientCache.get(oldestKey);
            oldCanvas.width = 0;   // Release bitmap backing store
            oldCanvas.height = 0;
            this._gradientCache.delete(oldestKey);
        }

        this._gradientCache.set(key, offCanvas);
        return offCanvas;
    },

    _pauseEffect() {
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
        }
        if (this._timerId) {
            clearTimeout(this._timerId);
            this._timerId = null;
        }
    },

    /** Someone is using the page: tab showing, window in front, recent input. */
    _canAnimate() {
        return !!(this._canvas && this._activeEffect) && !document.hidden
            && document.hasFocus() && Date.now() - this._lastInput < this._IDLE_MS;
    },

    _resizeCanvas() {
        if (!this._canvas) return;

        // The smoke shader draws a small picture the browser stretches.
        if (this._smokeGL) {
            this._sizeSmokeCanvas();
            return;
        }

        const oldW = this._canvas.width;
        const oldH = this._canvas.height;
        this._canvas.width = window.innerWidth;
        this._canvas.height = window.innerHeight;

        // Recalculate matrix columns on resize
        if (this._activeEffect === 'matrix') {
            const fontSize = 14;
            const colCount = Math.floor(this._canvas.width / fontSize);
            this._columns = [];
            for (let i = 0; i < colCount; i++) {
                this._columns[i] = Math.random() * this._canvas.height / fontSize | 0;
            }
        }

        // Remap fallback blob positions proportionally on resize
        if (this._activeEffect === 'cyberpunk' && oldW > 0 && oldH > 0) {
            const scaleX = this._canvas.width / oldW;
            const scaleY = this._canvas.height / oldH;

            if (this._smokeFallbackBalls) {
                for (let i = 0; i < this._smokeFallbackBalls.length; i++) {
                    this._smokeFallbackBalls[i].x *= scaleX;
                    this._smokeFallbackBalls[i].y *= scaleY;
                }
            }
        }
    },

    /**
     * Draw a frame now, then one every _FRAME_MS while _canAnimate() holds.
     * A timer between frames, rather than a callback on every screen refresh,
     * wakes the browser 20 times a second instead of 60 to 144. Stopped, the
     * last frame stays on screen; any input restarts it (see init()).
     */
    _startEffectLoop() {
        if (this._rafId || this._timerId || !this._canvas) return;

        const tick = () => {
            this._timerId = null;
            this._rafId = requestAnimationFrame(() => {
                this._rafId = null;
                this._drawEffectFrame();
                if (this._canAnimate()) {
                    this._timerId = setTimeout(tick, this._smokeGL ? this._SMOKE_FRAME_MS : this._FRAME_MS);
                }
            });
        };
        tick();
    },

    _drawEffectFrame() {
        if (this._activeEffect === 'matrix') {
            this._drawMatrixFrame();
        } else if (this._activeEffect === 'ocean') {
            this._drawOceanFrame();
        } else if (this._activeEffect === 'cyberpunk') {
            if (this._smokeGL) {
                this._drawSmokeFrame();
            } else {
                this._drawCyberpunkFallbackFrame();
            }
        } else if (this._activeEffect === 'christian') {
            this._drawChristianDustFrame();
        } else if (this._activeEffect === 'bladerunner') {
            this._drawBladeRunnerRainFrame();
        } else if (this._activeEffect === 'elite') {
            this._drawEliteStarfieldFrame();
        }
    },

    // =========================================================================
    // Matrix Digital Rain
    // =========================================================================

    _initMatrixRain() {
        this._createCanvas('matrixRainCanvas');
        this._activeEffect = 'matrix';

        const fontSize = 14;
        const colCount = Math.floor(this._canvas.width / fontSize);
        this._columns = [];
        for (let i = 0; i < colCount; i++) {
            this._columns[i] = Math.random() * this._canvas.height / fontSize | 0;
        }

        this._startEffectLoop();
    },

    _drawMatrixFrame() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        if (!ctx || !canvas) return;

        const fontSize = 14;
        const chars = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';

        // Fade effect
        ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        ctx.fillStyle = '#00ff41';
        ctx.font = fontSize + 'px monospace';

        for (let i = 0; i < this._columns.length; i++) {
            const char = chars[Math.random() * chars.length | 0];
            const x = i * fontSize;
            const y = this._columns[i] * fontSize;

            ctx.fillText(char, x, y);

            // Reset column at random point after going past bottom
            if (y > canvas.height && Math.random() > 0.975) {
                this._columns[i] = 0;
            }
            this._columns[i]++;
        }
    },

    // =========================================================================
    // Ocean Moon Reflection
    // =========================================================================

    _initOceanEffect() {
        this._createCanvas('oceanEffectCanvas');
        this._activeEffect = 'ocean';
        this._oceanTime = 0;
        this._startEffectLoop();
    },

    _drawOceanFrame() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        if (!ctx || !canvas) return;

        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);
        this._oceanTime += 0.015;

        // Water surface at 55% of screen height
        const waterY = h * 0.55;
        // Moon X position matches CSS radial-gradient at 70%
        const moonX = w * 0.7;
        const reflBaseWidth = w * 0.012;

        // --- Moon reflection shimmer column on water ---
        // Use globalAlpha + fixed color to avoid rgba string allocation per iteration
        ctx.fillStyle = 'rgb(180, 215, 255)';
        for (let y = waterY + 4; y < h; y += 3) {
            const distRatio = (y - waterY) / (h - waterY);
            ctx.globalAlpha = 0.06 * (1 - distRatio * 0.5);
            const wobble = Math.sin(this._oceanTime * 1.5 + y * 0.015) * (5 + distRatio * 30);
            const spread = reflBaseWidth * (1 + distRatio * 5);
            ctx.fillRect(moonX + wobble - spread / 2, y, spread, 2);
        }

        // --- Subtle horizontal wave lines across water surface ---
        ctx.lineWidth = 1;
        for (let y = waterY; y < h; y += 18) {
            const distRatio = (y - waterY) / (h - waterY);
            ctx.globalAlpha = 0.018 + distRatio * 0.008;
            ctx.strokeStyle = 'rgb(77, 171, 247)';
            ctx.beginPath();
            for (let x = 0; x < w; x += 6) {
                const wave = Math.sin(this._oceanTime * 0.8 + x * 0.004 + y * 0.008) * (1.5 + distRatio * 2);
                if (x === 0) ctx.moveTo(x, y + wave);
                else ctx.lineTo(x, y + wave);
            }
            ctx.stroke();
        }

        // --- Faint sparkle dots on water (occasional glints) ---
        ctx.fillStyle = 'rgb(220, 240, 255)';
        const sparkleCount = 4;
        for (let i = 0; i < sparkleCount; i++) {
            const sparklePhase = this._oceanTime * 0.7 + i * 1.7;
            const flicker = Math.sin(sparklePhase) * 0.5 + 0.5; // 0..1
            if (flicker > 0.85) {
                const sx = (Math.sin(i * 3.7 + this._oceanTime * 0.1) * 0.5 + 0.5) * w;
                const sy = waterY + (Math.sin(i * 2.3 + this._oceanTime * 0.05) * 0.5 + 0.5) * (h - waterY);
                ctx.globalAlpha = (flicker - 0.85) * 3; // 0..0.45
                ctx.fillRect(sx - 1, sy - 1, 2, 2);
            }
        }

        ctx.globalAlpha = 1;
    },

    // =========================================================================
    // Hardware Detection
    // =========================================================================

    /**
     * Detect hardware tier (cached after first run)
     * Returns 'high', 'medium', 'low', or 'fallback'
     */
    _detectHardwareTier() {
        if (this._hardwareTier) return this._hardwareTier;

        let score = 0;
        const details = {};

        // CPU cores (0-35)
        const cores = navigator.hardwareConcurrency || 2;
        details.cores = cores;
        if (cores >= 8) score += 35;
        else if (cores >= 6) score += 28;
        else if (cores >= 4) score += 20;
        else if (cores >= 2) score += 10;

        // Device memory (0-20)
        const mem = navigator.deviceMemory || 4;
        details.memory = mem;
        if (mem >= 8) score += 20;
        else if (mem >= 4) score += 14;
        else if (mem >= 2) score += 8;
        else score += 3;

        // Mobile penalty
        const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
        details.mobile = isMobile;
        if (isMobile) score -= 15;

        // Canvas benchmark: draw 50 radial gradients (0-35)
        try {
            const testCanvas = document.createElement('canvas');
            testCanvas.width = 200;
            testCanvas.height = 200;
            const testCtx = testCanvas.getContext('2d');
            const t0 = performance.now();
            for (let i = 0; i < 50; i++) {
                const grad = testCtx.createRadialGradient(100, 100, 0, 100, 100, 100);
                grad.addColorStop(0, 'rgba(76,201,240,0.3)');
                grad.addColorStop(0.5, 'rgba(247,37,133,0.15)');
                grad.addColorStop(1, 'transparent');
                testCtx.fillStyle = grad;
                testCtx.fillRect(0, 0, 200, 200);
            }
            const elapsed = performance.now() - t0;
            details.benchmarkMs = Math.round(elapsed * 100) / 100;
            if (elapsed < 5) score += 35;
            else if (elapsed < 10) score += 28;
            else if (elapsed < 20) score += 20;
            else if (elapsed < 40) score += 12;
            else score += 5;
            // Release benchmark canvas
            testCanvas.width = 0;
            testCanvas.height = 0;
        } catch (e) {
            details.benchmarkError = true;
            score += 10;
        }

        // WebGL probe: check for software renderer
        try {
            const glCanvas = document.createElement('canvas');
            const gl = glCanvas.getContext('webgl') || glCanvas.getContext('experimental-webgl');
            if (gl) {
                const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                if (debugInfo) {
                    const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || '';
                    details.renderer = renderer;
                    const lower = renderer.toLowerCase();
                    if (lower.includes('swiftshader') || lower.includes('llvmpipe') || lower.includes('software')) {
                        score -= 20;
                    } else {
                        score += 10;
                    }
                }
                // Lose the WebGL context to free GPU resources
                const loseCtx = gl.getExtension('WEBGL_lose_context');
                if (loseCtx) loseCtx.loseContext();
            }
            // Release probe canvas
            glCanvas.width = 0;
            glCanvas.height = 0;
        } catch (e) {
            // WebGL unavailable, no adjustment
        }

        // Clamp score
        score = Math.max(0, Math.min(100, score));
        this._hardwareScore = score;

        // Determine tier
        if (score >= 70) this._hardwareTier = 'high';
        else if (score >= 45) this._hardwareTier = 'medium';
        else if (score >= 20) this._hardwareTier = 'low';
        else this._hardwareTier = 'fallback';

        details.score = score;
        details.tier = this._hardwareTier;

        return this._hardwareTier;
    },

    // =========================================================================
    // Cyberpunk Smoke/Mist Effect
    // =========================================================================

    // Cyberpunk color palette
    _SMOKE_COLORS: [
        [76, 201, 240],   // Cyan
        [247, 37, 133],   // Magenta
        [114, 9, 183],    // Purple
        [250, 204, 21],   // Yellow
        [245, 158, 11],   // Orange
        [239, 68, 68]     // Red
    ],

    // Tier-specific configurations for noise-based smoke
    _SMOKE_TIERS: {
        high:   { scale: 6,  octaves: 5, colorTint: true,  colorRegions: 3 },
        medium: { scale: 8,  octaves: 4, colorTint: true,  colorRegions: 2 },
        low:    { scale: 10, octaves: 3, colorTint: false, colorRegions: 0 }
    },

    // Fallback tier config (separate since it uses different particle type)
    _SMOKE_FALLBACK_CFG: { count: 6, sizes: [[50,130],[120,280],[250,500],[420,800],[650,1100],[900,1500]], opacity: 0.08 },

    /**
     * Initialize cyberpunk smoke effect
     * Checks settings and accessibility preferences before starting
     */
    _initCyberpunkSmoke() {
        // Check enable_mist_effect setting via body attribute
        const mistEnabled = document.body.getAttribute('data-mist-enabled');
        if (mistEnabled === 'false') return;

        // Respect prefers-reduced-motion
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

        // Carry on from the previous page if it was a moment ago
        const state = this._takeSmokeState();
        const tier = state ? state.tier : this._detectHardwareTier();

        if (tier !== 'fallback' && this._initSmokeGL(tier)) {
            if (state && state.isNoise) this._smokeTime = state.smokeTime || 0;
        } else {
            // No graphics card to draw it (or a software one): soft blobs instead
            this._createCanvas('cyberpunkSmokeCanvas');
            this._activeEffect = 'cyberpunk';
            if (!(state && state.isFallback && this._restoreFallbackBalls(state.particles))) {
                this._initSmokeFallback();
            }
        }

        this._startEffectLoop();
    },

    // =========================================================================
    // Smoke State Persistence (across page navigations)
    // =========================================================================

    /**
     * Save current smoke state to sessionStorage
     * Called on beforeunload so the next page can restore seamlessly
     */
    _saveSmokeState() {
        if (this._activeEffect !== 'cyberpunk') return;
        if (!this._canvas) return;

        const w = this._canvas.width;
        const h = this._canvas.height;
        if (w === 0 || h === 0) return;

        const isFallback = !!this._smokeFallbackBalls;
        const isNoise = !!this._smokeGL;

        if (!isFallback && !isNoise) return;

        const state = {
            timestamp: Date.now(),
            tier: this._hardwareTier,
            score: this._hardwareScore,
            isFallback: isFallback,
            isNoise: isNoise
        };

        if (isFallback) {
            state.particles = this._smokeFallbackBalls.map(p => ({
                xr: p.x / w, yr: p.y / h,
                sz: p.size, c: p.color, o: p.opacity,
                l: p.life, ls: p.lifespan, ff: p.fadeFrames,
                dx: p.dx, dy: p.dy
            }));
        } else if (isNoise) {
            state.smokeTime = this._smokeTime;
        }

        try {
            sessionStorage.setItem(this._SMOKE_STATE_KEY, JSON.stringify(state));
        } catch (e) {
            // sessionStorage full or unavailable — no persistence, not critical
        }
    },

    /**
     * The state the previous page saved, if it is under 5 seconds old (a
     * normal page navigation), else null. Read once, then cleared. Restores
     * the cached hardware tier so it is not benchmarked again.
     */
    _takeSmokeState() {
        try {
            const raw = sessionStorage.getItem(this._SMOKE_STATE_KEY);
            if (!raw) return null;
            sessionStorage.removeItem(this._SMOKE_STATE_KEY);

            const state = JSON.parse(raw);
            if (Date.now() - state.timestamp > 5000) return null;
            if (!(state.tier in this._SMOKE_TIERS) && state.tier !== 'fallback') return null;

            this._hardwareTier = state.tier;
            this._hardwareScore = state.score;
            return state;
        } catch (e) {
            return null;
        }
    },

    /** Put the saved fallback blobs back; false if there were none. */
    _restoreFallbackBalls(particles) {
        if (!particles || !particles.length) return false;
        const w = this._canvas.width;
        const h = this._canvas.height;
        this._smokeCfg = this._SMOKE_FALLBACK_CFG;
        this._smokeFallbackBalls = particles.map(p => ({
            x: p.xr * w,
            y: p.yr * h,
            size: p.sz,
            color: p.c,
            opacity: p.o,
            life: p.l,
            lifespan: p.ls,
            fadeFrames: p.ff,
            dx: p.dx,
            dy: p.dy
        }));
        return true;
    },

    // =========================================================================
    // Noise-Based Volumetric Smoke (HIGH / MEDIUM / LOW tiers), on the GPU
    // =========================================================================

    /**
     * Start the smoke shader on a new canvas. False, with the canvas gone
     * again, when there is no WebGL, it runs in software (the processor would
     * do the work after all), or the shader does not build.
     */
    _initSmokeGL(tier) {
        const cfg = this._SMOKE_TIERS[tier];
        if (!cfg) return false;
        this._createCanvas('cyberpunkSmokeCanvas', true);
        this._activeEffect = 'cyberpunk';
        const canvas = this._canvas;
        const gl = canvas.getContext('webgl', {
            alpha: true, premultipliedAlpha: true, antialias: false,
            depth: false, stencil: false, powerPreference: 'low-power'
        });
        const fail = () => { this._destroyCanvas(); return false; };
        if (!gl) return fail();

        const info = gl.getExtension('WEBGL_debug_renderer_info');
        const renderer = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL) || '') : '';
        if (/swiftshader|llvmpipe|software/i.test(renderer)) return fail();

        const compile = (type, src) => {
            const sh = gl.createShader(type);
            gl.shaderSource(sh, src);
            gl.compileShader(sh);
            return gl.getShaderParameter(sh, gl.COMPILE_STATUS) ? sh : null;
        };
        const vs = compile(gl.VERTEX_SHADER, this._SMOKE_VERTEX);
        const fs = compile(gl.FRAGMENT_SHADER, this._SMOKE_FRAGMENT);
        if (!vs || !fs) return fail();
        const prog = gl.createProgram();
        gl.attachShader(prog, vs);
        gl.attachShader(prog, fs);
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return fail();
        gl.useProgram(prog);

        // One rectangle over the whole canvas
        gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        const pos = gl.getAttribLocation(prog, 'p');
        gl.enableVertexAttribArray(pos);
        gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

        // Colour tint per column, one row tall; filled by _sizeSmokeCanvas
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.uniform1i(gl.getUniformLocation(prog, 'u_regions'), 0);
        gl.uniform1i(gl.getUniformLocation(prog, 'u_octaves'), cfg.octaves);
        gl.uniform1f(gl.getUniformLocation(prog, 'u_tint'), cfg.colorTint ? 1 : 0);

        // A lost context (driver reset, too many contexts) falls back to blobs
        canvas.addEventListener('webglcontextlost', () => {
            if (!this._smokeGL || this._canvas !== canvas) return;
            this._destroyCanvas();
            this._hardwareTier = 'fallback';
            this._initCyberpunkSmoke();
        });

        this._smokeCfg = cfg;
        this._smokeGL = {
            gl,
            uRes: gl.getUniformLocation(prog, 'u_res'),
            uTime: gl.getUniformLocation(prog, 'u_time')
        };
        this._smokeTime = 0;
        this._sizeSmokeCanvas();
        return true;
    },

    /**
     * Size the smoke canvas to the window divided by the tier's scale (the
     * browser stretches it to fill the window), and redo the colour tint,
     * whose columns follow the canvas width.
     */
    _sizeSmokeCanvas() {
        const s = this._smokeGL;
        const cfg = this._smokeCfg;
        const gl = s.gl;
        const bw = Math.max(1, Math.ceil(window.innerWidth / cfg.scale));
        const bh = Math.max(1, Math.ceil(window.innerHeight / cfg.scale));
        this._canvas.width = bw;
        this._canvas.height = bh;
        this._smokeBufW = bw;
        this._smokeBufH = bh;
        gl.viewport(0, 0, bw, bh);
        gl.uniform2f(s.uRes, bw, bh);

        if (cfg.colorTint && cfg.colorRegions > 0) {
            this._computeColorRegions(cfg.colorRegions);
            // Clamped: left of the first anchor the blend can pass 255, and a
            // plain Uint8Array would wrap it round into dark stripes.
            const px = new Uint8ClampedArray(bw * 4);
            for (let i = 0; i < bw; i++) {
                const c = this._smokeColorRegions[i];
                px[i * 4] = c[0];
                px[i * 4 + 1] = c[1];
                px[i * 4 + 2] = c[2];
                px[i * 4 + 3] = 255;
            }
            gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, bw, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, px);
        }
    },

    /**
     * Pre-compute neon color tint per buffer column using smoothstep blending
     * between randomly placed color regions
     */
    _computeColorRegions(count) {
        const bw = this._smokeBufW;
        if (bw === 0) return;

        // Pick random anchor columns with colors
        const anchors = [];
        for (let i = 0; i < count; i++) {
            anchors.push({
                x: Math.random() * bw,
                color: this._SMOKE_COLORS[Math.random() * this._SMOKE_COLORS.length | 0]
            });
        }
        anchors.sort((a, b) => a.x - b.x);

        // Build per-column [r, g, b] array via nearest-anchor blending
        this._smokeColorRegions = new Array(bw);
        for (let col = 0; col < bw; col++) {
            // Find two nearest anchors (wrap around)
            let leftIdx = 0, rightIdx = 0;
            for (let i = 0; i < anchors.length; i++) {
                if (anchors[i].x <= col) leftIdx = i;
            }
            rightIdx = (leftIdx + 1) % anchors.length;
            const left = anchors[leftIdx];
            const right = anchors[rightIdx];

            let span = right.x - left.x;
            if (span <= 0) span = bw; // wrapped
            let t = (col - left.x) / span;
            if (t < 0) t += 1;
            // Smoothstep
            t = t * t * (3 - 2 * t);

            this._smokeColorRegions[col] = [
                left.color[0] + (right.color[0] - left.color[0]) * t,
                left.color[1] + (right.color[1] - left.color[1]) * t,
                left.color[2] + (right.color[2] - left.color[2]) * t
            ];
        }
    },

    /** One smoke frame: the shader does the work; this only moves time on. */
    _drawSmokeFrame() {
        const s = this._smokeGL;
        if (!s || s.gl.isContextLost()) return;
        s.gl.uniform1f(s.uTime, this._smokeTime);
        s.gl.drawArrays(s.gl.TRIANGLE_STRIP, 0, 4);
        this._smokeTime += 0.4 * this._SMOKE_FRAME_MS / 1000;   // 0.4 a second, whatever the frame rate
    },

    // =========================================================================
    // Cyberpunk Fallback (Gradient Blobs)
    // =========================================================================

    /**
     * Create fallback blob array for very low-end hardware
     */
    _initSmokeFallback() {
        this._smokeFallbackBalls = [];
        this._smokeCfg = this._SMOKE_FALLBACK_CFG;

        const w = this._canvas.width;
        const h = this._canvas.height;

        for (let i = 0; i < this._smokeCfg.count; i++) {
            this._smokeFallbackBalls.push(this._createFallbackBall(w, h, true));
        }
    },

    /**
     * Generate a random vivid neon RGB color from a random hue
     */
    _randomNeonColor() {
        const hue = Math.random() * 360;
        const sat = 0.8 + Math.random() * 0.2; // 80-100%
        const light = 0.5 + Math.random() * 0.2; // 50-70%

        // HSL to RGB conversion
        const c = (1 - Math.abs(2 * light - 1)) * sat;
        const x = c * (1 - Math.abs((hue / 60) % 2 - 1));
        const m = light - c / 2;
        let r, g, b;

        if (hue < 60)       { r = c; g = x; b = 0; }
        else if (hue < 120) { r = x; g = c; b = 0; }
        else if (hue < 180) { r = 0; g = c; b = x; }
        else if (hue < 240) { r = 0; g = x; b = c; }
        else if (hue < 300) { r = x; g = 0; b = c; }
        else                { r = c; g = 0; b = x; }

        return [
            Math.round((r + m) * 255),
            Math.round((g + m) * 255),
            Math.round((b + m) * 255)
        ];
    },

    /**
     * Factory for a single fallback blob with random neon color
     * @param {number} w - Canvas width
     * @param {number} h - Canvas height
     * @param {boolean} randomizeAge - Stagger initial age
     */
    _createFallbackBall(w, h, randomizeAge) {
        const cfg = this._smokeCfg;
        // Pick one of 6 size buckets randomly, then randomize within that bucket
        const bucket = cfg.sizes[Math.random() * cfg.sizes.length | 0];
        const size = bucket[0] + Math.random() * (bucket[1] - bucket[0]);
        const lifespan = 240 + Math.random() * 360; // 12-30s at 20fps
        const fadeFrames = 40; // ~2s fade

        // Random direction: angle + speed
        const angle = Math.random() * Math.PI * 2;
        const speed = 0.2 + Math.random() * 0.3;

        return {
            x: Math.random() * w,
            y: Math.random() * h,
            size: size,
            color: this._randomNeonColor(),
            opacity: cfg.opacity,
            life: randomizeAge ? Math.random() * lifespan | 0 : 0,
            lifespan: lifespan,
            fadeFrames: fadeFrames,
            dx: Math.cos(angle) * speed,
            dy: Math.sin(angle) * speed
        };
    },

    /**
     * Reset an existing fallback blob in-place (avoids object allocation on recycle)
     */
    _resetFallbackBall(b, w, h) {
        const cfg = this._smokeCfg;
        const bucket = cfg.sizes[Math.random() * cfg.sizes.length | 0];
        const angle = Math.random() * Math.PI * 2;
        const speed = 0.2 + Math.random() * 0.3;
        b.x = Math.random() * w;
        b.y = Math.random() * h;
        b.size = bucket[0] + Math.random() * (bucket[1] - bucket[0]);
        b.color = this._randomNeonColor();
        b.opacity = cfg.opacity;
        b.life = 0;
        b.lifespan = 240 + Math.random() * 360;
        b.fadeFrames = 40;
        b.dx = Math.cos(angle) * speed;
        b.dy = Math.sin(angle) * speed;
    },

    /**
     * Per-frame update + draw for fallback blobs
     */
    _drawCyberpunkFallbackFrame() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        if (!ctx || !canvas || !this._smokeFallbackBalls) return;

        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);

        for (let i = 0; i < this._smokeFallbackBalls.length; i++) {
            const b = this._smokeFallbackBalls[i];

            // Advance life
            b.life++;

            // Recycle when expired (reset in-place to avoid allocation)
            if (b.life >= b.lifespan) {
                this._resetFallbackBall(b, w, h);
                continue;
            }

            // Fade in/out
            let fadeAlpha = 1;
            if (b.life < b.fadeFrames) {
                fadeAlpha = b.life / b.fadeFrames;
            } else if (b.life > b.lifespan - b.fadeFrames) {
                fadeAlpha = (b.lifespan - b.life) / b.fadeFrames;
            }

            // Linear drift
            b.x += b.dx;
            b.y += b.dy;

            // Wrap around
            if (b.x < -b.size) b.x = w + b.size * 0.5;
            if (b.x > w + b.size) b.x = -b.size * 0.5;
            if (b.y < -b.size) b.y = h + b.size * 0.5;
            if (b.y > h + b.size) b.y = -b.size * 0.5;

            // Draw using cached offscreen gradient (no per-frame gradient allocation)
            const alpha = b.opacity * fadeAlpha;
            const halfSize = b.size / 2;
            const gradImg = this._getGradientImage(b.color, b.size, 'blob');
            ctx.globalAlpha = alpha;
            ctx.drawImage(gradImg, b.x - halfSize, b.y - halfSize, b.size, b.size);
        }

        ctx.globalAlpha = 1;
    },

    // =========================================================================
    // Christian — Golden Dust Motes (gentle upward-drifting light particles)
    // =========================================================================

    _initChristianDust() {
        this._createCanvas('christianDustCanvas');
        this._activeEffect = 'christian';
        this._dustTime = 0;

        const w = this._canvas.width;
        const h = this._canvas.height;
        const count = Math.min(60, Math.floor(w * h / 25000));
        this._dustParticles = [];
        for (let i = 0; i < count; i++) {
            this._dustParticles.push({
                x: Math.random() * w,
                y: Math.random() * h,
                size: 1.5 + Math.random() * 2.5,
                speed: 0.15 + Math.random() * 0.35,
                drift: (Math.random() - 0.5) * 0.3,
                phase: Math.random() * Math.PI * 2,
                brightness: 0.3 + Math.random() * 0.7,
            });
        }

        this._startEffectLoop();
    },

    _drawChristianDustFrame() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        if (!ctx || !canvas) return;

        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);
        this._dustTime += 0.02;

        // Soft divine light beam from top center
        const beamGrad = ctx.createRadialGradient(w * 0.5, 0, 0, w * 0.5, 0, h * 0.7);
        beamGrad.addColorStop(0, 'rgba(212, 168, 67, 0.06)');
        beamGrad.addColorStop(0.4, 'rgba(212, 168, 67, 0.02)');
        beamGrad.addColorStop(1, 'transparent');
        ctx.fillStyle = beamGrad;
        ctx.fillRect(0, 0, w, h);

        // Draw dust motes
        for (const p of this._dustParticles) {
            const flicker = Math.sin(this._dustTime * 1.5 + p.phase) * 0.3 + 0.7;
            const alpha = p.brightness * flicker * 0.4;
            const sway = Math.sin(this._dustTime * 0.8 + p.phase) * 8;

            ctx.globalAlpha = alpha;
            ctx.fillStyle = 'rgb(230, 200, 120)';
            ctx.beginPath();
            ctx.arc(p.x + sway, p.y, p.size, 0, Math.PI * 2);
            ctx.fill();

            // Soft glow around larger particles
            if (p.size > 2.5) {
                ctx.globalAlpha = alpha * 0.3;
                ctx.beginPath();
                ctx.arc(p.x + sway, p.y, p.size * 3, 0, Math.PI * 2);
                ctx.fill();
            }

            // Move upward
            p.y -= p.speed;
            p.x += p.drift;

            // Wrap around
            if (p.y < -10) {
                p.y = h + 10;
                p.x = Math.random() * w;
            }
            if (p.x < -20) p.x = w + 10;
            if (p.x > w + 20) p.x = -10;
        }

        ctx.globalAlpha = 1;
    },

    // =========================================================================
    // Blade Runner — Neon Rain (falling streaks with neon city reflections)
    // =========================================================================

    _initBladeRunnerRain() {
        this._createCanvas('bladeRunnerRainCanvas');
        this._activeEffect = 'bladerunner';
        this._rainTime = 0;

        const w = this._canvas.width;
        const h = this._canvas.height;
        const count = Math.min(200, Math.floor(w / 6));
        this._rainDrops = [];
        for (let i = 0; i < count; i++) {
            this._rainDrops.push(this._createRainDrop(w, h, true));
        }

        this._startEffectLoop();
    },

    _createRainDrop(w, h, randomY) {
        // Alternate between blue-white rain and occasional neon-tinted drops
        const neonChance = Math.random();
        let r, g, b;
        if (neonChance < 0.08) {
            // Pink neon reflection
            r = 255; g = 80; b = 160;
        } else if (neonChance < 0.14) {
            // Blue neon reflection
            r = 60; g = 160; b = 255;
        } else {
            // Normal rain (cool blue-white)
            r = 160 + Math.random() * 60 | 0;
            g = 180 + Math.random() * 50 | 0;
            b = 220 + Math.random() * 35 | 0;
        }
        return {
            x: Math.random() * w,
            y: randomY ? Math.random() * h : -(Math.random() * h * 0.3),
            length: 8 + Math.random() * 20,
            speed: 4 + Math.random() * 6,
            opacity: 0.08 + Math.random() * 0.15,
            r, g, b,
            wind: -0.3 - Math.random() * 0.5,
        };
    },

    _drawBladeRunnerRainFrame() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        if (!ctx || !canvas) return;

        const w = canvas.width;
        const h = canvas.height;
        ctx.clearRect(0, 0, w, h);
        this._rainTime += 0.01;

        // Neon glow pools at bottom (city lights reflecting on wet ground)
        const poolY = h * 0.92;
        ctx.globalAlpha = 0.03 + Math.sin(this._rainTime * 0.5) * 0.01;
        ctx.fillStyle = 'rgb(255, 45, 124)';
        ctx.fillRect(w * 0.05, poolY, w * 0.25, h - poolY);
        ctx.fillStyle = 'rgb(26, 159, 255)';
        ctx.fillRect(w * 0.65, poolY, w * 0.3, h - poolY);

        // Draw rain
        ctx.lineWidth = 1;
        for (const d of this._rainDrops) {
            ctx.globalAlpha = d.opacity;
            ctx.strokeStyle = `rgb(${d.r},${d.g},${d.b})`;
            ctx.beginPath();
            ctx.moveTo(d.x, d.y);
            ctx.lineTo(d.x + d.wind * 2, d.y + d.length);
            ctx.stroke();

            // Move
            d.y += d.speed;
            d.x += d.wind;

            // Reset when off-screen
            if (d.y > h + 10) {
                Object.assign(d, this._createRainDrop(w, h, false));
            }
        }

        ctx.globalAlpha = 1;
    },

    // =========================================================================
    // Elite — 1984 Vector Starfield (stars streaming past like hyperspace)
    // =========================================================================

    _eliteStars: null,
    _eliteTime: 0,

    _initEliteStarfield() {
        this._createCanvas('eliteStarfieldCanvas');
        this._activeEffect = 'elite';
        this._eliteTime = 0;

        const w = this._canvas.width;
        const h = this._canvas.height;
        const count = Math.min(120, Math.floor(w / 12));
        this._eliteStars = [];
        for (let i = 0; i < count; i++) {
            this._eliteStars.push(this._createEliteStar(w, h, true));
        }

        this._startEffectLoop();
    },

    _createEliteStar(w, h, randomZ) {
        return {
            x: (Math.random() - 0.5) * w * 2,
            y: (Math.random() - 0.5) * h * 2,
            z: randomZ ? Math.random() * 1000 : 1000 + Math.random() * 200,
            pz: 0,  // previous z for streak
        };
    },

    _drawEliteStarfieldFrame() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        if (!ctx || !canvas) return;

        const w = canvas.width;
        const h = canvas.height;
        const cx = w / 2;
        const cy = h / 2;

        // Fade trail instead of full clear — gives subtle streaking
        ctx.fillStyle = 'rgba(0, 0, 0, 0.15)';
        ctx.fillRect(0, 0, w, h);

        this._eliteTime += 0.005;
        const speed = 8;

        ctx.strokeStyle = '#00ff00';
        ctx.lineWidth = 1;

        for (const s of this._eliteStars) {
            s.pz = s.z;
            s.z -= speed;

            if (s.z <= 1) {
                Object.assign(s, this._createEliteStar(w, h, false));
                s.pz = s.z;
                continue;
            }

            // Project current position
            const sx = (s.x / s.z) * 300 + cx;
            const sy = (s.y / s.z) * 300 + cy;

            // Project previous position (streak tail)
            const px = (s.x / s.pz) * 300 + cx;
            const py = (s.y / s.pz) * 300 + cy;

            // Skip if off screen
            if (sx < 0 || sx > w || sy < 0 || sy > h) continue;

            // Brightness based on depth (closer = brighter)
            const brightness = 1 - s.z / 1000;
            ctx.globalAlpha = Math.max(0.05, brightness * 0.6);

            ctx.beginPath();
            ctx.moveTo(px, py);
            ctx.lineTo(sx, sy);
            ctx.stroke();

            // Bright dot at head of streak for close stars
            if (brightness > 0.6) {
                ctx.globalAlpha = brightness * 0.8;
                ctx.fillStyle = '#00ff00';
                ctx.fillRect(sx - 0.5, sy - 0.5, 1, 1);
            }
        }

        ctx.globalAlpha = 1;
    }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => ThemeManager.init());

// Export globally
window.ThemeManager = ThemeManager;
