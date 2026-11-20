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
import plistlib
import re
import sys
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


def _documents() -> Path:
    """Windows' Documents folder, wherever the user or OneDrive moved it."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows'
                            r'\CurrentVersion\Explorer\User Shell Folders') as key:
            return Path(os.path.expandvars(winreg.QueryValueEx(key, 'Personal')[0]))
    except (ImportError, OSError):
        return Path.home() / 'Documents'


_MAC_SUPPORT = Path('Library') / 'Application Support'


def _duckstation_dirs(binary: Path) -> list:
    # DuckStation's Core::SetAppRootAndResources (src/core/core.cpp): portable
    # beside the program; Windows Documents if there, else LOCALAPPDATA; macOS
    # Application Support; Linux $XDG_CONFIG_HOME if set, else ~/.local/share.
    portable = any((binary.parent / m).exists() for m in ('portable.txt', 'settings.ini'))
    dirs = [binary.parent] if portable else []
    if sys.platform == 'win32':
        local = os.environ.get('LOCALAPPDATA')
        return dirs + [_documents() / 'DuckStation'] + (
            [Path(local) / 'DuckStation'] if local else [])
    if sys.platform == 'darwin':
        return dirs + [Path.home() / _MAC_SUPPORT / 'DuckStation']
    home = _home_of(binary)
    if home:
        dirs.append(home / '.local' / 'share' / 'duckstation')
    xdg = os.environ.get('XDG_CONFIG_HOME', '')
    own = (Path(xdg) / 'duckstation' if os.path.isabs(xdg)
           else Path.home() / '.local' / 'share' / 'duckstation')
    flatpak = Path.home() / '.var/app/org.duckstation.DuckStation'
    return dirs + [own, flatpak / 'config/duckstation', flatpak / 'data/duckstation']


def _pcsx2_dirs(binary: Path) -> list:
    # PCSX2's EmuFolders::SetDataDirectory (pcsx2/Pcsx2Config.cpp): portable
    # beside the program; Windows Documents; macOS Application Support.
    portable = any((binary.parent / m).exists() for m in ('portable.txt', 'portable.ini'))
    dirs = [binary.parent] if portable else []
    if sys.platform == 'win32':
        return dirs + [_documents() / 'PCSX2']
    if sys.platform == 'darwin':
        return dirs + [Path.home() / _MAC_SUPPORT / 'PCSX2']
    home = _home_of(binary)
    if home:
        dirs.append(home / '.config' / 'PCSX2')
    return dirs + [_xdg('XDG_CONFIG_HOME', '.config') / 'PCSX2',
                   Path.home() / '.var/app/net.pcsx2.PCSX2/config/PCSX2']


def _rpcs3_dirs(binary: Path) -> list:
    # RPCS3's fs::get_config_dir(): a `portable` folder beside the program
    # wins; Windows keeps everything beside rpcs3.exe; macOS uses
    # Application Support; Linux XDG_CONFIG_HOME (or ~/.config).
    home = _home_of(binary)
    dirs = [binary.parent / 'portable', binary.parent]
    if home:
        dirs.append(home / '.config' / 'rpcs3')
    return dirs + [_xdg('XDG_CONFIG_HOME', '.config') / 'rpcs3',
                   Path.home() / '.var/app/net.rpcs3.RPCS3/config/rpcs3',
                   Path.home() / 'Library' / 'Application Support' / 'rpcs3']


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

def _pat(appimage, exe=None, app=None):
    """One pattern per kind of program file: an AppImage on Linux, the main
    program's exact `.exe` on Windows (never its updater or uninstaller),
    its `.app` bundle on macOS.  The walk only offers the host's own kind."""
    return tuple(re.compile(p, re.IGNORECASE) for p in (appimage, exe, app) if p)


def program_kinds() -> tuple:
    """The file-name endings an emulator program has on this OS (§4.2)."""
    if sys.platform == 'win32':
        return ('.exe',)
    if sys.platform == 'darwin':
        return ('.app',)
    return ('.appimage', '-portable.sh')


