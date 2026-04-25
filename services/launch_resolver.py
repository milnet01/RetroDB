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
#   6. Substitute {rom}, {rom_dir}, {rom_name}, {retroarch_core}, {disc_paths},
#      {system_extra_args}, {game_extra_args} via str.format_map(_SafeDict).
#   7. Auto-append extra_args / launch_args_override if template lacked tokens.
#   8. shlex.split -> argv.
#   9. Validate rom_path under scan roots.
#  10. Return LaunchContext.
# =============================================================================

from __future__ import annotations

import logging
import os
import re
import secrets
import shlex
import shutil
from pathlib import Path
from typing import Optional

from services.database import query
from services.launcher.base import LaunchContext, LaunchResolutionError
from settings_manager import get_setting

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

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


def _disc_paths_for_game(game_id: int) -> list:
    """Return absolute paths from the bonus_discs table for this game.
    Empty list if the table doesn't exist or has no rows."""
    try:
        rows = query("""SELECT rom_path FROM bonus_discs
                        WHERE parent_game_id = ? ORDER BY id""", (game_id,))
    except Exception:
        return []
    return [r['rom_path'] for r in rows if r and r.get('rom_path')]


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


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

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
    sys_emu = None
    if game.get('emulator_override_id'):
        emu = query("SELECT * FROM emulators WHERE id = ?",
                    (game['emulator_override_id'],), one=True)
        # Per-game override may still need a system_emulators row for
        # retroarch_core / extra_args.
        if emu:
            sys_emu = query("""
                SELECT * FROM system_emulators
                WHERE system_id = ? AND emulator_id = ?
                LIMIT 1
            """, (game['system_id'], emu['id']), one=True)
    else:
        sys_emu = query("""
            SELECT * FROM system_emulators
            WHERE system_id = ? AND is_default = 1
            ORDER BY id LIMIT 1
        """, (game['system_id'],), one=True)
        if not sys_emu:
            sys_emu = query("""
                SELECT * FROM system_emulators
                WHERE system_id = ? ORDER BY id LIMIT 1
            """, (game['system_id'],), one=True)
        if not sys_emu:
            raise LaunchResolutionError(
                f"No emulator configured for system {game['system_name']!r}")
        emu = query("SELECT * FROM emulators WHERE id = ?",
                    (sys_emu['emulator_id'],), one=True)
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
    disc_paths = _disc_paths_for_game(game_id)
    system_extra = (sys_emu.get('extra_args') if sys_emu else None) or ''
    game_extra = game.get('launch_args_override') or ''

    vars_dict = _SafeDict(
        rom=str(rom_path_obj),
        rom_dir=str(rom_path_obj.parent),
        rom_name=rom_path_obj.stem,
        retroarch_core=core_path,
        disc_paths=' '.join(disc_paths),
        system_extra_args=system_extra,
        game_extra_args=game_extra,
    )

    template = emu['args_template']
    template_tokens = shlex.split(template)
    substituted = [tok.format_map(vars_dict) for tok in template_tokens]

    # Auto-append if template did NOT explicitly use the token
    if '{system_extra_args}' not in template and system_extra:
        substituted.extend(shlex.split(system_extra))
    if '{game_extra_args}' not in template and game_extra:
        substituted.extend(shlex.split(game_extra))

    argv = list(binary_argv_prefix) + substituted

    # ---- validate rom_path under scan roots ---------------------------------
    if not rom_path_obj.exists():
        raise LaunchResolutionError(f"ROM file not found: {rom_path_obj}")
    if not rom_path_obj.is_file():
        raise LaunchResolutionError(f"ROM path is not a file: {rom_path_obj}")
    roots = _allowed_rom_roots()
    if roots and not _resolve_under(rom_path_obj, roots):
        raise LaunchResolutionError(
            f"ROM path is outside configured scan roots: {rom_path_obj}")

    return LaunchContext(
        game_id=game['id'],
        emulator_id=emu['id'],
        binary=binary_path,
        argv=argv,
        token=secrets.token_urlsafe(12),
    )
