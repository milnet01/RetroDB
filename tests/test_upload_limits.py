"""Upload size limits as the user meets them (2026-10-20 report).

A video over the request limit on the Edit modal replaced RetroDB with a bare
text page, a video over its own cap was dropped without a word, and a 50 MB
video cap refused ordinary game trailers.
"""
import io

import pytest


@pytest.fixture
def seeded_game():
    from services.database import execute
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('Upload System', 'upload-system'))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Upload Game', '/tmp/upload-game.bin'))
    yield game_id
    execute("DELETE FROM games WHERE id = ?", (game_id,))
    execute("DELETE FROM systems WHERE id = ?", (sys_id,))


def _flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


def test_video_cap_fits_a_game_trailer():
    import config
    assert config.MAX_VIDEO_SIZE >= 500 * 1024 * 1024
    assert config.MAX_UPLOAD_BYTES > config.MAX_VIDEO_SIZE


# The browser sends the CSRF token as a form field, so the CSRF check reads
# the body first and raises the 413 before any view runs.
def test_page_upload_over_limit_flashes_on_the_same_page(admin_test_client, monkeypatch,
                                                         seeded_game):
    import app as app_module
    client, csrf = admin_test_client()
    monkeypatch.setitem(app_module.app.config, 'MAX_CONTENT_LENGTH', 1024)
    rv = client.post(f'/game/{seeded_game}', data={
        '_csrf_token': csrf,
        'action': 'edit_metadata',
        'custom_video': (io.BytesIO(b'x' * 4096), 'trailer.mp4'),
    }, content_type='multipart/form-data')
    assert rv.status_code == 302
    assert rv.headers['Location'].endswith(f'/game/{seeded_game}')
    (category, message), = _flashes(client)
    assert category == 'error'
    assert 'MB' in message


def test_api_upload_over_limit_stays_json_413(admin_test_client, monkeypatch):
    import app as app_module
    client, csrf = admin_test_client()
    monkeypatch.setitem(app_module.app.config, 'MAX_CONTENT_LENGTH', 1024)
    rv = client.post('/api/museum/controller-image/1', data={
        '_csrf_token': csrf,
        'file': (io.BytesIO(b'x' * 4096), 'big.png'),
    }, content_type='multipart/form-data')
    assert rv.status_code == 413
    assert rv.get_json()['success'] is False


def test_refused_video_says_so(admin_test_client, seeded_game):
    client, csrf = admin_test_client()
    # A wrong type is refused before anything is written to static/videos.
    rv = client.post(f'/game/{seeded_game}', data={
        'action': 'edit_metadata',
        'edit_title': 'Upload Game',
        'custom_video': (io.BytesIO(b'not a video'), 'trailer.avi'),
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert rv.status_code == 200
    assert 'Video not saved' in rv.get_data(as_text=True)


def test_no_video_chosen_says_nothing(admin_test_client, seeded_game):
    client, csrf = admin_test_client()
    rv = client.post(f'/game/{seeded_game}', data={
        'action': 'edit_metadata',
        'edit_title': 'Upload Game',
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert rv.status_code == 200
    assert 'Video not saved' not in rv.get_data(as_text=True)
