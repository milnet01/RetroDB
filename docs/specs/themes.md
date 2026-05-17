# Themes — Spec

Audience: maintainers and Claude Code sessions adding a new theme or modifying
existing theme behaviour. This spec consolidates the full surface that section
8 of `docs/RETRODB_DESIGN_STANDARDS.md` only summarises (variable layer,
`ThemeManager`, canvas effects, themed icons, accessibility, FOUC, persistence).

For the design-token variable list itself (what `--primary-cyan` etc. mean), do
not re-read it here — see design-standards §2 "Color System" and §8 "Theme
System". This spec covers the wiring, not the palette inventory.

---

## 1. Purpose

A "theme" in RetroDB is a coordinated re-skin of the whole UI: a CSS-variable
override set (colours, shadows, borders), a body-pseudo-element backdrop
(gradients + scanlines), an animated canvas background effect, and a per-theme
icon glyph table for toasts/notifications. Themes are user-selectable from
settings, persisted across reloads, and applied **before** first paint to avoid
flash-of-unstyled-content. Cyberpunk is the default and ships as the `:root`
baseline — every other theme is a `[data-theme="..."]` override on top of that
baseline.

---

## 2. Theme inventory

Seven themes ship today. The token used in `data-theme` is **not always** the
display name — see §8.

| Display name        | `data-theme` token | Primary (`--primary-cyan`) | Secondary (`--secondary-magenta`) | Canvas effect                                     | Status / notes                          |
|---------------------|--------------------|----------------------------|-----------------------------------|---------------------------------------------------|-----------------------------------------|
| Cyberpunk           | *(none — default)* | `#4cc9f0` cyan             | `#f72585` magenta                 | Volumetric smoke (simplex-noise fBm) + GPU tiers  | Default; `:root` baseline (no override) |
| Matrix              | `matrix`           | `#00ff41` green            | `#008f11` dark-green              | Digital rain (katakana + Latin)                   | Maintained                              |
| Retro Amber         | `amber`            | `#ffb000` amber            | `#ff6600` orange                  | (no canvas effect — relies on body-gradient only) | Maintained                              |
| Midnight Ocean      | `ocean`            | `#4dabf7` blue             | `#20c997` teal                    | Moon shimmer column + horizontal wave lines       | Maintained                              |
| Cathedral           | `christian`        | `#d4a843` gold             | `#7b4db0` royal-purple            | Golden dust motes + divine light beam             | Maintained; legacy token name           |
| Blade Runner        | `bladerunner`      | `#1a9fff` electric-blue    | `#ff2d7c` neon-pink               | Neon rain streaks + neon glow pools               | Maintained                              |
| Elite 1984          | `elite`            | `#00ff00` vector-green     | `#cccccc` vector-white            | 1984-style vector starfield (hyperspace streaks)  | Maintained                              |

Notes:

- **Amber has no canvas effect.** `apply()` does not call any `_initX` for
  `amber`; the theme's atmosphere comes entirely from the `body::before`
  sunrise gradient and the amber-tinted `body::after` scanlines. If a future
  pass adds an amber effect (e.g. CRT phosphor flicker), wire it through the
  same dispatch in `apply()` and `_startEffectLoop()`.
- **Cyberpunk is special-cased twice.** In `apply()`, when `theme === 'cyberpunk'`
  the `data-theme` attribute is *removed* rather than set — because cyberpunk
  is the `:root` baseline, not an override. And `_initCyberpunkSmoke` checks
  `data-mist-enabled` (a per-user setting on `<body>`) and bails early if
  disabled.

---

## 3. CSS layer

Per-theme overrides live in `static/css/core/themes.css` as
`[data-theme="name"] { ... }` blocks that re-bind a subset of the variables
defined in `static/css/core/variables.css` (`:root`).

### Minimum override surface (every theme MUST set these)

Each theme block currently overrides the full set below. Skipping any of them
falls back to the cyberpunk baseline value, which will almost certainly clash
visually. Treat the list as required:

- Primary palette: `--primary-cyan`, `--primary-cyan-dark`,
  `--primary-cyan-light`, `--primary-cyan-glow`
- Secondary palette: `--secondary-magenta`, `--secondary-magenta-dark`,
  `--secondary-magenta-light`, `--secondary-magenta-glow`
- Accents: `--accent-purple`, `--accent-blue`, `--accent-violet`
- Backgrounds: `--bg-darkest`, `--bg-dark`, `--bg-darker`, `--bg-medium`,
  `--bg-light`, `--bg-lighter`
