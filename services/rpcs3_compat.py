# =============================================================================
# RETRODB - RPCS3 compatibility status for PS3 games
# =============================================================================
# RPCS3 keeps the rpcs3.net compatibility list it downloads (Game List >
# right-click > Download Compatibility Database) as
# `<config dir>/GuiConfigs/compat_database.dat`: the raw JSON of
# https://rpcs3.net/compatibility?api=v1&export, keyed by title ID without a
# dash (`BLUS30443`). RetroDB reads that file from the local RPCS3 install and
# never downloads it. Only PS3 games with a local ROM are looked up; imported
# games (PSN, Steam, Xbox, CLZ) have no disc to read a serial from.
#
# The status is not stored: the file is read again only when RPCS3 rewrites
# it, so a newer list shows at once.
# =============================================================================

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from services.database import get_db_with_context, query

logger = logging.getLogger(__name__)

# rpcs3.net's statuses, best first.
STATUSES = ('playable', 'ingame', 'intro', 'loadable', 'nothing')

COMPAT_FILE = Path('GuiConfigs') / 'compat_database.dat'
_PATH_TTL = 60.0

_lock = threading.Lock()
_path_cache = {'at': 0.0, 'path': None}
_db_cache = {'key': None, 'results': {}}
_serial_fill = {'running': False}


def _candidate_dirs() -> list:
    """RPCS3 config folders to try: those of each RPCS3 emulator row first,
    then the usual places for a program found on no row."""
    from services.emulator_adapters import ADAPTERS
    from services.launch_resolver import LaunchResolutionError, _resolve_binary
    adapter = ADAPTERS['rpcs3']
    dirs = []
    rows = query("SELECT * FROM emulators WHERE binary_name = 'rpcs3' ORDER BY id")
    for row in rows or []:
        try:
            dirs += adapter.data_dirs(Path(_resolve_binary(dict(row), None)))
        except (LaunchResolutionError, OSError):
            continue
    return dirs + adapter.data_dirs(Path('rpcs3'))


def compat_file() -> Optional[Path]:
    """The local RPCS3's compat_database.dat, or None. Looked for at most
    once a minute."""
    now = time.monotonic()
    with _lock:
        if now - _path_cache['at'] < _PATH_TTL:
            return _path_cache['path']
    found = None
    try:
        found = next((d / COMPAT_FILE for d in _candidate_dirs()
                      if (d / COMPAT_FILE).is_file()), None)
    except Exception as e:  # noqa: BLE001 — a page must render without it
        logger.info(f"RPCS3 compatibility: cannot look for the list: {e}")
    with _lock:
        _path_cache.update(at=now, path=found)
    return found


def _results() -> dict:
    """The list's `results`, re-read only when the file changes."""
    path = compat_file()
    if path is None:
        return {}
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _db_cache['key'] == key:
            return _db_cache['results']
    results = {}
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='replace'))
        if isinstance(data, dict) and int(data.get('return_code', -255)) >= 0 \
                and isinstance(data.get('results'), dict):
            results = data['results']
        else:
            logger.info(f"RPCS3 compatibility: {path} holds no results")
    except (OSError, ValueError, TypeError) as e:
        logger.info(f"RPCS3 compatibility: cannot read {path}: {e}")
    with _lock:
        _db_cache.update(key=key, results=results)
    return results


def stamp() -> str:
    """Changes when the list does: for ETags of responses that carry a status."""
    return str(_db_cache['key'] or '') if _results() else ''


def available() -> bool:
    """True when a local RPCS3 has downloaded its compatibility list."""
    return bool(_results())


def status_for_serial(serial) -> Optional[dict]:
    """{'status': 'playable', 'date': '2024-05-01'} for a serial written
    `BLUS-30443` or `BLUS30443`; None when it is not on the list."""
    if not serial:
        return None
    entry = _results().get(str(serial).replace('-', '').upper())
    if not isinstance(entry, dict):
        return None
    status = str(entry.get('status', '')).strip().lower()
    if status not in STATUSES:
        return None
    return {'status': status, 'date': str(entry.get('date') or '')}


def applies_to(game) -> bool:
    """A PS3 game with a local ROM. Imported games have a virtual rom_path."""
    from services.game_metadata_service import import_source_for_rom_path
    keys = game.keys() if hasattr(game, 'keys') else ()
    folder = game['system_folder'] if 'system_folder' in keys else None
    rom_path = game['rom_path'] if 'rom_path' in keys else None
    return folder == 'ps3' and bool(rom_path) and import_source_for_rom_path(rom_path) is None


def status_for_game(game) -> Optional[dict]:
    """The status of a games row (with system_folder, rom_path and
    disc_serial), or None. Reads nothing from disc."""
    if not applies_to(game):
        return None
    return status_for_serial(game['disc_serial'] if 'disc_serial' in game.keys() else None)


def ensure_serial(game) -> None:
    """Read and store the serial of one PS3 game that has none yet (the game
    page). A list page calls fill_missing_serials instead."""
    if not applies_to(game) or game.get('disc_serial') is not None:
        return
    from services.standalone_settings import disc_ids
    serial, _crc = disc_ids(game)
    game['disc_serial'] = serial


def fill_missing_serials() -> None:
    """Read, in the background, the serial of every local PS3 game not read
    yet, so list pages show their status from the next load. Does nothing
    when RPCS3 has no list, or a fill is already running."""
    if not available():
        return
    with _lock:
        if _serial_fill['running']:
            return
        _serial_fill['running'] = True
    threading.Thread(target=_fill_serials, name='rpcs3-serials', daemon=True).start()


def _fill_serials() -> None:
    from services.standalone_settings import disc_ids
    try:
        # Its own connection: the request one is not for other threads.
        with get_db_with_context() as conn:
            rows = conn.execute("""
                SELECT g.id, g.rom_path, g.disc_serial, g.disc_crc, s.folder AS system_folder
                FROM games g JOIN systems s ON s.id = g.system_id
                WHERE s.folder = 'ps3' AND g.disc_serial IS NULL
                  AND COALESCE(g.rom_path, '') != ''
            """).fetchall()
        for row in rows:
            game = dict(row)
            if applies_to(game):
                disc_ids(game)
    except Exception as e:  # noqa: BLE001 — a background helper must not raise
        logger.warning(f"RPCS3 compatibility: reading PS3 serials failed: {e}")
    finally:
        with _lock:
            _serial_fill['running'] = False
