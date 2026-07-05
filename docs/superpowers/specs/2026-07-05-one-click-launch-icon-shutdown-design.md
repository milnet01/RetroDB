# One-Click Launch, App Icon & Shutdown Button — Design

**Date:** 2026-07-05
**Status:** Approved (design); pending cold-eyes review → implementation
**Type:** Feature (minor version bump)

## Goal (user's words, plain)

Let the user run RetroDB by clicking a pinned taskbar icon instead of a
terminal, give the app a real icon (browser favicon + desktop launcher),
publish a click-to-run downloadable build for Linux and Windows on GitHub, and
add a **Shutdown Server** button next to the existing Restart on the Settings
page.

## Decisions locked in (from brainstorming Q&A)

1. **App shape = folder + launcher**, NOT a true single-file binary. RetroDB is
   ~600 MB (bundled onnxruntime AI upscaler); a `--onefile` build would
   self-extract ~600 MB to temp on every launch (~15–30 s startup) and trip
   Windows AV. The existing PyInstaller **onedir** standalone stays; we add a
   proper launcher + icon so "click one icon to run" is the user experience.
2. **Pinned icon targets the user's REAL source install** at
   `/mnt/Games/Scripts/Linux/RetroDB` (their ~5500-game library + DB), not the
   downloaded standalone. The GitHub download gets its own launcher for other
   people.
3. **Icon motif = neon gamepad** on a dark rounded-square tile (cyberpunk
   cyan/magenta), matching the current 🎮 logo.

## Current state (verified in-repo)

- Standalone build = PyInstaller **onedir** (`retrodb.spec`, `console=True`,
  no `icon=`); `build_dist.py --standalone` zips it per-platform; CI job
  `build-standalone` in `.github/workflows/release.yml` (matrix
  ubuntu/macos/windows, gated behind `workflow_dispatch` + `build_standalone:true`);
  `./release-standalone.sh` dispatches it and leaves a **draft** release.
- Favicon = inline emoji SVG in `templates/base.html` line ~30 (`🎮`), no real
  icon asset.
- Restart = `POST /api/restart` in `routes/maintenance.py` (~line 359,
  `os.execv` re-exec, `@admin_required`) + `restartServer()` in
  `static/js/main.js` (~line 870, `showConfirm` → `API.post('/api/restart')` →
  `checkServerStatus()` poll) + button in
  `templates/_settings_tabs/system.html` (~line 176, Server Controls card,
  `id="server"`).
- Graceful shutdown path exists: `services.jobs.base.request_shutdown`, invoked
  by the SIGTERM/SIGINT handler (drains running jobs). Must verify the handler
  actually exits the process (waitress) — see Open Items.

## Part 1 — App icon

- **Master:** `static/images/icon.svg` — neon gamepad, dark rounded tile.
- **Renderer:** `scripts/render_icons.py` — rasterizes the SVG into all outputs
  (reproducible; pick cairosvg pip dep or a system tool — verify availability
  during implementation, prefer no new heavy dep).
- **Outputs:**
  - `static/favicon.svg` + `favicon-32.png`, `favicon-16.png`,
    `apple-touch-icon.png` (180) → wired into `base.html` (replace inline emoji).
  - `packaging/icons/retrodb-256.png`, `retrodb-512.png` → Linux `.desktop`.
  - `packaging/icons/retrodb.ico` (multi-size) → Windows `.exe` (`icon=` in
    `retrodb.spec`) + taskbar.
  - `packaging/icons/retrodb.icns` → macOS bundle icon (CI already builds mac).

## Part 2 — One-click launch

**Local (pinned icon → real install):**
- `scripts/retrodb_launcher.py` — probe `localhost:<SERVER_PORT>/api/status`;
  if up, just open browser; else start server from source (auto-detect
  `.venv`/`venv`, fall back to system python), wait for readiness, open browser.
  Single-instance safe (no double server).
- `packaging/RetroDB.desktop` — `Exec`=launcher, `Icon`=256px PNG (absolute
  path OR installed hicolor name), `Categories=Game;Utility;`.
- `scripts/install_launcher.py` — copies `.desktop` into
  `~/.local/share/applications/`, installs icon, runs
  `update-desktop-database`. Run once.

**Standalone ZIP (GitHub download):** upgrade `start.sh`/`start.bat` to
auto-open the browser; drop `.desktop` + icon into the Linux zip; set `.exe`
icon for Windows. Packaging changes in `build_dist.py` + `retrodb.spec`.

## Part 3 — Shutdown button

- **Backend:** `POST /api/shutdown` in `routes/maintenance.py`, `@admin_required`,
  mirrors `/api/restart` but graceful STOP (no re-exec). Drain jobs via existing
  SIGTERM/graceful path then exit. Returns `success(message='Server shutting
  down...')`.
- **Frontend:** `shutdownServer()` in `static/js/main.js` — red `showConfirm` →
  `API.post('/api/shutdown')` → toast "Server stopped, you can close this tab";
  do NOT poll to reconnect. Export on `RetroDB`/`window` like `restartServer`.
- **UI:** **Shut Down Server** button (`btn-danger`) beside Restart in
  `templates/_settings_tabs/system.html` Server Controls card.

## Publishing (minor release)

Bump version + changelog → build Linux standalone locally → trigger CI matrix
via `release-standalone.sh` for Windows (+ mac) → all bundles attach to a
**DRAFT** GitHub release → user reviews & clicks Publish. Public repo, so pushes
are free/allowed; the release stays a draft for the user's final say.

## Mandatory RetroDB workflow steps (per CLAUDE.md)

- Bump `APP_VERSION`/`APP_LAST_UPDATE` in `config.py` + `config.example.py`.
- Changelog entry atop `data/changelog.yaml` (+ translate recent entry into the
  human-translation locales for a real release).
- i18n-wrap new user-facing strings (JS `t('...')`, template `_('...')`),
  regenerate catalogs (`build_js.py` + pybabel extract/update + pseudolocale +
  compile), pass `check_i18n_fresh.py`.
- Rebuild JS bundle (`python3 build_js.py`) — `main.js` is bundled.
- Rebuild CSS only if any CSS changed.
- Tests: add coverage for `/api/shutdown` (route exists, `@admin_required`,
  returns success); run `pytest`.
- Update `CLAUDE.md` if routes/assets/wiring change (they do: new route, new
  JS global, favicon assets, packaging files).

## Open items to verify during implementation

1. **SIGTERM actually exits the process** under waitress — confirm in `app.py`
   server-run + signal setup. If SIGTERM only drains jobs without stopping the
   WSGI server, use an explicit exit after `request_shutdown()` (documented,
   root-cause, not a hack).
2. **SVG→PNG/ICO renderer** — prefer an already-present tool (Pillow can't
   rasterize SVG; check for cairosvg / rsvg-convert / inkscape). Avoid adding a
   heavy dep just for icon generation; a build-time-only dep is acceptable if
   documented.
3. **`.desktop` Icon reference** — absolute repo path vs installed hicolor
   theme name; pick the one that survives reliably for pinning.
4. Version number: next minor (current 3.20.x → **3.21.0**), confirm at bump.

## Next steps

1. Cold-eyes review of this design doc (RetroDB rule for design docs) → loop
   until clean.
2. writing-plans skill → implementation plan.
3. Implement in order: icon → launcher/desktop → shutdown button → packaging →
   version/changelog/i18n/tests → publish (draft).
