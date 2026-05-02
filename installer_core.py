"""
RetroDB Installer Core
Shared logic between `install.py` (CLI) and `install_gui.py` (Tkinter wizard):
distro detection, pip-with-PEP-668-fallback, module import probe, build-script
runner, config-copy + directory manifests. Each frontend keeps its own UI loop
(print() vs self._log()) and reuses these helpers.

Pass 38.3 — extracted to close the rule-of-three triggered by the Pass 38.5
bundle-name drift (two installers checking different filenames in 'use
existing bundle' fallback).
"""

import os
import subprocess
import sys


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

MIN_PYTHON = (3, 8)


# ── Distro detection ─────────────────────────────────────────────────────────

def detect_distro():
    """Return canonical platform key.

    One of: 'fedora', 'debian', 'arch', 'darwin', 'win32', 'linux', 'unknown'.
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
    except FileNotFoundError:
        pass
    return 'linux'


_DISTRO_LABELS = {
    'fedora':  'Fedora/Nobara/RHEL',
    'debian':  'Debian/Ubuntu/Mint',
    'arch':    'Arch Linux',
    'darwin':  'macOS',
    'win32':   'Windows',
    'linux':   'Linux',
    'unknown': 'Unknown',
}


def distro_label(key):
    """Pretty-print a distro key for the banner / log."""
    return _DISTRO_LABELS.get(key, 'Unknown')


_PIP_HINTS = {
    'fedora': 'sudo dnf install python3-pip',
    'debian': 'sudo apt install python3-pip',
    'arch':   'sudo pacman -S python-pip',
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

def pip_install(args, base_dir=None, *, quiet=False):
    """Run `pip install <args>` with the PEP 668 break-system-packages fallback.

    Returns the `subprocess.CompletedProcess` from the final attempt — callers
    inspect `returncode` and `stderr` themselves.
    """
    cmd = [sys.executable, '-m', 'pip', 'install']
    if quiet:
        cmd.append('-q')
    cmd.extend(args)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=base_dir)
    if result.returncode != 0 and 'externally-managed-environment' in result.stderr:
        cmd.append('--break-system-packages')
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=base_dir)
    return result


def check_module(name):
    """Probe whether `import name` succeeds in the same interpreter."""
    try:
        subprocess.run(
            [sys.executable, '-c', f'import {name}'],
            capture_output=True, check=True
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_build_script(base_dir, script_name):
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
        [sys.executable, script],
        capture_output=True, text=True, cwd=base_dir
    )
    return result.returncode == 0, result.stdout or result.stderr


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
