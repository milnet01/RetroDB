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
from services.database import query, execute
from services.emulator_adapters import ADAPTERS, find_data_dir
from services.launch_resolver import _mapping_resolves
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
# Matches AppImages in the emulator_scan_paths setting against each adapter's
# name patterns (services/emulator_adapters.py, PASS-59-91 §4.1).  When a match
# has a sibling `<base>-portable.sh`, the portable script is preferred — it
# preserves the AppImage's portable .home dir (so e.g. RetroArch keeps its
# custom cores layout instead of falling back to ~/.config/retroarch/).

# Cap how many directory entries we consider per scan root, within the depth
# cap.  A guard against a misconfigured scan path pointing at /home or /; an
# emulator drive holds tens of thousands of shallow entries (its configs and
# content), so the cap sits well above that.
_MAX_ENTRIES_PER_ROOT = 100000
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
    """Yield the Path of each *.AppImage / *.appimage / *-portable.sh found
    under any root, at most _MAX_SCAN_DEPTH deep and _MAX_ENTRIES_PER_ROOT
    entries per root.  Hidden folders and AppImage `.home` folders are not
    entered: they hold an emulator's own files, thousands of them, and
    walking them used up the cap before the next emulator's folder."""
    for root in roots:
        if not root.is_dir():
            continue
        seen = 0
        for dirpath, dirnames, filenames in os.walk(
                root, onerror=lambda e: logger.warning("emulator scan: %s", e)):
            depth = len(Path(dirpath).relative_to(root).parts)
            dirnames[:] = sorted(d for d in dirnames
                                 if depth + 1 < _MAX_SCAN_DEPTH
                                 and not d.startswith('.') and not d.endswith('.home'))
            seen += len(dirnames) + len(filenames)
            if seen > _MAX_ENTRIES_PER_ROOT:
                logger.warning(
                    "emulator scan: %s exceeded %d entries; truncating",
                    root, _MAX_ENTRIES_PER_ROOT,
                )
                break
            for name in sorted(filenames):
                if name.lower().endswith('.appimage') or name.endswith('-portable.sh'):
                    yield Path(dirpath) / name


def _flatpak_bin_dirs() -> list:
    return [Path('/var/lib/flatpak/exports/bin'),
            Path.home() / '.local' / 'share' / 'flatpak' / 'exports' / 'bin']


def _suggestion(adapter, path, preferred, has_portable_script) -> dict:
    data_dir = find_data_dir(adapter, Path(preferred))
    return {
        'path': str(path),
        'preferred': str(preferred),
        'has_portable_script': has_portable_script,
        'systems': list(adapter.systems),
        'data_dir': str(data_dir) if data_dir else None,
    }


def _detect_emulators(roots) -> dict:
    """Return {binary_name: {'path', 'preferred', 'has_portable_script',
    'systems', 'data_dir'}, ...}.

    `path` is the AppImage absolute path; `preferred` is either the
    portable-script wrapper (if present alongside) or the AppImage itself.
    First match per emulator wins, except that a copy with a portable script
    beats an earlier one without (the user's own beside a bundled one, as
    ES-DE ships RetroArch).  An emulator with no file under the roots falls
    back to its exported Flatpak launcher, which is executable, so
    _resolve_binary takes it unchanged (§4.2)."""
    found = {}
    candidates = list(_walk_appimages(roots))
    for p in candidates:
        for key, adapter in ADAPTERS.items():
            if key in found and found[key]['has_portable_script']:
                continue
            if not any(pat.match(p.name) for pat in adapter.name_patterns):
                continue
            portable = p.parent / f"{adapter.portable_base}-portable.sh"
            preferred = portable if (portable.exists() and os.access(str(portable), os.X_OK)) else p
            if key not in found or portable.exists():
                found[key] = _suggestion(adapter, p, preferred, portable.exists())
            break  # one emulator per AppImage; move to next file
    for key, adapter in ADAPTERS.items():
        if key in found:
            continue
        for app_id in adapter.flatpak_ids:
            launcher = next((d / app_id for d in _flatpak_bin_dirs()
                             if os.access(d / app_id, os.X_OK)), None)
            if launcher:
                found[key] = _suggestion(adapter, launcher, launcher, False)
                break
    return found


def _wire_systems(emulator_id, system_ids) -> None:
    """Map the emulator to each system, keeping any existing row's core and
    extra args.  It becomes a system's default only when that system has no
    default or its default does not resolve (§4.3, §3.8)."""
    for system_id in system_ids:
        execute("""
            INSERT INTO system_emulators (system_id, emulator_id, is_default)
            VALUES (?, ?, 0)
            ON CONFLICT(system_id, emulator_id) DO NOTHING
        """, (system_id, emulator_id))
        current = query("""
            SELECT * FROM system_emulators
            WHERE system_id = ? AND is_default = 1 ORDER BY id LIMIT 1
        """, (system_id,), one=True)
        if current:
            emu = query("SELECT * FROM emulators WHERE id = ?",
                        (current['emulator_id'],), one=True)
            if _mapping_resolves(emu, current):
                continue
        execute("UPDATE system_emulators SET is_default = (emulator_id = ?) "
                "WHERE system_id = ?", (emulator_id, system_id))


@bp.route('/api/settings/emulators/detect', methods=['POST'])
@login_required
@admin_required
@handle_api_errors
def api_emulators_detect():
    """Walk emulator_scan_paths for AppImages, and the Flatpak exports, and
    return a suggestion for each detected emulator in the registry.
    Optional ?apply=true writes the binary_path_override on each matching
    emulators row and wires every suggestion to its systems (§4.3).
    """
    roots = _scan_paths()
    found = _detect_emulators(roots)
    apply_now = request.args.get('apply') == 'true'

    rows = query("SELECT id, name, binary_name, binary_path_override FROM emulators")
    by_binary = {r['binary_name']: r for r in rows}
    system_ids = {r['folder']: r['id'] for r in query("SELECT id, folder FROM systems")}

    suggestions = []
    for key, info in found.items():
        row = by_binary.get(key)
        if not row:
            continue  # registry has no entry for this emulator
        suggestions.append({
            'emulator_id':           row['id'],
            'emulator_name':         row['name'],
            'detected_path':         info['path'],
            'preferred_path':        info['preferred'],
            'has_portable_script':   info['has_portable_script'],
            'current_override':      row['binary_path_override'],
            'would_change':          row['binary_path_override'] != info['preferred'],
            'systems':               [f for f in info['systems'] if f in system_ids],
            'data_dir':              info['data_dir'],
        })

    applied = []
    if apply_now:
        for s in suggestions:
            if s['would_change']:
                execute(
                    "UPDATE emulators SET binary_path_override = ?, updated_at = datetime('now') WHERE id = ?",
                    (s['preferred_path'], s['emulator_id']),
                )
                applied.append(s['emulator_id'])
            _wire_systems(s['emulator_id'], [system_ids[f] for f in s['systems']])

    return success(
        scanned_paths=[str(r) for r in roots],
        found_count=len(suggestions),
        suggestions=suggestions,
        applied=applied,
    )
