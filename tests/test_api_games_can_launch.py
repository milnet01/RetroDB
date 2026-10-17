# PASS-59-91 INV-7 — /api/games marks `can_launch` true only for a caller
# with the launch permission and a game whose mapping resolves (spec §4.3,
# §4.5). /api/games/card-data carries the same flag, because a live card
# refresh re-renders the card from it.
import stat

import pytest

from services.database import execute

PROBE = 'CanLaunchProbe'


@pytest.fixture
def seeded(tmp_path, monkeypatch, setup_complete):
    """Two systems: one whose default emulator resolves, one whose does not.
    A third game sits on the resolving system but overrides to a disabled
    emulator that would otherwise resolve."""
    binary = tmp_path / 'fake-emu'
    binary.write_text('#!/bin/sh\n')
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    # A real ROM under a scan root, in a system folder that lists its type.
    roms = tmp_path / 'roms'
    (roms / 'canlaunch_ok').mkdir(parents=True)
    (roms / 'canlaunch_ok' / 'systeminfo.txt').write_text(
        'Supported file extensions:\n.bin\n')
    rom = roms / 'canlaunch_ok' / 'a.bin'
    rom.write_bytes(b'rom')
    monkeypatch.setattr('services.launch_resolver._allowed_rom_roots',
                        lambda: [roms.resolve()])

    ids = {}
    ids['sys_ok'] = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                            (f'{PROBE} OK', 'canlaunch_ok'))
    ids['sys_bad'] = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                             (f'{PROBE} Bad', 'canlaunch_bad'))
    emu_sql = ("INSERT INTO emulators (name, binary_name, binary_path_override, "
               "args_template, is_retroarch, enabled) VALUES (?, ?, ?, '\"{rom}\"', 0, ?)")
    ids['emu_ok'] = execute(emu_sql, (f'{PROBE} Emu OK', 'fake-emu', str(binary), 1))
    ids['emu_missing'] = execute(emu_sql, (f'{PROBE} Emu Missing',
                                           'canlaunch-not-installed', None, 1))
    ids['emu_disabled'] = execute(emu_sql, (f'{PROBE} Emu Off', 'fake-emu', str(binary), 0))
    for system, emu in (('sys_ok', 'emu_ok'), ('sys_bad', 'emu_missing'),
                        ('sys_ok', 'emu_disabled')):
        execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) "
                "VALUES (?, ?, ?)", (ids[system], ids[emu], int(emu == 'emu_ok' or system == 'sys_bad')))
    game_sql = ("INSERT INTO games (system_id, title, rom_path, emulator_override_id) "
                "VALUES (?, ?, ?, ?)")
    ids['game_ok'] = execute(game_sql, (ids['sys_ok'], f'{PROBE} A', str(rom), None))
    ids['game_norom'] = execute(game_sql, (ids['sys_ok'], f'{PROBE} D',
                                           str(rom.with_name('gone.bin')), None))
    ids['game_bad'] = execute(game_sql, (ids['sys_bad'], f'{PROBE} B', '/x/b.bin', None))
    ids['game_off'] = execute(game_sql, (ids['sys_ok'], f'{PROBE} C', '/x/c.bin',
                                         ids['emu_disabled']))
    yield ids
    execute("DELETE FROM games WHERE system_id IN (?, ?) OR title LIKE ?",
            (ids['sys_ok'], ids['sys_bad'], f'{PROBE}%'))
    execute("DELETE FROM system_emulators WHERE system_id IN (?, ?)",
            (ids['sys_ok'], ids['sys_bad']))
    execute("DELETE FROM emulators WHERE name LIKE ?", (f'{PROBE}%',))
    execute("DELETE FROM systems WHERE name LIKE ?", (f'{PROBE}%',))


def _client(monkeypatch, role):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 99, 'username': 'tester', 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    return app_module.app.test_client()


def _flags(client, ids):
    resp = client.get(f'/api/games?search={PROBE}')
    assert resp.status_code == 200, resp.data
    by_id = {g['id']: g for g in resp.get_json()['games']}
    return {name: by_id[ids[name]]['can_launch']
            for name in ('game_ok', 'game_bad', 'game_off', 'game_norom')}


def test_player_sees_can_launch_only_where_the_mapping_resolves(monkeypatch, seeded):
    # game_norom: the mapping resolves but the ROM file is gone, so the
    # launch would fail; the button must not promise it (user, 2026-10-17).
    assert _flags(_client(monkeypatch, 'player'), seeded) == {
        'game_ok': True, 'game_bad': False, 'game_off': False, 'game_norom': False}


def test_viewer_never_sees_can_launch(monkeypatch, seeded):
    assert _flags(_client(monkeypatch, 'viewer'), seeded) == {
        'game_ok': False, 'game_bad': False, 'game_off': False, 'game_norom': False}


def test_card_data_carries_the_same_flag(monkeypatch, seeded):
    client = _client(monkeypatch, 'player')
    ids = f"{seeded['game_ok']},{seeded['game_bad']}"
    games = {g['id']: g for g in client.get(f'/api/games/card-data?ids={ids}').get_json()['games']}
    assert games[seeded['game_ok']]['can_launch'] is True
    assert games[seeded['game_bad']]['can_launch'] is False
