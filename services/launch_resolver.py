# =============================================================================
# RETRODB - LaunchResolver
# =============================================================================
# Turns a game_id into a fully-resolved LaunchContext (binary path + argv +
# token). It spawns nothing, but it is not read-only: a RetroArch launch
# writes data/retroarch-overrides*.cfg, and a VICE launch adds pad defaults to
# the user's own core-options files. _mapping_resolves (the Play button's
# check) runs `flatpak info`.
#
# Resolution algorithm (spec §Resolution algorithm):
#   1. Load game; raise if missing.
#   2. Pick emulator: per-game override > system default > first system mapping;
#      the bundled player stands in where that mapping does not resolve and
#      the system is in data/player_cores.json (PASS-59-81 §3.7).
#   3. Verify enabled.
#   4. Resolve binary (RA-special-cased to read settings).
#   5. Resolve RA core (only when is_retroarch=1). The bundled player
#      (is_player=1) branches here: its core is PASS-59-81 §4.3's choice from
#      its own profile, and services/player.py builds its argv (PASS-59-64 §4.4).
#   6. shlex.split the template, then per token: {system_extra_args},
#      {game_extra_args} and {fullscreen_flag} as a whole token expand to
#      their words; {rom},
#      {rom_dir}, {rom_name}, {retroarch_core} substitute via
#      str.format_map(_SafeDict). A parse error names its field.
#   7. Auto-append extra_args / launch_args_override if template lacked tokens.
#   8. Prefix the binary -> argv.
#   9. Validate rom_path under scan roots, and its type against the system's
#      systeminfo.txt list.
#  10. Return LaunchContext.
# =============================================================================

from __future__ import annotations

import logging
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from services.database import query
from services.launcher.base import LaunchContext, LaunchResolutionError
from services import player, player_cores
from services.rom_scanner import rom_type_problem
import config
from settings_manager import get_setting

logger = logging.getLogger(__name__)

# PASS-59-140 — settings RetroDB lays over the user's own retroarch.cfg on
# every RetroArch launch, so one bad local value cannot break games.
_RETROARCH_OVERRIDES = Path(config.BASE_DIR) / 'data' / 'retroarch-overrides.cfg'
_RETROARCH_KEYBOARD_OVERRIDES = (Path(config.BASE_DIR) / 'data'
                                 / 'retroarch-overrides-keyboard.cfg')

# Cores for home computers whose games are played from the keyboard (VICE C64
# family, Amiga, ZX Spectrum/ZX81, MSX, DOS, Atari 8-bit/ST, Amstrad CPC, PC-98,
# X68000). RetroArch's keyboard hotkeys and RetroPad binds would eat space,
# return, the F-keys and many letters, so these launch in game focus: every key
# goes to the core, and Scroll Lock gives the hotkeys back.
_KEYBOARD_CORE_PREFIXES = (
    'vice_', 'puae', 'fuse_', '81_', 'bluemsx_', 'fmsx_', 'dosbox',
    'atari800_', 'hatari', 'cap32_', 'crocods_', 'np2kai_', 'px68k_',
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _is_keyboard_core(core: str) -> bool:
    """True for a keyboard computer's core; `core` is a file name or a path."""
    return Path(core).name.startswith(_KEYBOARD_CORE_PREFIXES)


def _retroarch_overrides(core_path: str) -> list:
    """Write the overrides file and return the argv words that load it, or
    [] when it cannot be written: a launch never fails for a settings reason.

    - fastforward_ratio 0 is RetroArch's default (unlimited); 1.0 capped
      fast-forward, including a core's own load warp, at normal speed.
    - input_driver must match the window system RetroArch opens on; "x" on
      a Wayland session leaves the keyboard dead. RetroArch's automatic
      video context picks Wayland whenever WAYLAND_DISPLAY is set.
    - A keyboard computer's core starts in game focus; its settings go to a
      file of their own, so a console launched at the same moment never
      reads them."""
    lines = ['fastforward_ratio = "0.000000"\n']
    if sys.platform.startswith('linux'):
        if os.environ.get('WAYLAND_DISPLAY'):
            lines.append('input_driver = "wayland"\n')
        elif os.environ.get('DISPLAY'):
            lines.append('input_driver = "x"\n')
    path = _RETROARCH_OVERRIDES
    if _is_keyboard_core(core_path):
        lines.append('input_auto_game_focus = "1"\n')
        path = _RETROARCH_KEYBOARD_OVERRIDES
    text = ''.join(lines)
    try:
        if not path.is_file() or path.read_text(encoding='utf-8') != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
    except OSError as e:
        logger.warning("RetroArch overrides not written (%s); launching without", e)
        return []
    return ['--appendconfig', str(path)]


# PASS-59-150 — VICE ships its right stick and Start unmapped, so a pad cannot
# press the cursor keys or F1 that C64 menus ask for.
_VICE_PAD_DEFAULTS = {
    'vice_mapper_ru': 'RETROK_UP', 'vice_mapper_rd': 'RETROK_DOWN',
    'vice_mapper_rl': 'RETROK_LEFT', 'vice_mapper_rr': 'RETROK_RIGHT',
    'vice_mapper_start': 'RETROK_F1',
}
_OPT_LINE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"?([^"\n]*)"?\s*$')


