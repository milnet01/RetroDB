"""PASS-59-183: MobyGames as a scrape source.

Every reply is a saved one (tests/fixtures/mobygames/), so no test reaches the
network. The Final Fantasy VII record was fetched on 2026-11-21 and trimmed.
"""
import json
import logging
import os
import pathlib
import sqlite3

import pytest

import config
from scraper import hybrid_scraper, metadata_merger, scrape_mobygames, service_limits
from services import box_scans
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (a fixture)

FIXTURES = pathlib.Path(__file__).parent / 'fixtures' / 'mobygames'
KEY = 'not-a-real-key'
PLAYSTATION = 6


class Reply:
    def __init__(self, body=None, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.text = json.dumps(body) if body is not None else ''
        self.content = self.text.encode()

    def json(self):
        return self._body


def _search_reply():
    return json.loads((FIXTURES / 'ff7_search.json').read_text())


@pytest.fixture
def moby(monkeypatch):
    """A saved key, a clean record cache and no pacing; returns the request log."""
    service_limits.clear()
    service_limits.set_pace(service_limits.MOBYGAMES, 0)
    scrape_mobygames._records.clear()
    monkeypatch.setattr(scrape_mobygames, '_get_api_key', lambda: KEY)
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append({'url': url, 'params': dict(params or {}), **kwargs})
        return Reply(_search_reply(), headers={
            'ratelimit-policy': '0.2;w=1, 720;w=3600',
            'ratelimit-remaining': '700', 'ratelimit-reset': '1800'})

    monkeypatch.setattr(scrape_mobygames, 'http_get', fake_get)
    yield calls
    service_limits.clear()
    scrape_mobygames._records.clear()


@pytest.fixture
def psx_library(library, monkeypatch):  # noqa: F811
    """The test library with a PlayStation game, its downloads faked."""
    conn = sqlite3.connect(library.db)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (2, 'Sony PlayStation', 'psx')")
    conn.commit()
    conn.close()
    library.add_game(rom='Final Fantasy VII (Europe) (Disc 1).chd', system_id=2,
                     title='Final Fantasy VII')
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', library.images)
    monkeypatch.setattr(config, 'IMAGE_PATH', library.images)
    downloaded = []

    def fake_download(url, local_path, *args, **kwargs):
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(b'picture')
        downloaded.append(url)
        return True

    monkeypatch.setattr(metadata_merger, '_download_and_finalize', fake_download)
    monkeypatch.setattr(metadata_merger, 'keep_screenshot_if_unique', lambda *a, **k: True)
    monkeypatch.setattr(metadata_merger, 'get_existing_screenshot_hashes', lambda *a, **k: [])
    monkeypatch.setattr(hybrid_scraper, 'load_scraper_settings',
                        lambda: {'enabled': {}, 'api_keys': {'mobygames_apikey': KEY},
                                 'priority': ['mobygames']})
    monkeypatch.setattr(hybrid_scraper, '_fallback_order', lambda *a, **k: ['mobygames'])
    monkeypatch.setattr('scraper.ss_regions.readable_regions', lambda: ['uk', 'us'])
    monkeypatch.setattr('services.version_groups.preferred_regions', lambda: [])
    library.downloaded = downloaded
    return library


def _lookup(title='Final Fantasy VII', game_id=1):
    return {'title': title, 'game_id': game_id, 'system_folder': 'psx',
            'system_name': 'Sony PlayStation', 'secondary_sources': [],
            'user_ticked': False, 'api_keys': {'mobygames_apikey': KEY}}


def _pending(lib):
    conn = sqlite3.connect(lib.db)
    rows = [r[0] for r in conn.execute("SELECT game_id FROM mobygames_pending")]
    conn.close()
    return rows


# INV-1
def test_a_game_found_costs_two_requests(moby, psx_library):
    data = hybrid_scraper._fetch_mobygames(_lookup())
    assert data and data['game_id'] == 858
    metadata = {k: None for k in ('title', 'description', 'developer', 'publisher', 'genre',
                                  'perspective', 'release_date', 'boxart', 'boxart_back',
                                  'screenshots', 'moby_score', 'mobygames_id', 'box_scans')}
    metadata_merger.apply_mobygames_to_metadata(metadata, data, 1, {'filled_fields': []},
                                                fill_only=True, platform_id=PLAYSTATION,
                                                own_region='Europe')
    # A light search, then the record by id; applying it asks nothing more.
    assert len(moby) == 2
    assert moby[0]['params']['include'] == scrape_mobygames.SEARCH_INCLUDE
    assert moby[1]['params']['id'] == 858 and moby[1]['params']['include'] == scrape_mobygames.INCLUDE
    assert all(call['retries'] == 0 and call['params']['platform'] == PLAYSTATION for call in moby)
    assert metadata['mobygames_id'] == 858 and metadata['moby_score'] == 8.4
    # A record fetched minutes ago is not asked for again.
    assert scrape_mobygames.fetch_game_details(858, 'psx')['game_id'] == 858
    assert len(moby) == 2


def test_unmapped_system_sends_nothing(moby):
    assert scrape_mobygames.search_games('Astrosmash', 'nowhere') == []
    assert moby == []


# INV-2
@pytest.mark.parametrize('policy, gap', [('0.2;w=1, 720;w=3600', 5.0),
                                         ('1;w=1, 720;w=3600', 1.0)])
def test_pace_follows_the_reply(moby, policy, gap):
    scrape_mobygames.read_limits(Reply({}, headers={'ratelimit-policy': policy,
                                                    'ratelimit-remaining': '10'}))
    assert service_limits._pace[service_limits.MOBYGAMES] == pytest.approx(gap)


# INV-3
def test_spent_hour_stops_mobygames_only(moby, psx_library, monkeypatch):
    scrape_mobygames.read_limits(Reply({}, headers={'ratelimit-remaining': '0',
                                                    'ratelimit-reset': '600'}))
    stop = service_limits.stopped(service_limits.MOBYGAMES)
    assert stop and stop['reason'] == service_limits.LIMIT_REACHED
    assert 590 <= stop['until'] - __import__('time').time() <= 600
    moby.clear()
    monkeypatch.setattr(hybrid_scraper, '_fallback_order', lambda *a, **k: ['rawg', 'mobygames'])
    monkeypatch.setitem(hybrid_scraper._FALLBACK_FETCHERS, 'rawg', lambda lookup: {'any': 1})

    def rawg_fill(metadata, data, db_game_id, result, fill_only=False, **_):
        metadata['developer'] = metadata['developer'] or 'Other Source'

    monkeypatch.setattr(hybrid_scraper, 'apply_rawg_to_metadata', rawg_fill)
    hybrid_scraper.apply_hybrid_metadata(1, 'none', None, 'psx')
    assert moby == []
    assert psx_library.row()['developer'] == 'Other Source'


@pytest.mark.parametrize('status, reason', [(401, service_limits.KEY_REJECTED),
                                            (403, service_limits.KEY_REJECTED),
                                            (429, service_limits.LIMIT_REACHED)])
def test_refusals_stop_mobygames(moby, status, reason):
    scrape_mobygames.read_limits(Reply({}, status=status, headers={'retry-after': '120'}))
    assert service_limits.stopped(service_limits.MOBYGAMES)['reason'] == reason


# INV-5
def test_scans_come_from_one_european_playstation_box(moby, psx_library):
    covers = _search_reply()['games'][0]['covers']
    group = box_scans.choose_group(covers, PLAYSTATION, 'Europe')
    assert [p['id'] for p in group['platforms']] == [PLAYSTATION]
    assert box_scans.packaging(group) == 'Jewel Case'
    assert [c['country_code'] for c in group['countries']] == ['uk']
    # Of the two UK jewel cases, the one with its spine scanned.
    assert group['cover_group_id'] == 38027

    hybrid_scraper.apply_hybrid_metadata(1, 'none', None, 'psx')
    record = json.loads(psx_library.row()['box_scans'])['mobygames']
    assert record['group'] == 38027 and record['countries'] == ['uk']
    assert record['packaging'] == 'Jewel Case'
    chosen = {i['image_url'] for i in group['images']}
    assert all(url in chosen for url in psx_library.downloaded if '/covers/' in url)
    kinds = [i['kind'] for i in record['items']]
    assert kinds.count('spine') == 4 and 'front' in kinds and 'manual' in kinds
    for item in record['items']:
        assert os.path.exists(os.path.join(psx_library.images, 'box_scans', item['file']))


def test_no_group_for_another_platform():
    covers = _search_reply()['games'][0]['covers']
    windows_only = [c for c in covers if all(p['id'] == 3 for p in c['platforms'])]
    assert box_scans.choose_group(windows_only, PLAYSTATION, 'Europe') is None


def test_electronic_and_promotional_are_dropped():
    covers = [c for c in _search_reply()['games'][0]['covers']
              if box_scans.packaging(c) in ('Electronic', 'Promotional')]
    assert covers and box_scans.choose_group(covers, PLAYSTATION, 'Japan') is None


# INV-6
def test_key_stays_out_of_logs(moby, caplog):
    from services.log_redactor import redact
    with caplog.at_level(logging.DEBUG):
        scrape_mobygames.search_games('Final Fantasy VII', 'psx')
    assert moby[0]['params']['api_key'] == KEY
    assert KEY not in moby[0]['url']
    assert KEY not in caplog.text
    # requests puts the whole address in a connection error's text.
    assert KEY not in redact(f'GET https://api.mobygames.com/v2/games?title=x&api_key={KEY}&id=1')


def test_settings_reply_masks_the_key():
    from routes.scraper import SECRET_API_KEY_FIELDS, mask_api_keys_for_response
    assert 'mobygames_apikey' in SECRET_API_KEY_FIELDS
    assert KEY not in json.dumps(mask_api_keys_for_response({'mobygames_apikey': KEY}))


# INV-7
def test_clear_never_deletes_outside_the_scans_folder(psx_library):
    outside = os.path.join(psx_library.images, 'boxart', 'x.webp')
    inside = os.path.join(psx_library.images, 'box_scans', '1_front_0_ab.webp')
    for path in (outside, inside):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').close()
    record = {'version': 1, 'mobygames': {'items': [
        {'kind': 'front', 'file': '../boxart/x.webp'}, {'kind': 'front', 'file': '1_front_0_ab.webp'}]}}
    box_scans.delete_scans(json.dumps(record))
    assert os.path.exists(outside)
    assert not os.path.exists(inside)


# INV-8
def test_a_game_skipped_for_the_hour_catches_up(moby, psx_library):
    from services.jobs.mobygames_catch_up import MobyGamesCatchUpJob
    service_limits.stop(service_limits.MOBYGAMES, 600, service_limits.LIMIT_REACHED)
    hybrid_scraper.apply_hybrid_metadata(1, 'none', None, 'psx')
    assert moby == [] and _pending(psx_library) == [1]

    service_limits.clear()
    service_limits.set_pace(service_limits.MOBYGAMES, 0)
    MobyGamesCatchUpJob().run_pending()
    assert len(moby) == 2
    assert _pending(psx_library) == []
    assert psx_library.row()['mobygames_id'] == 858


def test_a_refused_key_lists_nothing(moby, psx_library):
    service_limits.stop(service_limits.MOBYGAMES, 3600, service_limits.KEY_REJECTED)
    hybrid_scraper.apply_hybrid_metadata(1, 'none', None, 'psx')
    assert moby == [] and _pending(psx_library) == []


def test_a_deleted_game_leaves_the_list(psx_library):
    conn = sqlite3.connect(psx_library.db)
    conn.execute("INSERT INTO mobygames_pending (game_id, added_at) VALUES (1, 'now')")
    conn.execute("DELETE FROM games WHERE id = 1")
    conn.commit()
    conn.close()
    assert _pending(psx_library) == []


def test_fields_mobygames_fills(moby, psx_library):
    hybrid_scraper.apply_hybrid_metadata(1, 'none', None, 'psx')
    row = psx_library.row()
    assert row['developer'] == 'Square Co., Ltd.'
    # Only publishers credited on PlayStation.
    assert 'Sony Computer Entertainment Europe Ltd.' in row['publisher']
    assert row['genre'] and row['perspective']
    assert row['release_date'] == '1997'
    assert '<' not in row['description'] and '&amp;' not in row['description']
    assert row['boxart'] and row['boxart_back'] and row['screenshots']


@pytest.mark.parametrize('reply', [None, Reply(None, status=502), Reply(None, status=504)])
def test_a_sick_server_pauses_mobygames_and_lists_the_game(moby, psx_library, monkeypatch, reply):
    """A timeout or a server error stops MobyGames for a while, so later games do
    not each wait out the timeout, and the game is asked again later."""
    monkeypatch.setattr(scrape_mobygames, 'http_get', lambda *a, **k: moby.append(1) or reply)
    hybrid_scraper.apply_hybrid_metadata(1, 'none', None, 'psx')
    stop = service_limits.stopped(service_limits.MOBYGAMES)
    assert stop and stop['reason'] == service_limits.UNAVAILABLE
    assert len(moby) == 1 and _pending(psx_library) == [1]


def test_settings_and_dashboard_show_mobygames(admin_test_client, monkeypatch):
    """The pages render the new source; a check with no key saved sends nothing."""
    import copy
    import requests
    import settings_manager
    sent = []
    monkeypatch.setattr(requests, 'get', lambda *a, **k: sent.append(a) or None)
    settings = copy.deepcopy(settings_manager.DEFAULT_SETTINGS)
    settings['setup_completed'] = True
    client, _csrf = admin_test_client(settings=settings)
    settings = client.get('/settings')
    assert settings.status_code == 200
    page = settings.get_data(as_text=True)
    assert 'data-scraper="mobygames"' in page and 'id="apikey-mobygames"' in page
    home = client.get('/dashboard')
    assert home.status_code == 200 and 'id="status-mobygames"' in home.get_data(as_text=True)
    check = client.get('/api/check-scraper/mobygames').get_json()
    assert check['online'] is False and sent == []
