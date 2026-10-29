"""RPCS3 compatibility status, read from the local RPCS3's list.

RPCS3 keeps https://rpcs3.net/compatibility?api=v1&export as
GuiConfigs/compat_database.dat in its config folder, keyed by title ID with
no dash. Only PS3 games with a local ROM are looked up.
"""
import json

import pytest

from services import rpcs3_compat


@pytest.fixture
def compat_db(tmp_path, monkeypatch):
    path = tmp_path / 'GuiConfigs' / 'compat_database.dat'
    path.parent.mkdir()

    def write(results, return_code=0):
        path.write_text(json.dumps({'return_code': return_code, 'results': results}))
        return path

    monkeypatch.setattr(rpcs3_compat, 'compat_file', lambda: path if path.exists() else None)
    monkeypatch.setitem(rpcs3_compat._db_cache, 'key', None)
    return write


def _game(**kw):
    game = {'system_folder': 'ps3', 'rom_path': '/roms/ps3/Game.PS3', 'disc_serial': 'BLUS-30443'}
    game.update(kw)
    return game


def test_status_by_dashed_or_plain_serial(compat_db):
    compat_db({'BLUS30443': {'status': 'Playable', 'date': '2024-05-01'}})
    assert rpcs3_compat.status_for_serial('BLUS-30443') == {'status': 'playable', 'date': '2024-05-01'}
    assert rpcs3_compat.status_for_serial('blus30443')['status'] == 'playable'


def test_every_rpcs3_status_is_known(compat_db):
    compat_db({f'BLUS3000{i}': {'status': s} for i, s in
               enumerate(['Playable', 'Ingame', 'Intro', 'Loadable', 'Nothing'])})
    got = [rpcs3_compat.status_for_serial(f'BLUS3000{i}')['status'] for i in range(5)]
    assert got == list(rpcs3_compat.STATUSES)


def test_unknown_serial_or_status_gives_none(compat_db):
    compat_db({'BLUS30443': {'status': 'Weird'}})
    assert rpcs3_compat.status_for_serial('BLUS-30443') is None
    assert rpcs3_compat.status_for_serial('BLES-00001') is None
    assert rpcs3_compat.status_for_serial('') is None


def test_server_error_file_gives_nothing(compat_db):
    compat_db({}, return_code=-2)
    assert not rpcs3_compat.available()


def test_no_rpcs3_list_gives_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(rpcs3_compat, 'compat_file', lambda: None)
    assert rpcs3_compat.status_for_serial('BLUS-30443') is None
    assert not rpcs3_compat.available()


def test_list_is_reread_when_rpcs3_rewrites_it(compat_db):
    path = compat_db({'BLUS30443': {'status': 'Intro'}})
    assert rpcs3_compat.status_for_serial('BLUS-30443')['status'] == 'intro'
    path.write_text(json.dumps({'return_code': 0, 'results': {
        'BLUS30443': {'status': 'Playable', 'date': '2025-01-01'}, 'BLES00002': {'status': 'Ingame'}}}))
    assert rpcs3_compat.status_for_serial('BLUS-30443')['status'] == 'playable'


def test_only_local_ps3_games(compat_db):
    compat_db({'BLUS30443': {'status': 'Playable'}})
    assert rpcs3_compat.status_for_game(_game())['status'] == 'playable'
    assert rpcs3_compat.status_for_game(_game(system_folder='ps2')) is None
    assert rpcs3_compat.status_for_game(_game(rom_path='psn_import/BLUS30443')) is None
    assert rpcs3_compat.status_for_game(_game(rom_path='')) is None
    assert rpcs3_compat.status_for_game(_game(disc_serial=None)) is None


def test_compat_file_found_in_rpcs3_config_dir(tmp_path, monkeypatch):
    cfg = tmp_path / 'rpcs3'
    (cfg / 'GuiConfigs').mkdir(parents=True)
    (cfg / 'GuiConfigs' / 'compat_database.dat').write_text('{}')
    monkeypatch.setattr(rpcs3_compat, '_candidate_dirs', lambda: [tmp_path / 'nope', cfg])
    monkeypatch.setitem(rpcs3_compat._path_cache, 'at', 0.0)
    monkeypatch.setattr(rpcs3_compat, '_PATH_TTL', 0.0)
    assert rpcs3_compat.compat_file() == cfg / 'GuiConfigs' / 'compat_database.dat'


def test_windows_rpcs3_keeps_config_beside_the_program(tmp_path):
    from services.emulator_adapters import _rpcs3_dirs
    exe = tmp_path / 'RPCS3' / 'rpcs3.exe'
    dirs = _rpcs3_dirs(exe)
    assert exe.parent in dirs and exe.parent / 'portable' in dirs
