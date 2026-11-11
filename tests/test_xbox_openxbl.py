"""PASS-59-261: Xbox through each user's own OpenXBL key.

No network call is made: `http_get` and the token store are stubbed. The
reply shapes are Microsoft's TitleHub and achievements shapes, which OpenXBL
passes through; they are not yet checked against a live OpenXBL reply.
"""
import sqlite3

import pytest

from scraper import scrape_xbox, service_limits


@pytest.fixture(autouse=True)
def _fresh_limits():
    service_limits.clear()
    yield
    service_limits.clear()


class _Reply:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def calls(monkeypatch):
    """Record every OpenXBL call; `calls.replies` maps a path to its reply."""
    class Calls(list):
        replies = {}

    made = Calls()

    def fake_get(url, headers=None, timeout=None, retries=None, max_bytes=None, params=None):
        path = url.replace(scrape_xbox.OPENXBL_URL, '')
        made.append({'path': path, 'headers': headers, 'retries': retries})
        return made.replies.get(path, _Reply(404))

    monkeypatch.setattr(scrape_xbox, 'http_get', fake_get)
    return made


ACCOUNT = {'profileUsers': [{'id': '2533274', 'settings': [
    {'id': 'GameDisplayPicRaw', 'value': 'x'}, {'id': 'Gamertag', 'value': 'Ants'}]}]}


def test_the_key_goes_in_the_x_authorization_header_and_is_never_retried(calls):
    calls.replies['/account'] = _Reply(200, ACCOUNT)
    assert scrape_xbox.get_account('KEY') == ('2533274', 'Ants')
    assert calls[0]['headers']['X-Authorization'] == 'KEY'
    assert calls[0]['retries'] == 0


@pytest.mark.parametrize('status', [401, 403])
def test_a_refused_key_says_so(calls, status):
    calls.replies['/account'] = _Reply(status)
    assert scrape_xbox.get_account('KEY') is scrape_xbox.KEY_REFUSED


def test_no_answer_is_not_a_refusal(calls):
    calls.replies['/account'] = _Reply(500)
    assert scrape_xbox.get_account('KEY') is None


def test_the_hourly_limit_stops_calls_on_that_key_only(calls):
    calls.replies['/player/titleHistory'] = _Reply(429)
    assert scrape_xbox.get_title_history('KEY') is None
    assert scrape_xbox.minutes_until_allowed('KEY') > 0
    assert scrape_xbox.get_title_history('KEY') is None
    assert len(calls) == 1                     # the second ask made no call
    assert scrape_xbox.minutes_until_allowed('OTHER') == 0


def test_title_history_is_one_call(calls):
    titles = [{'titleId': 1, 'name': 'Halo'}]
    calls.replies['/player/titleHistory'] = _Reply(200, {'xuid': '1', 'titles': titles})
    assert scrape_xbox.get_title_history('KEY') == titles
    assert len(calls) == 1


@pytest.mark.parametrize('devices,folder', [
    (['XboxOne', 'XboxSeries'], 'xboxseriesx'),
    (['Xbox360'], 'xbox360'),
    (['PC'], 'windows'),
    (['Win32'], 'windows'),
    (['Mobile'], None),                        # X3: was filed as Xbox One
    (['Android', 'iOS'], None),
    ([], None),
])
def test_a_title_files_under_its_console_or_nowhere(devices, folder):
    assert scrape_xbox.parse_title_platform({'devices': devices}) == folder


@pytest.mark.parametrize('kind,kept', [('Game', True), ('App', False), (None, True)])
def test_apps_are_not_games(kind, kept):
    title = {'name': 'Netflix'} if kind is None else {'name': 'Netflix', 'type': kind}
    assert scrape_xbox.is_game(title) is kept


def test_xbox_360_achievements_use_their_own_path_and_shape(calls):
    calls.replies['/achievements/x360/9/title/1480659010'] = _Reply(200, {'achievements': [
        {'id': 1, 'name': 'Done', 'description': 'Won', 'unlocked': True,
         'timeUnlocked': '2010-05-01T10:00:00Z', 'gamerscore': 20},
        {'id': 2, 'name': 'Secret', 'description': 'Spoiler', 'lockedDescription': 'Hidden',
         'unlocked': False, 'timeUnlocked': '0001-01-01T00:00:00Z', 'gamerscore': 10},
    ]})
    result = scrape_xbox.get_achievements('KEY', '9', '1480659010', xbox360=True)
    assert (result['earned'], result['total']) == (1, 2)
    done, secret = result['achievements']
    assert done['progressState'] == 'Achieved'
    assert done['rewards'] == [{'type': 'Gamerscore', 'value': 20}]
    assert secret['progressState'] == 'NotStarted'
    assert secret['description'] == 'Hidden'
    assert scrape_xbox.unlock_time(secret) == ''


