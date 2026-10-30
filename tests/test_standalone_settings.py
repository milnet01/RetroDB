"""PASS-59-91 INV-11 to INV-16, INV-20 and INV-19's settings half —
per-game settings files for DuckStation, PCSX2 and RPCS3.

docs/specs/PASS-59-91-zero-setup-play.md §4.6. Data dirs live under
tmp_path; HOME and the XDG dirs point there too, so no fallback candidate
can reach a real emulator folder. The launcher is a stub.
"""
import stat
from itertools import count
from unittest.mock import MagicMock

import pytest

from services.database import execute, query
from services import standalone_settings as ss

_seq = count()
PROBE = 'StandaloneProbe'


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_DATA_HOME', str(home / 'share'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(home / 'config'))
    monkeypatch.setattr('services.launch_resolver._allowed_rom_roots', lambda: [])


def _exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _data_dir(tmp_path, kind, with_marker=True):
    """(binary, data_dir) laid out as each adapter's portable/AppImage home."""
    root = tmp_path / kind
    if kind == 'duckstation-qt':
        binary = _exe(root / 'DuckStation-x64.AppImage')
        (root / 'portable.txt').write_text('')
        data = root
        marker = data / 'settings.ini'
    elif kind == 'pcsx2-qt':
        binary = _exe(root / 'pcsx2.AppImage')
        (root / 'portable.ini').write_text('')
        data = root
        marker = data / 'inis' / 'PCSX2.ini'
    else:
        binary = _exe(root / 'RPCS3.AppImage')
        data = root / 'RPCS3.AppImage.home' / '.config' / 'rpcs3'
        marker = data / 'config.yml'
    if with_marker:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('')
    return binary, data


@pytest.fixture
def seed(tmp_path, setup_complete):
    made = {'systems': [], 'emus': [], 'games': []}

    def make(kind='duckstation-qt', serial='SLUS-20001', crc='67454C1E',
             with_marker=True, folder=None):
        n = next(_seq)
        binary, data = _data_dir(tmp_path / f'e{n}', kind, with_marker)
        sid = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                      (f'{PROBE} {n}', folder or f'ssprobe{n}'))
        template = '--no-gui "{rom}"' if kind == 'rpcs3' else '-batch {fullscreen_flag} "{rom}"'
        eid = execute("INSERT INTO emulators (name, binary_name, binary_path_override, "
                      "args_template, is_retroarch, enabled) VALUES (?, ?, ?, ?, 0, 1)",
                      (f'{PROBE} Emu {n}', kind, str(binary), template))
        execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) VALUES (?, ?, 1)",
                (sid, eid))
        rom = tmp_path / f'e{n}' / 'game.chd'
        rom.write_bytes(b'x')
        gid = execute("INSERT INTO games (system_id, title, rom_path, disc_serial, disc_crc) "
                      "VALUES (?, ?, ?, ?, ?)", (sid, f'{PROBE} game {n}', str(rom), serial, crc))
        made['systems'].append(sid)
        made['emus'].append(eid)
        made['games'].append(gid)
        return {'sid': sid, 'eid': eid, 'gid': gid, 'data': data, 'binary': binary}

    yield make
    for gid in made['games']:
        execute("DELETE FROM games WHERE id = ?", (gid,))
    for eid in made['emus']:
        execute("DELETE FROM emulator_setting_choices WHERE emulator_id = ?", (eid,))
        execute("DELETE FROM emulator_written_settings WHERE emulator_id = ?", (eid,))
        execute("DELETE FROM system_emulators WHERE emulator_id = ?", (eid,))
        execute("DELETE FROM emulators WHERE id = ?", (eid,))
    for sid in made['systems']:
        execute("DELETE FROM systems WHERE id = ?", (sid,))


@pytest.fixture
def launch(admin_test_client, monkeypatch):
    launcher = MagicMock()
    launcher.active.return_value = []
    launcher.launch.return_value = MagicMock(token='t', pid=1, game_id=1,
                                             emulator_id=1, started_at=0.0)
    monkeypatch.setattr('routes.launch.get_launcher', lambda: launcher)
    client, csrf = admin_test_client()

    def go(game_id):
        resp = client.post(f'/api/game/{game_id}/launch', headers={'X-CSRF-Token': csrf})
        assert resp.status_code == 202, resp.get_data(as_text=True)[:300]
        return resp
    go.launcher = launcher
    go.client = client
    go.csrf = csrf
    return go


def _ds_file(row):
    return row['data'] / 'gamesettings' / 'SLUS-20001.ini'


# INV-11 -----------------------------------------------------------------------

def test_inv11_only_managed_keys_are_added(seed, launch):
    row = seed()
    f = _ds_file(row)
    f.parent.mkdir(parents=True)
    original = ['# my notes\n', '[TextureReplacements]\n', 'EnableTextureReplacements = true\n']
    f.write_text(''.join(original))
    launch(row['gid'])
    lines = f.read_text().splitlines(keepends=True)
    it = iter(lines)
    assert all(any(o == ln for ln in it) for o in original)  # in order, untouched
    added = [ln.strip() for ln in lines if ln not in original and ln.strip()]
    assert sorted(added) == sorted(['[Display]', 'AspectRatio = Auto (Game Native)',
                                    '[GPU]', 'ResolutionScale = 4'])


