# Pass 44.1B — emulator AppImage auto-detect scanner.
import os
import stat
import pytest


def _make_executable(path):
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def fake_layout(tmp_path):
    """Recreate a /mnt/Emulators-style portable-AppImage layout."""
    base = tmp_path / 'Emulators'
    # RetroArch with portable script + cores
    ra_dir = base / 'Multi-System' / 'RetroArch'
    ra_dir.mkdir(parents=True)
    ra_app = ra_dir / 'RetroArch-Linux-x86_64.AppImage'
    ra_app.write_text('#!appimage')
    _make_executable(ra_app)
    ra_portable = ra_dir / 'retroarch-portable.sh'
    ra_portable.write_text('#!/bin/sh\nexec ./RetroArch-Linux-x86_64.AppImage')
    _make_executable(ra_portable)
    # PCSX2 with portable script
    pcsx2_dir = base / 'Sony_PlayStation_2' / 'PCSX2'
    pcsx2_dir.mkdir(parents=True)
    pcsx2_app = pcsx2_dir / 'pcsx2.AppImage'
    pcsx2_app.write_text('#!appimage')
    _make_executable(pcsx2_app)
    pcsx2_portable = pcsx2_dir / 'pcsx2-portable.sh'
    pcsx2_portable.write_text('#!/bin/sh\nexec ./pcsx2.AppImage')
    _make_executable(pcsx2_portable)
    # DuckStation: AppImage only (no portable script)
    duck_dir = base / 'Sony_PlayStation_1' / 'DuckStation'
    duck_dir.mkdir(parents=True)
    duck_app = duck_dir / 'DuckStation-x64.AppImage'
    duck_app.write_text('#!appimage')
    _make_executable(duck_app)
    return base


def test_walk_finds_all_appimages(fake_layout):
    from routes.launch_settings import _walk_appimages
    paths = sorted(p.name for p in _walk_appimages([fake_layout]))
    assert 'RetroArch-Linux-x86_64.AppImage' in paths
    assert 'pcsx2.AppImage' in paths
    assert 'DuckStation-x64.AppImage' in paths
    assert 'retroarch-portable.sh' in paths
    assert 'pcsx2-portable.sh' in paths


def test_detect_prefers_portable_script_over_appimage(fake_layout):
    from routes.launch_settings import _detect_emulators
    found = _detect_emulators([fake_layout])
    assert 'RetroArch' in found
    assert found['RetroArch']['preferred'].endswith('retroarch-portable.sh')
    assert found['RetroArch']['has_portable_script'] is True


def test_detect_falls_back_to_appimage_when_no_portable(fake_layout):
    from routes.launch_settings import _detect_emulators
    found = _detect_emulators([fake_layout])
    assert 'DuckStation' in found
    assert found['DuckStation']['preferred'].endswith('DuckStation-x64.AppImage')
    assert found['DuckStation']['has_portable_script'] is False


def test_detect_skips_unknown_emulator_names(fake_layout):
    """Random AppImages that don't match any known pattern are ignored."""
    rogue = fake_layout / 'NotAnEmulator.AppImage'
    rogue.write_text('#!appimage')
    _make_executable(rogue)
    from routes.launch_settings import _detect_emulators
    found = _detect_emulators([fake_layout])
    assert 'NotAnEmulator' not in found
    # And the known ones still detected
    assert 'PCSX2' in found


def test_walk_handles_nonexistent_root(tmp_path):
    from routes.launch_settings import _walk_appimages
    paths = list(_walk_appimages([tmp_path / 'does-not-exist']))
    assert paths == []


def test_detect_endpoint_registered():
    import app as app_module
    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    assert '/api/settings/emulators/detect' in rules


def test_unauth_detect_blocked(monkeypatch):
    import app as app_module
    # TESTING=True ensures Flask propagates exceptions through the test
    # client so we don't accept a 500 in the `in (302, 401, 403)` set
    # by mistake (test-audit c-002 MED isolation).
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    client = app_module.app.test_client()
    rv = client.post('/api/settings/emulators/detect')
    assert rv.status_code in (302, 401, 403)


def test_scan_paths_default_includes_mnt_emulators():
    """Spec invariant: /mnt/Emulators is in the default scan paths so users
    with that layout get auto-detection without configuration."""
    import settings_manager
    raw = settings_manager.DEFAULT_SETTINGS['emulator_scan_paths']
    assert '/mnt/Emulators' in raw


def test_emulator_scan_paths_validator_accepts_colon_separated():
    from services.settings_validators import validate_settings_value
    ok, _, _ = validate_settings_value(
        'emulator_scan_paths',
        '/mnt/Emulators:~/Downloads:~/.local/bin')
    assert ok
