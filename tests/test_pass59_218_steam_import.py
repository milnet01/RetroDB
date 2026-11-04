"""PASS-59-218: Steam imports keep what the service already sends.

The shapes below are cut down from real store replies captured 2026-11-02.
"""
import collections
import sqlite3
import types

import pytest

from scraper import hybrid_scraper, metadata_merger, scrape_steam, service_limits
from services.jobs import platform_sync
from tests.test_pass59_161_screenshots_own_system import downloads  # noqa: F401  (a fixture)
from tests._versions_util import vdb  # noqa: F401  (a fixture)
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (a fixture)

STORE_REPLY = {
    'about_the_game': 'Fight to <strong>Hell</strong>.<br><br>Then &quot;back&quot;.<ul><li>Co-op</li></ul>',
    'short_description': 'Short text.',
    'developers': ['id Software', 'Nightdive Studios'],
    'publishers': ['Bethesda Softworks'],
    'release_date': {'coming_soon': False, 'date': 'Aug 3, 2007'},
    'genres': [{'id': '1', 'description': 'Action'}],
    'categories': [{'id': 2, 'description': 'Single-player'},
                   {'id': 24, 'description': 'Shared/Split Screen'},
                   {'id': 28, 'description': 'Full controller support'}],
    'metacritic': {'score': 87, 'url': 'https://www.metacritic.com/game/pc/doom-3'},
    'ratings': {
        'esrb': {'rating': 'm', 'descriptors': 'Violence'},
        'pegi': {'rating': '18'},
        'usk': {'rating': '16'},
        'oflc': {'rating': 'ma15'},
        'cero': {'rating': 'b'},
        'kgrb': {'rating': '19'},
        'dejus': {'rating_generated': '1', 'rating': '16'},
        'steam_germany': {'rating_generated': '1', 'rating': '18'},
        'nzoflc': {'descriptors': '%NZoflcDescriptors%'},
    },
    'screenshots': [{'id': i, 'path_full': f'https://example.test/ss{i}.jpg'} for i in range(7)],
    'background_raw': 'https://example.test/bg.jpg',
}


def _metadata(**stored):
    return collections.defaultdict(lambda: None, stored)


def _apply(metadata, reply=None):
    result = {'filled_fields': []}
    metadata_merger.apply_steam_to_metadata(metadata, reply or STORE_REPLY, 9050, 1, result)
    return result


# --- What a store reply fills -------------------------------------------------

def test_store_text_arrives_clean(downloads):  # noqa: F811
    metadata = _metadata()
    _apply(metadata)
    assert metadata['description'] == 'Fight to Hell.\n\nThen "back".\nCo-op'
    assert metadata['developer'] == 'id Software, Nightdive Studios'
    assert metadata['publisher'] == 'Bethesda Softworks'
    assert metadata['critic_score'] == 87
    assert metadata['modes'] == 'Single-Player, Split-Screen'


def test_store_ratings_are_the_boards_own(downloads):  # noqa: F811
    metadata = _metadata()
    _apply(metadata)
    assert metadata['esrb_rating'] == 'M'
    assert metadata['pegi_rating'] == 'PEGI 18'
    assert metadata['usk_rating'] == '16'
    assert metadata['acb_rating'] == 'MA15+'
    assert metadata['cero_rating'] == 'B'
    assert metadata['grac_rating'] == '18'


def test_a_rating_steam_generated_itself_is_not_a_boards(downloads):  # noqa: F811
    metadata = _metadata()
    _apply(metadata)
    assert metadata['classind_rating'] is None


def test_store_date_and_genre_are_left_for_a_scrape(downloads):  # noqa: F811
    """DOOM 3 is dated 2007 on Steam. A filled field would keep out the real date."""
    metadata = _metadata()
    _apply(metadata)
    assert metadata['release_date'] is None
    assert metadata['genre'] is None


def test_store_fills_only_what_is_empty(downloads):  # noqa: F811
    metadata = _metadata(description='Mine', developer='Mine', esrb_rating='T',
                         critic_score=50, modes='Versus', boxart='a.jpg', fanart='b.jpg')
    _apply(metadata)
    assert (metadata['description'], metadata['developer'], metadata['esrb_rating'],
            metadata['critic_score'], metadata['modes'], metadata['boxart'], metadata['fanart']
            ) == ('Mine', 'Mine', 'T', 50, 'Versus', 'a.jpg', 'b.jpg')


