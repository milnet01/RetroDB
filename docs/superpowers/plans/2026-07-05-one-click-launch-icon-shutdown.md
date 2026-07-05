# One-Click Launch, App Icon & Shutdown Button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give RetroDB a real neon-gamepad icon (browser favicon + taskbar launcher), a one-click way to start it without a terminal, and a Shut Down Server button beside Restart on the Settings page.

**Architecture:** Three independent feature slices plus a packaging/release slice. (1) An SVG master icon is rasterized by a build-time script into favicon + `.desktop` + `.ico`/`.icns` assets. (2) A Python launcher probes the existing unauthenticated `/health` endpoint, starts the server from source if it's down, then opens the browser; a `.desktop` file + installer pin it to the taskbar. (3) A new `POST /api/shutdown` route mirrors the existing `/api/restart` delayed-thread pattern but sends `SIGTERM` to trigger the existing graceful-drain handler instead of re-exec. (4) Packaging wires the icon into PyInstaller and upgrades the standalone start scripts to auto-open the browser.

**Tech Stack:** Python 3 / Flask, PyInstaller (onedir), `cairosvg` (build-time only) + Pillow for rasterization, vanilla JS, Jinja templates, Babel i18n.

## Global Constraints

- **Version:** bump `3.20.0` → **`3.21.0`** (minor — new features) in BOTH `config.py` and `config.example.py` (`APP_VERSION` + `APP_LAST_UPDATE`).
- **Fill-only / lane discipline:** every changed line traces to this feature; no drive-by reformatting (global §11).
- **i18n:** every new user-facing string is wrapped — JS via `t('...')` (string literals only), templates via `{{ _('...') }}`; regenerate catalogs and pass `scripts/check_i18n_fresh.py`.
- **JS bundling:** `static/js/main.js` is bundled into `core.bundle.js` — after editing it run `python3 build_js.py`; never hand-edit `core.bundle.js`.
- **Health endpoints are unauthenticated by design** (`app.py:599-613`): `GET /health` (process-alive) and `GET /ready` (DB-ready). The launcher probes `/health`, NOT the `@admin_required` `/api/status`.
- **Shutdown mechanism is fixed:** delayed background thread → `os.kill(os.getpid(), signal.SIGTERM)`. NEVER `sys.exit()` (only unwinds the worker thread; waitress keeps serving) or `os._exit()` (skips the job drain). Requires `import signal` in `routes/maintenance.py`.
- **Port discovery:** the launcher reads `config.SERVER_PORT` (honours `RETRODB_PORT`, default 5000) for BOTH the probe and the browser URL.
- **`cairosvg` is build-time-only** — NOT added to `requirements.txt`. Rendered raster outputs are committed so end users never import it.
- **`.desktop` Icon = absolute path** to the installed 256px PNG (not a hicolor theme name).
- **Release stays a DRAFT** GitHub release for the user's final Publish click. Public repo → commits/pushes are free and allowed.
- **Sole-coder ownership:** all existing RetroDB code is the maintainer's own; own it, don't disclaim.

---

## File Structure

**New files:**
- `static/images/icon.svg` — neon-gamepad master (single source of truth).
- `scripts/render_icons.py` — build-time rasterizer (cairosvg + Pillow).
- `static/favicon.svg`, `static/favicon-32.png`, `static/favicon-16.png`, `static/apple-touch-icon.png` — favicon outputs (committed).
- `packaging/icons/retrodb-256.png`, `retrodb-512.png`, `retrodb.ico`, `retrodb.icns` — launcher/exe icons (committed).
- `scripts/retrodb_launcher.py` — probe-or-start-then-open-browser launcher.
- `packaging/RetroDB.desktop` — freedesktop launcher entry (template; installer rewrites paths).
- `scripts/install_launcher.py` — installs `.desktop` + icon into `~/.local/share/applications/`.
- `tests/test_shutdown_route.py` — route existence + `@admin_required` + success-envelope test.
- `tests/test_launcher.py` — port-discovery + probe-logic unit test (no real network).

