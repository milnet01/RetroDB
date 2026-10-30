# =============================================================================
# RETRODB - The bundled player's profile (PASS-59-64 §4.4–4.6)
# =============================================================================
# The player is RetroDB's own build of the RetroArch fork. It runs from a
# profile RetroDB owns, `<BASE_DIR>/data/player/`, kept apart from the user's
# own RetroArch. This module writes that profile's settings files before a
# launch, builds the argv the player binds to, and after a session keeps the
# changes the user made in the player's menu as that game's settings.
#
#   launch_args()   base cfg keys, game cfg/.opt, run layer -> argv after binary
#   after_session() absorb menu saves, mark user-set keys, drop the run layer,
#                   keep the in-game cheat switches (PASS-59-155)
#   reset()         Reset to recommended: delete the game's .cfg/.opt/.json
#
# The recommended settings come from services/player_cores.py (PASS-59-81).
# =============================================================================

from __future__ import annotations

import json
import logging
import re
import shlex
import socket
import sys
from pathlib import Path
from typing import Optional

import config
from services.launcher.base import LaunchResolutionError

logger = logging.getLogger(__name__)

_CFG_LINE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"([^"\n]*)"\s*$')
_SKIP_LINE = re.compile(r'^\s*(#.*)?$')

# §4.4's base block. Rewritten before every launch; every other line of the
# base cfg is the player's and is kept.
_BASE_KEYS = {
    'config_save_on_exit': 'false',
    'auto_overrides_enable': 'false',
    'game_specific_options': 'false',
    'global_core_options': 'false',
    'quit_on_close_content': '2',     # quit when launched from the CLI
    'confirm_quit': 'false',          # one QUIT must quit (§4.6)
    'ui_companion_start_on_boot': 'false',
    # On only in a launch's run layer, where RetroDB sends a command: official
    # RetroArch 1.22.2 listens on every network interface (PASS-59-139).
    'network_cmd_enable': 'false',
    # Load the game's cheat list, which RetroDB puts in place (PASS-59-155).
    'apply_cheats_after_load': 'true',
}
# The left stick works as the D-pad. Value 1 rather than the forced 3: RetroArch
# drops the mapping when a core asks for analog input, so a game that uses the
# stick keeps it, and no system needs listing.
_BASE_KEYS.update({f'input_player{port}_analog_dpad_mode': '1' for port in range(1, 9)})
# Keys a menu save may never bring back into a game's settings (§4.5).
_PROTECTED_KEYS = set(_BASE_KEYS) | {
    'rgui_config_directory', 'savefile_directory', 'savestate_directory',
    'input_remapping_directory', 'libretro_directory', 'system_directory',
    'core_options_path', 'cheat_database_path',
    # The launching user's RetroAchievements sign-in lives in the run layer
    # only, so a menu save can never copy a token into a game's settings.
    'cheevos_enable', 'cheevos_username', 'cheevos_password', 'cheevos_token',
    'cheevos_hardcore_mode_enable',
}


def uses_network_quit() -> bool:
    """macOS and Windows stop the player with a network QUIT; Linux with
    one SIGTERM (§4.6)."""
    return sys.platform == 'darwin' or sys.platform.startswith('win')


def needs_commands(rom_path: Path) -> bool:
    """Whether a launch turns network commands on: for QUIT (macOS,
    Windows), or for DISK_NEXT through a .m3u disc list (PASS-59-139)."""
    return uses_network_quit() or rom_path.suffix.lower() == '.m3u'


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

def profile_dir() -> Path:
    """The player's profile. Read per call so a test can move BASE_DIR."""
    return Path(config.BASE_DIR).resolve() / 'data' / 'player'


def core_file(retroarch_core: str) -> Path:
    """Where the player's core lives: the profile's own cores directory."""
    return profile_dir() / 'cores' / retroarch_core


def _game_file(game_id: int, ext: str) -> Path:
    return profile_dir() / 'settings' / 'game' / f'{game_id}.{ext}'


def _user_system_dir() -> str:
    """The user's RetroArch system (BIOS) directory, which the player reads
    and never writes (§3.7): from the user's RetroArch row's retroarch.cfg,
    else RetroArch's default."""
    # Imported here: launch_resolver imports this module at load time.
    from services.database import query
    from services.emulator_adapters import _cfg, retroarch_cfg, retroarch_path
    from services.launch_resolver import _resolve_binary
    row = query("SELECT * FROM emulators WHERE is_retroarch = 1 ORDER BY id LIMIT 1",
                one=True)
    try:
        found = retroarch_cfg(_resolve_binary(row, None)) if row else None
    except LaunchResolutionError:
        found = None
    if found:
        home, cfg_path = found
        value = _cfg(cfg_path).get('system_directory', '')
        if value and value != 'default':
            return retroarch_path(value, home)
    return str(Path('~/.config/retroarch/system').expanduser())