def test_xbox_one_achievements_pass_through(calls):
    ach = {'id': '5', 'name': 'A', 'progressState': 'Achieved',
           'progression': {'timeUnlocked': '2020-01-01T00:00:00Z'}}
    calls.replies['/achievements/player/9/title/77'] = _Reply(200, {'achievements': [ach]})
    result = scrape_xbox.get_achievements('KEY', '9', '77')
    assert result == {'achievements': [ach], 'earned': 1, 'total': 1}


def _achievement_table():
    conn = sqlite3.connect(':memory:')
    conn.execute("""CREATE TABLE xbox_achievements (
        game_id INTEGER, user_id INTEGER, achievement_id TEXT, name TEXT,
        description TEXT, icon_url TEXT, icon_locked_url TEXT, gamerscore INTEGER,
        achieved INTEGER, unlock_time TEXT,
        UNIQUE (game_id, achievement_id, user_id))""")
    return conn


def test_a_locked_achievement_stores_no_date():
    """X6: Microsoft dates a locked achievement 0001-01-01."""
    from services.jobs.platform_sync import _upsert_xbox_achievements
    conn = _achievement_table()
    _upsert_xbox_achievements(conn.cursor(), 1, [
        {'id': 'a', 'progressState': 'NotStarted',
         'progression': {'timeUnlocked': '0001-01-01T00:00:00.0000000Z'}},
        {'id': 'b', 'progressState': 'Achieved',
         'progression': {'timeUnlocked': '2021-03-04T05:06:07Z'}},
    ], 7)
    rows = conn.execute("SELECT achievement_id, unlock_time FROM xbox_achievements "
                        "ORDER BY achievement_id").fetchall()
    assert rows == [('a', ''), ('b', '2021-03-04T05:06:07Z')]


@pytest.mark.parametrize('stored,kept', [
    ({'api_key': 'k', 'xuid': '1'}, True),
    ({'access_token': 'a', 'refresh_token': 'r', 'xuid': '1'}, False),  # old Microsoft sign-in
    (None, False),
])
def test_only_a_stored_key_counts(monkeypatch, stored, kept):
    monkeypatch.setattr(scrape_xbox, '_platform_load_tokens', lambda _uid, _p: stored)
    assert (scrape_xbox.load_tokens(5) is not None) is kept


# --- routes -----------------------------------------------------------------

def _post(client, csrf, url, **kw):
    return client.post(url, headers={'X-CSRF-Token': csrf}, **kw)


@pytest.fixture
def key_store(monkeypatch):
    store = {}
    monkeypatch.setattr(scrape_xbox, '_platform_save_tokens',
                        lambda uid, _p, tokens: store.__setitem__(uid, dict(tokens)))
    monkeypatch.setattr(scrape_xbox, '_platform_load_tokens',
                        lambda uid, _p: store.get(uid))
    monkeypatch.setattr(scrape_xbox, '_platform_clear_tokens',
                        lambda uid, _p: store.pop(uid, None))
    return store


def test_saving_a_key_checks_it_and_never_sends_it_back(admin_test_client, key_store, calls):
    calls.replies['/account'] = _Reply(200, ACCOUNT)
    client, csrf = admin_test_client()
    resp = _post(client, csrf, '/api/xbox/key', json={'api_key': '  KEY  '})
    assert resp.get_json()['gamertag'] == 'Ants'
    (stored,) = key_store.values()
    assert (stored['api_key'], stored['xuid']) == ('KEY', '2533274')
    status = client.get('/api/xbox/status').get_json()
    assert status['connected'] is True and status['gamertag'] == 'Ants'
    assert 'KEY' not in client.get('/api/xbox/status').get_data(as_text=True)


def test_a_refused_key_is_not_saved(admin_test_client, key_store, calls):
    calls.replies['/account'] = _Reply(401)
    client, csrf = admin_test_client()
    resp = _post(client, csrf, '/api/xbox/key', json={'api_key': 'BAD'})
    assert resp.status_code == 400
    assert key_store == {}


