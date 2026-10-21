# =============================================================================
# RETRODB - LaunchResolver
# =============================================================================
# Turns a game_id into a fully-resolved LaunchContext (binary path + argv +
# token). Pure DB reads + template substitution; no process spawn.
#
# Resolution algorithm (spec §Resolution algorithm):
#   1. Load game; raise if missing.
#   2. Pick emulator: per-game override > system default > first system mapping.
#   3. Verify enabled.
#   4. Resolve binary (RA-special-cased to read settings).
#   5. Resolve RA core (only when is_retroarch=1).
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
    if Path(core_path).name.startswith(_KEYBOARD_CORE_PREFIXES):
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


def _vice_pad_defaults(binary_str: str, core_path: str, rom_path: Path) -> None:
    """Set _VICE_PAD_DEFAULTS in the core-options files RetroArch reads for a
    VICE game, only where a key is absent or still "---", so a mapping the
    user chose stays. Core options live outside retroarch.cfg, so
    --appendconfig cannot carry them. Never fails a launch."""
    m = re.match(r'vice_(\w+?)_libretro', Path(core_path).name)
    if not m:
        return
    from services.emulator_adapters import _cfg, retroarch_cfg
    found = retroarch_cfg(binary_str)
    if not found:
        return
    home, cfg_path = found
    try:
        cfg = _cfg(cfg_path)
        if cfg.get('global_core_options') == 'true':
            path = cfg.get('core_options_path') or str(cfg_path.parent / 'retroarch-core-options.cfg')
            targets = [Path(path.replace('~', str(home), 1) if path.startswith('~') else path)]
        else:
            conf_dir = cfg.get('rgui_config_directory', '')
            if not conf_dir or conf_dir == 'default':
                conf_dir = str(cfg_path.parent / 'config')
            elif conf_dir.startswith('~'):
                conf_dir = str(home) + conf_dir[1:]
            core_dir = Path(conf_dir) / f'VICE {m.group(1)}'
            # A game's own or its folder's options file wins over the core's
            # when game_specific_options is on; map those too where they exist.
            targets = [core_dir / f'VICE {m.group(1)}.opt'] + [
                p for p in (core_dir / f'{rom_path.parent.name}.opt',
                            core_dir / f'{rom_path.stem}.opt') if p.is_file()]
        for target in targets:
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
    except OSError as e:
        logger.warning("VICE pad mapping not written (%s); launching without", e)


class _SafeDict(dict):
    """str.format_map dict whose missing-key path raises a clear error."""
    def __missing__(self, key):
        raise LaunchResolutionError(f"Unknown template variable: {{{key}}}")


_FLATPAK_RE = re.compile(r'^flatpak run [A-Za-z0-9._\-]+$')


def _flatpak_split(binary_str: str) -> list:
    """If binary_str is `flatpak run org.libretro.RetroArch`, return that as
    a 3-element prefix. If it's an absolute path, return [path]."""
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
    """Apply the resolver's binary lookup chain."""
    if emu_row['is_retroarch']:
        ra_setting = get_setting('retroarch_binary', '')
        if ra_setting:
            return ra_setting
    if emu_row.get('binary_path_override'):
        path = emu_row['binary_path_override']
        if not os.access(path, os.X_OK):
            raise LaunchResolutionError(
                f"binary_path_override not executable: {path}{_FIX_HINT}")
        return path
    found = shutil.which(emu_row['binary_name'])
    if not found:
        raise LaunchResolutionError(
            f"Emulator binary not found on PATH: {emu_row['binary_name']!r}"
            f"{_FIX_HINT}")
    return found


def _pick_mapping(system_id, emulator_override_id, system_name=''):
    """Return (emulator row or None, system_emulators row or None): the game's
    override emulator with its system's row for it, else the system's default
    row, else its lowest-id row. Raises when the system has no row at all."""
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
    if emu.get('is_retroarch'):
        if not sys_emu or not sys_emu.get('retroarch_core'):
            return False
        cores_dir = get_setting('retroarch_cores_dir', '') or _default_cores_dir()
        return (Path(cores_dir).expanduser() / sys_emu['retroarch_core']).exists()
    return True


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


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