def _vice_option_files(binary_str: str, core_path: str, rom_path: Path) -> list:
    """The core-options files RetroArch reads for a VICE game: the global
    file when global_core_options is on, else the core's own file plus any
    game or folder file that exists. [] for a non-VICE core or when
    RetroArch's config cannot be found. May raise OSError."""
    m = re.match(r'vice_(\w+?)_libretro', Path(core_path).name)
    if not m:
        return []
    # Imported here: emulator_adapters imports this module at load time.
    from services.emulator_adapters import _cfg, retroarch_cfg, retroarch_path
    found = retroarch_cfg(binary_str)
    if not found:
        return []
    home, cfg_path = found
    cfg = _cfg(cfg_path)
    if cfg.get('global_core_options') == 'true':
        path = cfg.get('core_options_path') or str(cfg_path.parent / 'retroarch-core-options.cfg')
        return [Path(retroarch_path(path, home))]
    conf_dir = cfg.get('rgui_config_directory', '')
    if not conf_dir or conf_dir == 'default':
        conf_dir = str(cfg_path.parent / 'config')
    core_dir = Path(retroarch_path(conf_dir, home)) / f'VICE {m.group(1)}'
    # A game's own or its folder's options file wins over the core's
    # when game_specific_options is on; map those too where they exist.
    return [core_dir / f'VICE {m.group(1)}.opt'] + [
        p for p in (core_dir / f'{rom_path.parent.name}.opt',
                    core_dir / f'{rom_path.stem}.opt') if p.is_file()]


def _merge_pad_defaults(target: Path) -> None:
    """Add _VICE_PAD_DEFAULTS to one options file, only where a key is absent
    or still "---"; write it only when that changed it."""
    lines = target.read_text(encoding='utf-8').splitlines(True) if target.is_file() else []
    todo = dict(_VICE_PAD_DEFAULTS)
    for i, line in enumerate(lines):
        km = _OPT_LINE.match(line)
        if km and km.group(1) in todo:
            value = todo.pop(km.group(1))
            if km.group(2) == '---':
                lines[i] = f'{km.group(1)} = "{value}"\n'
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    lines += [f'{k} = "{v}"\n' for k, v in todo.items()]
    text = ''.join(lines)
    if not target.is_file() or target.read_text(encoding='utf-8') != text:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')


def _vice_pad_defaults(binary_str: str, core_path: str, rom_path: Path) -> None:
    """Set _VICE_PAD_DEFAULTS in the core-options files RetroArch reads for a
    VICE game, so a mapping the user chose stays. Core options live outside
    retroarch.cfg, so --appendconfig cannot carry them. Never fails a launch."""
    try:
        for target in _vice_option_files(binary_str, core_path, rom_path):
            _merge_pad_defaults(target)
    except OSError as e:
        logger.warning("VICE pad mapping not written (%s); launching without", e)


class _SafeDict(dict):
    """str.format_map dict whose missing-key path raises a clear error."""
    def __missing__(self, key):
        raise LaunchResolutionError(f"Unknown template variable: {{{key}}}")


_FLATPAK_RE = re.compile(r'^flatpak run [A-Za-z0-9._\-]+$')


def _flatpak_split(binary_str: str) -> list:
    """If binary_str is `flatpak run org.libretro.RetroArch`, return that as
    a 3-element prefix. Anything else is one program: return [binary_str]."""
    if _FLATPAK_RE.match(binary_str):
        return binary_str.split()
    return [binary_str]


