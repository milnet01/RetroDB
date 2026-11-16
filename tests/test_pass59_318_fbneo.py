"""PASS-59-318 — arcade games RetroAchievements links play in the player's
FBNeo core; the rest stay in MAME. FBNeo's cheat pack, its names on the
game page, and its file in RetroArch's system folder for one session.
docs/specs/PASS-59-155-cheats.md §4.9, PASS-59-81 §4.1.
"""
import zipfile
from pathlib import Path

import pytest

from services import cheats
from services.database import execute
from tests.test_launch_resolver import tmpdb  # noqa: F401  (fixture)
from tests.test_player_launch import playerdb  # noqa: F401  (fixture)

INI = ('cheat "Infinite Credits"\ndefault 0\n0 "Disabled"\n1 "Enabled", 0, 0xE018, 0x01\n\n'
       'cheat "Infinite Lives"\ndefault 0\n0 "Disabled"\n1 "Enabled", 0, 0xE101, 0x06\n\n'
       'cheat "Infinite Lives"\ndefault 0\n0 "Disabled"\n1 "Enabled", 0, 0xE102, 0x06\n')


@pytest.fixture
def arcade(playerdb, tmp_path):  # noqa: F811
    """playerdb plus a MAME system: MAME its default, the player beside it
    with FBNeo installed, one game with achievements (sf2, id 2) and one
    without (pacman, id 3)."""
    conn = playerdb['conn']
    conn.execute("ALTER TABLE games ADD COLUMN has_retroachievements INTEGER DEFAULT 0")
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (2, 'MAME', 'mame')")
    mame = tmp_path / 'mame'
    mame.write_text('#!/bin/sh\n')
    mame.chmod(0o755)
    conn.execute("INSERT INTO emulators (id, name, binary_name, binary_path_override, args_template, "
                 "is_retroarch, enabled) VALUES (4, 'MAME', 'mame', ?, '\"{rom}\"', 0, 1)", (str(mame),))
    conn.execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) VALUES (2, 4, 1)")
    conn.execute("INSERT INTO system_emulators (system_id, emulator_id, retroarch_core, is_default) "
                 "VALUES (2, 3, 'fbneo_libretro.so', 0)")
    roms = playerdb['rom_file'].parent.parent / 'mame'
    roms.mkdir()
    (roms / 'systeminfo.txt').write_text('Supported file extensions:\n.zip .7z\n')
    for gid, name, ra in ((2, 'sf2', 1), (3, 'pacman', 0)):
        (roms / f'{name}.zip').write_bytes(b'PK')
        conn.execute("INSERT INTO games (id, system_id, title, rom_path, has_retroachievements) "
                     "VALUES (?, 2, ?, ?, ?)", (gid, name, str(roms / f'{name}.zip'), ra))
    conn.commit()
    from services import player
    player.core_file('fbneo_libretro.so').write_bytes(b'\x7fELF')
    playerdb['index']['fbneo_libretro.so.zip'] = ('2026-11-16', '00000000')
    playerdb['mame'] = mame
    playerdb['ra_system'] = tmp_path / 'ra-system'
    return playerdb


def _resolve(game_id):
    from services.launch_resolver import resolve_launch_context
    return resolve_launch_context(game_id)


def _pack_ini(name='sf2', text=INI, layer='packs'):
    path = cheats.store_dir() / layer / 'fbneo' / f'{name}.ini'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# Routing ----------------------------------------------------------------------

def test_game_with_achievements_starts_in_fbneo(arcade):
    ctx = _resolve(2)
    assert ctx.emulator_id == 3
    assert ctx.argv[ctx.argv.index('-L') + 1].endswith('fbneo_libretro.so')


def test_game_without_achievements_stays_in_mame(arcade):
    ctx = _resolve(3)
    assert ctx.emulator_id == 4
    assert ctx.argv[0] == str(arcade['mame'])


def test_a_games_own_emulator_choice_wins(arcade):
    arcade['conn'].execute("UPDATE games SET emulator_override_id = 4 WHERE id = 2")
    arcade['conn'].commit()
    assert _resolve(2).emulator_id == 4


def test_player_turned_off_leaves_achievement_games_in_mame(arcade):
    arcade['conn'].execute("UPDATE emulators SET enabled = 0 WHERE id = 3")
    arcade['conn'].commit()
    assert _resolve(2).emulator_id == 4


def test_player_never_stands_in_for_mame_on_a_game_without_achievements(arcade):
    from services.launch_resolver import pick_launch_mapping
    arcade['mame'].chmod(0o644)           # MAME no longer resolves
    emu, _row = pick_launch_mapping(2, None)
    assert emu['id'] == 4
    emu, _row = pick_launch_mapping(2, None, achievements=True)
    assert emu['id'] == 3


def test_play_button_and_name_follow_the_game(arcade):
    from services.launch_resolver import launch_checker, launch_emulator_name
    assert launch_emulator_name(2, None, achievements=True) == 'RetroDB Player'
    assert launch_emulator_name(2, None) == 'MAME'
    can_launch = launch_checker()
    assert can_launch(2, None) and can_launch(2, None, True)


