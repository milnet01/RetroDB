"""PASS-59-224: game logos — kept from the sources, shown on the game page."""
import collections
import io
import os

import pytest
from PIL import Image

from scraper import metadata_merger


def _metadata(**stored):
    return collections.defaultdict(lambda: None, stored)


# --- INV-3: IGDB's logo and fanart picks -----------------------------------

def _igdb_downloads(monkeypatch, tmp_path, types):
    """URL -> image type for each picture an IGDB answer with `types` saves."""
    saved = {}
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))

    def fake(url, path, image_type, **kwargs):
        saved[url] = (image_type, os.path.basename(path))
        return True

    monkeypatch.setattr(metadata_merger, '_download_and_finalize', fake)
    answer = {'artworks': [{'url': f'//images.igdb.com/t_thumb/a{t}.jpg', 'artwork_type': t}
                           for t in types]}
    metadata = _metadata(game_logo=None)
    metadata_merger.apply_igdb_to_metadata(metadata, answer, 1, {'filled_fields': []})
    return metadata, saved


@pytest.mark.parametrize('types, logo, fanart', [
    ([7, 1], 7, 1),      # first artwork a logo: fanart still takes the second
    ([6, 5], 5, None),   # black logo skipped; white one used; no fanart
    ([6], None, None),   # only a black logo: no logo at all
    ([5, 7], 7, None),   # colour beats white
])
def test_igdb_picks(monkeypatch, tmp_path, types, logo, fanart):
    metadata, saved = _igdb_downloads(monkeypatch, tmp_path, types)
    by_type = {kind: url for url, (kind, _name) in saved.items()}
    if logo is None:
        assert 'game_logo' not in by_type and not metadata['game_logo']
    else:
        assert by_type['game_logo'] == f'https://images.igdb.com/t_original/a{logo}.png'
        assert metadata['game_logo'] == '1_igdb_logo' + os.path.splitext(metadata['game_logo'])[1]
    if fanart is None:
        assert 'fanart' not in by_type
    else:
        assert by_type['fanart'] == f'https://images.igdb.com/t_1080p/a{fanart}.jpg'


