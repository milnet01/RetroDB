"""A scrape only fills: an empty answer from a source never wipes a stored value,
and it never replaces stored media. Runs the path every scrape takes, the
per-source merge in `metadata_merger` and `hybrid_scraper`'s save.
"""

import collections
import sqlite3

import pytest

from scraper import hybrid_scraper, metadata_merger, scrape_thegamesdb
from tests.test_pass59_161_screenshots_own_system import downloads  # noqa: F401  (a fixture)
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (a fixture)

STORED = {
    'publisher': 'Squaresoft', 'developer': 'Square', 'release_date': '1995-03-11',
    'genre': 'RPG', 'rating': '92', 'esrb_rating': 'T', 'pegi_rating': '12',
    'players': 1, 'modes': 'Single-Player', 'description': 'Time-travel classic.',
}

IGDB_MEDIA = {
    'name': 'Curated Game',
    'cover': {'url': '//img/t_thumb/box.jpg'},
    'screenshots': [{'url': '//img/t_thumb/s1.jpg'}, {'url': '//img/t_thumb/s2.jpg'}],
    'platforms': [{'id': 26}],
    'artworks': [{'url': '//img/t_thumb/a1.jpg'}],
}
TGDB_MEDIA = {
    'name': 'Curated Game',
    'boxart_url': 'http://x/box.jpg',
    'screenshot_urls': ['http://x/s1.jpg', 'http://x/s2.jpg'],
    'fanart_urls': ['http://x/f1.jpg'],
}


def _metadata(**stored):
    return collections.defaultdict(lambda: None, stored)


@pytest.mark.parametrize('force', [False, True])
def test_a_source_with_nothing_keeps_every_value(library, force):  # noqa: F811
    library.add_game(boxart='curated_box.webp', **STORED)
    hybrid_scraper.apply_hybrid_metadata(1, 'esde', 'nothing', 'atari2600',
                                         fill_gaps=False, force_overwrite=force)
    row = library.row()
    assert {field: row[field] for field in STORED} == STORED
    assert row['boxart'] == 'curated_box.webp'


@pytest.fixture
def tgdb_downloads(downloads, monkeypatch):  # noqa: F811
    monkeypatch.setattr(scrape_thegamesdb, '_download_tgdb_image',
                        lambda db_id, url, kind, suffix='': f'{db_id}_{kind}{suffix}.webp')


@pytest.mark.parametrize('merge, answer', [
    (metadata_merger.apply_igdb_to_metadata, IGDB_MEDIA),
    (metadata_merger.apply_tgdb_to_metadata, TGDB_MEDIA),
])
def test_stored_media_stays_and_screenshots_are_added(tgdb_downloads, merge, answer):
    metadata = _metadata(title='Curated Game', boxart='curated_box.webp',
                         fanart='curated_fan.webp', screenshots='old_ss.webp')
    merge(metadata, answer, 1, {'filled_fields': []})
    assert metadata['boxart'] == 'curated_box.webp'
    assert metadata['fanart'] == 'curated_fan.webp'
    shots = metadata['screenshots'].split(',')
    assert shots[0] == 'old_ss.webp'
    assert len(shots) == 3


@pytest.mark.parametrize('merge, answer', [
    (metadata_merger.apply_igdb_to_metadata, IGDB_MEDIA),
    (metadata_merger.apply_tgdb_to_metadata, TGDB_MEDIA),
])
def test_empty_media_is_filled(tgdb_downloads, merge, answer):
    metadata = _metadata(title='Blank Game')
    merge(metadata, answer, 1, {'filled_fields': []})
    assert metadata['boxart']
    assert metadata['fanart']
    assert len(metadata['screenshots'].split(',')) == 2


# PASS-59-106 INV-10 — the hybrid scraper fills igdb_id and screenscraper_id
# only when empty; Full Re-scrape is the one mode that may replace them.
@pytest.mark.parametrize("force_overwrite,expected_igdb", [(False, 5), (True, 9)])
def test_source_ids_fill_only(force_overwrite, expected_igdb):
    from scraper import hybrid_scraper
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, igdb_id INTEGER, "
                 "screenscraper_id INTEGER)")
    conn.execute("INSERT INTO games (id, igdb_id) VALUES (1, 5)")
    hybrid_scraper._save_source_ids(
        conn.cursor(), 1, {'igdb': {'id': 9}, 'screenscraper': {'id': '77'}},
        force_overwrite=force_overwrite)
    assert conn.execute("SELECT igdb_id, screenscraper_id FROM games").fetchone() \
        == (expected_igdb, 77)
