"""PASS-59-280: Detect finds emulators on Windows and macOS.

On Linux an emulator is an AppImage. On Windows it is the program's own .exe,
named exactly so an updater or uninstaller beside it is never taken. On macOS
it is a .app bundle, whose program is Contents/MacOS/<CFBundleExecutable>.
"""

import plistlib
import sys
from pathlib import Path

import pytest


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'')
    path.chmod(0o755)
    return path


def _bundle(root: Path, name: str, program: str) -> Path:
    app = root / name
    (app / 'Contents' / 'MacOS').mkdir(parents=True)
    with open(app / 'Contents' / 'Info.plist', 'wb') as f:
        plistlib.dump({'CFBundleExecutable': program}, f)
    _touch(app / 'Contents' / 'MacOS' / program)
    return app


@pytest.fixture
def no_flatpaks(monkeypatch):
    monkeypatch.setattr('routes.launch_settings._flatpak_bin_dirs', lambda: [])


def test_windows_matches_each_main_program_exactly(tmp_path, monkeypatch, no_flatpaks):
    from routes import launch_settings as ls
    monkeypatch.setattr(sys, 'platform', 'win32')
    ra = _touch(tmp_path / 'RetroArch-Win64' / 'retroarch.exe')
    _touch(tmp_path / 'RetroArch-Win64' / 'retroarch_debug.exe')
    ds = _touch(tmp_path / 'duckstation' / 'duckstation-qt-x64-ReleaseLTCG.exe')
    _touch(tmp_path / 'duckstation' / 'updater.exe')
    _touch(tmp_path / 'pcsx2' / 'uninstaller.exe')
    pc = _touch(tmp_path / 'pcsx2' / 'pcsx2-qt.exe')
    pp = _touch(tmp_path / 'ppsspp' / 'PPSSPPWindows64.exe')
    _touch(tmp_path / 'stray' / 'retroarch-1.0.AppImage')

    found = ls._detect_emulators([tmp_path])

    assert found['retroarch']['preferred'] == str(ra)
    assert found['duckstation-qt']['preferred'] == str(ds)
    assert found['pcsx2-qt']['preferred'] == str(pc)
    assert found['PPSSPPSDL']['preferred'] == str(pp)
    assert set(found) == {'retroarch', 'duckstation-qt', 'pcsx2-qt', 'PPSSPPSDL'}


def test_macos_resolves_a_bundle_to_its_program(tmp_path, monkeypatch, no_flatpaks):
    from routes import launch_settings as ls
    monkeypatch.setattr(sys, 'platform', 'darwin')
    _bundle(tmp_path, 'RetroArch.app', 'RetroArch')
    _bundle(tmp_path, 'PCSX2-v2.4.0.app', 'PCSX2')
    _bundle(tmp_path / 'sub', 'Dolphin.app', 'DolphinQt')
    # A program inside a bundle is never walked into on its own.
    _touch(tmp_path / 'Cemu.app' / 'Contents' / 'Resources' / 'Cemu.app'
           / 'Contents' / 'Info.plist')

    found = ls._detect_emulators([tmp_path])

    assert found['retroarch']['preferred'] == str(
        tmp_path / 'RetroArch.app' / 'Contents' / 'MacOS' / 'RetroArch')
    assert found['pcsx2-qt']['preferred'] == str(
        tmp_path / 'PCSX2-v2.4.0.app' / 'Contents' / 'MacOS' / 'PCSX2')
    assert found['dolphin-emu']['preferred'] == str(
        tmp_path / 'sub' / 'Dolphin.app' / 'Contents' / 'MacOS' / 'DolphinQt')
    assert 'cemu' not in found


@pytest.mark.parametrize('program', ['../../../evil', '', None])
def test_macos_bundle_without_a_safe_program_is_skipped(tmp_path, monkeypatch,
                                                        no_flatpaks, program):
    from routes import launch_settings as ls
    monkeypatch.setattr(sys, 'platform', 'darwin')
    contents = tmp_path / 'RetroArch.app' / 'Contents'
    contents.mkdir(parents=True)
    with open(contents / 'Info.plist', 'wb') as f:
        plistlib.dump({} if program is None else {'CFBundleExecutable': program}, f)

    assert ls._detect_emulators([tmp_path]) == {}


def test_linux_still_ignores_exe_and_app(tmp_path, monkeypatch, no_flatpaks):
    from routes import launch_settings as ls
    monkeypatch.setattr(sys, 'platform', 'linux')
    _touch(tmp_path / 'retroarch.exe')
    _bundle(tmp_path, 'RetroArch.app', 'RetroArch')

    assert ls._detect_emulators([tmp_path]) == {}


@pytest.mark.parametrize('platform, sep, expected', [
    ('win32', ';', [r'~\Emulators', r'~\Downloads', r'C:\Emulators']),
    ('darwin', ':', ['/Applications', '~/Applications', '~/Downloads']),
    ('linux', ':', ['/mnt/Emulators', '~/Downloads', '~/.local/bin', '/opt']),
])
def test_default_scan_folders_per_os(monkeypatch, platform, sep, expected):
    import settings_manager
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(settings_manager.os, 'pathsep', sep)
    assert settings_manager.default_scan_paths().split(sep) == expected


@pytest.mark.parametrize('platform, binary, cores', [
    ('win32', r'C:\RetroArch-Win64\retroarch.exe', r'C:\RetroArch-Win64\cores'),
    ('darwin', '/Applications/RetroArch.app/Contents/MacOS/RetroArch',
     str(Path('~/Library/Application Support/RetroArch/cores').expanduser())),
])
def test_retroarch_probe_per_os(monkeypatch, platform, binary, cores):
    from routes import launch_settings as ls
    monkeypatch.setattr(sys, 'platform', platform)
    assert binary in ls._bin_chain()
    assert cores in ls._cores_chain()
