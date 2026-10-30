# =============================================================================
# RETRODB - The player's cores and recommended settings (PASS-59-81)
# =============================================================================
# Which libretro core the bundled player runs for a system, where it comes
# from, and the settings RetroDB writes for it. data/player_cores.json ranks
# the cores per system folder and gives each system's default settings.
#
#   core_file_name() / buildbot_dir()   the host platform's names (§4.2)
#   index()                             the buildbot's core list, cached an hour
#   chosen_core()                       game choice > system choice > ranking (§4.3)
#   install() / install_shaders()       download, check, move into place (§4.4)
#   map_system()                        the player's system row after an install
#   write_system_cfg() / game_recommended()   §4.6's files
#
# Every download URL is the fixed host, the platform directory and a core id
# from the table (INV-3); nothing a request carries reaches one. Redirects are
# refused, so nothing installs from another host (INV-13).
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import tempfile
import threading
import time
import zipfile
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests

import platform_utils
from services import player
from services.database import get_db_with_context, query
from services.launcher.base import LaunchResolutionError

logger = logging.getLogger(__name__)

TABLE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'player_cores.json'
HOST = 'https://buildbot.libretro.com'
SHADERS_URL = f'{HOST}/assets/frontend/shaders_slang.zip'
MAX_BYTES = 256 * 1024 * 1024          # a download, and an extracted core (§4.4)
MAX_SHADER_BYTES = 1024 * 1024 * 1024  # the extracted shader pack
_INDEX_TTL = 3600
_INDEX_RETRY = 300                     # after a failed fetch
_CHUNK = 1024 * 1024
_CORE_ID = re.compile(r'^[a-z0-9_]+$')


# Called after each chunk of a download with (bytes so far, size or None).
# The core job sets it so Settings > Emulators can show a percentage.
progress = None


def report_progress(done: int, size: Optional[int]) -> None:
    if progress:
        progress(done, size)


def content_length(r) -> Optional[int]:
    """A response's size from its Content-Length, or None."""
    try:
        return int(r.headers['Content-Length']) or None
    except (KeyError, ValueError):
        return None


class CoreInstallError(Exception):
    """An install that put nothing in place."""


# -----------------------------------------------------------------------------
# The table
# -----------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _raw() -> dict:
    with open(TABLE_PATH, encoding='utf-8') as f:
        return json.load(f)


def entry(folder) -> Optional[dict]:
    """The system's entry, following `same_as`; None for a folder the
    table does not cover."""
    if not folder or folder.startswith('_'):
        return None
    found = _raw().get(folder)
    if found and 'same_as' in found:
        found = _raw().get(found['same_as'])
    return found


def cores_for(folder) -> list:
    return list((entry(folder) or {}).get('cores', []))


def known_core(core) -> bool:
    return bool(isinstance(core, str) and _CORE_ID.match(core)) and any(
        core in e.get('cores', []) for k, e in _raw().items() if not k.startswith('_'))


def setting_values(setting) -> list:
    return list(_raw()['_settings'][setting]['values'])


def library_name(core) -> Optional[str]:
    """The name the core reports to RetroArch, which names its per-core
    folders such as cheats/ (PASS-59-155 §4.4); None for an unknown core."""
    return _raw().get('_library_names', {}).get(core)


def system_settings(folder) -> dict:
    """{setting: table default} for the managed settings the system has."""
    return dict((entry(folder) or {}).get('settings', {}))


# -----------------------------------------------------------------------------
# Platform (§4.2)
# -----------------------------------------------------------------------------

def core_file_name(core: str) -> str:
    if platform_utils.IS_WINDOWS:
        return f'{core}_libretro.dll'
    if platform_utils.IS_MACOS:
        return f'{core}_libretro.dylib'
    return f'{core}_libretro.so'


def buildbot_dir() -> Optional[str]:
    machine = platform.machine().lower()
    if platform_utils.IS_WINDOWS:
        return 'windows/x86_64' if machine in ('amd64', 'x86_64') else None
    if platform_utils.IS_MACOS:
        arch = {'x86_64': 'x86_64', 'arm64': 'arm64'}.get(machine)
        return f'apple/osx/{arch}' if arch else None
    if platform_utils.IS_LINUX:
        arch = {'x86_64': 'x86_64', 'amd64': 'x86_64',
                'aarch64': 'aarch64', 'arm64': 'aarch64'}.get(machine)
        return f'linux/{arch}' if arch else None
    return None


def _core_url(core: str) -> str:
    return f'{HOST}/nightly/{buildbot_dir()}/latest/{core_file_name(core)}.zip'


