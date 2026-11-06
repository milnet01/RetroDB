"""PASS-59-249 group E: the CLZ, Steam, Xbox and PSN imports.

Each test pins one finding from the 2026-11-04 audit
(docs/reviews/close-findings-2026-11-05-pass-59-249.md, group E).
"""
import sys
import types

import pytest

from scraper import scrape_steam, service_limits
from services import playtime
from services.jobs import platform_sync
from tests._versions_util import vdb  # noqa: F401  (a fixture)
from tests.test_pass59_218_steam_import import sync, windows  # noqa: F401  (fixtures)

_REAL_FILL = platform_sync._fill_from_steam_store
VIEWER = {'id': 1, 'username': 'viewer-stub', 'role': 'viewer'}


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """These tests post to rate-limited routes; leave no count for the next file."""
    import app as app_module
    app_module.limiter.reset()
    yield
    app_module.limiter.reset()


# --- CLZ ----------------------------------------------------------------------

def _clz_import(client, csrf, *games):
    return client.post('/api/clz-import/import', json={'games': list(games)},
                       headers={'X-CSRF-Token': csrf}).get_json()


def test_clz_titles_with_no_latin_letters_are_not_all_one_game(vdb, admin_test_client):  # noqa: F811
    vdb.game('ドラゴンクエスト')
    client, csrf = admin_test_client()
    reply = _clz_import(client, csrf, {'title': 'ファイナルファンタジー', 'system_id': vdb.sid,
                                       'system_folder': 'x'})
    assert (reply['imported'], reply['skipped']) == (1, 0)


def _fake_pdf(monkeypatch, *rows):
    page = types.SimpleNamespace(extract_tables=lambda: [[['Title', 'Platform'], *rows]])
    pdf = types.SimpleNamespace(pages=[page])

    class _Open:
        def __init__(self, _path):
            pass

        def __enter__(self):
            return pdf

        def __exit__(self, *a):
            return False
    monkeypatch.setitem(sys.modules, 'pdfplumber', types.SimpleNamespace(open=_Open))


def test_clz_preview_creates_no_system_and_the_import_does(vdb, monkeypatch, admin_test_client):  # noqa: F811
    import routes.clz_import as clz
    folder = 'p59249clz'
    monkeypatch.setitem(clz.CLZ_PLATFORM_MAP, 'test box', folder)
    _fake_pdf(monkeypatch, ['Some Game', 'Test Box'])
    client, csrf = admin_test_client()
    try:
        preview = client.post('/api/clz-import/parse', headers={'X-CSRF-Token': csrf},
                              data={'file': (__import__('io').BytesIO(b'%PDF-1.4'), 'x.pdf')},
                              content_type='multipart/form-data').get_json()
        assert vdb.conn.execute("SELECT COUNT(*) FROM systems WHERE folder = ?",
                                (folder,)).fetchone()[0] == 0
        game = preview['games'][0]
        assert game['system_folder'] == folder and game['new_system']

        reply = _clz_import(client, csrf, game)
        assert reply['imported'] == 1
        sid = vdb.conn.execute("SELECT id FROM systems WHERE folder = ?", (folder,)).fetchone()[0]
        assert vdb.conn.execute("SELECT title FROM games WHERE system_id = ?",
                                (sid,)).fetchone()[0] == 'Some Game'
    finally:
        vdb.conn.execute("DELETE FROM games WHERE system_id IN "
                         "(SELECT id FROM systems WHERE folder = ?)", (folder,))
        vdb.conn.execute("DELETE FROM systems WHERE folder = ?", (folder,))
        vdb.conn.commit()


# --- Steam, Xbox and PSN imports ----------------------------------------------

def _steam_import(client, csrf, *games):
    return client.post('/api/steam/import', json={'games': list(games)},
                       headers={'X-CSRF-Token': csrf}).get_json()


def test_an_import_refuses_a_game_with_no_id(windows, admin_test_client):  # noqa: F811
    client, csrf = admin_test_client()
    reply = _steam_import(client, csrf, {'appid': None, 'name': 'No Id'}, {'appid': '', 'name': 'Blank'},
                          {'name': 'Missing'})
    assert (reply['imported'], reply['failed']) == (0, 3)
    assert windows.conn.execute("SELECT COUNT(*) FROM games WHERE steam_app_id IN ('None', '') "
                                "OR rom_path = 'steam_import/windows/'").fetchone()[0] == 0


def test_an_import_does_not_match_two_titles_with_no_latin_letters(windows, admin_test_client):  # noqa: F811
    game_id = windows.game('ドラゴンクエスト')
    client, csrf = admin_test_client()
    reply = _steam_import(client, csrf, {'appid': 5, 'name': 'ファイナルファンタジー'})
    assert (reply['imported'], reply['linked']) == (1, 0)
    assert windows.conn.execute("SELECT steam_app_id FROM games WHERE id = ?",
                                (game_id,)).fetchone()[0] is None


def test_fetch_takes_a_steam_id_sent_as_a_number(windows, monkeypatch, admin_test_client):  # noqa: F811
    monkeypatch.setattr(scrape_steam, 'get_owned_games', lambda *a: [])
    client, csrf = admin_test_client()
    resp = client.post('/api/steam/fetch-library', json={'steam_api_key': 'k', 'steam_id': 76561198000000000},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 404


def test_a_viewer_creates_no_system(vdb):  # noqa: F811
    import app as app_module
    import routes.platform_import as pi
    from flask import g
    with app_module.app.test_request_context():
        g.user = VIEWER
        assert pi._ensure_system_exists('p59249view') is None
    assert vdb.conn.execute("SELECT COUNT(*) FROM systems WHERE folder = 'p59249view'").fetchone()[0] == 0


# --- The Steam sync -----------------------------------------------------------

def test_store_filled_does_not_depend_on_json_spacing(sync):  # noqa: F811
    c = sync.conn()
    c.execute("UPDATE games SET scrape_history = '[{\"primary_source\":\"steam\"}]' WHERE id = 2")
    c.commit()
    sync.run()
    assert sync.filled == [1]


def test_a_delisted_app_is_asked_about_once(sync, monkeypatch):  # noqa: F811
    monkeypatch.setattr(platform_sync, '_fill_from_steam_store', _REAL_FILL)
    monkeypatch.setattr(service_limits, '_pace', {})
    service_limits.clear()
    asked = []

    def store(_url, params=None, **_k):
        asked.append(params['appids'])
        return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                     json=lambda: {str(params['appids']): {'success': False}})
    monkeypatch.setattr(scrape_steam, 'http_get', store)
    sync.run()
    sync.run()
    assert asked == ['10']


# --- Play time ----------------------------------------------------------------

@pytest.mark.parametrize('text', ['Main: .', 'Main Story: .', 'Main:'])
def test_main_story_with_no_number_is_none(text):
    assert playtime.main_story_hours(text) is None