def _allowed_rom_roots() -> list:
    """Return the directories where ROMs may live. Reads from RetroDB's
    rom_path setting. Override target for tests via monkeypatch."""
    raw = get_setting('rom_path', '')
    if not raw:
        return []
    if isinstance(raw, list):
        roots = raw
    else:
        roots = [p.strip() for p in str(raw).split(os.pathsep) if p.strip()]
    return [Path(p).expanduser().resolve() for p in roots]


def _resolve_under(path: Path, roots: list) -> bool:
    p = path.resolve()
    for r in roots:
        try:
            p.relative_to(r)
            return True
        except ValueError:
            pass
    return False


def _default_cores_dir() -> str:
    return str(Path('~/.config/retroarch/cores/').expanduser())


def core_file(retroarch_core: str) -> Path:
    """Where a RetroArch core file lives: the `retroarch_cores_dir` setting,
    else RetroArch's default cores folder. The launch, the Play button's
    check and the BIOS check all find a core here."""
    cores_dir = get_setting('retroarch_cores_dir', '') or _default_cores_dir()
    return Path(cores_dir).expanduser() / retroarch_core


def _split(value: str, field: str) -> list:
    """shlex.split, with a parse error reported against the field it came
    from so the route answers 422 instead of 500 (PASS-59-64 §4.1)."""
    try:
        return shlex.split(value)
    except ValueError as e:
        raise LaunchResolutionError(f"Cannot parse {field} {value!r}: {e}") from e


_FIX_HINT = (
    " — set the path at /settings/emulators (Edit row → Binary path "
    "override) or click Auto-detect, or install the emulator via your "
    "package manager so it lands on PATH"
)


def _resolve_binary(emu_row, sys_emu_row) -> str:
    """Apply the resolver's binary lookup chain: the row's own override,
    then the `retroarch_binary` setting for RetroArch rows, then PATH
    (PASS-59-64 INV-1). Also called from emulator_adapters and
    standalone_settings, despite the underscore."""
    if emu_row.get('binary_path_override'):
        path = emu_row['binary_path_override']
        if not os.access(path, os.X_OK):
            raise LaunchResolutionError(
                f"binary_path_override not executable: {path}{_FIX_HINT}")
        return path
    if emu_row['is_retroarch']:
        ra_setting = get_setting('retroarch_binary', '')
        if ra_setting:
            return ra_setting
    found = shutil.which(emu_row['binary_name'])
    if not found:
        raise LaunchResolutionError(
            f"Emulator binary not found on PATH: {emu_row['binary_name']!r}"
            f"{_FIX_HINT}")
    return found


def _pick_mapping(system_id, emulator_override_id, system_name=''):
    """Return (emulator row or None, system_emulators row or None): the game's
    override emulator with its system's row for it, else the system's default
    row, else its lowest-id row. Raises when the system has no row at all.
    Also called from standalone_settings, despite the underscore."""
    if emulator_override_id:
        emu = query("SELECT * FROM emulators WHERE id = ?",
                    (emulator_override_id,), one=True)
        # Per-game override may still need a system_emulators row for
        # retroarch_core / extra_args.
        sys_emu = None
        if emu:
            sys_emu = query("""
                SELECT * FROM system_emulators
                WHERE system_id = ? AND emulator_id = ?
                LIMIT 1
            """, (system_id, emu['id']), one=True)
        return emu, sys_emu
    sys_emu = query("""
        SELECT * FROM system_emulators
        WHERE system_id = ? AND is_default = 1
        ORDER BY id LIMIT 1
    """, (system_id,), one=True)
    if not sys_emu:
        sys_emu = query("""
            SELECT * FROM system_emulators
            WHERE system_id = ? ORDER BY id LIMIT 1
        """, (system_id,), one=True)
    if not sys_emu:
        raise LaunchResolutionError(
            f"No emulator configured for system {system_name!r}")
    emu = query("SELECT * FROM emulators WHERE id = ?",
                (sys_emu['emulator_id'],), one=True)
    return emu, sys_emu


