#!/usr/bin/env python3
"""One-click launcher for the local RetroDB source install.

Pinned to the taskbar via packaging/RetroDB.desktop, this makes "run RetroDB"
a single click: if the server is already up it just opens the browser;
otherwise it starts the server from source, waits for /health, then opens the
browser.

Probe target is the unauthenticated GET /health (NOT /api/status, which is
@admin_required and would 302 an anonymous probe to the login page — it could
never confirm readiness). Port comes from server_port.resolve_server_port() —
the same chain app.py binds with (PORT / RETRODB_PORT / the saved server_port
setting) — so a user who moved the server off 5000 by any of those routes is
still probed and opened at the right port.

Start-race note: this launcher is intentionally NOT lock-protected. Two near-
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
import config  # noqa: E402  (needs ROOT on sys.path first)
from server_port import resolve_server_port  # noqa: E402

PROBE_TIMEOUT = 1.0     # seconds per /health probe
START_TIMEOUT = 60.0    # seconds to wait for a freshly-started server


def server_url() -> str:
    # Same resolution app.py binds with, saved-settings tier included — a
    # probe on a different port than the server uses would see "down", start a
    # second instance, and lose it to EADDRINUSE.
    return f'http://localhost:{resolve_server_port(default=config.SERVER_PORT, use_saved=True)}'


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