def test_an_empty_key_is_refused_without_a_call(admin_test_client, key_store, calls):
    client, csrf = admin_test_client()
    assert _post(client, csrf, '/api/xbox/key', json={'api_key': ' '}).status_code == 400
    assert calls == []


def test_the_library_leaves_out_apps_and_phone_titles(admin_test_client, key_store,
                                                      calls, monkeypatch):
    import routes.platform_import as pi
    monkeypatch.setattr(pi, '_ensure_system_exists', lambda folder, name=None: {
        'id': {'xbox360': 9001, 'xboxone': 9002}.get(folder, 9003), 'name': folder})
    monkeypatch.setattr(pi._DuplicateIndex, '__init__', lambda self, *_a: None)
    monkeypatch.setattr(pi._DuplicateIndex, 'find', lambda *a: None)
    monkeypatch.setattr(pi._DuplicateIndex, 'can_link', lambda *a: False)
    key_store[1] = {'api_key': 'KEY', 'xuid': '9'}
    calls.replies['/player/titleHistory'] = _Reply(200, {'titles': [
        {'titleId': 1, 'name': 'Halo 3', 'type': 'Game', 'devices': ['Xbox360']},
        {'titleId': 2, 'name': 'Netflix', 'type': 'App', 'devices': ['XboxOne']},
        {'titleId': 3, 'name': 'Phone Game', 'type': 'Game', 'devices': ['Mobile']},
    ]})
    client, csrf = admin_test_client()
    data = _post(client, csrf, '/api/xbox/fetch-library').get_json()
    assert [g['name'] for g in data['games']] == ['Halo 3']
    assert data['games'][0]['platform'] == 'xbox360'
    assert data['left_out'] == 2


# --- the bulk sync job ------------------------------------------------------

def test_the_sync_takes_unsynced_games_first_and_stops_at_the_limit(tmp_path, monkeypatch):
    from services.jobs import platform_sync as mod
    db = tmp_path / 'x.db'
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE systems (id INTEGER PRIMARY KEY, folder TEXT);
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, system_id INTEGER,
                            xbox_title_id TEXT);
        CREATE TABLE game_achievement_progress (game_id INTEGER, user_id INTEGER,
            earned_achievements INTEGER, total_achievements INTEGER,
            completion_percentage REAL, last_synced TEXT, xbox_title_id TEXT, source TEXT,
            UNIQUE (game_id, user_id));
        INSERT INTO systems VALUES (1, 'xboxone'), (2, 'xbox360');
        INSERT INTO games VALUES (1, 'Old', 1, '101'), (2, 'Never', 2, '102'),
                                 (3, 'Older', 1, '103'), (4, 'Also never', 1, '104');
        INSERT INTO game_achievement_progress (game_id, user_id, last_synced, source)
            VALUES (1, 7, '2026-11-02', 'xbox'), (3, 7, '2026-11-01', 'xbox'),
                   (1, 8, '2020-01-01', 'xbox');
    """)
    conn.commit()
    conn.close()

    def _conn():
        c = sqlite3.connect(str(db))
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(mod, '_get_conn', _conn)
    monkeypatch.setattr(mod, 'persist_job_start', lambda *_a: 'pid')
    monkeypatch.setattr(mod, 'persist_job_progress', lambda *_a: None)
    monkeypatch.setattr(mod, 'persist_job_complete', lambda *_a, **_k: None)
    monkeypatch.setattr(mod, '_upsert_xbox_achievements', lambda *_a: 0)
    monkeypatch.setattr(scrape_xbox, 'load_tokens', lambda _uid: {'api_key': 'KEY', 'xuid': '9'})

    asked = []

    def fake_achievements(api_key, xuid, title_id, xbox360=False):
        asked.append((title_id, xbox360))
        if len(asked) == 3:                    # OpenXBL says: over the hour's count
            service_limits.stop(scrape_xbox._limit_source(api_key), 3600)
            return None
        return {'achievements': [], 'earned': 0, 'total': 0}

    monkeypatch.setattr(scrape_xbox, 'get_achievements', fake_achievements)

    job = mod.XboxSyncJob()
    job.user_id = 7
    job.running = True
    job._run_sync()

    # Never synced by user 7 first (2, 4), then the longest ago (3); stop there.
    assert asked == [('102', True), ('104', False), ('103', False)]
    status = job.get_status()
    assert status['success'] == 2 and status['skipped'] == 0
    assert 'hourly limit' in status['error']