def app_program(bundle: Path) -> Optional[Path]:
    """The program a macOS `.app` runs: Contents/MacOS/<CFBundleExecutable>
    from its Info.plist.  None when the plist names nothing usable."""
    try:
        with open(bundle / 'Contents' / 'Info.plist', 'rb') as f:
            name = plistlib.load(f).get('CFBundleExecutable')
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    if not isinstance(name, str) or not name or Path(name).name != name or name in ('.', '..'):
        return None
    program = bundle / 'Contents' / 'MacOS' / name
    return program if program.is_file() else None


ADAPTERS = {a.binary_name: a for a in (
    # Windows and macOS names: each emulator's official release files
    # (read 2026-11-20); mame.exe is the probable name, unconfirmed.
    # RetroArch lists no systems: which core runs a system is PASS-59-81's.
    # Its Flatpak keeps its own probe (routes/launch_settings.py).
    EmulatorAdapter('retroarch', _pat(r'.*retroarch.*\.appimage$', r'retroarch\.exe$',
                                    r'retroarch\.app$'), 'retroarch',
                    bios=_retroarch_bios),
    EmulatorAdapter('duckstation-qt', _pat(r'duckstation.*\.appimage$',
                                              r'duckstation-qt-x64-releaseltcg\.exe$',
                                              r'duckstation\.app$'), 'duckstation',
                    ('org.duckstation.DuckStation',), ('psx',),
                    _duckstation_dirs, 'settings.ini', _duckstation_bios),
    EmulatorAdapter('pcsx2-qt', _pat(r'pcsx2.*\.appimage$', r'pcsx2-qt\.exe$',
                                        r'pcsx2(-v[0-9.]+)?\.app$'), 'pcsx2',
                    ('net.pcsx2.PCSX2',), ('ps2',),
                    _pcsx2_dirs, 'inis/PCSX2.ini', _pcsx2_bios),
    EmulatorAdapter('rpcs3', _pat(r'rpcs3.*\.appimage$', r'rpcs3\.exe$', r'rpcs3\.app$'), 'rpcs3',
                    ('net.rpcs3.RPCS3',), ('ps3',),
                    _rpcs3_dirs, 'config.yml', _rpcs3_bios),
    EmulatorAdapter('PPSSPPSDL', _pat(r'ppsspp.*\.appimage$', r'ppssppwindows64\.exe$',
                                           r'ppssppsdl\.app$'), 'ppsspp',
                    ('org.ppsspp.PPSSPP',), ('psp',)),
    EmulatorAdapter('dolphin-emu', _pat(r'dolphin.*\.appimage$', r'dolphin\.exe$',
                                             r'dolphin\.app$'), 'dolphin',
                    ('org.DolphinEmu.dolphin-emu',), ('gc', 'wii')),
    EmulatorAdapter('cemu', _pat(r'cemu.*\.appimage$', r'cemu\.exe$', r'cemu\.app$'), 'cemu',
                    ('info.cemu.Cemu',), ('wiiu',)),
    EmulatorAdapter('mgba-qt', _pat(r'mgba.*\.appimage$', r'mgba\.exe$', r'mgba\.app$'), 'mgba',
                    ('io.mgba.mGBA',), ('gb', 'gbc', 'gba')),
    EmulatorAdapter('melonDS', _pat(r'melonds.*\.appimage$', r'melonds\.exe$',
                                             r'melonds\.app$'), 'melonds',
                    ('net.kuribo64.melonDS',), ('nds',)),
    EmulatorAdapter('citra-qt', _pat(r'citra.*\.appimage$', None, r'azahar\.app$'), 'citra',
                    ('org.citra_emu.citra',), ('n3ds',)),
    EmulatorAdapter('scummvm', _pat(r'scummvm.*\.appimage$', r'scummvm\.exe$',
                                             r'scummvm\.app$'), 'scummvm',
                    ('org.scummvm.ScummVM',), ('scummvm',)),
    EmulatorAdapter('mame', _pat(r'mame.*\.appimage$', r'mame\.exe$'), 'mame',
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
