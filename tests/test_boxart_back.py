"""PASS-59-225: the back of a game's box — kept from the sources, shown behind
a Back button on the game page. ES-DE's copy is tested in
test_pass59_205_esde_merge.py, fill-only in test_scrape_fill_only.py."""
import collections
import io
import os
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from scraper import metadata_merger


def _metadata(**stored):
    return collections.defaultdict(lambda: None, stored)


# --- ScreenScraper -------------------------------------------------------------

def _ss_saves(monkeypatch, tmp_path, medias, **stored):
    saved = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(metadata_merger, 'download_ss_media',
                        lambda url, path, **k: saved.append((url, path, k.get('image_type'))) or True)
    monkeypatch.setattr(metadata_merger, 'keep_screenshot_if_unique', lambda *a, **k: True)
    monkeypatch.setattr(metadata_merger, 'get_existing_screenshot_hashes', lambda *a, **k: [])
    full = dict(boxart='b', boxart_3d='b3', fanart='f', game_logo='l', video='v', manual='m')
    full.update(stored)
    metadata = _metadata(**full)
    metadata_merger.apply_screenscraper_to_metadata(
        metadata, {'medias': medias}, 4, {'filled_fields': []}, own_region='eu')
    return metadata, saved


def test_screenscraper_back_nearest_the_games_region(monkeypatch, tmp_path):
    medias = [{'type': 'box-2D-back', 'url': 'http://x/us.png', 'region': 'us', 'format': 'png'},
              {'type': 'box-2D-back', 'url': 'http://x/eu.png', 'region': 'eu', 'format': 'png'}]
    metadata, saved = _ss_saves(monkeypatch, tmp_path, medias, boxart_back=None)
    assert [(url, kind) for url, _p, kind in saved] == [('http://x/eu.png', 'boxart_back')]
    assert os.path.dirname(saved[0][1]) == str(tmp_path / 'boxart_back')
    assert metadata['boxart_back'] == os.path.basename(saved[0][1])
    assert metadata['boxart_back'].startswith('4_ss_back')


def test_screenscraper_keeps_a_stored_back(monkeypatch, tmp_path):
    medias = [{'type': 'box-2D-back', 'url': 'http://x/eu.png', 'region': 'eu', 'format': 'png'}]
    metadata, saved = _ss_saves(monkeypatch, tmp_path, medias, boxart_back='mine.webp')
    assert saved == []
    assert metadata['boxart_back'] == 'mine.webp'


def test_a_record_with_no_back_slot_downloads_none(monkeypatch, tmp_path):
    """The wishlist's record has no boxart_back key, so no back is fetched for it."""
    from services.wishlist_scraper import _empty_metadata
    saved = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr('scraper.scrape_thegamesdb._download_tgdb_image',
                        lambda gid, url, kind, **k: saved.append(kind) or 'x.webp')
    metadata = _empty_metadata()
    metadata_merger.apply_tgdb_to_metadata(
        metadata, {'boxart_back_url': 'http://x/back.jpg'}, 'w1', {'filled_fields': []})
    assert 'boxart_back' not in saved and 'boxart_back' not in metadata


# --- TheGamesDB ----------------------------------------------------------------

def _tgdb_details(monkeypatch, sides):
    """fetch_game_details over a canned reply whose boxart has these sides.
    No request leaves the machine."""
    from scraper import scrape_thegamesdb as tgdb
    reply = MagicMock(status_code=200)
    reply.json.return_value = {
        'code': 200,
        'data': {'games': [{'id': 7, 'game_title': 'Some Game'}]},
        'include': {'boxart': {
            'base_url': {'original': 'http://cdn/'},
            'data': {'7': [{'side': side, 'filename': f'{side}.jpg'} for side in sides]},
        }},
    }
    monkeypatch.setattr(tgdb, '_tgdb_request', lambda *a, **k: reply)
    monkeypatch.setattr(tgdb, '_fetch_game_images', lambda gid: ([], [], []))
    monkeypatch.setattr(tgdb, '_resolve_names', lambda *a: '')
    monkeypatch.setattr(tgdb, '_resolve_genre_names', lambda *a: [])
    return tgdb.fetch_game_details(7)


@pytest.mark.parametrize('sides, front, back', [
    (['back', 'front'], 'http://cdn/front.jpg', 'http://cdn/back.jpg'),
    (['front'], 'http://cdn/front.jpg', None),
    (['back'], None, 'http://cdn/back.jpg'),          # a back never stands in for the front
    (['back', 'spine'], 'http://cdn/spine.jpg', 'http://cdn/back.jpg'),
])
def test_tgdb_front_and_back(monkeypatch, sides, front, back):
    details = _tgdb_details(monkeypatch, sides)
    assert details['boxart_url'] == front
    assert details['boxart_back_url'] == back