def _mapping_resolves(emu, sys_emu) -> bool:
    """PASS-59-91 §4.3: the emulator is enabled, its binary exists and is
    executable (or is a `flatpak run <id>` that `flatpak info` accepts), and
    a RetroArch row's core file exists. `_resolve_binary` returns the
    `retroarch_binary` setting unchecked, so not raising is not enough."""
    if not emu or not emu.get('enabled'):
        return False
    try:
        binary_str = _resolve_binary(emu, sys_emu)
    except LaunchResolutionError:
        return False
    if _FLATPAK_RE.match(binary_str):
        flatpak = shutil.which('flatpak')
        if not flatpak:
            return False
        done = subprocess.run([flatpak, 'info', binary_str.split()[2]],
                              capture_output=True, timeout=10, check=False)
        if done.returncode != 0:
            return False
    elif not (os.path.isfile(binary_str) and os.access(binary_str, os.X_OK)):
        return False
    if emu.get('is_player'):
        return bool(sys_emu) and player_cores.can_serve(_system_folder(sys_emu['system_id']))
    if emu.get('is_retroarch'):
        if not sys_emu or not sys_emu.get('retroarch_core'):
            return False
        return core_file(sys_emu['retroarch_core']).exists()
    return True


def _system_folder(system_id) -> str:
    row = query("SELECT folder FROM systems WHERE id = ?", (system_id,), one=True)
    return (row or {}).get('folder') or ''


def _player_serves(system_id):
    """(player row, its system row or None) when the player can stand in for
    this system: its row is enabled, its program is found and the system is
    in the core table. None otherwise."""
    if not player_cores.entry(_system_folder(system_id)):
        return None
    emu = player_cores.player_row()
    if not emu or not emu.get('enabled'):
        return None
    try:
        _resolve_binary(emu, None)
    except LaunchResolutionError:
        return None
    sys_emu = query("SELECT * FROM system_emulators WHERE system_id = ? AND emulator_id = ?",
                    (system_id, emu['id']), one=True)
    return emu, sys_emu


def pick_launch_mapping(system_id, emulator_override_id, system_name=''):
    """_pick_mapping, with the player standing in where the game has no
    override and the system's default does not resolve (PASS-59-81 §3.7,
    §4.5). The player's system row may be None until a core is installed."""
    try:
        emu, sys_emu = _pick_mapping(system_id, emulator_override_id, system_name)
    except LaunchResolutionError:
        found = None if emulator_override_id else _player_serves(system_id)
        if found:
            return found
        raise
    if emulator_override_id or (emu and emu.get('is_player')) or _mapping_resolves(emu, sys_emu):
        return emu, sys_emu
    return _player_serves(system_id) or (emu, sys_emu)


def _fullscreen_flag(emu, system_id) -> list:
    """{fullscreen_flag}: the emulator's flag for the system's choice, else
    the table default; no element for an emulator with no flag (INV-17).
    A flag is an argv input, so it is set per system only."""
    from services.standalone_settings import flag_args, settings_for
    spec = settings_for(emu.get('binary_name')).get('fullscreen')
    if not spec or 'flag' not in spec:
        return []
    row = query("""
        SELECT value FROM emulator_setting_choices
        WHERE emulator_id = ? AND scope = 'system' AND scope_id = ? AND setting = 'fullscreen'
    """, (emu['id'], system_id), one=True)
    return flag_args(spec, row['value'] if row else None)


def _build_args(emu, sys_emu, game, rom_path_obj: Path, core_path: str) -> list:
    """The argv words after the program: emu's args_template with every
    variable filled in.

    {rom}, {rom_dir}, {rom_name} and {retroarch_core} substitute inside a
    word. {system_extra_args}, {game_extra_args} and {fullscreen_flag} must
    each be a whole word, and expand to zero or more words. The two extra-args
    variables are appended at the end when the template does not name them;
    {fullscreen_flag} never is (PASS-59-91 §4.6)."""
    # Strategy: parse the template ONCE with shlex.split (outer quotes strip),
    # then substitute literal values into each argv token via format_map.
    # No re-splitting after substitution -> shell metacharacters in rom_path
    # cannot escape into multiple argv tokens.  This is stronger than the
    # shlex.quote-then-split round-trip suggested by the spec, which produced
    # paths wrapped in literal single-quotes that confused emulators.
    system_extra = (sys_emu.get('extra_args') if sys_emu else None) or ''
    game_extra = game.get('launch_args_override') or ''

    vars_dict = _SafeDict(
        rom=str(rom_path_obj),
        rom_dir=str(rom_path_obj.parent),
        rom_name=rom_path_obj.stem,
        retroarch_core=core_path,
    )
    # Appended when the template lacks them.
    appendable = {
        '{system_extra_args}': _split(system_extra, 'extra_args'),
        '{game_extra_args}': _split(game_extra, 'launch_args_override'),
    }
    list_vars = dict(appendable)

    template = emu['args_template']
    if '{fullscreen_flag}' in template:
        list_vars['{fullscreen_flag}'] = _fullscreen_flag(emu, game['system_id'])
    substituted = []
    for tok in _split(template, 'args_template'):
        if tok in list_vars:
            substituted.extend(list_vars[tok])
            continue
        for name in list_vars:
            if name in tok:
                raise LaunchResolutionError(
                    f"{name} must be a whole argument in args_template, "
                    f"not part of {tok!r}")
        substituted.append(tok.format_map(vars_dict))

    for name, words in appendable.items():
        if name not in template:
            substituted.extend(words)
    return substituted


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