def test_a_bare_reply_fills_nothing_and_does_not_fail(downloads):  # noqa: F811
    metadata = _metadata()
    result = {'filled_fields': []}
    metadata_merger.apply_steam_to_metadata(metadata, {'name': 'X', 'metacritic': None}, 1, 1, result)
    assert metadata['description'] is None
    assert metadata['critic_score'] is None


# --- Saving -------------------------------------------------------------------

def test_a_game_filled_from_the_store_still_waits_for_a_scrape(library, monkeypatch):  # noqa: F811
    library.add_game()
    monkeypatch.setattr(metadata_merger, '_download_and_finalize', lambda *a, **k: False)
    hybrid_scraper.apply_hybrid_metadata(1, 'steam', 9050, 'windows', fill_gaps=False,
                                         primary_data=STORE_REPLY, mark_scraped=False)
    row = library.row()
    assert row['scraped'] == 0
    assert row['critic_score'] == 87
    assert '"primary_source": "steam"' in row['scrape_history']


# --- The store's limit --------------------------------------------------------

@pytest.mark.parametrize('status', [403, 429])
def test_the_store_saying_stop_stops_the_calls(monkeypatch, status):
    service_limits.clear()
    calls = []

    def answer(*_a, **_k):
        calls.append(1)
        return types.SimpleNamespace(status_code=status)
    monkeypatch.setattr(scrape_steam, 'http_get', answer)
    monkeypatch.setattr(service_limits, '_pace', {})
    assert scrape_steam.get_app_details(1) is None
    assert scrape_steam.get_app_details(1) is None
    assert len(calls) == 1
    assert service_limits.stopped(service_limits.STEAM_STORE)
    service_limits.clear()


# --- The sync job -------------------------------------------------------------

@pytest.fixture
def sync(tmp_path, monkeypatch):
    path = tmp_path / 'sync.db'
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE systems (id INTEGER PRIMARY KEY, folder TEXT);
        INSERT INTO systems VALUES (1, 'windows');
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, system_id INTEGER,
                            steam_app_id TEXT, scrape_history TEXT);
        INSERT INTO games VALUES (1, 'New', 1, '10', NULL);
        INSERT INTO games VALUES (2, 'Filled', 1, '20', '[{"primary_source": "steam"}]');
        INSERT INTO games VALUES (3, 'Not Steam', 1, NULL, NULL);
        CREATE TABLE platform_play_time (user_id INTEGER, game_id INTEGER, source TEXT,
            minutes INTEGER, last_played INTEGER, updated_at TEXT,
            PRIMARY KEY (user_id, game_id, source));
    """)
    conn.commit()
    conn.close()

    def _conn():
        c = sqlite3.connect(path, timeout=5)
        c.row_factory = sqlite3.Row
        return c

    filled = []
    monkeypatch.setattr(platform_sync, '_get_conn', _conn)
    monkeypatch.setattr(platform_sync, 'persist_job_start', lambda *a: 'id')
    monkeypatch.setattr(platform_sync, 'persist_job_progress', lambda *a: None)
    monkeypatch.setattr(platform_sync, 'persist_job_complete', lambda *a, **k: None)
    monkeypatch.setattr(platform_sync, 'release_singleton_fd', lambda *a: None)
    monkeypatch.setattr(platform_sync, 'shutdown_requested',
                        types.SimpleNamespace(wait=lambda *_a: None))
    monkeypatch.setattr(platform_sync, '_fill_from_steam_store', lambda game: filled.append(game['id']))
    monkeypatch.setattr(scrape_steam, 'get_player_achievements', lambda *a: None)
    monkeypatch.setattr(scrape_steam, 'get_owned_games', lambda *a: [
        {'appid': 10, 'playtime_forever': 90, 'rtime_last_played': 1700000000}])

    def run(credentials=('key', 'id')):
        monkeypatch.setattr(platform_sync, '_get_steam_credentials', lambda user_id=None: credentials)
        job = platform_sync.SteamSyncJob()
        job._user_id = 7
        job.running = True
        job._run_sync()
        return job
    return types.SimpleNamespace(run=run, filled=filled, conn=_conn)


def test_sync_asks_the_store_once_per_game(sync):
    sync.run()
    assert sync.filled == [1]


def test_sync_keeps_play_time_per_user(sync):
    sync.run()
    rows = sync.conn().execute("SELECT * FROM platform_play_time").fetchall()
    assert [(r['user_id'], r['game_id'], r['source'], r['minutes'], r['last_played']) for r in rows] == [
        (7, 1, 'steam', 90, 1700000000)]


def test_sync_without_an_account_still_fills_from_the_store(sync):
    job = sync.run(('', ''))
    assert sync.filled == [1]
    assert job.error_message is None
    assert sync.conn().execute("SELECT COUNT(*) FROM platform_play_time").fetchone()[0] == 0


def test_sync_without_an_account_or_anything_to_fill_says_so(sync):
    c = sync.conn()
    c.execute("UPDATE games SET scrape_history = '[{\"primary_source\": \"steam\"}]'")
    c.commit()
    job = sync.run(('', ''))
    assert sync.filled == []
    assert 'not configured' in job.error_message


# --- The import routes --------------------------------------------------------

@pytest.fixture
def windows(vdb, monkeypatch):  # noqa: F811
    """The vdb's first system stands in as the Windows list the import fills."""
    import routes.platform_import as pi
    monkeypatch.setattr(pi, '_ensure_system_exists', lambda folder, name=None: {
        'id': vdb.sid, 'name': 'Windows', 'folder': folder})
    started = []
    monkeypatch.setattr('services.jobs.steam_sync_job.start',
                        lambda user_id=None: started.append(user_id) or {'success': True})
    vdb.started = started
    return vdb


