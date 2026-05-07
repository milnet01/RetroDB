# =============================================================================
# RETRODB - Launch settings auxiliary routes
# =============================================================================
# Auto-detect probe for the retroarch_binary and retroarch_cores_dir settings.
# Spec §RetroArch path auto-detect.
# =============================================================================

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from flask import Blueprint, request

from services.api_helpers import handle_api_errors, success
from services.auth import login_required, admin_required
from services.database import query, execute
from settings_manager import get_setting

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


# -----------------------------------------------------------------------------
# Pass 44.1B — generic emulator AppImage / portable-script auto-detect
# -----------------------------------------------------------------------------
# Matches AppImages in the emulator_scan_paths setting against case-insensitive
# regexes keyed on the emulators.name in the registry.  When a match has a
# sibling `<bin>-portable.sh`, the portable script is preferred — it preserves
# the AppImage's portable .home dir (so e.g. RetroArch keeps its custom
# cores layout instead of falling back to ~/.config/retroarch/).

_NAME_PATTERNS = {
    'RetroArch':    re.compile(r'.*retroarch.*\.appimage$', re.IGNORECASE),
    'DuckStation':  re.compile(r'duckstation.*\.appimage$', re.IGNORECASE),
    'PCSX2':        re.compile(r'pcsx2.*\.appimage$', re.IGNORECASE),
    'RPCS3':        re.compile(r'rpcs3.*\.appimage$', re.IGNORECASE),
    'PPSSPP':       re.compile(r'ppsspp.*\.appimage$', re.IGNORECASE),
    'Dolphin':      re.compile(r'dolphin.*\.appimage$', re.IGNORECASE),
    'Cemu':         re.compile(r'cemu.*\.appimage$', re.IGNORECASE),
    'mGBA':         re.compile(r'mgba.*\.appimage$', re.IGNORECASE),
    'melonDS':      re.compile(r'melonds.*\.appimage$', re.IGNORECASE),
    'Citra':        re.compile(r'citra.*\.appimage$', re.IGNORECASE),
    'ScummVM':      re.compile(r'scummvm.*\.appimage$', re.IGNORECASE),
    'MAME':         re.compile(r'mame.*\.appimage$', re.IGNORECASE),
}

# Friendly base names per emulator for the portable-script preference check.
# Looking for `<base>-portable.sh` next to the AppImage (the convention the
# user already follows in /mnt/Emulators).
_PORTABLE_BASE = {
    'RetroArch': 'retroarch',
    'DuckStation': 'duckstation',
    'PCSX2': 'pcsx2',
    'RPCS3': 'rpcs3',
    'PPSSPP': 'ppsspp',
    'Dolphin': 'dolphin',
    'Cemu': 'cemu',
    'mGBA': 'mgba',
    'melonDS': 'melonds',
    'Citra': 'citra',
    'ScummVM': 'scummvm',
    'MAME': 'mame',
}

# Cap how many directory entries we consider per scan root.  Walking
# /mnt/Emulators with millions of files would be silly; in practice
# emulator AppImages are top-level so depth is shallow.  This is a guard
# against a misconfigured scan path pointing at /home or /.
_MAX_ENTRIES_PER_ROOT = 5000
_MAX_SCAN_DEPTH = 4


def _scan_paths() -> list:
    raw = get_setting('emulator_scan_paths',
                      '/mnt/Emulators:~/Downloads:~/.local/bin:/opt')
    if isinstance(raw, list):
        parts = raw
    else:
        parts = [p.strip() for p in str(raw).split(':') if p.strip()]
    return [Path(p).expanduser() for p in parts]


def _walk_appimages(roots):
    """Yield (Path, parent_dir) for each *.AppImage / *.appimage / *-portable.sh
    found under any root, capped at _MAX_ENTRIES_PER_ROOT * _MAX_SCAN_DEPTH."""
    for root in roots:
        if not root.is_dir():
            continue
        seen = 0
        # rglob with manual depth check to avoid run-away walks on bad config.
        try:
            for p in root.rglob('*'):
                seen += 1
                if seen > _MAX_ENTRIES_PER_ROOT:
                    logger.warning(
                        "emulator scan: %s exceeded %d entries; truncating",
                        root, _MAX_ENTRIES_PER_ROOT,
                    )
                    break
                # Depth guard
                try:
                    depth = len(p.relative_to(root).parts)
                except ValueError:
                    continue
                if depth > _MAX_SCAN_DEPTH:
                    continue
                if not p.is_file():
                    continue
                name = p.name
                if name.lower().endswith('.appimage') or name.endswith('-portable.sh'):
                    yield p
        except OSError as e:
            logger.warning("emulator scan: %s: %s", root, e)


def _detect_emulators(roots) -> dict:
    """Return {emulator_name: {'path': str, 'preferred': str}, ...}.

    `path` is the AppImage absolute path; `preferred` is either the
    portable-script wrapper (if present alongside) or the AppImage itself.
    First match per emulator wins (further matches are ignored)."""
    found = {}
    candidates = list(_walk_appimages(roots))
    for p in candidates:
        for emu_name, pat in _NAME_PATTERNS.items():
            if emu_name in found:
                continue
            if not pat.match(p.name):
                continue
            base = _PORTABLE_BASE.get(emu_name, emu_name.lower())
            portable = p.parent / f"{base}-portable.sh"
            preferred = str(portable) if (portable.exists() and os.access(str(portable), os.X_OK)) else str(p)
            found[emu_name] = {
                'path': str(p),
                'preferred': preferred,
                'has_portable_script': portable.exists(),
            }
            break  # one emulator per AppImage; move to next file
    return found


@bp.route('/api/settings/emulators/detect', methods=['POST'])
@login_required
@admin_required
@handle_api_errors
def api_emulators_detect():
    """Walk emulator_scan_paths for AppImages and return suggestions for
    each emulator name that's still in the registry without a binary
    path override.  Optional ?apply=true atomically writes the
    binary_path_override on each matching emulators row.
    """
    roots = _scan_paths()
    found = _detect_emulators(roots)
    apply_now = request.args.get('apply') == 'true'

    rows = query("SELECT id, name, binary_path_override FROM emulators")
    by_name = {r['name']: r for r in rows}

    suggestions = []
    for emu_name, info in found.items():
        row = by_name.get(emu_name)
        if not row:
            continue  # registry has no entry for this emulator
        suggestions.append({
            'emulator_id':           row['id'],
            'emulator_name':         emu_name,
            'detected_path':         info['path'],
            'preferred_path':        info['preferred'],
            'has_portable_script':   info['has_portable_script'],
            'current_override':      row['binary_path_override'],
            'would_change':          row['binary_path_override'] != info['preferred'],
        })

    applied = []
    if apply_now:
        for s in suggestions:
            if not s['would_change']:
                continue
            execute(
                "UPDATE emulators SET binary_path_override = ?, updated_at = datetime('now') WHERE id = ?",
                (s['preferred_path'], s['emulator_id']),
            )
            applied.append(s['emulator_id'])

    return success(
        scanned_paths=[str(r) for r in roots],
        found_count=len(suggestions),
        suggestions=suggestions,
        applied=applied,
    )
