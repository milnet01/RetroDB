/**
 * RetroDB Theme Manager
 * Handles theme switching, persistence, and canvas background effects
 * (Matrix digital rain, Ocean moon reflection, Cyberpunk smoke/mist)
 */

const ThemeManager = {
    THEMES: ['cyberpunk', 'matrix', 'amber', 'ocean', 'christian', 'bladerunner', 'elite'],
    STORAGE_KEY: 'retrodb-theme',
    _SMOKE_STATE_KEY: 'retrodb-smoke-state',
    _rafId: null,
    _canvas: null,
    _ctx: null,
    _lastFrame: 0,
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

    // Noise-based smoke state (high/medium/low tiers)
    _smokeTime: 0,
    _smokeOffscreen: null,
    _smokeOffCtx: null,
    _smokeImageData: null,
    _smokePixels: null,
    _smokeBufW: 0,
    _smokeBufH: 0,
    _smokeColorRegions: null,

    // Offscreen gradient cache (used by fallback blobs)
    _gradientCache: new Map(),

    // =========================================================================
    // Embedded Simplex Noise (josephg/noisejs, public domain)
    // Only simplex3 is needed — minimal ~80 line extraction
    // =========================================================================

    _noise: (() => {
        // Permutation table (Perlin's original 256-entry table, doubled)
        const F3 = 1 / 3, G3 = 1 / 6;
        const grad3 = [
            [1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],
            [1,0,1],[-1,0,1],[1,0,-1],[-1,0,-1],
            [0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]
        ];
        const p = [151,160,137,91,90,15,131,13,201,95,96,53,194,233,7,225,
            140,36,103,30,69,142,8,99,37,240,21,10,23,190,6,148,
            247,120,234,75,0,26,197,62,94,252,219,203,117,35,11,32,
            57,177,33,88,237,149,56,87,174,20,125,136,171,168,68,175,
            74,165,71,134,139,48,27,166,77,146,158,231,83,111,229,122,
            60,211,133,230,220,105,92,41,55,46,245,40,244,102,143,54,
            65,25,63,161,1,216,80,73,209,76,132,187,208,89,18,169,
            200,196,135,130,116,188,159,86,164,100,109,198,173,186,3,64,
            52,217,226,250,124,123,5,202,38,147,118,126,255,82,85,212,
            207,206,59,227,47,16,58,17,182,189,28,42,223,183,170,213,
            119,248,152,2,44,154,163,70,221,153,101,155,167,43,172,9,
            129,22,39,253,19,98,108,110,79,113,224,232,178,185,112,104,
            218,246,97,228,251,34,242,193,238,210,144,12,191,179,162,241,
            81,51,145,235,249,14,239,107,49,192,214,31,181,199,106,157,
            184,84,204,176,115,121,50,45,127,4,150,254,138,236,205,93,
            222,114,67,29,24,72,243,141,128,195,78,66,215,61,156,180];
        const perm = new Uint8Array(512);
        const permMod12 = new Uint8Array(512);
        for (let i = 0; i < 512; i++) {
            perm[i] = p[i & 255];
            permMod12[i] = perm[i] % 12;
        }

        function dot3(g, x, y, z) { return g[0] * x + g[1] * y + g[2] * z; }

        return {
            seed(s) {
                // Simple seed shuffle (xorshift-inspired)
                if (s > 0 && s < 1) s *= 65536;
                s = Math.floor(s);
                if (s < 256) s |= s << 8;
                for (let i = 0; i < 256; i++) {
                    let v = (i & 1) ? (p[i] ^ (s & 255)) : (p[i] ^ ((s >> 8) & 255));
                    perm[i] = perm[i + 256] = v;
                    permMod12[i] = permMod12[i + 256] = v % 12;
                }
            },
            simplex3(xin, yin, zin) {
                const s = (xin + yin + zin) * F3;
                const i = Math.floor(xin + s), j = Math.floor(yin + s), k = Math.floor(zin + s);
                const t = (i + j + k) * G3;
                const X0 = i - t, Y0 = j - t, Z0 = k - t;
                const x0 = xin - X0, y0 = yin - Y0, z0 = zin - Z0;
                let i1, j1, k1, i2, j2, k2;
                if (x0 >= y0) {
                    if (y0 >= z0)      { i1=1;j1=0;k1=0;i2=1;j2=1;k2=0; }
                    else if (x0 >= z0) { i1=1;j1=0;k1=0;i2=1;j2=0;k2=1; }
                    else               { i1=0;j1=0;k1=1;i2=1;j2=0;k2=1; }
                } else {
                    if (y0 < z0)       { i1=0;j1=0;k1=1;i2=0;j2=1;k2=1; }
                    else if (x0 < z0)  { i1=0;j1=1;k1=0;i2=0;j2=1;k2=1; }
                    else               { i1=0;j1=1;k1=0;i2=1;j2=1;k2=0; }
                }
                const x1 = x0 - i1 + G3, y1 = y0 - j1 + G3, z1 = z0 - k1 + G3;
                const x2 = x0 - i2 + 2*G3, y2 = y0 - j2 + 2*G3, z2 = z0 - k2 + 2*G3;
                const x3 = x0 - 1 + 3*G3, y3 = y0 - 1 + 3*G3, z3 = z0 - 1 + 3*G3;
                const ii = i & 255, jj = j & 255, kk = k & 255;
                let n0 = 0, n1 = 0, n2 = 0, n3 = 0;
                let t0 = 0.6 - x0*x0 - y0*y0 - z0*z0;
                if (t0 > 0) { t0 *= t0; n0 = t0 * t0 * dot3(grad3[permMod12[ii+perm[jj+perm[kk]]]], x0, y0, z0); }
                let t1 = 0.6 - x1*x1 - y1*y1 - z1*z1;
                if (t1 > 0) { t1 *= t1; n1 = t1 * t1 * dot3(grad3[permMod12[ii+i1+perm[jj+j1+perm[kk+k1]]]], x1, y1, z1); }
                let t2 = 0.6 - x2*x2 - y2*y2 - z2*z2;
                if (t2 > 0) { t2 *= t2; n2 = t2 * t2 * dot3(grad3[permMod12[ii+i2+perm[jj+j2+perm[kk+k2]]]], x2, y2, z2); }
                let t3 = 0.6 - x3*x3 - y3*y3 - z3*z3;
                if (t3 > 0) { t3 *= t3; n3 = t3 * t3 * dot3(grad3[permMod12[ii+1+perm[jj+1+perm[kk+1]]]], x3, y3, z3); }
                return 32 * (n0 + n1 + n2 + n3); // Returns -1..1
            }
        };
    })(),

    /**
     * Initialize theme system
     */
    init() {
        const saved = localStorage.getItem(this.STORAGE_KEY) || 'cyberpunk';
        this.apply(saved, false);

        // Guard against duplicate listeners on re-init
        if (!this._listenersSet) {
            this._listenersSet = true;

            // Pause/resume canvas effects on tab visibility change
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    this._pauseEffect();
                } else if (this._canvas && this._activeEffect) {
                    this._startEffectLoop();
                }
            });

            // Save smoke state before page unload so it persists across navigations
            window.addEventListener('beforeunload', () => this._saveSmokeState());
        }
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
        if (!reduceMotion) {
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
        });

        // Save to server
        if (save) {
            this.save(theme);
        }
    },

    /**
     * Persist theme choice to server settings
     * @param {string} theme - Theme name
     */
    save(theme) {
        API.post('/api/settings', { theme: theme })
            .catch(err => console.error('Failed to save theme:', err));
    },

    // =========================================================================
    // Shared Canvas Management
    // =========================================================================

    _createCanvas(id) {
        const canvas = document.createElement('canvas');
        canvas.id = id;
        canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:-3;pointer-events:none;';
        document.body.appendChild(canvas);
        this._canvas = canvas;
        this._ctx = canvas.getContext('2d');
        let resizeTimer;
        this._boundResize = () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => this._resizeCanvas(), 150);
        };
        window.addEventListener('resize', this._boundResize, { passive: true });
        this._resizeCanvas();
    },

    _destroyCanvas() {
        if (this._rafId) {
            cancelAnimationFrame(this._rafId);
            this._rafId = null;
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
        // Release noise smoke buffer resources
        if (this._smokeOffscreen) {
            this._smokeOffscreen.width = 0;
            this._smokeOffscreen.height = 0;
        }
        this._smokeOffscreen = null;
        this._smokeOffCtx = null;
        this._smokeImageData = null;
        this._smokePixels = null;
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
    },

    _resizeCanvas() {
        if (!this._canvas) return;

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

        // Noise smoke: recreate buffer at new proportions
        if (this._activeEffect === 'cyberpunk' && this._smokeOffscreen) {
            this._createSmokeBuffer();
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

    _startEffectLoop() {
        if (this._rafId) return;
        this._lastFrame = 0;

        const loop = (timestamp) => {
            this._rafId = requestAnimationFrame(loop);

            // Throttle to ~20fps for low CPU usage
            if (timestamp - this._lastFrame < 50) return;
            this._lastFrame = timestamp;

            if (this._activeEffect === 'matrix') {
                this._drawMatrixFrame();
            } else if (this._activeEffect === 'ocean') {
                this._drawOceanFrame();
            } else if (this._activeEffect === 'cyberpunk') {
                if (this._hardwareTier === 'fallback') {
                    this._drawCyberpunkFallbackFrame();
                } else {
                    this._drawSmokeFrame();
                }
            } else if (this._activeEffect === 'christian') {
                this._drawChristianDustFrame();
            } else if (this._activeEffect === 'bladerunner') {
                this._drawBladeRunnerRainFrame();
            } else if (this._activeEffect === 'elite') {
                this._drawEliteStarfieldFrame();
            }
        };
        this._rafId = requestAnimationFrame(loop);
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

        this._createCanvas('cyberpunkSmokeCanvas');
        this._activeEffect = 'cyberpunk';

        // Try to restore state from previous page navigation
        if (this._restoreSmokeState()) {
            this._startEffectLoop();
            return;
        }

        // Fresh start: detect hardware and create system
        const tier = this._detectHardwareTier();

        if (tier === 'fallback') {
            this._initSmokeFallback();
        } else {
            this._initSmokeSystem(tier);
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
        const isNoise = !!this._smokeOffscreen;

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
     * Restore smoke state from sessionStorage
     * Returns true if state was successfully restored
     */
    _restoreSmokeState() {
        try {
            const raw = sessionStorage.getItem(this._SMOKE_STATE_KEY);
            if (!raw) return false;

            // Clear after reading (one-time restore)
            sessionStorage.removeItem(this._SMOKE_STATE_KEY);

            const state = JSON.parse(raw);

            // Only restore if less than 5 seconds old (covers normal page navigations)
            if (Date.now() - state.timestamp > 5000) return false;

            // Restore cached hardware tier (avoids re-benchmarking)
            this._hardwareTier = state.tier;
            this._hardwareScore = state.score;

            const w = this._canvas.width;
            const h = this._canvas.height;

            if (state.isFallback) {
                if (!state.particles || !state.particles.length) return false;
                this._smokeCfg = this._SMOKE_FALLBACK_CFG;
                this._smokeFallbackBalls = state.particles.map(p => ({
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
            } else if (state.isNoise) {
                const tierCfg = this._SMOKE_TIERS[state.tier];
                if (!tierCfg) return false;
                this._smokeCfg = tierCfg;
                // Seed noise identically then restore time coordinate
                this._noise.seed(42);
                this._smokeTime = state.smokeTime || 0;
                this._createSmokeBuffer();
                if (tierCfg.colorTint && tierCfg.colorRegions > 0) {
                    this._computeColorRegions(tierCfg.colorRegions);
                }
            } else {
                return false;
            }

            return true;
        } catch (e) {
            return false;
        }
    },

    // =========================================================================
    // Noise-Based Volumetric Smoke (HIGH / MEDIUM / LOW tiers)
    // =========================================================================

    /**
     * Fractal Brownian motion: layer multiple octaves of simplex noise
     * for organic, detailed turbulence
     */
    _fbm(x, y, t, octaves) {
        let value = 0;
        let amplitude = 0.5;
        let frequency = 1;
        const noise = this._noise;
        for (let i = 0; i < octaves; i++) {
            value += amplitude * noise.simplex3(x * frequency, y * frequency, t * frequency);
            frequency *= 2;
            amplitude *= 0.5;
        }
        return value;
    },

    /**
     * Allocate (or reallocate) the offscreen buffer at tier-appropriate resolution
     */
    _createSmokeBuffer() {
        const cfg = this._smokeCfg;
        const scale = cfg.scale;
        const bw = Math.max(1, Math.ceil(this._canvas.width / scale));
        const bh = Math.max(1, Math.ceil(this._canvas.height / scale));

        // Reuse existing offscreen canvas if possible, just resize
        if (!this._smokeOffscreen) {
            this._smokeOffscreen = document.createElement('canvas');
            this._smokeOffCtx = this._smokeOffscreen.getContext('2d');
        }
        this._smokeOffscreen.width = bw;
        this._smokeOffscreen.height = bh;
        this._smokeBufW = bw;
        this._smokeBufH = bh;
        this._smokeImageData = this._smokeOffCtx.createImageData(bw, bh);
        this._smokePixels = this._smokeImageData.data;
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

    /**
     * Core density function: fBm noise + vertical gradient mask + upward scroll
     * Returns density 0..1
     */
    _smokeDensity(bx, by, time, octaves, bw, bh) {
        // Normalize buffer coords to noise space (scale for good detail)
        const nx = bx / bw * 3;
        const ny = by / bh * 3;

        // Upward scroll: offset y by time to simulate rising smoke
        const scrollY = ny - time * 0.3;

        // Primary fBm
        let density = this._fbm(nx, scrollY, time * 0.15, octaves);

        // Add turbulence layer (faster-scrolling distortion)
        const turb = this._noise.simplex3(nx * 2.5 + 100, scrollY * 2.5, time * 0.25) * 0.15;
        density += turb;

        // Map from [-1,1] to [0,1] range
        density = density * 0.5 + 0.5;

        // Vertical gradient mask: dense at bottom, dissipating upward
        // by = 0 is top, by = bh-1 is bottom
        const heightRatio = by / bh; // 0 = top, 1 = bottom
        // Smooth density falloff: full at bottom 30%, fades to 0 by top 15%
        let mask;
        if (heightRatio > 0.7) {
            mask = 1;
        } else if (heightRatio > 0.15) {
            // Smooth cubic falloff
            const t = (heightRatio - 0.15) / 0.55;
            mask = t * t * (3 - 2 * t);
        } else {
            mask = 0;
        }

        density *= mask;

        // Clamp
        if (density < 0) density = 0;
        if (density > 1) density = 1;

        return density;
    },

    /**
     * Initialize the noise-based smoke system for HIGH/MEDIUM/LOW tiers.
     * Seeds noise, creates offscreen buffer, pre-computes color regions.
     */
    _initSmokeSystem(tier) {
        const cfg = this._SMOKE_TIERS[tier];
        this._smokeCfg = cfg;

        // Seed noise deterministically
        this._noise.seed(42);
        this._smokeTime = 0;

        // Create downscaled offscreen buffer
        this._createSmokeBuffer();

        // Pre-compute color regions for tinting (high/medium only)
        if (cfg.colorTint && cfg.colorRegions > 0) {
            this._computeColorRegions(cfg.colorRegions);
        }
    },

    /**
     * Per-frame renderer: sample noise into low-res buffer, then upscale to main canvas.
     * Uses bilinear interpolation via drawImage for smooth appearance.
     */
    _drawSmokeFrame() {
        const ctx = this._ctx;
        const canvas = this._canvas;
        if (!ctx || !canvas || !this._smokeOffscreen) return;

        const bw = this._smokeBufW;
        const bh = this._smokeBufH;
        const cfg = this._smokeCfg;
        const pixels = this._smokePixels;
        const time = this._smokeTime;
        const octaves = cfg.octaves;
        const colorRegions = this._smokeColorRegions;
        const hasColor = cfg.colorTint && colorRegions;

        // Base smoke color (slightly blue-tinted white for monochrome glow)
        const baseR = 140, baseG = 160, baseB = 180;

        // Fill pixel buffer with noise-derived smoke density
        let idx = 0;
        for (let by = 0; by < bh; by++) {
            for (let bx = 0; bx < bw; bx++) {
                const density = this._smokeDensity(bx, by, time, octaves, bw, bh);

                // Alpha: scale density to visible but subtle range (max ~0.12 opacity)
                const alpha = density * 0.12 * 255;

                if (hasColor && alpha > 0.5) {
                    // Blend base color with region tint based on density intensity
                    const region = colorRegions[bx];
                    const tintStrength = density * 0.4; // How much color to mix in
                    const invTint = 1 - tintStrength;
                    pixels[idx]     = baseR * invTint + region[0] * tintStrength; // R
                    pixels[idx + 1] = baseG * invTint + region[1] * tintStrength; // G
                    pixels[idx + 2] = baseB * invTint + region[2] * tintStrength; // B
                } else {
                    pixels[idx]     = baseR; // R
                    pixels[idx + 1] = baseG; // G
                    pixels[idx + 2] = baseB; // B
                }
                pixels[idx + 3] = alpha; // A
                idx += 4;
            }
        }

        // Write pixels to offscreen canvas
        this._smokeOffCtx.putImageData(this._smokeImageData, 0, 0);

        // Clear main canvas and upscale with bilinear interpolation
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'medium';
        ctx.drawImage(this._smokeOffscreen, 0, 0, canvas.width, canvas.height);

        // Advance time
        this._smokeTime += 0.02;
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