# -----------------------------------------------------------------------------
# cfg files
# -----------------------------------------------------------------------------

def _read(path: Path) -> Optional[dict]:
    """A `key = "value"` file as a dict; {} when absent, None when a line
    is neither a setting, a comment nor blank."""
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = _CFG_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
        elif not _SKIP_LINE.match(line):
            return None
    return out


def _write(path: Path, values: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(f'{k} = "{v}"\n' for k, v in values.items()),
                    encoding='utf-8')


def _set_keys(path: Path, values: dict) -> None:
    """Set `values` in a cfg the player also writes: rewrite only those keys'
    lines, append the missing ones, keep every other line (INV-9)."""
    lines = path.read_text(encoding='utf-8').splitlines(True) if path.is_file() else []
    todo = dict(values)
    for i, line in enumerate(lines):
        m = _CFG_LINE.match(line) or re.match(r'^\s*([A-Za-z0-9_]+)\s*=', line)
        if m and m.group(1) in values:
            lines[i] = f'{m.group(1)} = "{values[m.group(1)]}"\n' if m.group(1) in todo else ''
            todo.pop(m.group(1), None)
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    lines += [f'{k} = "{v}"\n' for k, v in todo.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(lines), encoding='utf-8')


# -----------------------------------------------------------------------------
# The game's record (§4.5): what RetroDB wrote, and what the user set
# -----------------------------------------------------------------------------

def _record(game_id: int) -> dict:
    path = _game_file(game_id, 'json')
    try:
        rec = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        rec = {}
    for part in ('written', 'user'):
        rec.setdefault(part, {}).setdefault('cfg', {})
        rec[part].setdefault('opt', {})
    rec.setdefault('customised', False)
    return rec


def _save_record(game_id: int, rec: dict) -> None:
    rec['customised'] = bool(rec['user']['cfg'] or rec['user']['opt'])
    path = _game_file(game_id, 'json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding='utf-8')


def _regenerate(game_id: int, rec: dict, part: str, recommended: dict) -> None:
    """Write the game's .cfg or .opt: its user-set keys as they are, then
    every recommended key the user has not set (INV-12)."""
    user = rec['user'][part]
    rec['written'][part] = {k: v for k, v in recommended.items() if k not in user}
    _write(_game_file(game_id, part), _compose(rec, part))


def _compose(rec: dict, part: str) -> dict:
    """A game file's content: the user's keys, then RetroDB's."""
    return {**rec['user'][part], **rec['written'][part]}


def release_keys(game_id: int, keys) -> None:
    """A choice saved in RetroDB's panel wins these keys back from the
    player's menu: the next launch writes RetroDB's value (PASS-59-81 §4.6)."""
    rec = _record(game_id)
    if [k for k in keys if rec['user']['cfg'].pop(k, None) is not None]:
        _save_record(game_id, rec)


def is_customised(game_id: int) -> bool:
    return _record(game_id)['customised']


def reset(game_id: int) -> None:
    """Reset to recommended: the next launch writes fresh files."""
    for ext in ('cfg', 'opt', 'json'):
        _game_file(game_id, ext).unlink(missing_ok=True)


# -----------------------------------------------------------------------------
# Before a launch
# -----------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def launch_args(game: dict, sys_emu: Optional[dict], core_path: str,
                rom_path: Path, token: str, recommended: Optional[dict] = None,
                core: Optional[str] = None, session_keys: Optional[dict] = None) -> tuple:
    """Write the profile's settings for one launch and return (argv words
    after the binary, network command port or None). `recommended` is
    {'cfg': {...}, 'opt': {...}} from PASS-59-81; `core` (its id) names
    the folder the game's cheats go in (PASS-59-155); `session_keys` are for
    this launch alone and go only in the run layer. Raises
    LaunchResolutionError when a file cannot be written (§6) or a path
    holds `|` (INV-10)."""
    profile = profile_dir()
    if '|' in str(profile) or '|' in str(rom_path.parent):
        raise LaunchResolutionError(
            f"The player cannot use a path containing '|': {profile}")
    extras = []
    for value, field in (((sys_emu or {}).get('extra_args') or '', 'extra_args'),
                         (game.get('launch_args_override') or '',
                          'launch_args_override')):
        try:
            extras += shlex.split(value)
        except ValueError as e:
            raise LaunchResolutionError(f"Cannot parse {field} {value!r}: {e}") from e

    base = profile / 'retroarch.cfg'
    system_cfg = (profile / 'settings' / 'system'
                  / f"{game.get('system_folder') or ''}.cfg")
    game_cfg = _game_file(game['id'], 'cfg')
    keys = dict(_BASE_KEYS,
                rgui_config_directory=str(profile / 'config'),
                savefile_directory=str(profile / 'saves'),
                savestate_directory=str(profile / 'states'),
                input_remapping_directory=str(profile / 'remaps'),
                libretro_directory=str(profile / 'cores'),
                system_directory=_user_system_dir(),
                cheat_database_path=str(profile / 'cheats'))
    port = _free_port() if needs_commands(rom_path) else None
    rec_values = recommended or {}
    try:
        for sub in ('config', 'saves', 'states', 'remaps', 'cores'):
            (profile / sub).mkdir(parents=True, exist_ok=True)
        _set_keys(base, keys)
        rec = _record(game['id'])
        _regenerate(game['id'], rec, 'cfg', dict(
            rec_values.get('cfg', {}),
            core_options_path=str(_game_file(game['id'], 'opt'))))
        _regenerate(game['id'], rec, 'opt', rec_values.get('opt', {}))
        _save_record(game['id'], rec)
        layers = [str(system_cfg)] if system_cfg.is_file() else []
        layers.append(str(game_cfg))
        run_keys = dict(session_keys or {})
        if port is not None:
            run_keys.update(network_cmd_enable='true', network_cmd_port=str(port))
        if run_keys:
            run_cfg = profile / 'run' / f'{token}.cfg'
            run_cfg.parent.mkdir(parents=True, exist_ok=True)
            run_cfg.touch(mode=0o600)   # it can hold a sign-in token
            _write(run_cfg, run_keys)
            layers.append(str(run_cfg))
    except OSError as e:
        raise LaunchResolutionError(
            f"Cannot write the player's settings ({e.filename or profile}): "
            f"{e.strerror or e}") from e
    if core:
        from services import cheats
        cheats.place_for_launch(game['id'], core, rom_path, profile)
    return (['--config', str(base), '--appendconfig', '|'.join(layers),
             *extras, '-L', core_path, str(rom_path)], port)


