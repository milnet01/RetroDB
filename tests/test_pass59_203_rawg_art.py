"""PASS-59-203: RAWG has no covers. Its background picture is fanart, the covers
older scrapes saved can be cleared, and RetroDB links back to RAWG.

No test here reaches RAWG; the replies are canned.
"""
import os
import sqlite3

import pytest

import config
from scraper import metadata_merger, scrape_rawg
from services import media_cleanup, migrations


def _details(monkeypatch, **images):
    monkeypatch.setattr(
        scrape_rawg, '_make_request',
        lambda endpoint, params=None: {'id': 7, 'name': 'Game', **images}
        if endpoint == 'games/7' else None,
    )
    return scrape_rawg.get_game_details(7)


def test_details_offer_no_cover(monkeypatch):
    details = _details(monkeypatch, background_image='https://r/bg.jpg')
    assert not details.get('boxart_url')


def test_background_picture_is_the_fanart(monkeypatch):
    details = _details(monkeypatch, background_image='https://r/bg.jpg',
                       background_image_additional='https://r/more.jpg')
    assert details['fanart_url'] == 'https://r/bg.jpg'


def test_additional_picture_is_the_fanart_when_there_is_no_background(monkeypatch):
    details = _details(monkeypatch, background_image_additional='https://r/more.jpg')
    assert details['fanart_url'] == 'https://r/more.jpg'


def test_merge_never_fills_a_cover_from_rawg(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(metadata_merger, '_download_and_finalize',
                        lambda url, path, kind, **k: saved.append(kind) or True)
    keys = ('title', 'description', 'release_date', 'developer', 'publisher', 'genre',
            'esrb_rating', 'players', 'modes', 'critic_score', 'user_score',
            'boxart', 'fanart', 'screenshots')
    metadata = {k: '' for k in keys}

    metadata_merger.apply_rawg_to_metadata(
        metadata,
        {'boxart_url': 'https://r/bg.jpg', 'fanart_url': 'https://r/bg.jpg'},
        1, {'filled_fields': []},
    )

    assert metadata['boxart'] == ''
    assert metadata['fanart'].startswith('1_rawg_fanart')
    assert saved == ['fanart']


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Two RAWG covers (one on the wishlist), and covers it must not touch."""
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Mega Drive', 'megadrive')")
    games = [
        (1, '1_rawg_boxart.webp', '1_rawg_fanart.webp'),
        (2, '2_ss_boxart.webp', None),
        (3, '3_custom_rawg_boxart_mine.webp', None),
        (4, None, None),
    ]
    for game_id, boxart, fanart in games:
        conn.execute("INSERT INTO games (id, system_id, title, rom_path, boxart, fanart) "
                     "VALUES (?, 1, ?, ?, ?, ?)",
                     (game_id, f'Game {game_id}', f'/roms/{game_id}.bin', boxart, fanart))
    conn.execute("INSERT INTO wishlist (id, title, boxart) VALUES (4, 'Wanted', 'w4_rawg_boxart.jpg')")
    conn.execute("INSERT INTO wishlist (id, title, boxart) VALUES (5, 'Other', 'w5_igdb_boxart.jpg')")
    conn.commit()
    conn.close()

    images = tmp_path / 'images'
    (images / 'boxart').mkdir(parents=True)
    (images / 'fanart').mkdir()
    for name in ('1_rawg_boxart.webp', '1_rawg_boxart-md.webp', '1_rawg_boxart-sm.webp',
                 '2_ss_boxart.webp', '3_custom_rawg_boxart_mine.webp',
                 'w4_rawg_boxart.jpg', 'w5_igdb_boxart.jpg'):
        (images / 'boxart' / name).write_bytes(b'x')
    (images / 'fanart' / '1_rawg_fanart.webp').write_bytes(b'x')

    monkeypatch.setattr(config, 'DB_PATH', path)
    monkeypatch.setattr(config, 'IMAGE_PATH', str(images))
    monkeypatch.setattr(config, 'STATIC_PATH', str(tmp_path))

    def value(table, row_id, column='boxart'):
        c = sqlite3.connect(path)
        found = c.execute(f"SELECT {column} FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]
        c.close()
        return found

    return value, images


def test_count_is_only_the_rawg_covers(library):
    assert media_cleanup.count_rawg_covers() == 2


def test_clear_empties_only_the_rawg_covers(library):
    value, _images = library

    assert media_cleanup.clear_rawg_covers() == 2

    assert not value('games', 1)
    assert not value('wishlist', 4)
    assert value('games', 2) == '2_ss_boxart.webp'
    assert value('games', 3) == '3_custom_rawg_boxart_mine.webp'
    assert value('wishlist', 5) == 'w5_igdb_boxart.jpg'
    assert media_cleanup.count_rawg_covers() == 0


def test_clear_deletes_the_cover_files_and_nothing_else(library):
    _value, images = library

    media_cleanup.clear_rawg_covers()

    assert sorted(os.listdir(images / 'boxart')) == [
        '2_ss_boxart.webp', '3_custom_rawg_boxart_mine.webp', 'w5_igdb_boxart.jpg',
    ]
    assert os.listdir(images / 'fanart') == ['1_rawg_fanart.webp']


def test_clear_keeps_the_fanart_value(library):
    value, _images = library
    media_cleanup.clear_rawg_covers()
    assert value('games', 1, 'fanart') == '1_rawg_fanart.webp'


def test_routes_report_the_count_then_clear(library, admin_test_client):
    client, csrf = admin_test_client()

    assert client.get('/api/maintenance/rawg-covers/preview').get_json()['count'] == 2

    reply = client.post('/api/maintenance/rawg-covers/clear', json={},
                        headers={'X-CSRF-Token': csrf})
    assert reply.get_json()['cleared'] == 2
    assert client.get('/api/maintenance/rawg-covers/preview').get_json()['count'] == 0


def test_every_page_links_back_to_rawg(admin_test_client):
    client, _csrf = admin_test_client()
    page = client.get('/help').get_data(as_text=True)
    assert 'href="https://rawg.io/"' in page
    assert 'class="sidebar-credit"' in page