def test_other_systems_ignore_achievements(arcade):
    from services.launch_resolver import pick_launch_mapping
    assert pick_launch_mapping(1, None, achievements=True)[0]['id'] == 3   # psx default


# The cheat file in RetroArch's system folder -----------------------------------

def test_launch_copies_the_sets_file_and_the_session_end_removes_it(arcade):
    from services import player
    _pack_ini()
    ctx = _resolve(2)
    placed = arcade['ra_system'] / 'fbneo' / 'cheats' / 'sf2.ini'
    assert placed.read_text() == INI
    player.after_session(2, Path(ctx.argv[-1]), ctx.token)
    assert not placed.exists()


def test_the_users_own_file_is_never_touched(arcade):
    from services import player
    _pack_ini()
    mine = arcade['ra_system'] / 'fbneo' / 'cheats' / 'sf2.ini'
    mine.parent.mkdir(parents=True)
    mine.write_text('cheat "Mine"\n')
    ctx = _resolve(2)
    player.after_session(2, Path(ctx.argv[-1]), ctx.token)
    assert mine.read_text() == 'cheat "Mine"\n'


def test_a_copy_left_by_a_session_that_never_ended_is_replaced(arcade):
    from services import player
    _pack_ini()
    _resolve(2)
    placed = arcade['ra_system'] / 'fbneo' / 'cheats' / 'sf2.ini'
    _pack_ini(text='cheat "Newer"\n')
    ctx = _resolve(2)
    assert placed.read_text() == 'cheat "Newer"\n'
    player.after_session(2, Path(ctx.argv[-1]), ctx.token)
    assert not placed.exists()


def test_no_pack_file_writes_nothing(arcade):
    _resolve(2)
    assert not (arcade['ra_system'] / 'fbneo').exists()


# The pack and the names --------------------------------------------------------

def test_pack_members_are_the_cheats_folders_ini_files():
    keep = cheats._pack_member('fbneo', zipfile.ZipInfo('FBNeo-cheats-master/cheats/1942.ini'))
    assert keep == Path('1942.ini')
    assert cheats._pack_member('fbneo', zipfile.ZipInfo('FBNeo-cheats-master/README.md')) is None


def test_notes_and_blank_separators_are_not_cheats(tmp_path, monkeypatch):
    """sf2.ini opens with a note and a `cheat " "` separator, neither with
    a choice under it (FBNeo-cheats, 2026-11-16)."""
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    _pack_ini(text='cheat "You must turn OFF ALL cheats first."\ncheat " "\n\n' + INI
              + '\ncheat " "\n')
    assert [c['name'] for c in cheats.fbneo_view('/roms/mame/sf2.zip')] == [
        'Infinite Credits', 'Infinite Lives']


def test_names_are_listed_once_and_locked(tmp_path, monkeypatch):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    _pack_ini()
    assert cheats.fbneo_view('/roms/mame/sf2.zip') == [
        {'name': 'Infinite Credits', 'enabled': False, 'locked': True},
        {'name': 'Infinite Lives', 'enabled': False, 'locked': True}]
    _pack_ini(text='cheat "Own"\ndefault 0\n0 "Disabled"\n1 "Enabled", 0, 0x1, 0x1\n', layer='own')
    assert [c['name'] for c in cheats.fbneo_view('/roms/mame/sf2.zip')] == ['Own']
    assert cheats.fbneo_view('/roms/mame/pacman.zip') == []


@pytest.fixture
def fbneo_game(tmp_path, monkeypatch, setup_complete):
    """A game the player runs on an achievements-only system, in the test DB."""
    from services import player_cores
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    monkeypatch.setattr(player_cores, 'achievements_only', lambda folder: folder == 'fbneoprobe')
    rom = tmp_path / 'sf2.zip'
    rom.write_bytes(b'PK')
    sid = execute("INSERT INTO systems (name, folder) VALUES ('FBNeoProbe', 'fbneoprobe')")
    eid = execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch, "
                  "is_player, enabled) VALUES ('FBNeoProbe Player', 'retrodb-player', 'x', 0, 1, 1)")
    execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) VALUES (?, ?, 1)",
            (sid, eid))
    gid = execute("INSERT INTO games (system_id, title, rom_path, has_retroachievements) "
                  "VALUES (?, 'Street Fighter II', ?, 1)", (sid, str(rom)))
    yield gid
    execute("DELETE FROM games WHERE id = ?", (gid,))
    execute("DELETE FROM system_emulators WHERE emulator_id = ?", (eid,))
    execute("DELETE FROM emulators WHERE id = ?", (eid,))
    execute("DELETE FROM systems WHERE id = ?", (sid,))


def test_panel_lists_fbneo_names_and_refuses_a_switch(fbneo_game, admin_test_client):
    client, csrf = admin_test_client()
    data = client.get(f'/api/games/{fbneo_game}/cheats').get_json()['data']
    assert data['emulator'] == 'fbneo' and data['cheats'] == [] and data['reason']
    _pack_ini()
    data = client.get(f'/api/games/{fbneo_game}/cheats').get_json()['data']
    assert [c['name'] for c in data['cheats']] == ['Infinite Credits', 'Infinite Lives']
    resp = client.put(f'/api/games/{fbneo_game}/cheats', json={'enabled': ['Infinite Lives']},
                      headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 400