def rom_launch_problem(rom_path):
    """Why the ROM at `rom_path` cannot be launched, or None. The checks
    resolve_launch_context applies: the file exists, sits under a scan root,
    and is a type its system lists (PASS-59-95). A folder passes the same
    type check, since a PS3 disc game is a `.PS3` folder (PASS-59-91).
    Shared with the library cards' Play button, so a card offers Play only
    where the launch would get past them."""
    rom_path_obj = Path(rom_path or '')
    if not rom_path or not rom_path_obj.exists():
        return f"ROM file not found: {rom_path_obj}"
    if not (rom_path_obj.is_file() or rom_path_obj.is_dir()):
        return f"ROM path is not a file or folder: {rom_path_obj}"
    roots = _allowed_rom_roots()
    if roots:
        root = next((r for r in roots if _resolve_under(rom_path_obj, [r])), None)
        if root is None:
            return f"ROM path is outside configured scan roots: {rom_path_obj}"
        # PASS-59-95 — only a file type the system's own list allows.
        problem = rom_type_problem(str(rom_path_obj), str(root))
        if problem:
            return f"Not launching {rom_path_obj.name}: {problem}"
    return None


def launch_checker():
    """Return can_launch(system_id, emulator_override_id) -> bool for one
    request, resolving each distinct (system, override) pair once
    (PASS-59-91 §4.5). The caller checks the launch permission."""
    cache = {}

    def can_launch(system_id, emulator_override_id):
        key = (system_id, emulator_override_id)
        if key not in cache:
            try:
                emu, sys_emu = pick_launch_mapping(system_id, emulator_override_id)
                if emu and emu.get('is_player') and not sys_emu:
                    cache[key] = (_player_serves(system_id) is not None
                                  and player_cores.can_serve(_system_folder(system_id)))
                else:
                    cache[key] = _mapping_resolves(emu, sys_emu)
            except LaunchResolutionError:
                cache[key] = False
        return cache[key]
    return can_launch


def keyboard_core(system_id, emulator_override_id) -> bool:
    """True when the game would launch in a RetroArch keyboard computer's
    core, so its hotkeys wait behind Scroll Lock (PASS-59-152)."""
    try:
        emu, sys_emu = _pick_mapping(system_id, emulator_override_id)
    except LaunchResolutionError:
        return False
    return bool(emu and emu.get('is_retroarch') and sys_emu
                and _is_keyboard_core(sys_emu.get('retroarch_core') or ''))


def _player_context(game, emu, sys_emu, binary_argv_prefix, rom_path_obj) -> LaunchContext:
    """The player's launch (PASS-59-64 §4.4): the core PASS-59-81 §4.3 picks,
    from the player's profile, and argv from services/player.py, never from
    args_template. The settings it writes come after every check, so a
    refused launch writes none. A core not installed yet raises CoreMissing,
    which the route turns into a download (§4.5)."""
    folder = game.get('system_folder') or ''
    if not player_cores.entry(folder):
        raise LaunchResolutionError(
            f"The player has no core for system {game['system_name']!r}")
    core = player_cores.chosen_core(folder, game['system_id'], game['id'], emu['id'])
    if core is None:
        raise LaunchResolutionError(
            f"No core for {game['system_name']} is built for this computer.")
    core_path_obj = player.core_file(player_cores.core_file_name(core))
    if not core_path_obj.exists():
        raise player_cores.CoreMissing(core, game['system_id'], game['system_name'],
                                       core_path_obj)
    problem = rom_launch_problem(rom_path_obj)
    if problem:
        raise LaunchResolutionError(problem)
    token = secrets.token_urlsafe(12)
    rom_abs = rom_path_obj.resolve()
    try:
        if not sys_emu:
            # Installed for another folder sharing the core (same_as).
            player_cores.map_system(game['system_id'], core)
        player_cores.write_system_cfg(folder, game['system_id'], emu['id'])
    except OSError as e:
        raise LaunchResolutionError(
            f"Cannot write the player's settings ({e.filename}): {e.strerror or e}") from e
    recommended = player_cores.game_recommended(folder, game['id'], emu['id'], core)
    words, port = player.launch_args(game, sys_emu, str(core_path_obj), rom_abs, token,
                                     recommended)
    return LaunchContext(
        game_id=game['id'],
        emulator_id=emu['id'],
        binary=Path(binary_argv_prefix[0]),
        argv=list(binary_argv_prefix) + words,
        token=token,
        is_player=True,
        quit_port=port,
        on_exit=lambda: player.after_session(game['id'], rom_abs, token),
    )