**Modified files:**
- `templates/base.html:29-30` — replace inline emoji favicon with real `<link>` tags.
- `routes/maintenance.py` — add `import signal`; add `api_shutdown()` route.
- `static/js/main.js` — add `shutdownServer()`, export on `RetroDB`/`window`.
- `templates/_settings_tabs/system.html` — add Shut Down button in Server Controls card.
- `retrodb.spec` — add `icon=` to `EXE(...)`; add `packaging/icons` to `DATAS`.
- `build_dist.py` — bundle start scripts + `.desktop` + icons into standalone zip.
- `start.sh` / `start.bat` / `start.command` — auto-open browser after server start (standalone UX).
- `config.py` + `config.example.py` — version bump.
- `data/changelog.yaml` (+ per-locale changelog files) — release entry.
- `CLAUDE.md` — document new route, JS global, favicon assets, packaging files, icon-regen build step.

---

## Task 1: Shutdown backend route

**Files:**
- Modify: `routes/maintenance.py` (imports ~line 10-14; new route after `api_restart` ~line 369)
- Test: `tests/test_shutdown_route.py`

**Interfaces:**
- Produces: `POST /api/shutdown` → `success(message='Server shutting down...')`; `@admin_required` + `@handle_api_errors`. Delayed thread sends `os.kill(os.getpid(), signal.SIGTERM)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_shutdown_route.py`:

```python
"""Contract test for POST /api/shutdown (Pass: one-click-launch feature)."""
import inspect
import routes.maintenance as maint


def test_shutdown_route_registered():
    # The blueprint must expose an /api/shutdown POST rule.
    rules = [
        (r.rule, sorted(r.methods))
        for r in maint.bp.deferred_functions  # placeholder — replaced below
    ] if False else None
    # Introspect the source for the decorator + function instead (blueprints
    # don't expose rules until registered on an app).
    src = inspect.getsource(maint)
    assert "@bp.route('/api/shutdown', methods=['POST'])" in src
    assert 'def api_shutdown' in src


def test_shutdown_is_admin_guarded_and_uses_sigterm():
    src = inspect.getsource(maint.api_shutdown)
    assert 'signal.SIGTERM' in src
    assert 'os.kill' in src
    # Must NOT use the wrong exit paths.
    assert 'os._exit' not in src
    assert 'sys.exit' not in src


def test_signal_is_imported():
    assert hasattr(maint, 'signal')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_shutdown_route.py -v`
Expected: FAIL — `api_shutdown` does not exist / `signal` not imported.

- [ ] **Step 3: Add `import signal` to `routes/maintenance.py`**

In the import block (currently `import os / sys / time / threading / logging`), add after `import threading`:

```python
import signal
```

- [ ] **Step 4: Add the route after `api_restart` (after line 369)**

```python
@bp.route('/api/shutdown', methods=['POST'])
@admin_required
@handle_api_errors
def api_shutdown():
    """Gracefully shut the server down.

    Mirrors api_restart's delayed-thread pattern, but sends SIGTERM to
    trigger the graceful-drain handler installed in app.py (drains running
    jobs, then re-raises to exit) instead of re-exec'ing. The ~1 s sleep
    lets the JSON response flush to the browser before the process dies.

    SIGTERM (not sys.exit / os._exit): sys.exit only unwinds this worker
    thread while waitress keeps serving; os._exit skips the job drain the
    graceful handler exists to provide.
    """
    def shutdown():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=shutdown, daemon=True).start()
    return success(message='Server shutting down...')
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/test_shutdown_route.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Stage-only check (test imports production symbol)**

Run: `git add routes/maintenance.py tests/test_shutdown_route.py && git stash --keep-index && python3 -m pytest tests/test_shutdown_route.py -v && git stash pop`
Expected: PASS against the staged-only tree (proves the production half is staged, not just in the working copy — CLAUDE.md verification rule).

- [ ] **Step 7: Commit**

```bash
git commit -m "feat: add POST /api/shutdown graceful-shutdown route

SIGTERM to the existing drain handler; delayed thread flushes the response
first. Rejects sys.exit/os._exit. (v3.21.0 one-click-launch feature)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Shutdown frontend (button + JS)

**Files:**
- Modify: `static/js/main.js` (add `shutdownServer()` near `restartServer` ~line 870; exports ~line 1733 + ~line 1756)
- Modify: `templates/_settings_tabs/system.html` (Server Controls card ~line 175-183)

**Interfaces:**
- Consumes: `showConfirm`, `showNotification`, `API.post`, `t` (all existing globals).
- Produces: `window.shutdownServer` / `RetroDB.shutdownServer` — called by the button's `onclick`.

- [ ] **Step 1: Add `shutdownServer()` in `static/js/main.js`**

Immediately after the `restartServer()` function (after its closing `}` ~line 892), insert:

