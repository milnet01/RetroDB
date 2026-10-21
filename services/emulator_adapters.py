# =============================================================================
# RETRODB - Emulator adapters
# =============================================================================
# One EmulatorAdapter per known emulator, keyed by emulators.binary_name
# (PASS-59-91 §4.1): how detection recognises its files and Flatpak, which
# system folders it runs, where its data directory lives, and how to tell
# whether its BIOS is in place (§4.4). Reads only; never writes a file.
# =============================================================================

from __future__ import annotations

import configparser
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from services.launch_resolver import (LaunchResolutionError, _FLATPAK_RE,
                                      _resolve_binary, core_file)

# (binary, data dir or None, system_emulators row) -> status dict
BiosRule = Callable[[Path, Optional[Path], Optional[dict]], dict]


@dataclass(frozen=True)
class EmulatorAdapter:
    binary_name: str                 # key: matches emulators.binary_name
    name_patterns: tuple             # regexes on a file name, case-insensitive
    portable_base: str               # `<base>-portable.sh` beside the AppImage
    flatpak_ids: tuple = ()
    systems: tuple = ()              # system folders it runs
    data_dirs: Callable[[Path], list] = lambda binary: []
    data_marker: str = ''            # file that proves a candidate is the data dir
    bios: Optional[BiosRule] = None


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

def _xdg(var, default):
    return Path(os.environ.get(var) or Path.home() / default)


def appimage_for(binary: Path) -> Optional[Path]:
    """The AppImage a binary runs: itself, or the one beside a launcher
    script such as `*-portable.sh` (§4.1)."""
    if binary.name.lower().endswith('.appimage'):
        return binary
    if binary.name.endswith('.sh'):
        try:
            return next((p for p in sorted(binary.parent.iterdir())
                         if p.name.lower().endswith('.appimage')), None)
        except OSError:
            return None
    return None


def _home_of(binary: Path) -> Optional[Path]:
    app = appimage_for(binary)
    return app.with_name(app.name + '.home') if app else None


def _duckstation_dirs(binary: Path) -> list:
    home = _home_of(binary)
    dirs = [binary.parent] if (binary.parent / 'portable.txt').exists() else []
    if home:
        dirs.append(home / '.local' / 'share' / 'duckstation')
    return dirs + [_xdg('XDG_DATA_HOME', '.local/share') / 'duckstation',
                   Path.home() / '.var/app/org.duckstation.DuckStation/data/duckstation']


def _pcsx2_dirs(binary: Path) -> list:
    home = _home_of(binary)
    portable = any((binary.parent / m).exists() for m in ('portable.txt', 'portable.ini'))
    dirs = [binary.parent] if portable else []
    if home:
        dirs.append(home / '.config' / 'PCSX2')
    return dirs + [_xdg('XDG_CONFIG_HOME', '.config') / 'PCSX2',
                   Path.home() / '.var/app/net.pcsx2.PCSX2/config/PCSX2']


def _rpcs3_dirs(binary: Path) -> list:
    home = _home_of(binary)
    dirs = [home / '.config' / 'rpcs3'] if home else []
    return dirs + [_xdg('XDG_CONFIG_HOME', '.config') / 'rpcs3',
                   Path.home() / '.var/app/net.rpcs3.RPCS3/config/rpcs3']


def find_data_dir(adapter: EmulatorAdapter, binary: Path) -> Optional[Path]:
    """The first candidate holding the adapter's marker, or None (§4.1)."""
    if not adapter.data_marker:
        return None
    return next((d for d in adapter.data_dirs(binary)
                 if (d / adapter.data_marker).is_file()), None)


# -----------------------------------------------------------------------------
# BIOS rules (§4.4)
# -----------------------------------------------------------------------------

def _status(missing, checked):
    return {'state': 'missing' if missing else 'ok',
            'missing': missing, 'checked': checked}


_UNKNOWN = {'state': 'unknown', 'missing': [], 'checked': []}


def _ini(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.read_string(path.read_text(encoding='utf-8', errors='replace'))
    return cp


def _under(data_dir: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return Path(os.path.normpath(p if p.is_absolute() else data_dir / p))


_PS1_BIOS_SIZE = 524288


def _duckstation_bios(binary, data_dir, sys_emu):
    ini = _ini(data_dir / 'settings.ini')
    bios_dir = _under(data_dir, ini.get('BIOS', 'SearchDirectory', fallback='bios'))
    if not bios_dir.is_dir():
        return _status([str(bios_dir)], [str(bios_dir)])
    found = any(p.is_file() and p.stat().st_size == _PS1_BIOS_SIZE
                for p in bios_dir.iterdir())
    return _status([] if found else [str(bios_dir)], [str(bios_dir)])


def _pcsx2_bios(binary, data_dir, sys_emu):
    ini = _ini(data_dir / 'inis' / 'PCSX2.ini')
    bios_dir = _under(data_dir, ini.get('Folders', 'Bios', fallback='bios'))
    name = ini.get('Filenames', 'BIOS', fallback='')
    target = bios_dir / name if name else bios_dir
    ok = bool(name) and target.is_file()
    return _status([] if ok else [str(target)], [str(target)])


def _rpcs3_bios(binary, data_dir, sys_emu):
    firmware = data_dir / 'dev_flash' / 'vsh' / 'module' / 'vsh.self'
    return _status([] if firmware.is_file() else [str(firmware)], [str(firmware)])


_CFG_LINE = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*"?([^"\n]*)"?\s*$')


