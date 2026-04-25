# =============================================================================
# RETRODB - Launch settings auxiliary routes
# =============================================================================
# Auto-detect probe for the retroarch_binary and retroarch_cores_dir settings.
# Spec §RetroArch path auto-detect.
# =============================================================================

import logging
import os
import shutil
import subprocess
from pathlib import Path

from flask import Blueprint, request

from services.api_helpers import handle_api_errors, success
from services.auth import login_required, admin_required

logger = logging.getLogger(__name__)

bp = Blueprint('launch_settings', __name__)


_BIN_CHAIN = (
    '/usr/bin/retroarch',
    '/usr/local/bin/retroarch',
    str(Path('~/.local/bin/retroarch').expanduser()),
)
_CORES_CHAIN = (
    str(Path('~/.config/retroarch/cores/').expanduser()),
    '/usr/lib64/libretro/',
    '/usr/lib/libretro/',
    '/var/lib/flatpak/exports/share/libretro/cores/',
)


def _probe_retroarch_binary() -> str:
    for cand in _BIN_CHAIN:
        if Path(cand).exists() and os.access(cand, os.X_OK):
            return cand
    try:
        rv = subprocess.run(['flatpak', 'info', 'org.libretro.RetroArch'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=5)
        if rv.returncode == 0:
            return 'flatpak run org.libretro.RetroArch'
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return shutil.which('retroarch') or ''


def _probe_cores_dir() -> str:
    for cand in _CORES_CHAIN:
        if Path(cand).is_dir():
            return cand
    return ''


def _validate_binary(path: str) -> dict:
    if not path:
        return {'path': '', 'error': 'empty'}
    if path.startswith('flatpak run '):
        return {'path': path, 'version': 'flatpak'}
    if not Path(path).exists():
        return {'path': path, 'error': 'not found'}
    try:
        rv = subprocess.run([path, '--version'],
                            capture_output=True, text=True, timeout=5)
        out = (rv.stdout or '') + (rv.stderr or '')
        if 'RetroArch' not in out:
            return {'path': path, 'error': 'binary did not report RetroArch'}
        first = out.strip().split('\n', 1)[0]
        return {'path': path, 'version': first[:120]}
    except Exception as e:
        return {'path': path, 'error': str(e)}


def _validate_cores_dir(path: str) -> dict:
    if not path:
        return {'path': '', 'error': 'empty'}
    p = Path(path).expanduser()
    if not p.is_dir():
        return {'path': str(p), 'error': 'not a directory'}
    cores = list(p.glob('*_libretro.so')) + list(p.glob('*_libretro.dll')) + \
        list(p.glob('*_libretro.dylib'))
    if not cores:
        return {'path': str(p), 'error': 'no *_libretro.* files'}
    return {'path': str(p), 'core_count': len(cores)}


@bp.route('/api/settings/retroarch/detect', methods=['POST'])
@login_required
@admin_required
@handle_api_errors
def api_retroarch_detect():
    """Run the auto-detect probe.  Persistence is the admin's responsibility:
    the response shows the suggestion; the UI then PUTs to the existing
    settings endpoint to save."""
    binary = _probe_retroarch_binary()
    cores = _probe_cores_dir()
    do_validate = request.args.get('validate') == 'true'
    return success(
        binary=_validate_binary(binary) if do_validate else {'path': binary},
        cores_dir=_validate_cores_dir(cores) if do_validate else {'path': cores},
    )