def _steam_import(client, csrf, *games):
    return client.post('/api/steam/import', json={'games': list(games)},
                       headers={'X-CSRF-Token': csrf}).get_json()


def _row(vdb, game_id):
    return vdb.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()


def test_a_game_found_by_title_gets_its_steam_id(windows, admin_test_client):
    game_id = windows.game('Doom 3')
    client, csrf = admin_test_client()
    reply = _steam_import(client, csrf, {'appid': 9050, 'name': 'DOOM 3'})
    assert (reply['imported'], reply['linked'], reply['skipped']) == (0, 1, 0)
    assert _row(windows, game_id)['steam_app_id'] == '9050'
    assert windows.started


def test_a_game_holding_another_steam_id_keeps_it(windows, admin_test_client):
    game_id = windows.game('Doom 3', steam_app_id='1')
    client, csrf = admin_test_client()
    reply = _steam_import(client, csrf, {'appid': 9050, 'name': 'DOOM 3'})
    assert (reply['imported'], reply['linked'], reply['skipped']) == (0, 0, 1)
    assert _row(windows, game_id)['steam_app_id'] == '1'
    assert not windows.started


def test_an_imported_title_is_clean_and_sorts(windows, admin_test_client):
    client, csrf = admin_test_client()
    reply = _steam_import(client, csrf, {'appid': 77, 'name': ' Final Fantasy IX\u2122 '})
    assert reply['imported'] == 1
    row = windows.conn.execute("SELECT * FROM games WHERE steam_app_id = '77'").fetchone()
    assert row['title'] == 'Final Fantasy IX'
    assert row['sort_title'] == 'Final Fantasy 09'
    assert row['scraped'] == 0


def test_fetch_tells_a_game_to_link_from_one_already_imported(windows, monkeypatch, admin_test_client):
    windows.game('Doom 3')
    windows.game('Portal', steam_app_id='400')
    monkeypatch.setattr(scrape_steam, 'get_owned_games', lambda *a: [
        {'appid': 9050, 'name': 'DOOM 3'}, {'appid': 400, 'name': 'Portal'}, {'appid': 5, 'name': 'New One'}])
    monkeypatch.setattr(scrape_steam, 'get_player_summary', lambda *a: None)
    client, csrf = admin_test_client()
    data = client.post('/api/steam/fetch-library', json={'steam_api_key': 'k', 'steam_id': '1'},
                       headers={'X-CSRF-Token': csrf}).get_json()
    state = {g['name']: (g['already_imported'], g['will_link']) for g in data['games']}
    assert state == {'DOOM 3': (False, True), 'Portal': (True, False), 'New One': (False, False)}


def test_fetch_uses_the_saved_key_when_the_page_echoes_its_mask(windows, monkeypatch, admin_test_client):
    """The page fills its key box from a settings reply that masks the key."""
    from services.jobs import platform_sync as jobs
    monkeypatch.setattr(jobs, '_get_steam_credentials', lambda user_id=None: ('real-key', '1'))
    used = []
    monkeypatch.setattr(scrape_steam, 'get_owned_games', lambda key, sid: used.append(key) or [])
    client, csrf = admin_test_client()
    client.post('/api/steam/fetch-library', json={'steam_api_key': '***abcd', 'steam_id': '1'},
                headers={'X-CSRF-Token': csrf})
    client.post('/api/steam/fetch-library', json={'steam_api_key': 'typed-key', 'steam_id': '1'},
                headers={'X-CSRF-Token': csrf})
    assert used == ['real-key', 'typed-key']
