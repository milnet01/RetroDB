"""PASS-59-286: a rename from the ROM Reports page must not act on a stale scan.

The page keeps its scan in the browser with no expiry. A batch rename sent
suggestions from that scan, and the server renamed whatever file the game now
has, so a file renamed since the scan was overwritten with an old suggestion.
The page now sends the file name it saw (`old_name`); the server refuses when
the game's file has a different name.
"""
import uuid

import pytest

from tests._util import delete_rows

_CSRF = 'tok'
HEADERS = {'X-CSRF-Token': _CSRF}


@pytest.fixture
def rom_root(tmp_path):
    root = tmp_path / 'roms'
    root.mkdir()
    return root


@pytest.fixture
def admin_client(monkeypatch, rom_root):
    import app as app_module
    user = {'id': 1, 'username': 'admin', 'role': 'admin'}
    monkeypatch.setattr('app.get_current_user', lambda: user)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': str(rom_root)})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF
    return client


@pytest.fixture
def game(rom_root):
    from services.database import execute
    folder = f'pass59-286-{uuid.uuid4().hex}'
    sys_dir = rom_root / folder
    sys_dir.mkdir()
    (sys_dir / 'systeminfo.txt').write_text('Supported file extensions:\n.zip\n')
    rom = sys_dir / 'Newer Name (USA).zip'
    rom.write_bytes(b'rom')
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('Pass59 286', folder))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Newer Name', str(rom)))
    yield game_id, rom
    delete_rows(('games', game_id), ('systems', sys_id))


def _rom_path(game_id):
    from services.database import query
    return query("SELECT rom_path FROM games WHERE id = ?", (game_id,), one=True)['rom_path']


def test_rename_refuses_when_the_file_changed_since_the_scan(admin_client, game):
    game_id, rom = game
    resp = admin_client.post('/api/reports/rename-rom',
                             json={'game_id': game_id,
                                   'old_name': 'Old Name (USA).zip',
                                   'new_name': 'Old Suggestion (USA).zip'},
                             headers=HEADERS)
    assert resp.status_code == 409
    assert resp.get_json()['success'] is False
    assert rom.exists()
    assert not (rom.parent / 'Old Suggestion (USA).zip').exists()
    assert _rom_path(game_id) == str(rom)


def test_rename_goes_ahead_when_the_file_is_as_scanned(admin_client, game):
    game_id, rom = game
    resp = admin_client.post('/api/reports/rename-rom',
                             json={'game_id': game_id,
                                   'old_name': rom.name,
                                   'new_name': 'Renamed (USA).zip'},
                             headers=HEADERS)
    assert resp.status_code == 200, resp.get_json()
    new = rom.parent / 'Renamed (USA).zip'
    assert new.exists() and not rom.exists()
    assert _rom_path(game_id) == str(new)
