# PASS-59-91 INV-4 / INV-5 — BIOS status reads the emulator's own settings
# and reports what is missing, writing nothing (spec §4.4).
import stat

from services.emulator_adapters import bios_status


def _exe(path):
    path.write_text('#!/bin/sh\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _listing(root):
    return sorted(str(p) for p in root.rglob('*'))


def test_duckstation_bios_missing_then_ok_and_nothing_written(tmp_path):
    """INV-4."""
    folder = tmp_path / 'DuckStation'
    folder.mkdir()
    app = _exe(folder / 'DuckStation-x64.AppImage')
    (folder / 'portable.txt').write_text('')
    (folder / 'settings.ini').write_text(
        '; comment\n[BIOS]\nSearchDirectory = ../BIOS_Files/PSX\n')
    bios_dir = tmp_path / 'BIOS_Files' / 'PSX'
    bios_dir.mkdir(parents=True)
    (bios_dir / 'readme.txt').write_text('not a bios')
    emu = {'is_retroarch': 0, 'binary_name': 'duckstation-qt',
           'binary_path_override': str(app)}

    before = _listing(tmp_path)
    status = bios_status(emu, None)
    assert status['state'] == 'missing'
    assert _listing(tmp_path) == before

    (bios_dir / 'scph5501.bin').write_bytes(b'\0' * 524288)
    before = _listing(tmp_path)
    assert bios_status(emu, None)['state'] == 'ok'
    assert _listing(tmp_path) == before


def test_retroarch_lists_only_required_firmware(tmp_path, monkeypatch):
    """INV-5."""
    app = _exe(tmp_path / 'RetroArch-Linux-x86_64.AppImage')
    cfg_dir = tmp_path / 'RetroArch-Linux-x86_64.AppImage.home' / '.config' / 'retroarch'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'retroarch.cfg').write_text('system_directory = "~/bios"\n')
    cores = tmp_path / 'cores'
    cores.mkdir()
    (cores / 'probe_libretro.so').write_text('')
    (cores / 'probe_libretro.info').write_text(
        'firmware_count = 2\n'
        'firmware0_desc = "needed"\nfirmware0_path = "scph5501.bin"\nfirmware0_opt = "false"\n'
        'firmware1_desc = "optional"\nfirmware1_path = "extra.bin"\nfirmware1_opt = "true"\n')
    settings = {'retroarch_binary': str(app), 'retroarch_cores_dir': str(cores)}
    lookup = lambda key, default=None: settings.get(key, default)  # noqa: E731
    monkeypatch.setattr('services.launch_resolver.get_setting', lookup)
    emu = {'is_retroarch': 1, 'binary_name': 'retroarch', 'binary_path_override': None}

    status = bios_status(emu, {'retroarch_core': 'probe_libretro.so'})
    assert status['state'] == 'missing'
    assert status['missing'] == ['scph5501.bin']