# -----------------------------------------------------------------------------
# After a session (§4.5)
# -----------------------------------------------------------------------------

def _overrides(rom_path: Path) -> list:
    """Override files the player saved this session, core first, then
    folder, then game, from every subdirectory of its config directory."""
    conf = profile_dir() / 'config'
    found = []
    subdirs = sorted(p for p in conf.iterdir() if p.is_dir()) if conf.is_dir() else []
    for name in ('core', 'folder', 'game'):
        for sub in subdirs:
            stem = {'core': sub.name, 'folder': rom_path.parent.name,
                    'game': rom_path.stem}[name]
            path = sub / f'{stem}.cfg'
            if path.is_file() and path not in found:
                found.append(path)
    return found


def after_session(game_id: int, rom_path: Path, token: str) -> None:
    """Keep what the user changed during play as the game's settings. Runs
    once per player session, from the launcher, whatever the exit code."""
    from services import cheats
    cheats.take_back(game_id, rom_path, profile_dir())
    rec = _record(game_id)
    for part in ('cfg', 'opt'):
        current = _read(_game_file(game_id, part)) or {}
        for key, value in current.items():
            if key in rec['user'][part]:
                rec['user'][part][key] = value
            elif rec['written'][part].get(key) != value and key not in _PROTECTED_KEYS:
                rec['user'][part][key] = value
                rec['written'][part].pop(key, None)
    for path in _overrides(rom_path):
        values = _read(path)
        if values is None:
            dest = profile_dir() / 'rejected' / f'{token}-{path.parent.name}-{path.name}'
            dest.parent.mkdir(parents=True, exist_ok=True)
            path.replace(dest)
            logger.warning("player override %s could not be read; moved to %s",
                           path, dest)
            continue
        for key, value in values.items():
            if key in _PROTECTED_KEYS or key.startswith('network_cmd_'):
                continue
            rec['user']['cfg'][key] = value
            rec['written']['cfg'].pop(key, None)
        path.unlink()
    if rec['user']['cfg']:
        _write(_game_file(game_id, 'cfg'), _compose(rec, 'cfg'))
    _save_record(game_id, rec)
    (profile_dir() / 'run' / f'{token}.cfg').unlink(missing_ok=True)