```javascript
async function shutdownServer() {
    showConfirm(
        t('🛑 Shut Down Server'),
        t('Are you sure you want to shut down the server? You will need to start it again manually.'),
        async function() {
            showNotification(t('Shutting down server...'), 'info');
            try {
                await API.post('/api/shutdown');
            } catch (error) {
                // Expected — the connection drops as the server exits.
            }
            // Do NOT poll to reconnect: the server is going down for good.
            showNotification(t('Server stopped. You can close this tab.'), 'success');
        },
        { confirmClass: 'btn-danger', confirmText: t('Shut Down') }
    );
}
```

> Note: `showConfirm(title, msg, onConfirm, opts?)` — confirm the `opts` shape (`confirmClass` / `confirmText`) against `base.html`'s `showConfirm` definition during implementation; if the primitive doesn't accept those keys, drop the 4th arg (the red styling can live on the button instead) rather than inventing options.

- [ ] **Step 2: Export the new global**

After `RetroDB.restartServer = restartServer;` (~line 1733) add:

```javascript
RetroDB.shutdownServer = shutdownServer;
```

After `window.restartServer = restartServer;` (~line 1756) add:

```javascript
window.shutdownServer = shutdownServer;
```

- [ ] **Step 3: Add the button in `templates/_settings_tabs/system.html`**

