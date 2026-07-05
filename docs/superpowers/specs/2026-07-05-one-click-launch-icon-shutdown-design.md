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
  `templates/_settings_tabs/system.html` (~line 171, Server Controls card,
  `id="server"`, Restart button ~line 176).
- **Unauthenticated health endpoints already exist** (`app.py:599-613`):
  `GET /health` (process-alive, no DB hit, returns `{status:'alive', version}`,
  HTTP 200) and `GET /ready` (exercises the DB, 200 / 503). Both are exempt from
  the first-time-setup redirect. These — NOT the `@admin_required` `/api/status`
  — are what an unauthenticated launcher probes for readiness.
- Graceful shutdown path exists: `request_shutdown` (defined in
  `services/jobs/base.py`, imported at `app.py:1729`), invoked by the
  SIGTERM/SIGINT handler def
  (`app.py:1731-1739`, registered at `1741-1742`). The handler drains running
  jobs, then restores the default handler and re-raises
  (`_signal.signal(signum, SIG_DFL); os.kill(getpid(), signum)`) — so SIGTERM's
  default action **does** terminate the process. Registration sits inside the
  `if _is_worker:` block (`app.py:1712`; `_is_worker` is assigned at
  `app.py:1711` = `WERKZEUG_RUN_MAIN=='true' or not config.DEBUG_MODE`), on the
  main thread; any process that actually serves the shutdown HTTP request is that
  worker, so the handler is registered on both the debug and packaged paths. The
  `except (ValueError, OSError)` at `1743-1748` only swallows the off-main-thread
  case (a WSGI host that imports the app on a worker thread — then the host owns
  signal handling). RetroDB's own runner (`python app.py` / the standalone
  binary) imports on the main thread, so the handler is live.

## Part 1 — App icon