# -----------------------------------------------------------------------------
# HTTP — the one place a request leaves; tests replace these two
# -----------------------------------------------------------------------------

def _http_get(url: str, stream: bool = False):
    return requests.get(url, stream=stream, timeout=30, allow_redirects=False)


def _http_head(url: str):
    return requests.head(url, timeout=15, allow_redirects=False)


# -----------------------------------------------------------------------------
# The index
# -----------------------------------------------------------------------------

_index_lock = threading.Lock()
_index_cache = {'dir': None, 'at': 0.0, 'data': None}


def _parse_index(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and re.fullmatch(r'[0-9a-fA-F]{8}', parts[1]):
            out[parts[2]] = (parts[0], parts[1].lower())
    return out


def index() -> Optional[dict]:
    """{'<file>.zip': (date, crc)} for this platform, or None when it
    cannot be fetched. Fetched at most once an hour; a failure is retried
    after five minutes."""
    d = buildbot_dir()
    if d is None:
        return None
    with _index_lock:
        c = _index_cache
        ttl = _INDEX_TTL if c['data'] is not None else _INDEX_RETRY
        if c['dir'] == d and time.time() - c['at'] < ttl:
            return c['data']
        data = None
        try:
            r = _http_get(f'{HOST}/nightly/{d}/latest/.index-extended')
            if r.status_code == 200:
                data = _parse_index(r.text)
            else:
                logger.warning("core index: HTTP %s", r.status_code)
        except requests.RequestException as e:
            logger.warning("core index: %s", e)
        c.update(dir=d, at=time.time(), data=data)
        return data


def is_installed(core: str) -> bool:
    return player.core_file(core_file_name(core)).is_file()


def auto_core(folder) -> Optional[str]:
    """§4.3 step 3: the first table core the platform's index lists. When
    the index cannot be fetched, the first one already installed, so an
    offline launch still plays."""
    cores = cores_for(folder)
    idx = index()
    if idx is None:
        return next((c for c in cores if is_installed(c)), None)
    return next((c for c in cores if f'{core_file_name(c)}.zip' in idx), None)


# -----------------------------------------------------------------------------
# Choices (§4.3, §4.6) — PASS-59-91's table, emulator_id the player's row
# -----------------------------------------------------------------------------

def player_row() -> Optional[dict]:
    """The player's emulators row. Every row is read, so a schema without
    is_player answers None instead of failing."""
    return next((r for r in query("SELECT * FROM emulators") if r.get('is_player')), None)


def _scope_choices(player_id, scope, scope_id) -> dict:
    rows = query("""SELECT setting, value FROM emulator_setting_choices
                    WHERE emulator_id = ? AND scope = ? AND scope_id = ?""",
                 (player_id, scope, scope_id))
    return {r['setting']: r['value'] for r in rows}


def valid_choice(folder, setting, value) -> bool:
    if setting == 'core':
        return value in cores_for(folder)
    return setting in system_settings(folder) and value in setting_values(setting)


def chosen_core(folder, system_id, game_id, player_id) -> Optional[str]:
    """The game's choice, else the system's, else auto_core. A stored
    choice no longer in the system's list is ignored (§4.3)."""
    for scope, sid in (('game', game_id), ('system', system_id)):
        if sid is None:
            continue
        value = _scope_choices(player_id, scope, sid).get('core')
        if value and valid_choice(folder, 'core', value):
            return value
    return auto_core(folder)


def effective_settings(folder, system_id, game_id, player_id) -> dict:
    """{setting: (value, source)} — the game's choice, else the system's,
    else the table default (INV-8)."""
    out = {s: (v, 'default') for s, v in system_settings(folder).items()}
    for scope, sid in (('system', system_id), ('game', game_id)):
        if sid is None:
            continue
        for s, v in _scope_choices(player_id, scope, sid).items():
            if s in out and valid_choice(folder, s, v):
                out[s] = (v, scope)
    return out


# -----------------------------------------------------------------------------
# Settings files (§4.6)
# -----------------------------------------------------------------------------

def shaders_dir() -> Path:
    return player.profile_dir() / 'shaders'


def shaders_ready() -> bool:
    return shaders_dir().is_dir()


def setting_keys(setting) -> set:
    """Every cfg key any value of the setting writes."""
    return {k for v in _raw()['_settings'][setting]['values'].values() for k in v}


def _keys(setting, value) -> dict:
    """The cfg keys one value writes. A shader with no pack on disk writes
    none, so the game runs without it this once (§6)."""
    if setting == 'shader' and value != 'none' and not shaders_ready():
        return {}
    values = _raw()['_settings'][setting]['values'][value]
    return {k: v.replace('<shaders>', str(shaders_dir())) for k, v in values.items()}


def value_of(setting, cfg: dict) -> Optional[str]:
    """The setting's value whose keys all appear in `cfg` with the values it
    writes, or None — how a key set in the player's menu reads back."""
    if not any(k in cfg for k in setting_keys(setting)):
        return None
    for value, keys in _raw()['_settings'][setting]['values'].items():
        wanted = {k: v.replace('<shaders>', str(shaders_dir())) for k, v in keys.items()}
        if all(cfg.get(k) == v for k, v in wanted.items()):
            return value
    return None


def needs_shaders(folder, system_id, game_id, player_id) -> bool:
    """A launch's settings name a shader the profile does not hold yet."""
    value = effective_settings(folder, system_id, game_id, player_id).get('shader', ('none',))[0]
    return value != 'none' and not shaders_ready()


def system_cfg_path(folder) -> Path:
    return player.profile_dir() / 'settings' / 'system' / f'{folder}.cfg'


def write_system_cfg(folder, system_id, player_id) -> None:
    """The system's choice, else the table default, for every managed
    setting the system has; every other line of the file is kept."""
    keys = {}
    for setting, (value, _source) in effective_settings(folder, system_id, None,
                                                         player_id).items():
        keys.update(_keys(setting, value))
    player._set_keys(system_cfg_path(folder), keys)


def game_recommended(folder, game_id, player_id, core) -> dict:
    """{'cfg': the keys of each game choice, 'opt': _options[core]} —
    what player.launch_args writes around the user-set keys."""
    cfg = {}
    for setting, value in _scope_choices(player_id, 'game', game_id).items():
        if setting != 'core' and valid_choice(folder, setting, value):
            cfg.update(_keys(setting, value))
    return {'cfg': cfg, 'opt': dict(_raw().get('_options', {}).get(core, {}))}


# -----------------------------------------------------------------------------
# Downloads (§4.4)
# -----------------------------------------------------------------------------

def download_size(core: str) -> Optional[int]:
    """The core zip's size from a HEAD, or None."""
    if not known_core(core) or buildbot_dir() is None:
        return None
    try:
        r = _http_head(_core_url(core))
        return int(r.headers['Content-Length']) if r.status_code == 200 else None
    except (requests.RequestException, KeyError, ValueError):
        return None


def _download(url: str, part: Path, get=None) -> None:
    """Stream `url` to `part`; anything but a 200 under the cap fails.
    `get` replaces _http_get (the cheat packs follow redirects)."""
    r = (get or _http_get)(url, stream=True)
    try:
        if r.status_code != 200:
            raise CoreInstallError(f'HTTP {r.status_code}')
        total, size = 0, content_length(r)
        with open(part, 'wb') as f:
            for chunk in r.iter_content(_CHUNK):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise CoreInstallError('the download is larger than 256 MiB')
                f.write(chunk)
                report_progress(total, size)
    finally:
        r.close()


def _record_path() -> Path:
    return player.profile_dir() / 'cores' / 'installed.json'


def installed() -> dict:
    """{core: {'crc', 'date'}} for the cores RetroDB installed."""
    try:
        return json.loads(_record_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def install(core: str) -> Path:
    """Download, check and install <profile>/cores/<core_file_name(core)>.
    Raises CoreInstallError and leaves any existing file untouched."""
    if not known_core(core):
        raise CoreInstallError(f'{core!r} is not a core RetroDB offers')
    if buildbot_dir() is None:
        raise CoreInstallError('cores are not built for this computer')
    name = core_file_name(core)
    idx = index()
    if idx is None:
        raise CoreInstallError('the core list could not be fetched')
    line = idx.get(f'{name}.zip')
    if line is None:
        raise CoreInstallError(f'{core} is not built for this computer')
    cores = player.profile_dir() / 'cores'
    part = cores / f'.{name}.zip.part'
    tmp = None
    try:
        cores.mkdir(parents=True, exist_ok=True)
        _download(_core_url(core), part)
        with zipfile.ZipFile(part) as zf:
            try:
                member = zf.getinfo(name)   # the exact name: no directory part
            except KeyError:
                raise CoreInstallError(f'the download holds no {name}') from None
            fd, tmp = tempfile.mkstemp(dir=cores, prefix=f'.{name}.')
            crc, size = 0, 0
            with os.fdopen(fd, 'wb') as out, zf.open(member) as src:
                for chunk in iter(lambda: src.read(_CHUNK), b''):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise CoreInstallError('the core is larger than 256 MiB')
                    crc = zlib.crc32(chunk, crc)
                    out.write(chunk)
        if f'{crc:08x}' != line[1]:
            raise CoreInstallError(f'{name} failed its checksum')
        if not platform_utils.IS_WINDOWS:
            # A core is a library the player loads; the PASS-59-81 spec's
            # install steps make it executable. 0o755 lets only the owner write.
            os.chmod(tmp, 0o755)  # noqa: S103  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
        dest = cores / name
        os.replace(tmp, dest)
        tmp = None
        record = installed()
        record[core] = {'crc': line[1], 'date': line[0]}
        _record_path().write_text(json.dumps(record, indent=1, sort_keys=True),
                                  encoding='utf-8')
        return dest
    except (OSError, zipfile.BadZipFile, requests.RequestException) as e:
        raise CoreInstallError(str(e)) from e
    finally:
        part.unlink(missing_ok=True)
        if tmp:
            Path(tmp).unlink(missing_ok=True)


def install_shaders() -> Path:
    """The slang shader pack into <profile>/shaders/, whole or not at all.
    No CRC is published for it (§4.5)."""
    profile = player.profile_dir()
    part = profile / '.shaders_slang.zip.part'
    staging = None
    try:
        profile.mkdir(parents=True, exist_ok=True)
        _download(SHADERS_URL, part)
        staging = Path(tempfile.mkdtemp(dir=profile, prefix='.shaders-'))
        root = staging.resolve()
        total = 0
        with zipfile.ZipFile(part) as zf:
            for info in zf.infolist():
                target = (staging / info.filename).resolve()
                if target != root and root not in target.parents:
                    raise CoreInstallError(f'unsafe path in the shader pack: {info.filename}')
                total += info.file_size
                if total > MAX_SHADER_BYTES:
                    raise CoreInstallError('the shader pack is larger than 1 GiB')
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, 'wb') as out:
                    shutil.copyfileobj(src, out, _CHUNK)
        dest = shaders_dir()
        old = None
        if dest.exists():
            old = profile / f'.shaders-old-{os.getpid()}'
            os.replace(dest, old)
        os.replace(staging, dest)
        staging = None
        if old:
            shutil.rmtree(old, ignore_errors=True)
        return dest
    except (OSError, zipfile.BadZipFile, requests.RequestException) as e:
        raise CoreInstallError(str(e)) from e
    finally:
        part.unlink(missing_ok=True)
        if staging:
            shutil.rmtree(staging, ignore_errors=True)


# -----------------------------------------------------------------------------
# The player's system rows (§4.4)
# -----------------------------------------------------------------------------

def map_system(system_id, core: str) -> None:
    """The player's system row names the core; it becomes the default only
    where the system has no default mapping that resolves (INV-5); then the
    system cfg is written."""
    # Imported here: launch_resolver imports this module at load time.
    from services.launch_resolver import _mapping_resolves, _pick_mapping
    emu = player_row()
    system = query("SELECT folder FROM systems WHERE id = ?", (system_id,), one=True)
    if not emu or not system:
        return
    try:
        cur_emu, cur_row = _pick_mapping(system_id, None)
        make_default = (bool(cur_emu and cur_emu.get('is_player'))
                        or not _mapping_resolves(cur_emu, cur_row))
    except LaunchResolutionError:
        make_default = True
    with get_db_with_context() as conn:
        updated = conn.execute("""UPDATE system_emulators SET retroarch_core = ?
                                  WHERE system_id = ? AND emulator_id = ?""",
                               (core_file_name(core), system_id, emu['id'])).rowcount
        if not updated:
            conn.execute("""INSERT INTO system_emulators
                            (system_id, emulator_id, is_default, retroarch_core)
                            VALUES (?, ?, 0, ?)""",
                         (system_id, emu['id'], core_file_name(core)))
        if make_default:
            conn.execute("""UPDATE system_emulators SET is_default = (emulator_id = ?)
                            WHERE system_id = ?""", (emu['id'], system_id))
        conn.commit()
    write_system_cfg(system['folder'], system_id, emu['id'])


def can_serve(folder) -> bool:
    """The Play button's check for a player system: a ranked core is
    installed, or one may be downloaded. Makes no request."""
    from settings_manager import get_setting
    cores = cores_for(folder)
    if any(is_installed(c) for c in cores):
        return True
    return bool(cores and buildbot_dir() is not None
                and get_setting('player_core_downloads', True))


class CoreMissing(LaunchResolutionError):
    """The player's chosen core is not installed yet (§4.5). The launch
    route turns this into a download, or into §6's 422."""

    def __init__(self, core, system_id, system_name, path):
        super().__init__(f"Player core not found: {path}")
        self.core, self.system_id, self.system_name = core, system_id, system_name
