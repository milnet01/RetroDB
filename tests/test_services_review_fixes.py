# =============================================================================
# Regression pins for the services/ review fixes (2026-10-27).
# =============================================================================

import os
import sqlite3

import pytest


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / 'roms.db'
    import config as _config
    monkeypatch.setattr(_config, 'DB_PATH', str(path))
    return path


# -----------------------------------------------------------------------------
# clear_scraped_data reset the titles on a connection it never committed
# -----------------------------------------------------------------------------
def test_clear_scraped_data_commits_title_reset(db_path):
    from services.game_cleanup import _SCRAPED_FIELDS
    cols = ', '.join(f"{c} TEXT" for c in dict.fromkeys(
        tuple(_SCRAPED_FIELDS) + ('scrape_history',)))
    conn = sqlite3.connect(str(db_path))
    with conn:
        conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, folder TEXT)")
        conn.execute(f"""CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT,
            sort_title TEXT, rom_path TEXT, system_id INTEGER,
            scraped INTEGER DEFAULT 0, title_locked INTEGER DEFAULT 0, {cols})""")
        conn.execute("INSERT INTO systems VALUES (1, 'snes')")
        conn.execute("INSERT INTO games (id, title, rom_path, system_id, scraped) "
                     "VALUES (1, 'Scraped Name', '/roms/snes/Real Name (USA).sfc', 1, 1)")
    conn.close()

    from services import game_cleanup
    game_cleanup.clear_scraped_data()

    conn = sqlite3.connect(str(db_path))
    try:
        (title,) = conn.execute("SELECT title FROM games WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert title == 'Real Name'


# -----------------------------------------------------------------------------
# NULL and 'not_started' completion groups overwrote each other's count
# -----------------------------------------------------------------------------
def test_analytics_counts_null_and_not_started_together(db_path):
    conn = sqlite3.connect(str(db_path))
    with conn:
        conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, file_size INTEGER, "
                     "completion_status TEXT)")
        conn.executemany("INSERT INTO games (completion_status) VALUES (?)",
                         [(None,), (None,), ('not_started',), ('completed',)])
    conn.close()

    from services.analytics import _get_analytics_stats
    total, _stats, completion = _get_analytics_stats()
    assert total == 4
    assert completion[0] == 3   # two NULL + one not_started
    assert completion[3] == 1


# -----------------------------------------------------------------------------
# query() outside an app context closes the connection it opened
# -----------------------------------------------------------------------------
def test_query_outside_app_context_closes_its_connection(db_path, monkeypatch):
    import services.database as database
    opened = []
    real_get_db = database.get_db

    def tracking_get_db():
        conn = real_get_db()
        opened.append(conn)
        return conn

    monkeypatch.setattr(database, 'get_db', tracking_get_db)
    assert database.query("SELECT 1 AS one", one=True) == {'one': 1}
    database.execute("CREATE TABLE t (a)")
    assert len(opened) == 2
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


# -----------------------------------------------------------------------------
# A palette / alpha image could not be saved to a .jpg path
# -----------------------------------------------------------------------------
@pytest.mark.parametrize('mode', ['P', 'LA', 'PA'])
def test_save_image_converts_non_jpeg_modes(tmp_path, mode):
    from PIL import Image
    from services.image_utils import _save_image
    path = tmp_path / 'x.jpg'
    _save_image(Image.new(mode, (8, 8)), str(path))
    assert path.exists()
    with Image.open(path) as im:
        assert im.format == 'JPEG'


# -----------------------------------------------------------------------------
# The orphan scan still spares a file referenced by a path-form DB value
# -----------------------------------------------------------------------------
def test_orphan_scan_spares_basename_reference(tmp_path, monkeypatch):
    import config as _config
    image_path = tmp_path / 'images'
    boxart = image_path / 'boxart'
    boxart.mkdir(parents=True)
    (boxart / 'kept.png').write_bytes(b'x')
    (boxart / '99_gone.png').write_bytes(b'x')
    monkeypatch.setattr(_config, 'IMAGE_PATH', str(image_path))
    monkeypatch.setattr(_config, 'STATIC_PATH', str(tmp_path / 'static'))

    from services.media_cleanup import find_orphaned_media
    games = [{'id': 1, 'boxart': 'some/dir/kept.png', 'boxart_3d': None,
              'fanart': None, 'video': None, 'manual': None, 'screenshots': None}]
    orphans, _ = find_orphaned_media(games)
    assert [os.path.basename(o['path']) for o in orphans] == ['99_gone.png']