- Cards: `--card-bg`, `--card-bg-hover`, `--card-border`, `--card-border-hover`
- Text: `--text-primary`, `--text-secondary`, `--text-muted`, `--text-accent`
- Border alias: `--border-color`
- Status palette: `--status-success`, `--status-warning`, `--status-error`,
  `--status-info`, `--status-online`, `--status-offline`, `--status-connected`
- Glow shadows: `--shadow-glow-cyan`, `--shadow-glow-magenta`
- Neon set: `--neon-cyan`, `--neon-green`, `--neon-orange`, `--neon-red`,
  `--neon-purple`, `--neon-gray`
- Trophy tiers: `--trophy-platinum`, `--trophy-gold`, `--trophy-silver`,
  `--trophy-bronze`
- Toast backgrounds: `--toast-bg-from`, `--toast-bg-to`,
  `--toast-queued-bg-from`, `--toast-queued-bg-to`

Plus two **mandatory pseudo-element blocks** per theme (these are the body
backdrop and scanlines — they don't fall back, they vanish if absent):

```css
[data-theme="newtheme"] body::before { background: <gradients>; }
[data-theme="newtheme"] body::after  { background: repeating-linear-gradient(...); }
```

### Optional

All other variables in `variables.css` (`:root`) — sidebar tokens, generic
shadow scale, transition tokens, modal tokens — are inherited unchanged unless
the theme has a specific reason to diverge.

---

## 4. JS layer (`ThemeManager`)

File: `static/js/theme.js`. Single module-style object exported as
`window.ThemeManager` and initialised on `DOMContentLoaded`.

### Surface

- `ThemeManager.THEMES` — frozen list of valid tokens:
  `['cyberpunk', 'matrix', 'amber', 'ocean', 'christian', 'bladerunner', 'elite']`.
  Order matters only for the settings picker; functional code keys off the
  string.
- `ThemeManager.STORAGE_KEY` — `'retrodb-theme'`. The localStorage key. **Stable
  across versions** — any rename invalidates every user's saved choice.
- `ThemeManager._SMOKE_STATE_KEY` — `'retrodb-smoke-state'`. sessionStorage
  key used to carry cyberpunk smoke state across page navigations (so the
  background doesn't visibly reset on every nav).
- `init()` — reads `localStorage[STORAGE_KEY]` (default `'cyberpunk'`), calls
  `apply(saved, false)` (the `false` suppresses a redundant server save on
  page load), and wires `visibilitychange` (pause/resume canvas) and
  `beforeunload` (save smoke state) listeners.
- `apply(theme, save = true)` — validates against `THEMES`, sets / removes the
  `data-theme` attribute on `<html>`, writes to localStorage, tears down any
  active canvas, then dispatches to the theme's `_initX` method (unless
  `prefers-reduced-motion: reduce` is true — see §6). Updates the
  `.theme-option` UI active state and (if `save`) POSTs to `/api/settings` so
  the choice is recorded server-side too.
- `save(theme)` — fire-and-forget POST to `/api/settings`.

### Per-theme methods (one pair each, plus dispatch)

| Theme       | Init                    | Per-frame draw                                                   |
|-------------|-------------------------|------------------------------------------------------------------|
| matrix      | `_initMatrixRain`       | `_drawMatrixFrame`                                               |
| ocean       | `_initOceanEffect`      | `_drawOceanFrame`                                                |
| cyberpunk   | `_initCyberpunkSmoke`   | `_drawSmokeFrame` (high/medium/low) or `_drawCyberpunkFallbackFrame` |
| christian   | `_initChristianDust`    | `_drawChristianDustFrame`                                        |
| bladerunner | `_initBladeRunnerRain`  | `_drawBladeRunnerRainFrame`                                      |
| elite       | `_initEliteStarfield`   | `_drawEliteStarfieldFrame`                                       |
| amber       | *(none)*                | *(none)*                                                         |

Dispatch happens in two places — both must be updated when adding a theme:
`apply()` (selecting the `_initX`) and `_startEffectLoop()` (selecting the
per-frame draw method based on `this._activeEffect`).

### Shared canvas plumbing

- `_createCanvas(id)` — appends a fixed-position, full-viewport `<canvas>` at
  `z-index: -3`, `pointer-events: none`. Stores it as `this._canvas` /
  `this._ctx` and attaches a debounced (150 ms) resize listener.
- `_destroyCanvas()` — cancels the RAF loop, zeroes the canvas dimensions
  (force-releases the bitmap backing store — important on mobile), removes the
  element, detaches the resize listener, and clears **every** per-theme state
  field (columns, dust, rain, smoke buffers, gradient cache). This is the
  one-stop teardown — new themes that hold state MUST clear it here.
- `_pauseEffect()` — cancels the RAF but leaves state intact, so
  `visibilitychange` can resume seamlessly.
- `_startEffectLoop()` — single RAF loop, **throttled to ~20 fps** (50 ms
  minimum frame budget) for low CPU. Dispatches to the active draw method.

### Hardware-tier detection (cyberpunk only)

`_detectHardwareTier()` runs once per session and caches into
`this._hardwareTier`. It scores 0–100 from:

- `navigator.hardwareConcurrency` (0–35)
- `navigator.deviceMemory` (0–20)
- Mobile UA penalty (−15)
- A 50-radial-gradient canvas micro-benchmark (0–35)
- WebGL renderer string probe — software renderers (SwiftShader, llvmpipe,
  "software") subtract 20; hardware adds 10

Tiers: `high ≥ 70`, `medium ≥ 45`, `low ≥ 20`, `fallback < 20`.

- `high` / `medium` / `low` use the simplex-noise volumetric pipeline
  (`_initSmokeSystem` → noise buffer, fBm density, optional colour regions).
- `fallback` switches to `_initSmokeFallback` — 6 large gradient blobs drifting
  with random neon colours, drawn via a cached offscreen-gradient pool
  (`_getGradientImage`) capped at 60 entries to avoid unbounded growth.

State is preserved across page navigations via sessionStorage
(`_saveSmokeState` on `beforeunload`, `_restoreSmokeState` on init). If the
saved state is older than 5 seconds it's discarded.

---

## 5. FOUC prevention

The inline script at the top of `templates/base.html` (lines ~13–18) runs
**before** the main stylesheet `<link>` and before `theme.js` loads:

```html
<script>
(function(){
    var t = localStorage.getItem('retrodb-theme');
    if (t && t !== 'cyberpunk') document.documentElement.setAttribute('data-theme', t);
})();
</script>
```

Why this matters:

- CSS variable overrides cascade via the `[data-theme="..."]` attribute
  selector. If the attribute isn't on `<html>` by the time the first paint
  resolves variable values, the page paints in cyberpunk colours and then
  re-paints into the user's theme as soon as `theme.js` runs in
  `DOMContentLoaded`. That visible flash is the FOUC bug this prevents.
- Cyberpunk is exempt because it's the `:root` baseline — no attribute needed.

What breaks if you defer it: any user on matrix/amber/ocean/christian/
bladerunner/elite sees a cyberpunk-cyan flash for one or two frames on every
page load. It's particularly jarring on the elite (pure-black) and matrix
(pure-green) themes.

Rules for this script:

- Keep it inline. **Do not** move it into an external `.js` file — external
  scripts are network-blocked and lose the pre-paint guarantee.
- Keep it minimal (no API calls, no DOM queries beyond `documentElement`).
- Use the literal `'retrodb-theme'` key — must match `ThemeManager.STORAGE_KEY`.

---

## 6. Canvas effects

Every non-amber theme ships an animated canvas backdrop. Contract:

- **Frame budget**: ~20 fps, enforced by `_startEffectLoop()` (50 ms
  `timestamp - this._lastFrame` gate). New effects should target the same.
- **Pause on hidden tab**: `visibilitychange` listener in `init()` calls
  `_pauseEffect()` when `document.hidden` and re-starts the loop when the tab
  becomes visible again. No work needed in the per-theme effect — it's all in
  the shared loop.
- **Destroy on theme switch**: every `apply()` call begins with
  `_destroyCanvas()`. State teardown is centralised there; per-theme state
  fields (e.g. `_dustParticles`, `_rainDrops`, `_eliteStars`,
  `_smokeFallbackBalls`) must be nulled in `_destroyCanvas` so they don't leak
  into the next theme.
- **Z-index / pointer events**: the canvas is `position: fixed`, full viewport,
  `z-index: -3`, `pointer-events: none`. It sits behind `body::before` (the
  gradient backdrop) and `body::after` (scanlines), so the canvas effect, the
  body gradient, and the scanlines all compose.

### Hardware-tier dispatch (cyberpunk only)

Cyberpunk is the only effect with a tiered pipeline. Other themes use a single
implementation regardless of hardware. If a new theme has expensive rendering,
follow the cyberpunk pattern: call `_detectHardwareTier()` and branch the
draw method.

### Reduced-motion respect (Pass 37, v3.4.0)

WCAG SC 2.3.3 "Animation from Interactions" requires honouring the OS-level
`prefers-reduced-motion: reduce` flag. CSS-driven animations are covered
project-wide by a `@media (prefers-reduced-motion: reduce)` block in
`reset.css`, but canvas effects ignore CSS, so they're gated explicitly in
`apply()`:

```js
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
if (!reduceMotion) {
    if (theme === 'matrix') { this._initMatrixRain(); }
    // ... etc
}
```

Cyberpunk has a second gate inside `_initCyberpunkSmoke` (the smoke effect is
particularly motion-heavy and is also disabled by the `enable_mist_effect`
user setting via the `data-mist-enabled` body attribute). New canvas effects
MUST sit inside the `!reduceMotion` branch in `apply()`.

---

## 7. Themed icons

**Important location note**: despite touching theme behaviour, `getThemedIcon`
is defined in `static/js/toast-controller.js`, not `theme.js`. (Historical:
themed icons grew out of the toast system.) `theme.js` does not depend on the
icon table — the two layers compose at render-time via `getThemedIcon`.

Surface: `getThemedIcon(key, fallback?) → string`. Reads
`document.documentElement.getAttribute('data-theme')` to pick the active
table; falls back to cyberpunk for unknown themes; falls back to the
`fallback` argument (or the cyberpunk entry for the same key, or the key
itself) for unknown keys. Always returns a string — never null/undefined.

Templates hook in via `data-themed-icon="key"` on any element; `main.js`'s
`DOMContentLoaded` handler walks `[data-themed-icon]` and sets
`textContent = getThemedIcon(el.dataset.themedIcon)`. JS callers use the
function directly.

### Key categories

Pulled from `ThemeIcons` in `toast-controller.js` (~line 72) and CLAUDE.md:

| Category       | Keys                                                                                       |
|----------------|--------------------------------------------------------------------------------------------|
| Job types      | `bulk-scrape`, `ra-sync`, `ra-refresh`, `psn-refresh`, `image-resize`                      |
| Job states     | `paused`, `resume`, `complete`, `queued`, `cancelled`, `background`                        |
| Notifications  | `success`, `error`, `warning`, `info`                                                      |
| Stats          | `stat-success`, `stat-failed`, `stat-skipped`                                              |
| Actions        | `starting`, `running`, `cancel`, `save`, `loading`                                         |

### Sample mapping (illustrative — see source for the full table)

| Key       | cyberpunk | matrix | amber | ocean | christian | bladerunner | elite |
|-----------|-----------|--------|-------|-------|-----------|-------------|-------|
| `success` | `✅`      | `✓`    | `●`   | `◉`   | `✧`       | `◉`         | `OK`  |
| `error`   | `❌`      | `✗`    | `■`   | `⊘`   | `✘`       | `✕`         | `X`   |
| `warning` | `⚠️`     | `▲`    | `▲`   | `◈`   | `◈`       | `◈`         | `!`   |
| `queued`  | `📋`      | `≡`    | `░`   | `⊕`   | `⚜`       | `▫`         | `...` |
| `loading` | `🔄`      | `⟳`    | `↻`   | `↺`   | `❋`       | `⟲`         | `~`   |

Pattern: cyberpunk uses full-colour emoji; every other theme uses
monochrome / ASCII / Unicode-glyph variants that match its aesthetic
(matrix → minimalist, elite → pure ASCII, christian → cross/fleur-de-lis,
bladerunner → squares and hexagons).

---

## 8. Display-name vs token mapping

Three themes display under a different name than their `data-theme` token:

| Display name (settings UI) | `data-theme` token | Reason for divergence                                  |
|----------------------------|--------------------|--------------------------------------------------------|
| Cathedral                  | `christian`        | Legacy key — predates the Cathedral re-branding        |
| Blade Runner               | `bladerunner`      | Tokens are `[a-z]` only (HTML attribute hygiene)       |
| Elite 1984                 | `elite`            | Tokens are `[a-z]` only — year and brand stripped      |

Tokens are stable across versions; the display name lives in
`templates/settings.html` (Display Preferences section, around line 455) and
can be changed freely without invalidating saved preferences. Renaming a
**token** would silently reset every user back to cyberpunk — don't.

---

## 9. Accessibility / contrast

Themes must satisfy WCAG 2.2 AA contrast ratios for body text, secondary text,
muted text, and primary UI controls.

Tooling: `scripts/audit_contrast.py` parses `variables.css` and `themes.css`,
computes relative-luminance contrast for the text/background pairs each theme
actually uses, and writes a markdown report to `docs/theme_contrast.md` with
PASS / FAIL / NOTE rows.

Thresholds applied:

- **4.5:1** — normal body text (`--text-primary`, `--text-secondary`,
  `--text-muted` over backgrounds)
- **3.0:1** — large text (≥ 18pt regular or 14pt bold) and graphical UI
  controls (`--primary-cyan`, `--secondary-magenta` for buttons / icons)

When to run:

- After any colour-variable change in `variables.css` or `themes.css`
- Before bumping a minor version that touches theme palettes
- As part of independent-review accessibility sweeps

```bash
python3 scripts/audit_contrast.py   # writes docs/theme_contrast.md
```

The script exits 0 regardless — it's a report, not a CI gate. CI can grep the
output for `FAIL` lines.

Known fix-from-audit example: blade runner `--text-muted` was bumped from
`#505868` to `#78809a` to clear 4.5:1 on both `--bg-darkest` (5.10) and
`--card-bg` (4.92). Comment in `themes.css` records the change so it isn't
"cleaned up" later.

---

## 10. Adding a new theme

Seven mechanical steps. Most live in well-known files; the icon step (6) is
the one most easily missed.

1. **Add CSS variable overrides.** New block in
   `static/css/core/themes.css`:

   ```css
   [data-theme="newtheme"] {
       --primary-cyan: ...;
       /* ...full surface from §3 — all primary, secondary, accent, bg, card,
          text, border, status, shadow-glow, neon, trophy, toast variables */
   }
   [data-theme="newtheme"] body::before { background: <atmospheric gradients>; }
   [data-theme="newtheme"] body::after  { background: repeating-linear-gradient(...); }
   ```

   What this does: re-binds the design tokens. Every existing component
   already references the variables, so the entire UI re-skins.

2. **Register the token.** Add `'newtheme'` to `ThemeManager.THEMES` in
   `static/js/theme.js` (line ~8). What this does: validates the string in
   `apply()` (unknown tokens fall back to `'cyberpunk'`).

3. **Write the canvas effect** (optional — skip for static themes like amber).
   Add an `_initNewTheme()` + `_drawNewThemeFrame()` pair to `ThemeManager`.
   Init creates the canvas (`_createCanvas('newThemeCanvas')`), sets
   `this._activeEffect = 'newtheme'`, seeds state, then calls
   `_startEffectLoop()`. The draw method runs once per frame at ~20 fps.

4. **Wire the dispatch.** Two adds in `theme.js`:
   - In `apply()` inside the `if (!reduceMotion)` branch, add
     `else if (theme === 'newtheme') { this._initNewTheme(); }`.
   - In `_startEffectLoop()`'s loop body, add
     `else if (this._activeEffect === 'newtheme') { this._drawNewThemeFrame(); }`.

5. **Add teardown.** In `_destroyCanvas()`, null out any per-theme state
   fields you added (e.g. `this._newThemeParticles = null;`). What this does:
   prevents leftover state from contaminating the next theme.

6. **Add the icon table.** New entry in `ThemeIcons` in
   `static/js/toast-controller.js` (around line 72). All 26 keys (see §7) MUST
   be present — `getThemedIcon` falls back per-key to cyberpunk, so missing
   keys won't crash, but it'll look incoherent. Pick glyphs that match the
   theme's aesthetic. **This step is also where bundle membership matters:**
   `toast-controller.js` *is* in `core.bundle.js`, so you must run
   `python3 build_js.py` after editing.

7. **Add the picker UI.** New `.theme-option` card in `templates/settings.html`
   under the Display Preferences section (around line 455):

   ```html
   <div class="theme-option" data-theme="newtheme" onclick="ThemeManager.apply('newtheme')">
       <div class="theme-preview newtheme-preview"></div>
       <span class="theme-name">New Theme</span>
   </div>
   ```

   Display name here can differ from the token (see §8). Add a matching
   `.newtheme-preview` selector in the settings CSS for the swatch.

No `theme.js` bundle rebuild is needed — `theme.js` is loaded standalone (see
§11). The cache-bust on `?v={{ config.APP_VERSION }}` picks up the change on
the next version bump.

---

## 11. Bundle membership

`static/js/theme.js` is **NOT** part of `core.bundle.js`. It is loaded
standalone from `templates/base.html` (around line 359):

```html
<script src="{{ url_for('static', filename='js/theme.js') }}?v={{ config.APP_VERSION }}"></script>
```

Why standalone:

- The inline FOUC-prevention script (§5) must run pre-paint, but it only sets
  the attribute — the full `ThemeManager.init()` needs to run on
  `DOMContentLoaded` to start canvas effects. Keeping `theme.js` outside the
  core bundle keeps both halves small and lets the rest of the bundle parse in
  parallel.
- Cache-bust is via `?v={{ APP_VERSION }}` query string, **not** via the
  `asset_manifest.json` SHA-prefix system used for bundled assets — because
  `theme.js` isn't run through `build_js.py`. After editing `theme.js`, the
  next version bump invalidates the cached file for all users.

`toast-controller.js` (which owns `getThemedIcon`) **is** in `core.bundle.js`
— so editing the `ThemeIcons` table requires `python3 build_js.py`.

---

## 12. Testability

What can be tested:

- **No FOUC**: load the app in a non-cyberpunk theme, hard-reload, capture
  paint timeline in DevTools — first paint should already show the chosen
  theme. (Manual only; not automated.)
- **Persistence across reload**: `localStorage['retrodb-theme'] === <chosen>`
  after switching themes; reload → theme stays.
- **Persistence across navigation**: switch to cyberpunk, navigate between
  pages — smoke effect should appear continuous (sessionStorage handoff).
- **Theme switch teardown**: switch between all 7 themes in sequence; check
  DevTools Memory snapshot shows no orphaned canvas elements / gradient cache
  bloat.
- **Reduced-motion gate**: enable `prefers-reduced-motion: reduce` in
  DevTools rendering panel, reload — no canvas should be attached.
- **Contrast pass**: `python3 scripts/audit_contrast.py` exits 0 and
  `docs/theme_contrast.md` shows no `FAIL` rows.

What is **not** automated-tested:

- Canvas rendering correctness. Effects produce visual output that's
  expensive to assert on; smoke tests would be flaky. Visual review only.
- Hardware-tier scoring. Depends on the runner's CPU/GPU; treat as an
  empirical heuristic, not a contract.
- FOUC absence (manual paint-timeline inspection).

---

## 13. Known invariants

1. **Persistence key is stable.** `localStorage['retrodb-theme']` must never
   be renamed — doing so silently resets every user back to cyberpunk on next
   load.
2. **Cyberpunk is the `:root` baseline.** No `[data-theme="cyberpunk"]` block
   exists in `themes.css`. `apply('cyberpunk')` *removes* the `data-theme`
   attribute rather than setting it.
3. **Every theme overrides the full variable surface from §3.** Missing
   variables fall back to cyberpunk values and create visual incoherence.
4. **`getThemedIcon` always returns a string.** Fallback chain:
   `themeTable[key] → fallback arg → cyberpunkTable[key] → key`.
5. **Canvas effects gate on `prefers-reduced-motion: reduce`.** New effects
   MUST sit inside the `!reduceMotion` branch in `apply()`.
6. **`_destroyCanvas()` is the single teardown path.** Per-theme state fields
   MUST be cleared there, not in their own init methods.
7. **`theme.js` is not bundled.** Loaded standalone for FOUC reasons;
   cache-bust via `?v={{ APP_VERSION }}`, not the asset manifest.
8. **`toast-controller.js` *is* bundled.** Edits to `ThemeIcons` need
   `python3 build_js.py`.
9. **Display name and `data-theme` token can diverge** (Cathedral / Blade
   Runner / Elite 1984) — renaming the token is a breaking change; renaming
   the display name is not.
10. **Effect frame budget is ~20 fps.** Enforced in `_startEffectLoop()`. New
    effects targeting higher fps need to argue for the CPU cost.

---

## See also

- `docs/RETRODB_DESIGN_STANDARDS.md` §2 (Color System), §8 (Theme System)
- `docs/theme_contrast.md` — generated contrast report
- `scripts/audit_contrast.py` — the generator
- `static/js/theme.js` — `ThemeManager`
- `static/js/toast-controller.js` — `getThemedIcon` and `ThemeIcons` table
- `static/css/core/themes.css` — per-theme variable overrides
- `static/css/core/variables.css` — `:root` baseline
- `templates/base.html` — FOUC script + standalone `theme.js` `<script>` tag
- `templates/settings.html` Display Preferences — theme picker UI