# INV-12 -----------------------------------------------------------------------

def test_inv12_a_key_the_user_changed_survives(seed, launch):
    row = seed()
    launch(row['gid'])
    f = _ds_file(row)
    assert 'ResolutionScale = 4' in f.read_text()
    f.write_text(f.read_text().replace('ResolutionScale = 4', 'ResolutionScale = 2'))
    ss.set_choice(row['eid'], 'system', row['sid'], 'resolution_scale', '5x')
    launch(row['gid'])
    assert 'ResolutionScale = 2' in f.read_text()


def test_inv12_a_file_with_no_record_is_the_users(seed, launch):
    row = seed()
    f = _ds_file(row)
    f.parent.mkdir(parents=True)
    f.write_text('[GPU]\nResolutionScale = 3\n')
    launch(row['gid'])
    assert 'ResolutionScale = 3' in f.read_text()
    assert 'ResolutionScale = 4' not in f.read_text()


# INV-13 -----------------------------------------------------------------------

def test_inv13_game_beats_system_beats_default(seed, launch):
    row = seed()
    f = _ds_file(row)

    def scale():
        launch(row['gid'])
        return ss.read_value(f.read_text().splitlines(keepends=True),
                             ss.settings_for('duckstation-qt')['resolution_scale'])
    assert scale() == '4'
    ss.set_choice(row['eid'], 'system', row['sid'], 'resolution_scale', '3x')
    assert scale() == '3'
    ss.set_choice(row['eid'], 'game', row['gid'], 'resolution_scale', '2x')
    assert scale() == '2'
    ss.set_choice(row['eid'], 'game', row['gid'], 'resolution_scale', None)
    assert scale() == '3'


# INV-14 -----------------------------------------------------------------------

def test_inv14_duckstation_file(seed, launch):
    row = seed()
    launch(row['gid'])
    assert _ds_file(row).is_file()


def test_inv14_pcsx2_reuses_the_existing_file(seed, launch):
    row = seed('pcsx2-qt')
    existing = row['data'] / 'gamesettings' / 'SLUS-20001_DEADBEEF.ini'
    existing.parent.mkdir(parents=True)
    existing.write_text('[EmuCore/GS]\nLoadTextureReplacements = true\n')
    launch(row['gid'])
    assert [p.name for p in existing.parent.iterdir()] == ['SLUS-20001_DEADBEEF.ini']
    assert 'upscale_multiplier = 3' in existing.read_text()


def test_inv14_pcsx2_creates_serial_crc_file(seed, launch):
    row = seed('pcsx2-qt')
    launch(row['gid'])
    assert (row['data'] / 'gamesettings' / 'SLUS-20001_67454C1E.ini').is_file()


def test_inv14_rpcs3_drops_the_dash(seed, launch):
    row = seed('rpcs3', serial='BLUS-31024', crc=None)
    launch(row['gid'])
    f = row['data'] / 'custom_configs' / 'config_BLUS31024.yml'
    assert f.is_file()
    assert '  Resolution Scale: 100' in f.read_text().splitlines()


# INV-15 -----------------------------------------------------------------------

@pytest.mark.parametrize('serial', ['../../evil', 'SLUS-2000'])
def test_inv15_bad_serial_writes_nothing(seed, launch, tmp_path, serial):
    row = seed(serial=serial)
    before = sorted(p for p in tmp_path.rglob('*'))
    launch(row['gid'])
    assert launch.launcher.launch.called
    assert sorted(p for p in tmp_path.rglob('*')) == before


# INV-16 -----------------------------------------------------------------------

def _view(launch, gid):
    resp = launch.client.get(f'/api/games/{gid}/emulator-settings')
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()['data']


def test_inv16_unreadable_serial_still_launches(seed, launch):
    row = seed(serial='')
    launch(row['gid'])
    assert launch.launcher.launch.called
    view = _view(launch, row['gid'])
    assert view['supported'] is False and view['reason']


def test_inv16_no_data_dir_still_launches(seed, launch):
    row = seed(with_marker=False)
    launch(row['gid'])
    assert launch.launcher.launch.called
    view = _view(launch, row['gid'])
    assert view['supported'] is False and 'once' in view['reason']


def test_inv16_two_pcsx2_files_write_nothing(seed, launch):
    row = seed('pcsx2-qt')
    d = row['data'] / 'gamesettings'
    d.mkdir(parents=True)
    for name in ('SLUS-20001_AAAAAAAA.ini', 'SLUS-20001_BBBBBBBB.ini'):
        (d / name).write_text('')
    launch(row['gid'])
    assert launch.launcher.launch.called
    assert all((d / n).read_text() == '' for n in ('SLUS-20001_AAAAAAAA.ini',
                                                     'SLUS-20001_BBBBBBBB.ini'))
    view = _view(launch, row['gid'])
    assert view['supported'] is False and len(view['candidates']) == 2