def test_igdb_artwork_with_no_type_is_still_fanart(monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(metadata_merger, '_download_and_finalize',
                        lambda url, path, image_type, **k: saved.setdefault(image_type, url) or True)
    metadata_merger.apply_igdb_to_metadata(
        _metadata(game_logo=None), {'artworks': [{'url': '//x/t_thumb/a.jpg'}]}, 1,
        {'filled_fields': []})
    assert saved == {'fanart': 'https://x/t_1080p/a.jpg'}


# --- The other sources' logos ------------------------------------------------

def test_steam_logo_address(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(metadata_merger, '_download_and_finalize',
                        lambda url, path, kind, **k: saved.append((url, path, kind)) or kind == 'game_logo')
    metadata = _metadata(game_logo=None, boxart='b', fanart='f')
    metadata_merger.apply_steam_to_metadata(metadata, {}, 9050, 3, {'filled_fields': []})
    url, path, kind = saved[0]
    assert url.endswith('/9050/logo.png') and kind == 'game_logo'
    assert os.path.dirname(path) == str(tmp_path / 'game_logos')
    assert metadata['game_logo'] == os.path.basename(path)


def test_screenscraper_takes_wheel_hd_before_wheel(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(metadata_merger, 'download_ss_media',
                        lambda url, path, **k: saved.append((url, k.get('image_type'))) or True)
    monkeypatch.setattr(metadata_merger, 'keep_screenshot_if_unique', lambda *a, **k: True)
    monkeypatch.setattr(metadata_merger, 'get_existing_screenshot_hashes', lambda *a, **k: [])
    medias = [{'type': 'wheel', 'url': 'http://x/w.png', 'region': 'wor', 'format': 'png'},
              {'type': 'wheel-hd', 'url': 'http://x/whd.png', 'region': 'wor', 'format': 'png'}]
    metadata = _metadata(game_logo=None, boxart='b', boxart_3d='b3', fanart='f', video='v', manual='m')
    metadata_merger.apply_screenscraper_to_metadata(metadata, {'medias': medias}, 4, {'filled_fields': []})
    assert ('http://x/whd.png', 'game_logo') in saved
    assert ('http://x/w.png', 'game_logo') not in saved
    assert metadata['game_logo'].startswith('4_ss_logo')


def test_a_record_with_no_logo_slot_downloads_none(monkeypatch, tmp_path):
    """The wishlist's record has no game_logo key, so no logo is fetched for it."""
    from services.wishlist_scraper import _empty_metadata
    kinds = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(metadata_merger, '_download_and_finalize',
                        lambda url, path, kind, **k: kinds.append(kind) or True)
    metadata = _empty_metadata()
    answer = {'artworks': [{'url': '//x/t_thumb/a.jpg', 'artwork_type': 7}]}
    metadata_merger.apply_igdb_to_metadata(metadata, answer, 'w1', {'filled_fields': []})
    assert 'game_logo' not in kinds and 'game_logo' not in metadata


# --- INV-2: a logo keeps its clear background and its size --------------------

@pytest.mark.parametrize('fmt, ext', [('webp', '.webp'), ('jpeg', '.png')])
def test_logo_keeps_alpha_and_size(monkeypatch, tmp_path, fmt, ext):
    import config
    from services import image_utils
    monkeypatch.setattr(config, 'IMAGE_FORMAT', fmt)
    resized = []
    real = image_utils.standardize_downloaded_image
    # Recorded rather than run for real past the logo check: the GPU upscaler
    # is never loaded (standardize_image is what would load it).
    monkeypatch.setattr(image_utils, 'standardize_image', lambda path, kind, *a, **k: resized.append(kind))
    monkeypatch.setattr(image_utils, 'standardize_downloaded_image',
                        lambda path, kind, *a, **k: real(path, kind, *a, **k))

    logo = Image.new('P', (40, 20), 1)
    logo.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    logo.putpixel((0, 0), 0)
    logo.info['transparency'] = 0
    name = 'logo' + image_utils.preferred_image_extension('game_logo', '.png')
    assert name.endswith(ext)
    path = tmp_path / name
    logo.save(tmp_path / 'src.png')
    os.replace(tmp_path / 'src.png', path) if ext == '.png' else \
        Image.open(tmp_path / 'src.png').save(path, 'PNG')  # wrong bytes: finalize re-encodes

    image_utils.finalize_downloaded_image(str(path), 'game_logo')

    with Image.open(path) as out:
        assert out.size == (40, 20)
        assert out.convert('RGBA').getpixel((0, 0))[3] == 0
        assert out.convert('RGBA').getpixel((5, 5))[3] == 255
    assert resized == []
    assert not os.path.exists(tmp_path / f'logo-sm{ext}')


# --- INV-6: Fill Missing visits a game whose only gap is its logo --------------

def test_fill_missing_visits_logo_gap():
    from services.jobs.bulk_scrape import FILL_MISSING_FIELDS, missing_fields
    game = {field: 'x' for field in FILL_MISSING_FIELDS}
    assert missing_fields(game) == []
    game['game_logo'] = None
    assert missing_fields(game) == ['game_logo']


# --- INV-7 and INV-8: the game page and the Edit window -------------------------

@pytest.fixture
def logo_game():
    import config
    from services.database import execute, query
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)", ('Logo System', 'logo-system'))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Logo Game', '/tmp/logo-game.bin'))
    folder = os.path.join(config.IMAGE_PATH, 'game_logos')
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
    from unittest.mock import patch
    with patch('scraper.retroachievements.check_retroachievements', return_value=None):
        return client.get(f'/game/{game_id}').get_data(as_text=True)


def test_game_page_logo(admin_test_client, logo_game):
    game_id, _folder, _row, set_media = logo_game
    client, _ = admin_test_client()

    set_media(game_logo='1_ss_logo.webp', boxart='1_box.webp')
    html = _page(client, game_id)
    assert 'class="game-page-logo"' in html
    assert 'images/game_logos/1_ss_logo.webp"\n             alt=""' in html
    assert '<h1 class="game-page-title">Logo Game</h1>' in html
    assert html.index('class="game-page-logo"') < html.index('<h1 class="game-page-title"')
    assert 'game-boxart-logo-image' not in html

    set_media(boxart=None)
    html = _page(client, game_id)
    assert 'game-boxart-logo-image' in html
    assert '<h1 class="game-page-title">Logo Game</h1>' in html

    set_media(game_logo=None)
    html = _page(client, game_id)
    assert 'game_logos/' not in html
    assert 'boxart-empty-icon">🎮' in html


def test_edit_window_logo(admin_test_client, logo_game):
    game_id, folder, row, set_media = logo_game
    client, csrf = admin_test_client()
    picture = io.BytesIO()
    Image.new('RGBA', (30, 10), (255, 0, 0, 0)).save(picture, 'PNG')
    picture.seek(0)

    rv = client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Logo Game',
        'custom_game_logo': (picture, 'mine.png'),
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert rv.status_code == 200
    saved = row()['game_logo']
    assert saved and saved.startswith(f'{game_id}_custom_logo')
    assert os.path.exists(os.path.join(folder, saved))

    rv = client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Logo Game', 'remove_game_logo': '1',
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert rv.status_code == 200
    assert row()['game_logo'] is None
    assert not os.path.exists(os.path.join(folder, saved))


def test_an_uploaded_logo_replaces_the_old_file(admin_test_client, logo_game):
    game_id, folder, row, set_media = logo_game
    client, csrf = admin_test_client()
    old = os.path.join(folder, f'{game_id}_ss_logo.png')
    Image.new('RGBA', (8, 8)).save(old)
    set_media(game_logo=os.path.basename(old))
    picture = io.BytesIO()
    Image.new('RGBA', (30, 10), (0, 255, 0, 0)).save(picture, 'PNG')
    picture.seek(0)

    client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Logo Game',
        'custom_game_logo': (picture, 'mine.png'),
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')
    assert row()['game_logo'].startswith(f'{game_id}_custom_logo')
    assert not os.path.exists(old)
