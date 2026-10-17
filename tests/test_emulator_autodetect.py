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
    assert 'retroarch' in found
    assert found['retroarch']['preferred'].endswith('retroarch-portable.sh')
    assert found['retroarch']['has_portable_script'] is True


def test_detect_falls_back_to_appimage_when_no_portable(fake_layout):
    from routes.launch_settings import _detect_emulators
    found = _detect_emulators([fake_layout])
    assert 'duckstation-qt' in found
    assert found['duckstation-qt']['preferred'].endswith('DuckStation-x64.AppImage')
    assert found['duckstation-qt']['has_portable_script'] is False


def test_detect_skips_unknown_emulator_names(fake_layout):
    """Random AppImages that don't match any known pattern are ignored."""
    rogue = fake_layout / 'NotAnEmulator.AppImage'
    rogue.write_text('#!appimage')
    _make_executable(rogue)
    from routes.launch_settings import _detect_emulators
    found = _detect_emulators([fake_layout])
    assert all('NotAnEmulator' not in v['path'] for v in found.values())
    # And the known ones still detected
    assert 'pcsx2-qt' in found


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


# -----------------------------------------------------------------------------
# PASS-59-91 stage 2 — adapters, Flatpak launchers, wiring (spec §4.1–4.3)
# -----------------------------------------------------------------------------

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """An empty home, so the real one's Flatpaks and XDG dirs stay out."""
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    for var in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME'):
        monkeypatch.delenv(var, raising=False)
    return home


def test_portable_duckstation_suggests_appimage_psx_and_its_folder(tmp_path, fake_home):
    """INV-1."""
    folder = tmp_path / 'emus' / 'DuckStation'
    folder.mkdir(parents=True)
    app = folder / 'DuckStation-x64.AppImage'
    app.write_text('#!appimage')
    _make_executable(app)
    (folder / 'portable.txt').write_text('')
    (folder / 'settings.ini').write_text('[Main]\n')
    from routes.launch_settings import _detect_emulators
    found = _detect_emulators([tmp_path / 'emus'])
    duck = found['duckstation-qt']
    assert duck['preferred'] == str(app)
    assert 'psx' in duck['systems']
    assert duck['data_dir'] == str(folder)


def test_flatpak_launcher_is_suggested_and_resolves(fake_home):
    """INV-2."""
    bin_dir = fake_home / '.local' / 'share' / 'flatpak' / 'exports' / 'bin'
    bin_dir.mkdir(parents=True)
    launcher = bin_dir / 'org.duckstation.DuckStation'
    launcher.write_text('#!/bin/sh\n')
    _make_executable(launcher)
    from routes.launch_settings import _detect_emulators
    from services.launch_resolver import _resolve_binary
    found = _detect_emulators([])
    assert found['duckstation-qt']['preferred'] == str(launcher)
    row = {'is_retroarch': 0, 'binary_name': 'duckstation-qt',
           'binary_path_override': found['duckstation-qt']['preferred']}
    assert _resolve_binary(row, None) == str(launcher)


def test_walk_ignores_a_tree_deeper_than_the_cap(tmp_path, fake_home):
    """INV-19, the cap half."""
    from routes.launch_settings import _MAX_SCAN_DEPTH, _detect_emulators
    deep = tmp_path / 'root'
    for i in range(_MAX_SCAN_DEPTH):
        deep = deep / f'd{i}'
    deep.mkdir(parents=True)
    app = deep / 'pcsx2.AppImage'
    app.write_text('#!appimage')
    _make_executable(app)
    assert 'pcsx2-qt' not in _detect_emulators([tmp_path / 'root'])


PROBE = 'WireProbe'


@pytest.fixture
def wiring(tmp_path, monkeypatch, setup_complete):
    """A system whose default is a RetroArch row, plus a standalone emulator
    that detection just found. `settings` drives retroarch_binary."""
    ra_bin = tmp_path / 'retroarch'
    ra_bin.write_text('#!/bin/sh\n')
    _make_executable(ra_bin)
    cores = tmp_path / 'cores'
    cores.mkdir()
    (cores / 'probe_libretro.so').write_text('')
    duck = tmp_path / 'duckstation'
    duck.write_text('#!/bin/sh\n')
    _make_executable(duck)
    settings = {'retroarch_binary': str(ra_bin), 'retroarch_cores_dir': str(cores)}
    monkeypatch.setattr('services.launch_resolver.get_setting',
                        lambda key, default=None: settings.get(key, default))

    from services.database import execute
    ids = {'settings': settings, 'ra_bin': ra_bin}
    ids['sys'] = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                         (f'{PROBE} PSX', 'wireprobe_psx'))
    ids['ra'] = execute(
        "INSERT INTO emulators (name, binary_name, args_template, is_retroarch, enabled) "
        "VALUES (?, 'wireprobe-ra', '\"{rom}\"', 1, 1)", (f'{PROBE} RA',))
    ids['duck'] = execute(
        "INSERT INTO emulators (name, binary_name, binary_path_override, args_template, "
        "is_retroarch, enabled) VALUES (?, 'wireprobe-duck', ?, '\"{rom}\"', 0, 1)",
        (f'{PROBE} Duck', str(duck)))
    execute("INSERT INTO system_emulators (system_id, emulator_id, is_default, retroarch_core) "
            "VALUES (?, ?, 1, 'probe_libretro.so')", (ids['sys'], ids['ra']))
    yield ids
    execute("DELETE FROM system_emulators WHERE system_id = ?", (ids['sys'],))
    execute("DELETE FROM emulators WHERE name LIKE ?", (f'{PROBE}%',))
    execute("DELETE FROM systems WHERE name LIKE ?", (f'{PROBE}%',))


