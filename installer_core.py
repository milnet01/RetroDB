"""
RetroDB Installer Core
Shared logic between `install.py` (CLI) and `install_gui.py` (Tkinter wizard):
distro detection, RetroDB's own Python folder, pip install, module import
probe, build-script runner, config-copy + directory manifests. Each frontend keeps its own UI loop
(print() vs self._log()) and reuses these helpers.

Pass 38.3 — extracted to close the rule-of-three triggered by the Pass 38.5
bundle-name drift (two installers checking different filenames in 'use
existing bundle' fallback).
"""

import os
import subprocess
import sys
import sysconfig


# ── Shared manifests ─────────────────────────────────────────────────────────

CONFIG_COPIES = (
    ('config.example.py', 'config.py'),
    ('data/scraper_settings.example.json', 'data/scraper_settings.json'),
    ('docs/psn-npsso.env.example', 'docs/psn-npsso.env'),
)

DIRECTORIES = (
    'database',
    'logs',
    'data',
    'static/images/boxart',
    'static/images/boxart_3d',
    'static/images/screenshots',
    'static/images/systems',
    'static/images/ratings',
    'static/images/fanart',
    'static/images/game_logos',
    'static/images/boxart_back',
    'static/videos',
    'static/images/manuals',
    'static/images/trophies',
    'static/images/avatars',
    'static/images/hardware',
)

CORE_MODULES = (
    ('flask', 'Flask'),
    ('requests', 'Requests'),
    ('yaml', 'PyYAML'),
    ('waitress', 'Waitress'),
)

# The oldest Python the locked requirements install on: numpy needs 3.12.
# Raise it when `uv pip compile --python-version` refuses this one.
MIN_PYTHON = (3, 12)


# ── Distro detection ─────────────────────────────────────────────────────────

def detect_distro():
    """Return canonical platform key.

    One of: 'fedora', 'debian', 'arch', 'suse', 'darwin', 'win32', 'linux',
    'unknown'.
    """
    if sys.platform == 'darwin':
        return 'darwin'
    if sys.platform == 'win32':
        return 'win32'
    if sys.platform != 'linux':
        return 'unknown'
    try:
        with open('/etc/os-release') as f:
            content = f.read().lower()
        for line in content.splitlines():
            if line.startswith('id_like=') or line.startswith('id='):
                val = line.split('=', 1)[1].strip('"\'')
                if any(d in val for d in ('fedora', 'rhel', 'centos', 'nobara')):
                    return 'fedora'
                if any(d in val for d in ('debian', 'ubuntu', 'mint', 'pop')):
                    return 'debian'
                if 'arch' in val:
                    return 'arch'
                if 'suse' in val:
                    return 'suse'
    except FileNotFoundError:
        pass
    return 'linux'


_DISTRO_LABELS = {
    'fedora':  'Fedora/Nobara/RHEL',
    'debian':  'Debian/Ubuntu/Mint',
    'arch':    'Arch Linux',
    'suse':    'openSUSE',
    'darwin':  'macOS',
    'win32':   'Windows',
    'linux':   'Linux',
    'unknown': 'Unknown',
}


def distro_label(key):
    """Pretty-print a distro key for the banner / log."""
    return _DISTRO_LABELS.get(key, 'Unknown')


_VENV_HINTS = {
    'debian': 'sudo apt install python3-venv',
}


def venv_install_hint(key):
    """The package that gives Python its `venv` module, where it is separate."""
    return _VENV_HINTS.get(key, 'Install the Python venv module for your system')


_PIP_HINTS = {
    'fedora': 'sudo dnf install python3-pip',
    'debian': 'sudo apt install python3-pip',
    'arch':   'sudo pacman -S python-pip',
    'suse':   'sudo zypper install python3-pip',
    'darwin': 'python3 -m ensurepip',
    'win32':  'python -m ensurepip',
}


def pip_install_hint(key):
    """Return the right pip install command for the distro key."""
    return _PIP_HINTS.get(key, 'Install pip for your distribution')


# ── Version check ────────────────────────────────────────────────────────────

def python_version_ok():
    """True when the running interpreter satisfies MIN_PYTHON."""
    return sys.version_info[:2] >= MIN_PYTHON


# ── Subprocess helpers ───────────────────────────────────────────────────────