def test_tgdb_back_is_downloaded(monkeypatch):
    saved = []
    monkeypatch.setattr('scraper.scrape_thegamesdb._download_tgdb_image',
                        lambda gid, url, kind, suffix='': saved.append((url, kind, suffix)) or f'{gid}_tgdb{suffix}.webp')
    metadata = _metadata(boxart='b', fanart='f', game_logo='l', boxart_back=None)
    metadata_merger.apply_tgdb_to_metadata(
        metadata, {'boxart_back_url': 'http://cdn/back.jpg'}, 3, {'filled_fields': []})
    assert ('http://cdn/back.jpg', 'boxart_back', '_back') in saved
    assert metadata['boxart_back'] == '3_tgdb_back.webp'


# --- Fill Missing does not count a missing back ---------------------------------

def test_fill_missing_does_not_revisit_for_a_back():
    """User, 2026-11-03: many games have no back anywhere, so a missing one
    alone would send them back to the sources on every run."""
    from services.jobs.bulk_scrape import FILL_MISSING_FIELDS
    assert 'boxart_back' not in FILL_MISSING_FIELDS


# --- The game page and the Edit window ------------------------------------------

@pytest.fixture
def back_game():
    import config
    from services.database import execute, query
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)", ('Back System', 'back-system'))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Back Game', '/tmp/back-game.bin'))
    folder = os.path.join(config.IMAGE_PATH, 'boxart_back')
    os.makedirs(folder, exist_ok=True)

    def row():
        return query("SELECT * FROM games WHERE id = ?", (game_id,), one=True)

    def set_media(**fields):
        for field, value in fields.items():
            execute(f"UPDATE games SET {field} = ? WHERE id = ?", (value, game_id))

    yield game_id, folder, row, set_media
    execute("DELETE FROM games WHERE id = ?", (game_id,))
    execute("DELETE FROM systems WHERE id = ?", (sys_id,))


def _page(client, game_id):
    with patch('scraper.retroachievements.check_retroachievements', return_value=None):
        return client.get(f'/game/{game_id}').get_data(as_text=True)


def test_game_page_back_button(admin_test_client, back_game):
    game_id, _folder, _row, set_media = back_game
    client, _ = admin_test_client()

    set_media(boxart='1_box.webp', boxart_back='1_ss_back.webp')
    html = _page(client, game_id)
    assert 'id="boxartBackBtn"' in html
    assert 'images/boxart_back/1_ss_back.webp' in html
    # The back zooms as a plain picture, never the Slipcase box.
    assert '''data-args='["$this.dataset.zoomUrl", true]\'''' in html

    set_media(boxart_back=None)
    html = _page(client, game_id)
    assert 'boxartBackBtn"' not in html
    assert 'boxart_back/' not in html

    # A back with no front shows nothing: the box slot keeps its placeholder.
    set_media(boxart=None, boxart_back='1_ss_back.webp')
    html = _page(client, game_id)
    assert 'boxartBackBtn"' not in html


def test_edit_window_back(admin_test_client, back_game):
    game_id, folder, row, _set_media = back_game
    client, csrf = admin_test_client()
    picture = io.BytesIO()
    Image.new('RGB', (30, 40), (255, 0, 0)).save(picture, 'PNG')
    picture.seek(0)

    with patch('services.image_utils.standardize_downloaded_image'):
        rv = client.post(f'/game/{game_id}', data={
            'action': 'edit_metadata', 'edit_title': 'Back Game',
            'custom_boxart_back': (picture, 'mine.png'),
        }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert rv.status_code == 200
    saved = row()['boxart_back']
    assert saved and saved.startswith(f'{game_id}_custom_back')
    assert os.path.exists(os.path.join(folder, saved))

    rv = client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Back Game', 'remove_boxart_back': '1',
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert rv.status_code == 200
    assert row()['boxart_back'] is None
    assert not os.path.exists(os.path.join(folder, saved))


def test_box_back_kept_apart_from_slipcase_faces(admin_test_client, back_game):
    """Removing a back leaves the Slipcase record alone (PASS-59-142's owner)."""
    game_id, _folder, row, set_media = back_game
    client, csrf = admin_test_client()
    set_media(boxart_back='x_back.webp', box_faces='{"faces": {}}')
    client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Back Game', 'remove_boxart_back': '1',
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert row()['boxart_back'] is None
    assert row()['box_faces'] == '{"faces": {}}'