def _defaults(system_id):
    from services.database import query
    return [r['emulator_id'] for r in query(
        "SELECT emulator_id FROM system_emulators WHERE system_id = ? AND is_default = 1",
        (system_id,))]


def test_wiring_keeps_a_resolving_default(wiring):
    """INV-3, first half: the user's working choice beats a guess."""
    from routes.launch_settings import _wire_systems
    _wire_systems(wiring['duck'], [wiring['sys']])
    assert _defaults(wiring['sys']) == [wiring['ra']]
    from services.database import query
    row = query("SELECT * FROM system_emulators WHERE system_id = ? AND emulator_id = ?",
                (wiring['sys'], wiring['duck']), one=True)
    assert row is not None and row['is_default'] == 0


def test_wiring_replaces_a_default_that_does_not_resolve(wiring):
    """INV-3, second half: retroarch_binary names a deleted file."""
    wiring['ra_bin'].unlink()
    from routes.launch_settings import _wire_systems
    _wire_systems(wiring['duck'], [wiring['sys']])
    assert _defaults(wiring['sys']) == [wiring['duck']]


def _role_client(monkeypatch, role):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 99, 'username': 'tester', 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'tok'
    return client


def test_editor_cannot_detect_or_list_mappings(monkeypatch, setup_complete):
    """INV-19, the permission half."""
    client = _role_client(monkeypatch, 'editor')
    assert client.post('/api/settings/emulators/detect',
                       headers={'X-CSRF-Token': 'tok'}).status_code == 403
    assert client.get('/api/system_emulators').status_code == 403


def test_detect_response_carries_systems_and_data_dir(monkeypatch, setup_complete,
                                                      fake_layout, fake_home):
    """§4.2: each suggestion gains `systems` and `data_dir`."""
    monkeypatch.setattr('routes.launch_settings._scan_paths', lambda: [fake_layout])
    rv = _role_client(monkeypatch, 'admin').post(
        '/api/settings/emulators/detect', headers={'X-CSRF-Token': 'tok'})
    assert rv.status_code == 200, rv.data
    suggestions = rv.get_json()['suggestions']
    assert suggestions
    assert all('systems' in s and 'data_dir' in s for s in suggestions)


def test_appimage_home_dirs_do_not_use_up_the_entry_cap(tmp_path, fake_home, monkeypatch):
    """An AppImage's `.home` holds thousands of files; walking it must not
    starve the folders after it (found on /mnt/Emulators, 2026-10-17)."""
    monkeypatch.setattr('routes.launch_settings._MAX_ENTRIES_PER_ROOT', 20)
    root = tmp_path / 'emus'
    # The /mnt/Emulators shape: <Maker_System>/<Emulator>/<AppImage>.
    for sub in ('A_Multi', 'B_Multi', 'C_Multi'):
        home = root / sub / 'RetroArch' / 'RetroArch-Linux-x86_64.AppImage.home'
        for d in range(8):
            (home / f'd{d}').mkdir(parents=True)
            for i in range(10):
                (home / f'd{d}' / f'f{i}').write_text('')
    app = root / 'Sony_PlayStation_2' / 'PCSX2' / 'pcsx2.AppImage'
    app.parent.mkdir(parents=True)
    app.write_text('#!appimage')
    _make_executable(app)
    from routes.launch_settings import _detect_emulators
    assert 'pcsx2-qt' in _detect_emulators([root])


@pytest.mark.parametrize('mine_first', [True, False])
def test_a_copy_with_a_portable_script_beats_a_bare_one(tmp_path, fake_home, mine_first):
    """/mnt/Emulators holds a bare RetroArch AppImage under ES-DE and the
    user's own beside retroarch-portable.sh; the portable one is theirs."""
    root = tmp_path / 'emus'
    bare, mine = 'ES-DE', 'RetroArch'
    # tmpfs lists a directory in creation order reversed, so creating the
    # two in each order covers both walk orders.
    for sub in ((mine, bare) if mine_first else (bare, mine)):
        (root / sub).mkdir(parents=True)
        app = root / sub / 'RetroArch-Linux-x86_64.AppImage'
        app.write_text('#!appimage')
        _make_executable(app)
    script = root / mine / 'retroarch-portable.sh'
    script.write_text('#!/bin/sh\n')
    _make_executable(script)
    from routes.launch_settings import _detect_emulators
    assert _detect_emulators([root])['retroarch']['preferred'] == str(script)
