"""PASS-59-175: the Edit form's picture work.

A picture ticked for removal is deleted only once the save has gone through,
and a small uploaded picture is left for the background upscaler instead of
holding up the save.
"""
import io
import os
from unittest.mock import patch

import pytest
from PIL import Image


@pytest.fixture
def edit_game():
    import config
    from services.database import execute, query
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)", ('Edit Media System', 'edit-media-system'))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Edit Media Game', '/tmp/edit-media-game.bin'))
    folder = os.path.join(config.IMAGE_PATH, 'boxart')
    os.makedirs(folder, exist_ok=True)

    def row():
        return query("SELECT * FROM games WHERE id = ?", (game_id,), one=True)

    yield game_id, folder, row
    for f in os.listdir(folder):
        if f.startswith(f'{game_id}_'):
            os.remove(os.path.join(folder, f))
    execute("DELETE FROM games WHERE id = ?", (game_id,))
    execute("DELETE FROM systems WHERE id = ?", (sys_id,))


def _post(client, csrf, game_id, **fields):
    return client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Edit Media Game', **fields,
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')


def _stored_boxart(game_id, folder):
    from services.database import execute
    name = f'{game_id}_stored.webp'
    path = os.path.join(folder, name)
    Image.new('RGB', (10, 10)).save(path, 'WEBP')
    execute("UPDATE games SET boxart = ? WHERE id = ?", (name, game_id))
    return name, path


def test_removed_boxart_kept_when_the_save_fails(admin_test_client, edit_game):
    import routes.games as games_routes
    game_id, folder, row = edit_game
    client, csrf = admin_test_client()
    name, path = _stored_boxart(game_id, folder)
    real_execute = games_routes.execute

    def failing_update(sql, *args, **kwargs):
        if 'boxart = NULLIF' in sql:
            raise RuntimeError('database is locked')
        return real_execute(sql, *args, **kwargs)

    with patch.object(games_routes, 'execute', failing_update):
        rv = _post(client, csrf, game_id, remove_boxart='1')
    assert rv.status_code == 200
    assert row()['boxart'] == name
    assert os.path.exists(path), 'the picture went although the save failed'


def test_removed_boxart_goes_after_a_save(admin_test_client, edit_game):
    game_id, folder, row = edit_game
    client, csrf = admin_test_client()
    _name, path = _stored_boxart(game_id, folder)

    rv = _post(client, csrf, game_id, remove_boxart='1')
    assert rv.status_code == 200
    assert row()['boxart'] is None
    assert not os.path.exists(path)


def test_small_upload_is_upscaled_later(admin_test_client, edit_game):
    import services.upscale_queue as upscale_queue
    game_id, _folder, row = edit_game
    client, csrf = admin_test_client()
    picture = io.BytesIO()
    Image.new('RGB', (30, 40), (255, 0, 0)).save(picture, 'PNG')
    picture.seek(0)
    queued = []

    def fake_enqueue(gid):
        # The worker reads the game's row, so it must already name the upload.
        queued.append((gid, row()['boxart']))

    with patch('services.image_utils._upscale_image') as upscale, \
            patch.object(upscale_queue, 'enqueue', fake_enqueue):
        rv = _post(client, csrf, game_id, custom_boxart=(picture, 'mine.png'))
    assert rv.status_code == 200
    saved = row()['boxart']
    assert saved and saved.startswith(f'{game_id}_custom')
    upscale.assert_not_called()
    assert queued == [(game_id, saved)]


def test_save_with_no_upload_queues_nothing(admin_test_client, edit_game):
    import services.upscale_queue as upscale_queue
    game_id, _folder, _row = edit_game
    client, csrf = admin_test_client()
    with patch.object(upscale_queue, 'enqueue') as enqueue:
        rv = _post(client, csrf, game_id)
    assert rv.status_code == 200
    enqueue.assert_not_called()
