"""PASS-59-241: features that silently did nothing.

The HLTB auto-apply and RA Refresh hash-match tests sit with their jobs'
other tests (test_pass59_209_hltb.py, test_pass59_210_ra_links.py).
"""
import json
import shutil
import subprocess

import pytest

from tests._util import REPO_ROOT
from tests._versions_util import vdb  # noqa: F401  (a fixture)

NODE = shutil.which('node')
needs_node = pytest.mark.skipif(NODE is None, reason='node not available')

# Loads the real toast controller in Node with the few globals it touches
# at load time, then polls one job.
_TOAST = r"""
const vm = require('vm'); const fs = require('fs');
const ctx = {console, setInterval: () => 1, clearInterval(){}, setTimeout: () => 1,
  clearTimeout(){}, Date, Map, Set, JSON, Promise, AbortController,
  localStorage: {getItem(){return null}, setItem(){}, removeItem(){}},
  document: {addEventListener(){}, dispatchEvent(){}, hidden: false, readyState: 'complete',
             querySelector(){return null}, getElementById(){return null}},
  CustomEvent: class { constructor(t, o) { this.type = t; Object.assign(this, o); } },
  showNotification(){}, t: s => s, addEventListener(){}};
ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync('static/js/toast-controller.js', 'utf8'), ctx);
const C = ctx.UnifiedToastController;
const seen = [];
C.broadcast = (ev, type) => seen.push(ev);
C.getTypeConfig = () => ({name: 'RA Refresh'});
C.activeOperations.set('ra-refresh', %(was_active)s);
ctx.API = {get: async () => (%(status)s)};
C.pollStatus('ra-refresh', '/x').then(() => console.log(JSON.stringify(seen)));
"""


