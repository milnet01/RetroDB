"""Pass 59.47 and 59.48: admin file operations must stay inside their roots.

59.47 — `image_types` from the request reached `os.path.join(IMAGE_PATH, t)`
in the resize worker, so `"/etc"` or `"../../.."` pointed an in-place image
re-encode at any directory.

59.48 — two ROM-rename endpoints had no ROM-root jail, and the third's jail
keyed on `config.ROM_PATH`, which is always `""`, so it never ran. A stored
rom_path outside the ROM root made each a rename-anywhere primitive.
"""
import uuid

import pytest

_CSRF = 'tok'
HEADERS = {'X-CSRF-Token': _CSRF}


@pytest.fixture
def roots(tmp_path):
    rom_root = tmp_path / 'roms'
    outside = tmp_path / 'elsewhere'
    rom_root.mkdir()
    outside.mkdir()
    return rom_root, outside


@pytest.fixture
def admin_client(monkeypatch, roots):
    import app as app_module
    rom_root, _ = roots
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
def game_outside_root(roots):
    """A game whose stored rom_path lies outside the ROM root."""
    from services.database import execute
    _, outside = roots
    rom = outside / 'Victim Game (USA).zip'
    rom.write_bytes(b'rom')
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('Pass59 Paths', f'pass59p-{uuid.uuid4().hex}'))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Victim Game', str(rom)))
    yield game_id, rom
    execute("DELETE FROM games WHERE id = ?", (game_id,))
    execute("DELETE FROM systems WHERE id = ?", (sys_id,))


# ---------------------------------------------------------------------------
# 59.47
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad', ['/etc', '../../..', 'boxart/../../x'])
def test_resize_route_refuses_a_path_as_an_image_type(admin_client, bad, monkeypatch):
    from services.jobs import image_resize_job
    started = []
    monkeypatch.setattr(image_resize_job, '_worker', lambda *a, **k: started.append(a))
    resp = admin_client.post('/api/maintenance/image-resize/start',
                             json={'image_types': ['boxart', bad]}, headers=HEADERS)
    assert resp.status_code == 400
    assert not started


def test_resize_job_refuses_a_path_as_an_image_type(tmp_path, monkeypatch):
    # A throwaway absolute path and a stubbed worker: if the guard is missing,
    # a red run must not re-encode anything real.
    from services.jobs.image_resize import ImageResizeJob
    job = ImageResizeJob()
    started = []
    monkeypatch.setattr(job, '_worker', lambda *a, **k: started.append(a))
    result = job.start(image_types=[str(tmp_path)])
    assert result['success'] is False
    # Not merely refused: refused for the type, not for a lock another test holds.
    assert 'Unknown image type' in result['error']
    assert not started


# ---------------------------------------------------------------------------
# 59.48
# ---------------------------------------------------------------------------

def test_reports_rename_rom_is_jailed(admin_client, game_outside_root):
    game_id, rom = game_outside_root
    resp = admin_client.post('/api/reports/rename-rom',
                             json={'game_id': game_id, 'new_name': 'Renamed (USA).zip'},
                             headers=HEADERS)
    assert resp.status_code == 400
    assert rom.exists()


def test_reports_rename_to_scraped_is_jailed(admin_client, game_outside_root):
    game_id, rom = game_outside_root
    resp = admin_client.post('/api/reports/rename-to-scraped',
                             json={'game_id': game_id}, headers=HEADERS)
    assert resp.status_code == 400
    assert rom.exists()


def test_games_media_rename_rom_is_jailed(admin_client, game_outside_root):
    game_id, rom = game_outside_root
    resp = admin_client.post(f'/api/rename-rom/{game_id}',
                             json={'new_filename': 'Renamed (USA).zip'}, headers=HEADERS)
    assert resp.status_code == 400
    assert rom.exists()


def test_rename_inside_the_root_still_works(admin_client, roots):
    """Control: the jail must not block a legitimate rename."""
    from services.database import execute
    rom_root, _ = roots
    rom = rom_root / 'Good Game (USA).zip'
    rom.write_bytes(b'rom')
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('Pass59 Paths OK', f'pass59p-{uuid.uuid4().hex}'))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Good Game', str(rom)))
    try:
        resp = admin_client.post(f'/api/rename-rom/{game_id}',
                                 json={'new_filename': 'Better Game (USA).zip'},
                                 headers=HEADERS)
        assert resp.status_code == 200, resp.get_json()
        assert (rom_root / 'Better Game (USA).zip').exists()
    finally:
        execute("DELETE FROM games WHERE id = ?", (game_id,))
        execute("DELETE FROM systems WHERE id = ?", (sys_id,))