- **Master:** `static/images/icon.svg` — neon gamepad, dark rounded tile.
- **Renderer:** `scripts/render_icons.py` — rasterizes the SVG into all outputs.
  Uses **`cairosvg`** for SVG→PNG (build-time-only dependency; NOT added to the
  runtime `requirements.txt` — icons are generated once by the maintainer and
  the raster outputs are committed, so end users never import it). Pillow (already
  a runtime dep) assembles the multi-size `.ico` / `.icns` from the rendered PNGs.
  Document the build-only dep where the icon-regen step is described (a comment in
  `render_icons.py` + a note in CLAUDE.md's asset-build section).
- **Outputs:**
  - `static/favicon.svg` + `favicon-32.png`, `favicon-16.png`,
    `apple-touch-icon.png` (180) → wired into `base.html` (replace inline emoji).
  - `packaging/icons/retrodb-256.png`, `retrodb-512.png` → Linux `.desktop`.
  - `packaging/icons/retrodb.ico` (multi-size) → Windows `.exe` (`icon=` in
    `retrodb.spec`) + taskbar.
  - `packaging/icons/retrodb.icns` → macOS bundle icon (CI already builds mac).

## Part 2 — One-click launch

**Local (pinned icon → real install):**
- `scripts/retrodb_launcher.py` — imports `config.SERVER_PORT` (which honours the
  `RETRODB_PORT` env override, default 5000) and uses it for BOTH the probe and
  the browser URL, so a user who has moved the server off 5000 still gets probed
  and opened at the right port. Probe
  `http://localhost:<config.SERVER_PORT>/health` (the unauthenticated endpoint
  above — do NOT use `/api/status`, which is `@admin_required` and redirects an
  anonymous probe to the login page, so it can never confirm readiness). "Up" =
  any HTTP response on that port; connection-refused = down. If up, just open the
  browser; else start the server from source (auto-detect `.venv`/`venv`, fall
  back to system python), poll `/health` until it answers (bounded timeout), then
  open the browser. (`/health` is process-alive, not DB-ready — acceptable here:
  the browser lands on a live server a beat before the DB warms, and the page's
  own requests tolerate that; polling `/ready` instead would only add latency for
  no user-visible gain.)
- **Start-race:** the launcher is NOT lock-protected — two near-simultaneous
  clicks can both probe "down" and both try to start. That's bounded, not
  catastrophic: the OS port bind is the real single-instance guard — the losing
  process hits `_die_port_in_use()` (`app.py:1758`), which prints an EADDRINUSE
  diagnostic to stderr and exits non-zero, leaving exactly one server running.
  (A lockfile is deliberately omitted; YAGNI for a
  single-user launcher — revisit only if the clean-exit-on-race proves noisy.)
- `packaging/RetroDB.desktop` — `Exec`=launcher, `Icon`=256px PNG (absolute
  path OR installed hicolor name), `Categories=Game;Utility;`.
- `scripts/install_launcher.py` — copies `.desktop` into
  `~/.local/share/applications/`, installs icon, runs
  `update-desktop-database`. Run once.

**Standalone ZIP (GitHub download):** upgrade `start.sh`/`start.bat` to
auto-open the browser; drop `.desktop` + icon into the Linux zip; set `.exe`
icon for Windows. Packaging changes in `build_dist.py` + `retrodb.spec`.

## Part 3 — Shutdown button

- **Backend:** `POST /api/shutdown` in `routes/maintenance.py`, `@admin_required`
  + `@handle_api_errors` (same envelope pattern as the other mutating routes in
  the file, so a drain-phase exception still returns JSON before the process
  dies). Mirrors `/api/restart`'s delayed-background-thread pattern but does a
  graceful STOP instead of a re-exec. **Concrete mechanism** (do not leave to the
  implementer): add `import signal` to `maintenance.py` (it currently imports only
  `os, sys, time, threading, logging` — `signal` is missing, and a route-exists /
  decorator-only test would not catch the `NameError`). A `threading.Thread`
  sleeps ~1 s — long enough for the HTTP response to flush to the browser, exactly
  as `api_restart` does (`maintenance.py:364`) — then calls
  `os.kill(os.getpid(), signal.SIGTERM)`. That fires the existing signal handler
  (`app.py:1731-1739`), which drains running jobs and re-raises to exit the
  process. Do NOT use `sys.exit()` (raises `SystemExit` only in the worker
  thread — waitress keeps serving) or `os._exit()` (skips the job drain the
  graceful path exists to provide). Returns
  `success(message='Server shutting down...')`. Shutdown is validated on the
  packaged/waitress path (main-thread `serve()`, `app.py:1891`); it is not
  exercised under the `--debug` werkzeug dev-server, which the feature does not
  target.
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

All previously-open mechanism questions were resolved against current code during
the design's cold-eyes review (2026-07-05); they are recorded here as
already-answered so the implementer doesn't re-investigate:

1. **SIGTERM exits the process — RESOLVED.** The handler at `app.py:1731-1739`
   drains jobs, restores `SIG_DFL`, and re-raises via `os.kill(getpid(), signum)`,
   so the process terminates the default way. No explicit extra exit needed on the
   main-thread runner. (Caveat carried into Part 3 / Current state: the handler is
   main-thread-only.)
2. **SVG→PNG/ICO renderer — RESOLVED:** `cairosvg` as a build-time-only dep (see
   Part 1). Not added to runtime `requirements.txt`.
3. **`.desktop` Icon reference — DECIDED:** use an **absolute path** to the
   installed 256px PNG (written by `install_launcher.py` into
   `~/.local/share/applications/` alongside the copied icon), not a hicolor theme
   name — absolute path survives without a full icon-theme install and is the more
   reliable choice for a single-user pin.
4. **Version number:** next minor (current **3.20.0** → **3.21.0**, confirmed
   against `config.py`), set at bump time.

## Next steps

1. Cold-eyes review of this design doc (RetroDB rule for design docs) → loop
   until clean.
2. writing-plans skill → implementation plan.
3. Implement in order: icon → launcher/desktop → shutdown button → packaging →
   version/changelog/i18n/tests → publish (draft).