In the Server Controls `card-body` (after the Restart button's `</button>` ~line 179, before the descriptive `<p>`), insert:

```html
        <button type="button" onclick="shutdownServer()" class="btn btn-danger">
            <span class="btn-icon">🛑</span>
            Shut Down Server
        </button>
```

- [ ] **Step 4: Rebuild the JS bundle**

Run: `python3 build_js.py`
Expected: `core.bundle.js` + `asset_manifest.json` regenerated (SHA prefix changes); `services/js_i18n_strings.py` picks up the 4 new `t('...')` msgids.

- [ ] **Step 5: Verify the strings landed in the JS i18n manifest**

Run: `grep -c 'Shut Down Server\|Shutting down server\|Server stopped' services/js_i18n_strings.py`
Expected: ≥ 1 (msgids extracted).

- [ ] **Step 6: Commit**

```bash
git add static/js/main.js static/js/core.bundle.js static/asset_manifest.json templates/_settings_tabs/system.html services/js_i18n_strings.py
git commit -m "feat: add Shut Down Server button to Settings

Red btn-danger beside Restart; shutdownServer() posts /api/shutdown and
tells the user to close the tab (no reconnect poll). (v3.21.0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: App icon assets

**Files:**
- Create: `static/images/icon.svg`, `scripts/render_icons.py`
- Create (generated, committed): `static/favicon.svg`, `static/favicon-32.png`, `static/favicon-16.png`, `static/apple-touch-icon.png`, `packaging/icons/retrodb-256.png`, `retrodb-512.png`, `retrodb.ico`, `retrodb.icns`
- Modify: `templates/base.html:29-30`

**Interfaces:**
- Produces: committed raster/vector icon files consumed by base.html (Task 3), the `.desktop` (Task 4), and `retrodb.spec` (Task 5).

- [ ] **Step 1: Install the build-time dependency**

Run: `pip install cairosvg` (maintainer's env only — do NOT add to `requirements.txt`).
Expected: cairosvg + its cairo binding import cleanly (`python3 -c "import cairosvg"`).

- [ ] **Step 2: Author the master SVG**

Create `static/images/icon.svg` — a neon gamepad on a dark rounded-square tile, cyberpunk cyan (`#00f0ff`) + magenta (`#ff00d4`) glow on near-black (`#0a0a12`). 512×512 viewBox. Keep it self-contained (no external font/href refs) so cairosvg renders it headless:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="pad" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#00f0ff"/>
      <stop offset="1" stop-color="#ff00d4"/>
    </linearGradient>
    <filter id="glow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="8" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect x="16" y="16" width="480" height="480" rx="104" fill="#0a0a12"
        stroke="#1b1b2e" stroke-width="4"/>
  <g filter="url(#glow)" fill="none" stroke="url(#pad)" stroke-width="18"
     stroke-linejoin="round" stroke-linecap="round">
    <!-- gamepad body -->
    <path d="M150 190 h212 a70 70 0 0 1 66 92 l-26 86 a52 52 0 0 1-92 10
             l-14-26 h-146 l-14 26 a52 52 0 0 1-92-10 l-26-86 a70 70 0 0 1 66-92 Z"/>
    <!-- d-pad -->
    <path d="M150 262 h48 M174 238 v48"/>
    <!-- action buttons -->
    <circle cx="338" cy="248" r="12"/>
    <circle cx="374" cy="284" r="12"/>
  </g>
</svg>
```

> The exact path geometry is illustrative — refine visually in Step 4's preview. The contract is: self-contained SVG, cyan→magenta gradient, dark rounded tile, gamepad silhouette.

- [ ] **Step 3: Write `scripts/render_icons.py`**

```python
#!/usr/bin/env python3
"""Rasterize static/images/icon.svg into all favicon / launcher / exe icons.

BUILD-TIME ONLY. Requires cairosvg (`pip install cairosvg`) which is NOT a
runtime dependency — it is deliberately absent from requirements.txt. The
maintainer runs this once when the icon changes and commits the outputs.

Usage:  python3 scripts/render_icons.py
"""
import io
from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / 'static' / 'images' / 'icon.svg'


def _png(size: int) -> Image.Image:
    data = cairosvg.svg2png(url=str(MASTER), output_width=size, output_height=size)
    return Image.open(io.BytesIO(data)).convert('RGBA')


def main() -> None:
    static = ROOT / 'static'
    pkg = ROOT / 'packaging' / 'icons'
    pkg.mkdir(parents=True, exist_ok=True)

    # Favicon: keep the vector master + PNG fallbacks.
    (static / 'favicon.svg').write_bytes(MASTER.read_bytes())
    _png(32).save(static / 'favicon-32.png')
    _png(16).save(static / 'favicon-16.png')
    _png(180).save(static / 'apple-touch-icon.png')

    # Linux .desktop launcher icons.
    _png(256).save(pkg / 'retrodb-256.png')
    _png(512).save(pkg / 'retrodb-512.png')

    # Windows .ico (multi-size) + macOS .icns, assembled by Pillow.
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    _png(256).save(pkg / 'retrodb.ico', sizes=ico_sizes)
    # .icns: Pillow writes from a single high-res RGBA image.
    _png(512).save(pkg / 'retrodb.icns')

    print('Rendered favicon + launcher + exe icons from', MASTER.name)


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run the renderer and eyeball the output**

Run: `python3 scripts/render_icons.py`
Expected: all 8 output files written. Open `packaging/icons/retrodb-256.png` — confirm it reads as a neon gamepad at a glance and isn't clipped. Iterate on the SVG in Step 2 until it looks right, then re-run.

- [ ] **Step 5: Wire the favicon into `templates/base.html`**

Replace line 29-30 (the `<!-- Favicon -->` comment + the inline-emoji `<link rel="icon" ...data:image/svg+xml...>`) with:

```html
    <!-- Favicon -->
    <link rel="icon" type="image/svg+xml" href="{{ asset_url('favicon.svg') }}">
    <link rel="alternate icon" type="image/png" sizes="32x32" href="{{ asset_url('favicon-32.png') }}">
    <link rel="alternate icon" type="image/png" sizes="16x16" href="{{ asset_url('favicon-16.png') }}">
    <link rel="apple-touch-icon" sizes="180x180" href="{{ asset_url('apple-touch-icon.png') }}">
```

> Verify `asset_url('favicon.svg')` resolves — `asset_url` (from `services/assets.py`) keys off `static/asset_manifest.json`. If the favicon files aren't in the manifest, `asset_url` falls back to `?v={APP_VERSION}` on the static path, which is fine (they live directly under `static/`). Confirm the served path is `static/favicon.svg` during verification.

- [ ] **Step 6: Verify favicon renders**

Start the dev server, load any page, DevTools → Network: confirm `favicon.svg` returns 200 and the browser tab shows the gamepad (not the old emoji). Check one PNG fallback path returns 200.

- [ ] **Step 7: Commit**

```bash
git add static/images/icon.svg scripts/render_icons.py static/favicon.svg static/favicon-*.png static/apple-touch-icon.png packaging/icons/ templates/base.html
git commit -m "feat: real neon-gamepad app icon (favicon + launcher/exe assets)

SVG master + render_icons.py (build-time cairosvg, not a runtime dep);
committed favicon + .desktop/.ico/.icns outputs; base.html favicon wired
to the real files. (v3.21.0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: One-click local launcher

**Files:**
- Create: `scripts/retrodb_launcher.py`, `packaging/RetroDB.desktop`, `scripts/install_launcher.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `config.SERVER_PORT`; the unauthenticated `GET /health`; `packaging/icons/retrodb-256.png`.
- Produces: a launcher runnable as `python3 scripts/retrodb_launcher.py`; a `.desktop` pinned via `install_launcher.py`.

- [ ] **Step 1: Write the failing launcher test**

Create `tests/test_launcher.py`:

```python
"""Unit tests for scripts/retrodb_launcher — port discovery + probe logic.

No real network / subprocess: server_url() is pure and is_running() is
exercised against a monkeypatched urlopen.
"""
import importlib.util
from pathlib import Path
from urllib.error import URLError

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    'retrodb_launcher', ROOT / 'scripts' / 'retrodb_launcher.py')
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


def test_server_url_uses_config_port(monkeypatch):
    monkeypatch.setattr(launcher.config, 'SERVER_PORT', 5000)
    assert launcher.server_url() == 'http://localhost:5000'
    monkeypatch.setattr(launcher.config, 'SERVER_PORT', 8080)
    assert launcher.server_url() == 'http://localhost:8080'


def test_is_running_true_on_any_http_response(monkeypatch):
    monkeypatch.setattr(launcher, 'urlopen', lambda *a, **k: _FakeResp())
    assert launcher.is_running() is True


def test_is_running_false_on_connection_refused(monkeypatch):
    def _boom(*a, **k):
        raise URLError('Connection refused')
    monkeypatch.setattr(launcher, 'urlopen', _boom)
    assert launcher.is_running() is False


class _FakeResp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    status = 200
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m pytest tests/test_launcher.py -v`
Expected: FAIL — `scripts/retrodb_launcher.py` does not exist.

- [ ] **Step 3: Write `scripts/retrodb_launcher.py`**

```python
#!/usr/bin/env python3
"""One-click launcher for the local RetroDB source install.

Pinned to the taskbar via packaging/RetroDB.desktop, this makes "run RetroDB"
a single click: if the server is already up it just opens the browser;
otherwise it starts the server from source, waits for /health, then opens the
browser.

Probe target is the unauthenticated GET /health (NOT /api/status, which is
@admin_required and would 302 an anonymous probe to the login page — it could
never confirm readiness). Port comes from config.SERVER_PORT, which honours
the RETRODB_PORT override, so a user who moved the server off 5000 is still
probed and opened at the right port.

Start-race note: this launcher is intentionally NOT lock-protected. Two near
simultaneous clicks can both see "down" and both try to start; that is bounded,
not catastrophic — the OS port bind is the real single-instance guard. The
loser hits _die_port_in_use() in app.py, prints EADDRINUSE, and exits non-zero,
leaving exactly one server. A lockfile is YAGNI for a single-user launcher.
"""
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config  # noqa: E402  (needs ROOT on the path first)

PROBE_TIMEOUT = 1.0     # seconds per /health probe
START_TIMEOUT = 60.0    # seconds to wait for a freshly-started server


def server_url() -> str:
    return f'http://localhost:{config.SERVER_PORT}'


def is_running() -> bool:
    """True if anything answers HTTP on /health; False on connection-refused."""
    try:
        with urlopen(f'{server_url()}/health', timeout=PROBE_TIMEOUT):
            return True
    except URLError:
        return False
    except OSError:
        return False


def _python() -> str:
    """Prefer a project venv interpreter, else the current one."""
    for venv in ('.venv', 'venv'):
        cand = ROOT / venv / ('Scripts' if os.name == 'nt' else 'bin') / (
            'python.exe' if os.name == 'nt' else 'python')
        if cand.exists():
            return str(cand)
    return sys.executable


def start_server() -> None:
    """Launch app.py detached and poll /health until it answers."""
    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NEW_CONSOLE  # own window on Windows
    subprocess.Popen(
        [_python(), str(ROOT / 'app.py')],
        cwd=str(ROOT),
        creationflags=creationflags,
    )
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if is_running():
            return
        time.sleep(0.5)
    print('RetroDB did not become ready within '
          f'{START_TIMEOUT:.0f}s; opening the browser anyway.', file=sys.stderr)


def main() -> None:
    if not is_running():
        start_server()
    webbrowser.open(server_url())


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_launcher.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Write the `.desktop` template `packaging/RetroDB.desktop`**

```ini
[Desktop Entry]
Type=Application
Name=RetroDB
Comment=Retro Gaming ROM Library Manager
Exec=__EXEC__
Icon=__ICON__
Terminal=false
Categories=Game;Utility;
StartupNotify=true
```

> `__EXEC__` / `__ICON__` are placeholders that `install_launcher.py` rewrites to absolute paths at install time.

- [ ] **Step 6: Write `scripts/install_launcher.py`**

```python
#!/usr/bin/env python3
"""Install the RetroDB taskbar launcher (Linux, XDG desktops).

Copies the icon into ~/.local/share/icons and writes a .desktop file into
~/.local/share/applications with absolute Exec/Icon paths, then refreshes the
desktop database. Run once: `python3 scripts/install_launcher.py`.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if sys.platform != 'linux':
        print('install_launcher.py targets Linux XDG desktops only.', file=sys.stderr)
        sys.exit(1)

    apps = Path.home() / '.local' / 'share' / 'applications'
    icons = Path.home() / '.local' / 'share' / 'icons'
    apps.mkdir(parents=True, exist_ok=True)
    icons.mkdir(parents=True, exist_ok=True)

    src_icon = ROOT / 'packaging' / 'icons' / 'retrodb-256.png'
    dst_icon = icons / 'retrodb.png'
    shutil.copyfile(src_icon, dst_icon)

    launcher = ROOT / 'scripts' / 'retrodb_launcher.py'
    python = sys.executable
    exec_line = f'{python} {launcher}'

    template = (ROOT / 'packaging' / 'RetroDB.desktop').read_text()
    desktop = template.replace('__EXEC__', exec_line).replace('__ICON__', str(dst_icon))
    dst_desktop = apps / 'RetroDB.desktop'
    dst_desktop.write_text(desktop)
    os.chmod(dst_desktop, 0o755)

    # Best-effort refresh so the entry appears without a re-login.
    if shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(apps)], check=False)

    print(f'Installed launcher: {dst_desktop}')
    print('Find "RetroDB" in your app menu and pin it to the taskbar.')


if __name__ == '__main__':
    main()
```

- [ ] **Step 7: Smoke-test the installer + launcher end to end**

Run: `python3 scripts/install_launcher.py` then confirm `~/.local/share/applications/RetroDB.desktop` exists with absolute `Exec=`/`Icon=` lines. With the server stopped, run `python3 scripts/retrodb_launcher.py` — it should start the server and open the browser at the configured port. Run it again with the server up — it should just open a tab (no second server; check no EADDRINUSE).

- [ ] **Step 8: Commit**

```bash
git add scripts/retrodb_launcher.py scripts/install_launcher.py packaging/RetroDB.desktop tests/test_launcher.py
git commit -m "feat: one-click launcher + .desktop installer for local install

retrodb_launcher probes /health, starts app.py if down, opens the browser;
install_launcher pins a .desktop with absolute paths. (v3.21.0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Standalone packaging (icon + browser-opening start scripts)

**Files:**
- Modify: `retrodb.spec` (EXE `icon=`; DATAS `packaging/icons`)
- Modify: `build_dist.py` (`build_standalone` — bundle start scripts + `.desktop` + icons)
- Modify: `start.sh`, `start.bat`, `start.command` (auto-open browser)

**Interfaces:**
- Consumes: `packaging/icons/retrodb.ico` (Windows exe), `packaging/icons/retrodb.icns` (mac), `packaging/RetroDB.desktop` + `retrodb-256.png` (Linux zip).

- [ ] **Step 1: Give the PyInstaller exe its icon**

In `retrodb.spec`, in the `EXE(...)` call, add an `icon=` argument. PyInstaller picks `.ico` on Windows, `.icns` on macOS; pass both via a list and it selects per-platform:

```python
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='retrodb',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=[str(PROJECT_ROOT / 'packaging' / 'icons' / 'retrodb.ico'),
          str(PROJECT_ROOT / 'packaging' / 'icons' / 'retrodb.icns')],
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

Also add the icons dir to `DATAS` (so the running app can serve/refer to them if needed and the Linux zip has them):

```python
    ('packaging/icons', 'packaging/icons'),
```

- [ ] **Step 2: Auto-open the browser from `start.sh`**

Replace the final `$PYTHON app.py` (line 110) with a background browser-open + foreground server:

```bash
# Open the browser a moment after the server binds (background; non-fatal).
( sleep 3; xdg-open "http://localhost:5000" >/dev/null 2>&1 || true ) &

$PYTHON app.py
```

- [ ] **Step 3: Auto-open the browser from `start.command` (macOS)**

Mirror the same pattern, using `open` instead of `xdg-open`. Read `start.command` first; before its server-launch line add:

```bash
( sleep 3; open "http://localhost:5000" >/dev/null 2>&1 || true ) &
```

- [ ] **Step 4: Auto-open the browser from `start.bat` (Windows)**

In `start.bat`, immediately before `%PYTHON% app.py` (line 61), add:

```bat
start "" http://localhost:5000
```

> `start ""` returns immediately, so the following `%PYTHON% app.py` still runs in the foreground. The browser may open a beat before the server is ready; it retries on refresh — acceptable for the standalone UX.

- [ ] **Step 5: Bundle launcher scripts + icons into the standalone zip**

In `build_dist.py`'s `build_standalone`, after the `os.walk(bundle_dir)` loop that writes the PyInstaller output (after line 316, still inside the `with zipfile...` block), add the platform's start script + (Linux only) the `.desktop` + icon:

```python
        # Ship the platform's browser-opening start script next to the binary.
        _start = {'Linux': 'start.sh', 'macOS': 'start.command', 'Windows': 'start.bat'}[host_name]
        zf.write(os.path.join(base_dir, _start), os.path.join(folder_name, _start))
        file_count += 1
        # Linux: include the .desktop template + icon so users can pin it.
        if host_name == 'Linux':
            for extra in ('packaging/RetroDB.desktop', 'packaging/icons/retrodb-256.png'):
                zf.write(os.path.join(base_dir, extra), os.path.join(folder_name, extra))
                file_count += 1
```

> Confirm `host_name` values match the `PLATFORMS` keys (`'Linux'`/`'macOS'`/`'Windows'`) during implementation — `build_standalone` is called with `host` from `_host_platform()`; align the dict keys to whatever that returns.

- [ ] **Step 6: Verify the spec still parses**

Run: `python3 -c "import ast; ast.parse(open('retrodb.spec').read())"`
Expected: no error (syntactic check; a full PyInstaller build is deferred to release time and is heavy).

- [ ] **Step 7: Commit**

```bash
git add retrodb.spec build_dist.py start.sh start.command start.bat
git commit -m "feat: standalone packaging — exe icon + browser-opening start scripts

retrodb.spec gets icon= (.ico/.icns); start scripts auto-open the browser;
build_dist bundles the start script + Linux .desktop/icon into the zip. (v3.21.0)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Version bump, changelog, i18n, docs, full verification

**Files:**
- Modify: `config.py`, `config.example.py` (version)
- Modify: `data/changelog.yaml` + per-locale `data/changelog.<locale>.yaml` (de, es, fr, it, ja, pt_BR)
- Modify: `CLAUDE.md`
- Regenerate: translation catalogs

- [ ] **Step 1: Bump the version in both config files**

In `config.py` AND `config.example.py`, set `APP_VERSION = "3.21.0"` and update `APP_LAST_UPDATE` to `2026-07-05` (match the existing date format in each file — read the current line first).

- [ ] **Step 2: Add the changelog entry atop `data/changelog.yaml`**

Prepend a `3.21.0` entry (match the existing YAML shape — `version`, `date`, tagged bullets). Cover: neon-gamepad icon + favicon, one-click launcher + taskbar pin, Shut Down Server button, browser-opening standalone start scripts.

- [ ] **Step 3: Translate the entry into each human-translation locale**

Copy the new entry verbatim (repeat `version`, `date`, and every tag) into `data/changelog.de.yaml`, `.es`, `.fr`, `.it`, `.ja`, `.pt_BR.yaml`, translating the prose. (Per CLAUDE.md — the `/changelog` route swaps the whole entry by version, so omissions are dropped, not inherited.)

- [ ] **Step 4: Regenerate i18n catalogs**

Run:
```bash
python3 build_js.py && \
pybabel extract -F babel.cfg --ignore-dirs='.* __pycache__ node_modules venv .venv env build dist staging tests' -o messages.pot . && \
pybabel update -i messages.pot -d translations && \
python3 scripts/gen_pseudolocale.py && \
pybabel compile -d translations
```
Expected: the 4 new JS msgids (Shut Down Server, Shutting down…, Server stopped…, the confirm body) appear in `messages.pot` and are added (untranslated → English fallback) across catalogs.

- [ ] **Step 5: i18n freshness gate**

Run: `python3 scripts/check_i18n_fresh.py`
Expected: PASS (catalogs in sync with sources).

- [ ] **Step 6: Update `CLAUDE.md`**

Add, in the relevant existing sections (do not restate global rules):
- Non-Obvious JS/Template Contracts: `shutdownServer()` global (mirrors `restartServer`).
- Routes note: `POST /api/shutdown` (admin-only graceful stop via SIGTERM).
- Distribution/asset section: `scripts/render_icons.py` is the build-time icon regen step (needs `cairosvg`, not a runtime dep); icon assets live in `static/favicon*` + `packaging/icons/`; standalone zip now ships a browser-opening start script (+ Linux `.desktop`/icon).
- Local launcher: `scripts/retrodb_launcher.py` + `scripts/install_launcher.py` pin RetroDB to the taskbar.

- [ ] **Step 7: Run the full test suite**

Run: `python3 -m pytest`
Expected: all green (new `test_shutdown_route.py` + `test_launcher.py` included; no regressions).

- [ ] **Step 8: Rebuild CSS if any CSS changed**

No CSS was edited in this feature (the button reuses `btn-danger`). Skip `build_css.py` unless a diff shows a CSS change.

- [ ] **Step 9: Manual golden-path verification**

Start the dev server. Desktop + ~375px mobile:
- Favicon shows the gamepad in the browser tab.
- Settings → Server Controls: Shut Down button renders red beside Restart.
- Click Shut Down → confirm dialog (red) → toast "Server stopped…"; confirm the server process actually exits (check the terminal drained jobs and exited, not just the toast). Then Ctrl-C is unnecessary — the process is gone.
- Restart still works (regression check on the shared card).
- One error path: click Shut Down then Cancel — no request fires.

- [ ] **Step 10: Commit the release**

```bash
git add config.py config.example.py data/changelog.yaml data/changelog.*.yaml \
        translations messages.pot services/js_i18n_strings.py CLAUDE.md static/js/core.bundle.js static/asset_manifest.json
git commit -m "v3.21.0: one-click launch, app icon & shutdown button

Neon-gamepad favicon/launcher icon, taskbar launcher, Shut Down Server
button, browser-opening standalone start scripts. i18n catalogs + changelog
(9 locales) regenerated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 11: Push (public repo — allowed) and prepare the DRAFT release**

Per memory, version-bump changes may be pushed automatically (public repo, free CI):
```bash
git push origin main
```
Then, when the user wants the downloadable builds: build the Linux standalone locally (`python3 build_dist.py --standalone --cpu-only`) and run `./release-standalone.sh` to dispatch the Windows/mac CI matrix. **The GitHub release is left as a DRAFT** — the user reviews and clicks Publish.

---

## Self-Review

**Spec coverage:**
- Part 1 (icon): Task 3 (SVG + renderer + favicon wiring) + Task 5 (exe icon). ✓
- Part 2 (launch): Task 4 (launcher + .desktop + installer) + Task 5 (standalone start scripts). ✓
- Part 3 (shutdown): Task 1 (backend) + Task 2 (frontend). ✓
- Publishing (draft release): Task 6 Step 11. ✓
- Mandatory workflow (version/changelog/i18n/tests/CLAUDE.md): Task 6. ✓

**Placeholder scan:** No "TBD"/"handle appropriately". The two illustrative-content notes (SVG path geometry in Task 3, `showConfirm` opts shape in Task 2) are explicitly flagged as verify-at-implementation with a concrete fallback, not vague hand-waves.

**Type consistency:** `shutdownServer` named identically across JS definition + both exports + button `onclick` + CLAUDE.md. `server_url()` / `is_running()` / `start_server()` names match between `retrodb_launcher.py` and `test_launcher.py`. `api_shutdown` matches between route + test assertions. Health probe target `/health` consistent across launcher, plan constraints, and spec.

**Known implementation-time verifications (flagged inline, not gaps):**
1. `showConfirm` opts shape (Task 2 Step 1) — fall back to no-opts + button styling if unsupported.
2. `asset_url('favicon.svg')` resolution (Task 3 Step 5) — falls back to versioned static path.
3. `host_name` vs `PLATFORMS` key casing (Task 5 Step 5) — align to `_host_platform()` return.
4. PyInstaller `icon=` list form for per-platform selection (Task 5 Step 1).