def pip_install(args, base_dir=None, *, quiet=False, python=None, system_ok=False):
    """Run `pip install <args>` with `python` (default: this interpreter).

    A system Python that forbids pip installs (PEP 668) refuses, and the
    refusal is returned: a new install goes into RetroDB's own Python folder
    instead (`choose_python`). `system_ok` is for the updater alone, whose
    install already lives in that system Python; there it retries with
    --break-system-packages, as every release before PASS-59-280 did.

    Returns the `subprocess.CompletedProcess` from the final attempt — callers
    inspect `returncode` and `stderr` themselves.
    """
    cmd = [python or sys.executable, '-m', 'pip', 'install']
    if quiet:
        cmd.append('-q')
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=base_dir)
    if (system_ok and result.returncode != 0
            and 'externally-managed-environment' in result.stderr):
        cmd.append('--break-system-packages')
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=base_dir)
    return result


# ── RetroDB's own Python folder ──────────────────────────────────────────────

VENV_DIR = '.venv'


def venv_python(base_dir):
    """Path of the Python inside RetroDB's own folder (it may not exist)."""
    if os.name == 'nt':
        return os.path.join(base_dir, VENV_DIR, 'Scripts', 'python.exe')
    return os.path.join(base_dir, VENV_DIR, 'bin', 'python')


def externally_managed():
    """True when this interpreter is a system Python that forbids pip
    installs: PEP 668's EXTERNALLY-MANAGED file, outside any venv."""
    if sys.prefix != sys.base_prefix:
        return False
    stdlib = sysconfig.get_path('stdlib')
    return bool(stdlib) and os.path.isfile(os.path.join(stdlib, 'EXTERNALLY-MANAGED'))


def choose_python(base_dir):
    """Return `(python, how, output)`: the interpreter to install into.

    how is 'venv' (RetroDB's own folder already exists), 'venv-created'
    (made now, because this system Python forbids installs), 'system' (this
    interpreter), or 'failed' (the folder could not be made; output says why).
    """
    existing = venv_python(base_dir)
    if os.path.exists(existing):
        return existing, 'venv', ''
    if not externally_managed():
        return sys.executable, 'system', ''
    result = subprocess.run(
        [sys.executable, '-m', 'venv', os.path.join(base_dir, VENV_DIR)],
        capture_output=True, text=True, cwd=base_dir)
    if result.returncode != 0 or not os.path.exists(existing):
        return None, 'failed', (result.stderr or result.stdout).strip()
    return existing, 'venv-created', ''


def copy_private(src, dst):
    """Copy a settings template to `dst`, readable by its owner only (the
    files hold passwords and keys). Never replaces an existing file, or
    follows a link someone left at `dst`. Returns False when `dst` exists."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(dst, flags, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'wb') as out, open(src, 'rb') as inp:
        out.write(inp.read())
    return True


def check_module(name, python=None):
    """Probe whether `import name` succeeds in `python` (default: this one)."""
    try:
        subprocess.run(
            [python or sys.executable, '-c', f'import {name}'],
            capture_output=True, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_build_script(base_dir, script_name, python=None):
    """Run a build script in `base_dir`.

    Returns `(success, output)` where:
      - `success` is True on rc==0, False on failure, None when the script
        file is missing.
      - `output` is the script's stdout (falling back to stderr when stdout
        is empty), or a 'not found' message.
    """
    script = os.path.join(base_dir, script_name)
    if not os.path.exists(script):
        return None, f'{script_name} not found'
    result = subprocess.run(
        [python or sys.executable, script],
        capture_output=True, text=True, cwd=base_dir
    )
    return result.returncode == 0, result.stdout or result.stderr


def server_url(base_dir, python=None):
    """The address RetroDB will answer on: server_port.py's port (the
    environment, then the saved setting, then config), as the start scripts
    print it. Falls back to port 5000 if that cannot be read."""
    port = '5000'
    try:
        result = subprocess.run([python or sys.executable, 'server_port.py'],
                                capture_output=True, text=True, cwd=base_dir)
        if result.returncode == 0 and result.stdout.strip().isdigit():
            port = result.stdout.strip()
    except OSError:
        pass
    return f'http://localhost:{port}'


def select_pip_args(base_dir):
    """Return `(args, source)` for the dependency-install pip command.

    Pass 39.4 — prefer the hashed lockfile (fail-closed on MITM / PyPI
    tamper). Fall back to `requirements.txt` only when the lockfile is
    absent (fresh dev checkout before lockfile regen).

    Returns:
        (['--require-hashes', '-r', lock_path], 'lock')   lockfile present
        (['-r', req_path], 'fallback')                    lockfile missing
        (None, 'missing')                                 neither exists
    """
    lock_path = os.path.join(base_dir, 'requirements.lock')
    req_path = os.path.join(base_dir, 'requirements.txt')
    if os.path.exists(lock_path):
        return ['--require-hashes', '-r', lock_path], 'lock'
    if os.path.exists(req_path):
        return ['-r', req_path], 'fallback'
    return None, 'missing'