def launches_on_player(game_id) -> bool:
    """True when the game's launch would pick the bundled player, so the
    route can hold it to one player session at a time (PASS-59-64 §4.5)."""
    game = query("SELECT system_id, emulator_override_id FROM games WHERE id = ?",
                 (game_id,), one=True)
    if not game:
        return False
    try:
        emu, _ = pick_launch_mapping(game['system_id'], game.get('emulator_override_id'))
    except LaunchResolutionError:
        return False
    return bool(emu and emu.get('is_player'))


def resolve_launch_context(game_id: int) -> LaunchContext:
    """Work out how to launch one game: the emulator, its program, the RetroArch
    core and the full argv, as the header's algorithm sets out. Raises
    LaunchResolutionError with a message for the user when it cannot."""
    game = query("""
        SELECT g.id, g.system_id, g.rom_path, g.emulator_override_id, g.launch_args_override,
               s.name AS system_name, s.folder AS system_folder
        FROM games g JOIN systems s ON s.id = g.system_id
        WHERE g.id = ?
    """, (game_id,), one=True)
    if not game:
        raise LaunchResolutionError(f"game_id {game_id} not found")

    # ---- pick emulator -------------------------------------------------------
    emu, sys_emu = pick_launch_mapping(game['system_id'], game.get('emulator_override_id'),
                                       game['system_name'])
    if not emu:
        raise LaunchResolutionError("emulator row missing")
    if not emu.get('enabled'):
        raise LaunchResolutionError(f"emulator {emu['name']!r} is disabled")

    # ---- binary --------------------------------------------------------------
    binary_str = _resolve_binary(emu, sys_emu)
    binary_argv_prefix = _flatpak_split(binary_str)
    # The program argv[0] runs: for a Flatpak launch that is `flatpak`
    # itself, not the emulator.
    binary_path = Path(binary_argv_prefix[0])

    # ---- core (RA only) -----------------------------------------------------
    core_path = ''
    if emu.get('is_retroarch'):
        if not sys_emu or not sys_emu.get('retroarch_core'):
            raise LaunchResolutionError(
                f"RetroArch emulator selected for system {game['system_name']!r} "
                "but no retroarch_core configured on system_emulators row")
        core_path_obj = core_file(sys_emu['retroarch_core'])
        if not core_path_obj.exists():
            raise LaunchResolutionError(
                f"RetroArch core not found: {core_path_obj}")
        core_path = str(core_path_obj)

    rom_path_obj = Path(game['rom_path'])
    if emu.get('is_player'):
        return _player_context(game, emu, sys_emu, binary_argv_prefix, rom_path_obj)
    substituted = _build_args(emu, sys_emu, game, rom_path_obj, core_path)

    # ---- validate rom_path under scan roots ---------------------------------
    # Before any settings file is written, so a refused launch writes none.
    problem = rom_launch_problem(rom_path_obj)
    if problem:
        raise LaunchResolutionError(problem)
    overrides = _retroarch_overrides(core_path) if emu.get('is_retroarch') else []
    argv = list(binary_argv_prefix) + overrides + substituted
    if core_path:
        _vice_pad_defaults(binary_str, core_path, rom_path_obj)

    return LaunchContext(
        game_id=game['id'],
        emulator_id=emu['id'],
        binary=binary_path,
        argv=argv,
        token=secrets.token_urlsafe(12),
    )