def rom_launch_problem(rom_path):
    """Why the ROM at `rom_path` cannot be launched, or None. The checks
    resolve_launch_context applies: the file exists, sits under a scan root,
    and is a type its system lists (PASS-59-95). Shared with the library
    cards' Play button, so a card offers Play only where the launch would
    get past them."""
    rom_path_obj = Path(rom_path or '')
    if not rom_path or not rom_path_obj.exists():
        return f"ROM file not found: {rom_path_obj}"
    if not rom_path_obj.is_file():
        return f"ROM path is not a file: {rom_path_obj}"
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
                cache[key] = _mapping_resolves(
                    *_pick_mapping(system_id, emulator_override_id))
            except LaunchResolutionError:
                cache[key] = False
        return cache[key]
    return can_launch


def resolve_launch_context(game_id: int) -> LaunchContext:
    game = query("""
        SELECT g.id, g.system_id, g.rom_path, g.emulator_override_id, g.launch_args_override,
               s.name AS system_name, s.folder AS system_folder
        FROM games g JOIN systems s ON s.id = g.system_id
        WHERE g.id = ?
    """, (game_id,), one=True)
    if not game:
        raise LaunchResolutionError(f"game_id {game_id} not found")

    # ---- pick emulator -------------------------------------------------------
    emu, sys_emu = _pick_mapping(game['system_id'], game.get('emulator_override_id'),
                                 game['system_name'])
    if not emu:
        raise LaunchResolutionError("emulator row missing")
    if not emu.get('enabled'):
        raise LaunchResolutionError(f"emulator {emu['name']!r} is disabled")

    # ---- binary --------------------------------------------------------------
    binary_str = _resolve_binary(emu, sys_emu)
    binary_argv_prefix = _flatpak_split(binary_str)
    binary_path = Path(binary_argv_prefix[0])

    # ---- core (RA only) -----------------------------------------------------
    core_path = ''
    if emu.get('is_retroarch'):
        if not sys_emu or not sys_emu.get('retroarch_core'):
            raise LaunchResolutionError(
                f"RetroArch emulator selected for system {game['system_name']!r} "
                "but no retroarch_core configured on system_emulators row")
        cores_dir_str = get_setting('retroarch_cores_dir', '') or _default_cores_dir()
        core_path_obj = Path(cores_dir_str).expanduser() / sys_emu['retroarch_core']
        if not core_path_obj.exists():
            raise LaunchResolutionError(
                f"RetroArch core not found: {core_path_obj}")
        core_path = str(core_path_obj)

    # ---- template variables --------------------------------------------------
    # Strategy: parse the template ONCE with shlex.split (outer quotes strip),
    # then substitute literal values into each argv token via format_map.
    # No re-splitting after substitution -> shell metacharacters in rom_path
    # cannot escape into multiple argv tokens.  This is stronger than the
    # shlex.quote-then-split round-trip suggested by the spec, which produced
    # paths wrapped in literal single-quotes that confused emulators.
    rom_path_obj = Path(game['rom_path'])
    system_extra = (sys_emu.get('extra_args') if sys_emu else None) or ''
    game_extra = game.get('launch_args_override') or ''

    vars_dict = _SafeDict(
        rom=str(rom_path_obj),
        rom_dir=str(rom_path_obj.parent),
        rom_name=rom_path_obj.stem,
        retroarch_core=core_path,
    )
    # List variables: a token that is exactly one expands to zero or more
    # argv elements; inside a larger token it cannot, so it is refused.
    list_vars = {
        '{system_extra_args}': _split(system_extra, 'extra_args'),
        '{game_extra_args}': _split(game_extra, 'launch_args_override'),
    }

    template = emu['args_template']
    # PASS-59-91 §4.6 — never auto-appended; only a template naming it gets it.
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

    # Auto-append if template did NOT explicitly use the token
    list_vars.pop('{fullscreen_flag}', None)
    for name, words in list_vars.items():
        if name not in template:
            substituted.extend(words)

    overrides = _retroarch_overrides(core_path) if emu.get('is_retroarch') else []
    argv = list(binary_argv_prefix) + overrides + substituted

    # ---- validate rom_path under scan roots ---------------------------------
    problem = rom_launch_problem(rom_path_obj)
    if problem:
        raise LaunchResolutionError(problem)
    if core_path:
        _vice_pad_defaults(binary_str, core_path, rom_path_obj)

    return LaunchContext(
        game_id=game['id'],
        emulator_id=emu['id'],
        binary=binary_path,
        argv=argv,
        token=secrets.token_urlsafe(12),
    )