def _cfg(path: Path) -> dict:
    """RetroArch's `key = "value"` format, shared by retroarch.cfg and .info."""
    out = {}
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = _CFG_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def retroarch_cfg(binary) -> Optional[tuple]:
    """(home, retroarch.cfg) for the RetroArch a binary runs (§4.4): the
    AppImage's own home when it holds the file, else ~. None for a Flatpak
    or when neither file exists."""
    if _FLATPAK_RE.match(str(binary)):
        return None
    for home in (_home_of(Path(binary)), Path.home()):
        cfg_path = home / '.config/retroarch/retroarch.cfg' if home else None
        if cfg_path and cfg_path.is_file():
            return home, cfg_path
    return None


def retroarch_path(value: str, home: Path) -> str:
    """A path from retroarch.cfg with a leading ~ expanded against `home`,
    the one retroarch_cfg returned. An AppImage's own home is not the server
    user's, so expanduser() would point at the wrong folder."""
    return str(home) + value[1:] if value.startswith('~') else value


def _retroarch_bios(binary, data_dir, sys_emu):
    found = retroarch_cfg(binary)
    if not found or not sys_emu or not sys_emu.get('retroarch_core'):
        return dict(_UNKNOWN)
    home, cfg_path = found
    system_dir = _cfg(cfg_path).get('system_directory', '')
    if not system_dir or system_dir == 'default':
        return dict(_UNKNOWN)
    system_dir = retroarch_path(system_dir, home)
    info_path = core_file(sys_emu['retroarch_core']).with_suffix('.info')
    if not info_path.is_file():
        return dict(_UNKNOWN)
    info = _cfg(info_path)
    required = [info[f'firmware{i}_path']
                for i in range(int(info.get('firmware_count') or 0))
                if info.get(f'firmware{i}_path')
                and info.get(f'firmware{i}_opt', 'false') == 'false']
    missing = [f for f in required if not (Path(system_dir) / f).is_file()]
    return _status(missing, required)


# -----------------------------------------------------------------------------
# The adapters
# -----------------------------------------------------------------------------

def _pat(regex):
    return (re.compile(regex, re.IGNORECASE),)


ADAPTERS = {a.binary_name: a for a in (
    # RetroArch lists no systems: which core runs a system is PASS-59-81's.
    # Its Flatpak keeps its own probe (routes/launch_settings.py).
    EmulatorAdapter('retroarch', _pat(r'.*retroarch.*\.appimage$'), 'retroarch',
                    bios=_retroarch_bios),
    EmulatorAdapter('duckstation-qt', _pat(r'duckstation.*\.appimage$'), 'duckstation',
                    ('org.duckstation.DuckStation',), ('psx',),
                    _duckstation_dirs, 'settings.ini', _duckstation_bios),
    EmulatorAdapter('pcsx2-qt', _pat(r'pcsx2.*\.appimage$'), 'pcsx2',
                    ('net.pcsx2.PCSX2',), ('ps2',),
                    _pcsx2_dirs, 'inis/PCSX2.ini', _pcsx2_bios),
    EmulatorAdapter('rpcs3', _pat(r'rpcs3.*\.appimage$'), 'rpcs3',
                    ('net.rpcs3.RPCS3',), ('ps3',),
                    _rpcs3_dirs, 'config.yml', _rpcs3_bios),
    EmulatorAdapter('PPSSPPSDL', _pat(r'ppsspp.*\.appimage$'), 'ppsspp',
                    ('org.ppsspp.PPSSPP',), ('psp',)),
    EmulatorAdapter('dolphin-emu', _pat(r'dolphin.*\.appimage$'), 'dolphin',
                    ('org.DolphinEmu.dolphin-emu',), ('gc', 'wii')),
    EmulatorAdapter('cemu', _pat(r'cemu.*\.appimage$'), 'cemu',
                    ('info.cemu.Cemu',), ('wiiu',)),
    EmulatorAdapter('mgba-qt', _pat(r'mgba.*\.appimage$'), 'mgba',
                    ('io.mgba.mGBA',), ('gb', 'gbc', 'gba')),
    EmulatorAdapter('melonDS', _pat(r'melonds.*\.appimage$'), 'melonds',
                    ('net.kuribo64.melonDS',), ('nds',)),
    EmulatorAdapter('citra-qt', _pat(r'citra.*\.appimage$'), 'citra',
                    ('org.citra_emu.citra',), ('n3ds',)),
    EmulatorAdapter('scummvm', _pat(r'scummvm.*\.appimage$'), 'scummvm',
                    ('org.scummvm.ScummVM',), ('scummvm',)),
    EmulatorAdapter('mame', _pat(r'mame.*\.appimage$'), 'mame',
                    ('org.mamedev.MAME',), ('arcade', 'mame')),
)}


def adapter_for(emu_row) -> Optional[EmulatorAdapter]:
    return ADAPTERS.get((emu_row or {}).get('binary_name') or '')


def bios_status(emu_row, sys_emu_row) -> dict:
    """{"state": "ok" | "missing" | "unknown", "missing": [str], "checked": [str]}.
    Unknown when there is no rule, no binary, no data dir a rule needs, or a
    file cannot be read (§4.4, §6). Never blocks a launch."""
    adapter = adapter_for(emu_row)
    if not adapter or not adapter.bios:
        return dict(_UNKNOWN)
    try:
        binary = Path(_resolve_binary(emu_row, sys_emu_row))
        data_dir = find_data_dir(adapter, binary)
        if adapter.data_marker and data_dir is None:
            return dict(_UNKNOWN)
        return adapter.bios(binary, data_dir, sys_emu_row)
    except (LaunchResolutionError, OSError, configparser.Error, ValueError):
        return dict(_UNKNOWN)
