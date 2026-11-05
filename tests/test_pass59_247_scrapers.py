"""PASS-59-247: scrapers follow the service rules and close what they open."""
import ipaddress

import pytest

from services import ssrf
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (a fixture)


@pytest.mark.parametrize('ip,public', [
    ('8.8.8.8', True), ('2001:4860:4860::8888', True),
    ('100.64.0.1', False),          # carrier-grade NAT: not global, missed before
    ('192.0.0.8', False), ('127.0.0.1', False), ('169.254.169.254', False),
    ('::ffff:127.0.0.1', False), ('224.0.0.1', False),
])
def test_only_global_addresses_are_public(ip, public):
    assert ssrf._ip_is_public(ipaddress.ip_address(ip)) is public


def test_a_relative_redirect_is_followed_from_where_it_came(monkeypatch):
    monkeypatch.setattr(ssrf, 'validate_outbound_url', lambda url, **k: (True, url, None))

    class Resp:
        def __init__(self, status, location=None):
            self.status_code = status
            self.headers = {'Location': location} if location else {}

    class Session:
        def head(self, url, **k):
            return Resp(302, '/next') if url == 'https://example.com/start' else Resp(200)
    final, err = ssrf.validate_redirect_chain(Session(), 'https://example.com/start')
    assert (final, err) == ('https://example.com/next', None)


@pytest.mark.parametrize('release_date', ['TBA', '199?', 'Unknown', ''])
def test_an_odd_release_date_is_no_gap_not_a_crash(release_date):
    """It raised, and the raise rolled back the whole scrape."""
    from services.release_dates import year_gap_with_own_region
    assert year_gap_with_own_region(release_date, '{"NA": "1991-06-23"}', 'USA') is False


@pytest.mark.parametrize('fetch', ['scraper.scrape_igdb.fetch_game_details',
                                   'scraper.hybrid_scraper.fetch_igdb_extended'])
def test_an_igdb_id_that_is_not_a_number_never_reaches_the_query(fetch, monkeypatch):
    import importlib
    module, name = fetch.rsplit('.', 1)
    mod = importlib.import_module(module)
    sent = []
    monkeypatch.setattr(mod, 'igdb_auth', lambda: 'token', raising=False)
    monkeypatch.setattr('scraper.scrape_igdb.igdb_auth', lambda: 'token')
    for attr in ('http_post', 'requests'):
        if hasattr(mod, attr) and attr == 'http_post':
            monkeypatch.setattr(mod, attr, lambda *a, **k: sent.append(k.get('data')) or None)
    assert getattr(mod, name)('1; fields *') is None
    assert sent == []


def test_a_record_with_no_system_is_found_in_the_cache():
    from scraper import scraper_cache
    scraper_cache.cache_screenscraper_result('987654', '', {'id': 'x'})
    assert scraper_cache.get_cached_screenscraper_result('987654', None) == {'id': 'x'}


def test_esde_folders_typed_with_a_tilde_mean_the_home_folder(monkeypatch):
    import os
    from scraper import scrape_esde
    monkeypatch.setattr(scrape_esde.settings_manager, 'get_effective_path',
                        lambda key, fallback='': '~/ES-DE/gamelists')
    assert scrape_esde._get_esde_gamelists_path() == os.path.expanduser('~/ES-DE/gamelists')


def test_an_oversized_esde_picture_is_not_copied(library, monkeypatch):  # noqa: F811
    import os
    from scraper import scrape_esde
    monkeypatch.setattr(scrape_esde.config, 'MAX_MEDIA_DOWNLOAD_BYTES', 10)
    library.add_game()
    media = os.path.join(library.esde, 'downloaded_media', 'atari2600', 'covers')
    os.makedirs(media, exist_ok=True)
    with open(os.path.join(media, 'Fatal Run (USA).png'), 'wb') as f:
        f.write(b'x' * 100)
    copied = scrape_esde.copy_esde_media(1, {'name': 'Fatal Run'}, 'atari2600')
    assert 'boxart' not in copied


def test_a_listed_region_outside_the_options_is_kept_not_defaulted(monkeypatch):
    """'Brazil, Korea' became the default region, USA."""
    from scraper import hybrid_scraper
    monkeypatch.setattr('settings_manager.load_settings',
                        lambda: {'region_options': ['USA', 'Europe', 'Japan'], 'default_region': 'USA'})
    for given, kept in (('Brazil, Korea', 'Brazil'), ('Korea, Japan', 'Japan')):
        metadata, result = {'region': given}, {'filled_fields': []}
        hybrid_scraper._normalize_region(metadata, result)
        assert metadata['region'] == kept, given


@pytest.mark.parametrize('source,breaker', [('tgdb', '_tgdb_breaker'), ('igdb', '_igdb_breaker'),
                                            ('rawg', '_rawg_breaker'),
                                            ('screenscraper', '_screenscraper_breaker')])
def test_gap_fill_runs_each_service_under_its_breaker(source, breaker, monkeypatch):
    """Only the AI ran under its breaker; the others called a failing service
    on every gap-fill."""
    from scraper import hybrid_scraper, scraper_manager
    used = []

    def wrap(fn):
        def run(*a, **k):
            used.append(source)
            return fn(*a, **k)
        return run
    monkeypatch.setattr(scraper_manager, breaker, wrap)
    monkeypatch.setitem(hybrid_scraper._FALLBACK_FETCHERS, source, lambda lookup: {'ok': 1})
    assert hybrid_scraper._fetch_fallback(source, {}) == {'ok': 1}
    assert used == [source]


class _SSReply:
    def __init__(self, text, status=200):
        self.status_code, self.text = status, text

    def json(self):
        import json
        return json.loads(self.text)


def _ss_game_info(monkeypatch, reply):
    from scraper import scrape_screenscraper as ss
    monkeypatch.setattr(ss, 'get_system_id', lambda folder: 1)
    monkeypatch.setattr(ss, '_ss_request_with_retry', lambda *a, **k: reply)
    return ss.get_game_info('/roms/nes/Contra.nes', 'nes', 'u', 'p', use_checksums=False)


def test_a_quota_reply_to_a_game_lookup_stops_screenscraper(monkeypatch):
    from scraper import service_limits
    _ss_game_info(monkeypatch, _SSReply('API closed: quota maximum reached'))
    assert service_limits.stopped(service_limits.SCREENSCRAPER)


def test_a_game_lookup_learns_the_accounts_limits(monkeypatch):
    from scraper import scrape_screenscraper as ss
    seen = []
    monkeypatch.setattr(ss, '_note_account_limits', lambda data: seen.append(data))
    _ss_game_info(monkeypatch, _SSReply('{"response": {"ssuser": {"maxrequestspermin": "20"}}}'))
    assert seen


@pytest.mark.parametrize('status,headers', [(200, {'Content-Length': str(10 ** 9)}), (429, {}), (503, {})])
def test_a_screenscraper_reply_dropped_early_is_closed(status, headers, monkeypatch):
    from scraper import scrape_screenscraper as ss
    closed = []

    class Reply:
        status_code = status
        text = ''

        def __init__(self):
            self.headers = headers

        def close(self):
            closed.append(status)

        def iter_content(self, chunk_size):
            return iter(())
    monkeypatch.setattr(ss._http_session, 'get', lambda *a, **k: Reply())
    monkeypatch.setattr('time.sleep', lambda s: None)
    monkeypatch.setattr(ss.service_limits, 'wait_for_turn', lambda *a, **k: True, raising=False)
    ss._ss_request_with_retry('https://example.invalid', [], retries=1)
    assert closed