def test_view_reports_sources(seed, launch):
    row = seed()
    ss.set_choice(row['eid'], 'system', row['sid'], 'aspect_ratio', '16:9')
    view = _view(launch, row['gid'])
    assert view['supported'] is True and view['serial'] == 'SLUS-20001'
    by = {s['setting']: s for s in view['settings']}
    assert by['aspect_ratio']['value'] == '16:9' and by['aspect_ratio']['source'] == 'system'
    assert by['resolution_scale']['source'] == 'default'
    assert by['fullscreen']['per_game'] is False


# INV-20 -----------------------------------------------------------------------

def test_inv20_rpcs3_yaml_keeps_every_other_line(seed, launch):
    row = seed('rpcs3', serial='BLUS-31024', crc=None)
    f = row['data'] / 'custom_configs' / 'config_BLUS31024.yml'
    f.parent.mkdir(parents=True)
    text = ('Core:\n  PPU Threads: 2\nVideo:\n  Aspect ratio: 16:9\n'
            '  Resolution Scale: 100\nMiscellaneous:\n'
            '  Start games in fullscreen mode: false\n')
    f.write_text(text)
    execute("INSERT INTO emulator_written_settings (emulator_id, file_path, setting, written) "
            "VALUES (?, ?, 'resolution_scale', '100')", (row['eid'], str(f)))
    ss.set_choice(row['eid'], 'system', row['sid'], 'resolution_scale', '150%')
    launch(row['gid'])
    before, after = text.splitlines(), f.read_text().splitlines()
    assert len(before) == len(after)
    changed = [(b, a) for b, a in zip(before, after) if b != a]
    assert changed == [('  Resolution Scale: 100', '  Resolution Scale: 150')]


# Routes (INV-19's settings half) ---------------------------------------------

EDITOR = {'id': 1, 'username': 'editor-stub', 'role': 'editor'}
VIEWER = {'id': 1, 'username': 'viewer-stub', 'role': 'viewer'}


def test_inv19_editor_cannot_set_system_level(seed, admin_test_client):
    row = seed()
    client, csrf = admin_test_client(user=EDITOR)
    url = f"/api/systems/{row['sid']}/emulator-settings/{row['eid']}"
    assert client.get(url).status_code == 403
    resp = client.put(url, json={'resolution_scale': '2x'}, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 403
    assert not query("SELECT 1 FROM emulator_setting_choices WHERE emulator_id = ?",
                     (row['eid'],))


def test_inv19_game_level_flag_is_refused(seed, admin_test_client):
    row = seed()
    client, csrf = admin_test_client(user=EDITOR)
    resp = client.put(f"/api/games/{row['gid']}/emulator-settings",
                      json={'fullscreen': 'off'}, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 400


def test_editor_sets_and_clears_a_game_choice(seed, admin_test_client):
    row = seed()
    client, csrf = admin_test_client(user=EDITOR)
    url = f"/api/games/{row['gid']}/emulator-settings"
    resp = client.put(url, json={'resolution_scale': '2x'}, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    by = {s['setting']: s for s in resp.get_json()['data']['settings']}
    assert by['resolution_scale'] == {**by['resolution_scale'], 'value': '2x', 'source': 'game'}
    client.put(url, json={'resolution_scale': None}, headers={'X-CSRF-Token': csrf})
    assert not query("SELECT 1 FROM emulator_setting_choices WHERE scope = 'game' "
                     "AND scope_id = ?", (row['gid'],))


def test_viewer_can_read_but_not_write(seed, admin_test_client):
    row = seed()
    client, csrf = admin_test_client(user=VIEWER)
    url = f"/api/games/{row['gid']}/emulator-settings"
    assert client.get(url).status_code == 200
    assert client.put(url, json={'resolution_scale': '2x'},
                      headers={'X-CSRF-Token': csrf}).status_code == 403


def test_admin_sets_system_level(seed, admin_test_client):
    row = seed()
    client, csrf = admin_test_client()
    url = f"/api/systems/{row['sid']}/emulator-settings/{row['eid']}"
    resp = client.put(url, json={'fullscreen': 'off'}, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    by = {s['setting']: s for s in resp.get_json()['data']['settings']}
    assert by['fullscreen']['value'] == 'off' and by['fullscreen']['source'] == 'system'
    assert client.put(url, json={'fullscreen': 'sideways'},
                      headers={'X-CSRF-Token': csrf}).status_code == 400


# PASS-59-194 -------------------------------------------------------------------

def test_play_signs_pcsx2_in_as_whoever_pressed_it(seed, launch, monkeypatch):
    row = seed('pcsx2-qt')
    monkeypatch.setattr('services.ra_sign_in._record',
                        lambda _uid: {'username': 'Ants', 'token': 'tok-1', 'hardcore': False})
    launch(row['gid'])
    text = (row['data'] / 'inis' / 'PCSX2.ini').read_text()
    assert 'Username = Ants' in text and 'Token = tok-1' in text and 'Enabled = true' in text
    launch.launcher.launch.assert_called_once()
