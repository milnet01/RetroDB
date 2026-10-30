"""PASS-59-155 INV-10 — the cheats API accepts only a list that is one of
the game's candidates. docs/specs/PASS-59-155-cheats.md §4.7.
"""
import pytest

from services import cheats
from services.database import execute

CHT = 'cheats = 1\n\ncheat0_desc = "Infinite Lives"\ncheat0_code = "1"\ncheat0_enable = false\n'


@pytest.fixture
def player_game(tmp_path, monkeypatch, setup_complete):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    monkeypatch.setattr('services.cheats.cheats_folder', lambda folder: 'Sony - PlayStation')
    folder = cheats.store_dir() / 'packs' / 'retroarch' / 'Sony - PlayStation'
    folder.mkdir(parents=True)
    (folder / 'Crash (USA).cht').write_text(CHT)
    rom = tmp_path / 'Crash (USA).chd'
    rom.write_bytes(b'x')
    sid = execute("INSERT INTO systems (name, folder) VALUES ('CheatsProbe', 'cheatsprobe')")
    eid = execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch, "
                  "is_player, enabled) VALUES ('CheatsProbe Player', 'retrodb-player', 'x', 0, 1, 1)")
    execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) VALUES (?, ?, 1)",
            (sid, eid))
    gid = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, 'Crash', ?)",
                  (sid, str(rom)))
    yield gid
    execute("DELETE FROM games WHERE id = ?", (gid,))
    execute("DELETE FROM system_emulators WHERE emulator_id = ?", (eid,))
    execute("DELETE FROM emulators WHERE id = ?", (eid,))
    execute("DELETE FROM systems WHERE id = ?", (sid,))


def _put(client, csrf, gid, body):
    return client.put(f'/api/games/{gid}/cheats', json=body, headers={'X-CSRF-Token': csrf})


def test_get_lists_the_candidate_and_its_cheats(player_game, admin_test_client):
    client, _csrf = admin_test_client()
    data = client.get(f'/api/games/{player_game}/cheats').get_json()['data']
    assert data['emulator'] == 'player'
    assert data['source'] == 'packs/retroarch/Sony - PlayStation/Crash (USA).cht'
    assert data['cheats'] == [{'name': 'Infinite Lives', 'enabled': False, 'locked': False}]


@pytest.mark.parametrize('source', ['../../config.py', '/etc/passwd',
                                    'packs/retroarch/Sony - PlayStation/Other.cht'])
def test_inv10_a_source_not_among_the_candidates_is_refused(player_game, admin_test_client, source):
    client, csrf = admin_test_client()
    resp = _put(client, csrf, player_game, {'enabled': [], 'source': source})
    assert resp.status_code == 400


def test_put_switches_a_cheat_on(player_game, admin_test_client):
    client, csrf = admin_test_client()
    resp = _put(client, csrf, player_game, {'enabled': ['Infinite Lives']})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()['data']['cheats'][0]['enabled'] is True
    from services import player
    assert 'cheat0_enable = "true"' in player._game_file(player_game, 'cht').read_text()


def test_unknown_pack_is_refused(admin_test_client, setup_complete):
    client, csrf = admin_test_client()
    resp = client.post('/api/cheats/packs/nope', headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 404


def test_pass_59_197_game_page_names_the_emulator(player_game, admin_test_client):
    client, _csrf = admin_test_client()
    page = client.get(f'/game/{player_game}').get_data(as_text=True)
    assert 'Launches in: CheatsProbe Player' in page


def test_pass_59_197_an_unsupported_emulator_gets_a_reason(player_game, admin_test_client):
    execute("UPDATE emulators SET is_player = 0, binary_name = 'mednafen' "
            "WHERE name = 'CheatsProbe Player'")
    client, _csrf = admin_test_client()
    data = client.get(f'/api/games/{player_game}/cheats').get_json()['data']
    assert data['emulator'] is None
    assert data['reason'] == 'Cheats work in the player, DuckStation and PCSX2.'