def _poll(was_active, status):
    script = _TOAST % {'was_active': json.dumps(was_active), 'status': json.dumps(status)}
    res = subprocess.run([NODE, '-e', script], cwd=REPO_ROOT, capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr[-1500:]
    return json.loads(res.stdout.strip().splitlines()[-1])


@needs_node
def test_a_job_that_finishes_says_so():
    """`wasActive` was read after updateToasts overwrote it, so the end of a
    running job was never noticed."""
    assert _poll(True, {'running': False, 'completed': True}) == ['job-completed']


@needs_node
def test_an_idle_job_stays_quiet():
    assert _poll(False, {'running': False, 'completed': True}) == []


# --- Xbox: a refresh keeps the gamertag, and only a refusal ends the sign-in ---

class _Resp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return {'access_token': 'new'}


def _xbox(monkeypatch, refreshed):
    """A stale stored sign-in; `refreshed` is what the refresh returns."""
    import time
    from scraper import scrape_xbox
    store = {'tokens': {'access_token': 'old', 'refresh_token': 'rt',
                        'expires_at': time.time() - 1, 'xuid': 'x1', 'gamertag': 'Old'},
             'cleared': False}
    monkeypatch.setattr(scrape_xbox, 'load_tokens', lambda uid: dict(store['tokens']))
    monkeypatch.setattr(scrape_xbox, 'save_tokens',
                        lambda tokens, uid: store.update(tokens=dict(tokens)))
    monkeypatch.setattr(scrape_xbox, 'clear_tokens', lambda uid: store.update(cleared=True))
    monkeypatch.setattr(scrape_xbox, 'refresh_access_token', lambda *a, **k: refreshed)
    monkeypatch.setattr(scrape_xbox, 'authenticate_xbox_live', lambda tok: ('xbl', 'hash'))
    monkeypatch.setattr(scrape_xbox, 'get_xsts_token', lambda tok: ('xsts', 'x1'))
    monkeypatch.setattr(scrape_xbox, 'get_gamertag', lambda auth, xuid: 'NewName')
    session = scrape_xbox.get_authenticated_session('cid', 'csec', 7)
    return session, store


def test_a_refresh_fetches_the_gamertag_again(monkeypatch):
    session, store = _xbox(monkeypatch, {'access_token': 'new', 'expires_in': 3600})
    assert session['gamertag'] == 'NewName'
    assert store['tokens']['gamertag'] == 'NewName'
    assert store['tokens']['xuid'] == 'x1'


def test_no_answer_from_microsoft_keeps_the_sign_in(monkeypatch):
    session, store = _xbox(monkeypatch, None)
    assert session is None
    assert store['cleared'] is False


def test_a_refused_refresh_ends_the_sign_in(monkeypatch):
    from scraper import scrape_xbox
    session, store = _xbox(monkeypatch, scrape_xbox.REFRESH_REFUSED)
    assert session is None
    assert store['cleared'] is True


@pytest.mark.parametrize('status,refused', [(400, True), (401, True), (500, False), (None, False)])
def test_only_a_refusal_counts_as_refused(monkeypatch, status, refused):
    from scraper import scrape_xbox
    monkeypatch.setattr(scrape_xbox, 'http_post',
                        lambda *a, **k: _Resp(status) if status else None)
    result = scrape_xbox.refresh_access_token('cid', 'csec', 'rt')
    assert (result is scrape_xbox.REFRESH_REFUSED) is refused


# --- RPCS3: any signed-in user can re-read their own trophies ---

def test_a_viewer_can_rescan_their_own_trophies(admin_test_client, monkeypatch, tmp_path):
    """The cache was cleared only by an admin-only route, so other users saw
    stale trophies until the server restarted."""
    from routes import trophies
    monkeypatch.setattr(trophies, 'get_user_trophy_path', lambda: str(tmp_path))
    client, csrf = admin_test_client(user={'id': 2, 'username': 'kid', 'role': 'viewer'})
    resp = client.post('/api/scan-trophies', headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()['games_found'] == 0


# --- PSN: links by title, never to a sequel, and a hand link stays ---

def test_the_trophy_matcher_does_not_take_a_sequel(monkeypatch):
    import routes.trophies as tr
    rows = [{'id': 1, 'title': 'Doom Eternal', 'folder': 'ps4'},
            {'id': 2, 'title': 'Uncharted 2: Among Thieves', 'folder': 'ps3'}]
    monkeypatch.setattr(tr, 'query', lambda *a, **k: rows)
    candidates = tr._ps_match_candidates()
    assert tr.find_matching_game('Doom', candidates) is None
    assert tr.find_matching_game('Uncharted 2', candidates)['id'] == 2


def test_the_full_sync_does_not_take_a_sequel():
    import routes.trophies as tr
    games = [(1, 'ps4', 'Doom Eternal'), (2, 'ps3', 'Uncharted 2: Among Thieves'),
             (3, 'ps4', 'Journey'), (4, 'ps3', 'Journey')]
    games = tr._psn_link_candidates(games)
    assert tr._psn_link_for('DOOM', 'ps4', games) is None
    assert tr._psn_link_for('Uncharted 2', 'ps3', games) == 2
    assert tr._psn_link_for('Journey', 'ps3', games) == 4
    assert tr._psn_link_for('Journey', 'ps5', games) == 3


def _psn_row(conn, linked):
    conn.execute("DELETE FROM psn_games WHERE npwr_id = 'NPWR241'")
    conn.execute("INSERT INTO psn_games (npwr_id, user_id, title, linked_game_id) "
                 "VALUES ('NPWR241', 1, 'Doom', ?)", (linked,))


def test_the_full_sync_keeps_a_link_set_by_hand(vdb):
    import types
    import routes.trophies as tr
    mine = vdb.game('Doom (1993)')
    other = vdb.game('Doom')
    _psn_row(vdb.conn, mine)
    title = types.SimpleNamespace(np_communication_id='NPWR241', title_name='Doom',
                                  defined_trophies=None, earned_trophies=None)
    tr._upsert_psn_title(vdb.conn, 1, title, 'ps4', None, other)
    assert vdb.conn.execute("SELECT linked_game_id FROM psn_games "
                            "WHERE npwr_id = 'NPWR241'").fetchone()[0] == mine
    _psn_row(vdb.conn, None)
    tr._upsert_psn_title(vdb.conn, 1, title, 'ps4', None, other)
    assert vdb.conn.execute("SELECT linked_game_id FROM psn_games "
                            "WHERE npwr_id = 'NPWR241'").fetchone()[0] == other


@pytest.fixture
def psn_systems(vdb, monkeypatch):
    import routes.platform_import as pi
    monkeypatch.setattr(pi, '_ensure_system_exists', lambda folder, name=None: {
        'id': vdb.sid, 'name': 'PS4', 'folder': folder})
    return vdb


def test_a_psn_import_links_a_game_found_by_title(psn_systems, admin_test_client):
    vdb = psn_systems
    game_id = vdb.game('Journey')
    _psn_row(vdb.conn, None)
    vdb.conn.commit()
    client, csrf = admin_test_client()
    reply = client.post('/api/psn/import', headers={'X-CSRF-Token': csrf}, json={'games': [
        {'npwr_id': 'NPWR241', 'name': 'JOURNEY', 'platform': 'ps4'}]}).get_json()
    assert (reply['imported'], reply['linked'], reply['skipped']) == (0, 1, 0)
    row = vdb.conn.execute("SELECT psn_npwr_id FROM games WHERE id = ?", (game_id,)).fetchone()
    assert row[0] == 'NPWR241'
    assert vdb.conn.execute("SELECT linked_game_id FROM psn_games "
                            "WHERE npwr_id = 'NPWR241'").fetchone()[0] == game_id


def test_a_psn_import_of_a_known_id_links_its_trophies(psn_systems, admin_test_client):
    vdb = psn_systems
    game_id = vdb.game('Journey', psn_npwr_id='NPWR241')
    _psn_row(vdb.conn, None)
    vdb.conn.commit()
    client, csrf = admin_test_client()
    reply = client.post('/api/psn/import', headers={'X-CSRF-Token': csrf}, json={'games': [
        {'npwr_id': 'NPWR241', 'name': 'Journey', 'platform': 'ps4'}]}).get_json()
    assert reply['skipped'] == 1
    assert vdb.conn.execute("SELECT linked_game_id FROM psn_games "
                            "WHERE npwr_id = 'NPWR241'").fetchone()[0] == game_id


# --- Tags: a name is unique per person, not across the household ---

def _tag_db(path, upto=None):
    import sqlite3
    from services import migrations
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.execute("INSERT INTO users VALUES (1, 'ann', 'admin'), (2, 'bob', 'viewer')")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    if upto is None:
        migrations.apply_pending(conn)
    else:
        for name in migrations.MIGRATIONS[:upto]:
            migrations._load(name).apply(conn)
        conn.execute(f"PRAGMA user_version = {upto}")
        conn.commit()
    return conn


def test_two_people_can_each_have_a_tag_of_the_same_name(tmp_path):
    import sqlite3
    conn = _tag_db(str(tmp_path / 't.db'))
    conn.execute("INSERT INTO tags (name, owner_id) VALUES ('Favourites', 1)")
    conn.execute("INSERT INTO tags (name, owner_id) VALUES ('favourites', 2)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tags (name, owner_id) VALUES ('FAVOURITES', 1)")


def test_the_upgrade_keeps_every_tag_and_its_games(tmp_path):
    from services import migrations
    index = migrations.MIGRATIONS.index('039_tags_unique_per_owner')
    conn = _tag_db(str(tmp_path / 'u.db'), upto=index)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'NES', 'nes')")
    conn.execute("INSERT INTO games (id, system_id, title, rom_path) VALUES (5, 1, 'Zelda', 'z')")
    conn.execute("INSERT INTO tags (id, name, color, owner_id) VALUES (7, 'Done', '#fff', 1)")
    conn.execute("INSERT INTO game_tags VALUES (5, 7)")
    conn.commit()
    migrations.apply_pending(conn)
    assert conn.execute("SELECT id, name, color, owner_id FROM tags").fetchall() == [
        (7, 'Done', '#fff', 1)]
    assert conn.execute("SELECT * FROM game_tags").fetchall() == [(5, 7)]
    conn.execute("INSERT INTO tags (name, owner_id) VALUES ('Done', 2)")
    conn.execute("DELETE FROM tags WHERE id = 7")
    assert conn.execute("SELECT COUNT(*) FROM game_tags").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# --- Steam: the shared key in Settings is the admins', never another person's ---

@pytest.mark.parametrize('user_id,expected', [
    (1, ('shared-key', '765')),   # an admin with no keys of their own
    (2, ('', '')),                # anyone else gets nothing, not the admin's library
    (None, ('shared-key', '765')),
])
def test_the_shared_steam_key_is_for_admins_only(vdb, monkeypatch, user_id, expected):
    from services.jobs import platform_sync
    vdb.conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                     "VALUES (2, 'kid', 'x', 'viewer')")
    for uid in (1, 2):
        vdb.conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (uid,))
        vdb.conn.execute("UPDATE user_settings SET steam_api_key = '', steam_id = '' "
                         "WHERE user_id = ?", (uid,))
    vdb.conn.commit()
    monkeypatch.setattr(platform_sync, '_shared_steam_credentials',
                        lambda: ('shared-key', '765'))
    got = platform_sync._get_steam_credentials(user_id=user_id)
    assert got == expected
