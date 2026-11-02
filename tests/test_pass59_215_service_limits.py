"""PASS-59-215: RetroDB keeps to each service's limits and stops when told to."""

from unittest.mock import MagicMock

import pytest

from scraper import hltb_lookup, scrape_igdb, scrape_rawg, scrape_screenscraper, scrape_thegamesdb
from scraper import service_limits as limits


@pytest.fixture(autouse=True)
def real_paces():
    """conftest turns paces off for every other test; these read them."""
    limits.clear()


def reply(status=200, json_data=None, text='', headers=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = json_data if json_data is not None else {}
    r.headers = headers or {}
    r.iter_content.return_value = [text.encode() or b'{}']
    return r


@pytest.fixture
def ss_calls(monkeypatch):
    """ScreenScraper's HTTP session, answering with what the test queues."""
    calls = []
    queue = []

    def get(url, params=None, timeout=None, stream=None):
        calls.append(url)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(scrape_screenscraper._http_session, 'get', get)
    monkeypatch.setattr('time.sleep', lambda _s: None)
    return calls, queue


def _ss_search():
    return scrape_screenscraper._search_once('Sonic', 1, 'user', 'secret', None, None)


class TestPace:
    def test_calls_to_one_service_are_spaced(self, monkeypatch):
        limits.set_pace(limits.IGDB, 0.5)
        waits = []
        monkeypatch.setattr(limits.time, 'monotonic', lambda: 100.0)
        monkeypatch.setattr(limits.time, 'sleep', waits.append)
        assert limits.wait_for_turn(limits.IGDB)
        assert limits.wait_for_turn(limits.IGDB)
        assert waits == [0.5]

    def test_igdb_keeps_to_four_a_second(self):
        assert limits._DEFAULT_PACE[limits.IGDB] >= 0.25

    def test_igdb_waits_its_turn_before_each_request(self, monkeypatch):
        turns = []
        monkeypatch.setattr(limits, 'wait_for_turn', turns.append)
        monkeypatch.setattr(scrape_igdb, '_get_igdb_credentials', lambda: ('id', 'secret'))
        monkeypatch.setattr(scrape_igdb, 'http_post', lambda *a, **k: reply(json_data=[]))
        scrape_igdb.igdb_request('games', 'fields id;', 'token')
        assert turns == [limits.IGDB]

    def test_slowing_down_survives_a_reply_stating_the_rate(self):
        limits.set_pace(limits.SCREENSCRAPER, 0.02)
        limits.slow_down(limits.SCREENSCRAPER)
        limits.set_pace(limits.SCREENSCRAPER, 0.02)
        assert limits._pace[limits.SCREENSCRAPER] == 0.5

    def test_a_slow_down_has_a_ceiling(self):
        for _ in range(10):
            limits.slow_down(limits.RAWG)
        assert limits._pace[limits.RAWG] == limits.SLOWEST_PACE


class TestStop:
    def test_a_stop_ends_on_time(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(limits.time, 'time', lambda: now[0])
        limits.stop(limits.RAWG, 60)
        assert limits.stopped(limits.RAWG)
        assert limits.wait_for_turn(limits.RAWG) is False
        now[0] = 1061.0
        assert limits.stopped(limits.RAWG) is None
        assert limits.wait_for_turn(limits.RAWG) is True

    def test_one_service_stopping_leaves_the_others(self):
        limits.stop(limits.RAWG, 60)
        assert limits.stopped(limits.IGDB) is None


class TestScreenScraper:
    @pytest.mark.parametrize('status', [430, 431])
    def test_a_limit_reply_stops_at_once_and_no_more_calls_go_out(self, ss_calls, status):
        calls, queue = ss_calls
        queue.append(reply(status))
        assert _ss_search() is None
        assert len(calls) == 1
        assert limits.stopped(limits.SCREENSCRAPER)
        assert _ss_search() is None
        assert len(calls) == 1

    def test_a_game_not_found_does_not_stop(self, ss_calls):
        calls, queue = ss_calls
        queue.append(reply(200, text='Erreur : Aucun jeu trouvé !'))
        assert _ss_search() is None
        assert limits.stopped(limits.SCREENSCRAPER) is None

    def test_a_limit_said_in_words_stops(self, ss_calls):
        calls, queue = ss_calls
        queue.append(reply(200, text='Votre quota de scrape est dépassé pour aujourd\'hui !'))
        assert _ss_search() is None
        assert limits.stopped(limits.SCREENSCRAPER)

    def test_too_fast_slows_down_and_does_not_stop(self, ss_calls):
        calls, queue = ss_calls
        queue.append(reply(429))
        before = limits._pace[limits.SCREENSCRAPER]
        assert _ss_search() is None
        assert limits._pace[limits.SCREENSCRAPER] > before
        assert limits.stopped(limits.SCREENSCRAPER) is None

    def test_a_reply_sets_the_accounts_rate(self):
        scrape_screenscraper._note_account_limits({'response': {'ssuser': {
            'maxrequestspermin': '3000', 'requeststoday': '10', 'maxrequestsperday': '50000',
        }}})
        assert limits._pace[limits.SCREENSCRAPER] == pytest.approx(0.02)
        assert limits.stopped(limits.SCREENSCRAPER) is None

    @pytest.mark.parametrize('user', [
        {'requeststoday': '50000', 'maxrequestsperday': '50000'},
        {'requestskotoday': '5000', 'maxrequestskoperday': '5000'},
    ])
    def test_a_reply_at_the_days_limit_stops_before_the_next_call(self, user):
        scrape_screenscraper._note_account_limits({'response': {'ssuser': user}})
        assert limits.stopped(limits.SCREENSCRAPER)

    @pytest.mark.parametrize('data', [{}, {'response': {}}, {'response': None}, [], {'response': {'ssuser': {
        'maxrequestspermin': 'lots', 'requeststoday': None, 'maxrequestsperday': '0'}}}])
    def test_odd_replies_change_nothing(self, data):
        before = limits._pace[limits.SCREENSCRAPER]
        scrape_screenscraper._note_account_limits(data)
        assert limits._pace[limits.SCREENSCRAPER] == before
        assert limits.stopped(limits.SCREENSCRAPER) is None


class TestTheGamesDB:
    @pytest.fixture
    def tgdb(self, monkeypatch):
        keys = []
        queue = []

        def get(url, params=None, **_kw):
            keys.append(params['apikey'])
            return queue.pop(0)

        monkeypatch.setattr(scrape_thegamesdb, 'http_get', get)
        monkeypatch.setattr(scrape_thegamesdb, 'get_api_keys', lambda: ('PUB', 'PRIV'))
        return keys, queue

    def test_a_spent_key_is_passed_over_until_its_timer_ends(self, tgdb, monkeypatch):
        keys, queue = tgdb
        queue.extend([
            reply(json_data={'remaining_monthly_allowance': 0, 'extra_allowance': 0,
                             'allowance_refresh_timer': 500}),
            reply(json_data={'remaining_monthly_allowance': 9}),
        ])
        assert scrape_thegamesdb._tgdb_request('u').status_code == 200
        assert limits.stopped(limits.THEGAMESDB) is None
        assert scrape_thegamesdb._tgdb_request('u').status_code == 200
        assert keys == ['PUB', 'PRIV']

    def test_extra_allowance_keeps_a_key_going(self, tgdb):
        keys, queue = tgdb
        queue.extend([reply(json_data={'remaining_monthly_allowance': 0, 'extra_allowance': 3}),
                      reply(json_data={'remaining_monthly_allowance': 0, 'extra_allowance': 2})])
        scrape_thegamesdb._tgdb_request('u')
        scrape_thegamesdb._tgdb_request('u')
        assert keys == ['PUB', 'PUB']

    def test_both_keys_spent_stops_the_service(self, tgdb):
        keys, queue = tgdb
        spent = {'remaining_monthly_allowance': 0, 'allowance_refresh_timer': 0}
        queue.extend([reply(json_data=spent), reply(json_data=spent)])
        scrape_thegamesdb._tgdb_request('u')
        scrape_thegamesdb._tgdb_request('u')
        entry = limits.stopped(limits.THEGAMESDB)
        assert entry['reason'] == limits.LIMIT_REACHED
        assert scrape_thegamesdb._tgdb_request('u') is None
        assert keys == ['PUB', 'PRIV']

    @pytest.mark.parametrize('status', [403, 429])
    def test_both_keys_refused_stops_the_service(self, tgdb, status):
        keys, queue = tgdb
        queue.extend([reply(status), reply(status)])
        assert scrape_thegamesdb._tgdb_request('u') is None
        assert limits.stopped(limits.THEGAMESDB)['reason'] == limits.KEY_REFUSED
        assert scrape_thegamesdb._tgdb_request('u') is None
        assert keys == ['PUB', 'PRIV']


class TestRawg:
    @pytest.fixture
    def rawg(self, monkeypatch):
        calls = []
        queue = []

        def get(url, **_kw):
            calls.append(url)
            return queue[0]

        monkeypatch.setattr(scrape_rawg, 'http_get', get)
        monkeypatch.setattr(scrape_rawg, '_get_api_key', lambda: 'KEY')
        return calls, queue

    def test_the_months_limit_stops_it(self, rawg):
        calls, queue = rawg
        queue.append(reply(401, text='{"error":"The monthly API limit reached."}'))
        assert scrape_rawg._make_request('games') is None
        assert limits.stopped(limits.RAWG)
        assert scrape_rawg._make_request('games') is None
        assert len(calls) == 1

    def test_a_bad_key_is_not_a_limit(self, rawg):
        calls, queue = rawg
        queue.append(reply(401, text='{"error":"Invalid key"}'))
        assert scrape_rawg._make_request('games') is None
        assert limits.stopped(limits.RAWG) is None

    def test_the_last_allowed_call_stops_the_next(self, rawg):
        calls, queue = rawg
        queue.append(reply(200, json_data={'results': []},
                           headers={'X-RateLimit-Remaining': '0'}))
        assert scrape_rawg._make_request('games') == {'results': []}
        assert limits.stopped(limits.RAWG)


class TestHowLongToBeat:
    def test_too_many_requests_stops_it(self, monkeypatch):
        monkeypatch.setattr(hltb_lookup, '_get_auth_token', lambda: ('t', None, None))
        posts = []

        def post(*_a, **_k):
            posts.append(1)
            return reply(429)

        monkeypatch.setattr(hltb_lookup, 'http_post', post)
        assert hltb_lookup._search_hltb('Doom') is None
        assert limits.stopped(limits.HOWLONGTOBEAT)
        assert hltb_lookup._search_hltb('Doom') is None
        assert len(posts) == 1

    def test_the_token_retry_after_a_403_waits_its_turn(self, monkeypatch):
        monkeypatch.setattr(hltb_lookup, '_get_auth_token', lambda: ('t', None, None))
        monkeypatch.setattr(hltb_lookup, 'http_post', lambda *a, **k: reply(403))
        turns = []
        monkeypatch.setattr(limits, 'wait_for_turn', lambda s: turns.append(s) or True)
        hltb_lookup._search_hltb('Doom')
        assert turns == [limits.HOWLONGTOBEAT, limits.HOWLONGTOBEAT]


class TestBulkScrapeStamp:
    def _job(self, monkeypatch):
        from services.jobs.bulk_scrape import BulkScrapeJob
        stamped = []
        monkeypatch.setattr(BulkScrapeJob, '_stamp_bulk_scraped', staticmethod(stamped.append))
        return BulkScrapeJob(), stamped

    def test_a_game_with_no_answer_while_a_source_is_stopped_can_be_tried_again(self, monkeypatch):
        job, stamped = self._job(monkeypatch)
        limits.stop(limits.THEGAMESDB, 60)
        job._count_no_match(5, {'tgdb': True})
        assert stamped == []
        assert (job.failed_count, job.skipped_count) == (0, 1)

    def test_a_real_miss_is_stamped(self, monkeypatch):
        job, stamped = self._job(monkeypatch)
        job._count_no_match(5, {'tgdb': True})
        assert stamped == [5]
        assert (job.failed_count, job.skipped_count) == (1, 0)

    def test_a_stopped_source_that_is_switched_off_does_not_count(self, monkeypatch):
        job, stamped = self._job(monkeypatch)
        limits.stop(limits.THEGAMESDB, 60)
        job._count_no_match(5, {'tgdb': False})
        assert stamped == [5]


class TestWords:
    def test_each_reason_has_its_own_sentence(self, app_context_for_i18n):
        from services.service_stop_text import stop_sentences
        limits.stop(limits.SCREENSCRAPER, 3600)
        limits.stop(limits.THEGAMESDB, 3600, limits.KEY_REFUSED)
        said = stop_sentences()
        assert len(said) == 2
        assert 'ScreenScraper' in said[0] and 'limit' in said[0]
        assert 'TheGamesDB' in said[1] and 'key' in said[1]

    def test_only_the_services_asked_about(self, app_context_for_i18n):
        from services.service_stop_text import stop_sentences
        limits.stop(limits.SCREENSCRAPER, 3600)
        assert stop_sentences([limits.HOWLONGTOBEAT]) == []


@pytest.fixture
def app_context_for_i18n():
    from flask import Flask
    from flask_babel import Babel
    app = Flask(__name__)
    Babel(app)
    with app.test_request_context('/'):
        yield


class TestRoutes:
    def test_status_routes_carry_the_words(self, admin_test_client):
        limits.stop(limits.SCREENSCRAPER, 3600)
        limits.stop(limits.HOWLONGTOBEAT, 3600)
        client, _csrf = admin_test_client()
        for url in ('/api/bulk-scrape-job/status', '/api/maintenance/ss-region-repair/status',
                    '/api/hltb/bulk/status'):
            assert client.get(url).get_json()['service_stops'], url

    def test_saving_keys_lets_a_stopped_service_be_tried_again(self, admin_test_client, monkeypatch, tmp_path):
        import routes.scraper as mod
        monkeypatch.setattr(mod, 'SCRAPER_SETTINGS_FILE', str(tmp_path / 'scraper_settings.json'))
        limits.stop(limits.THEGAMESDB, 3600, limits.KEY_REFUSED)
        client, csrf = admin_test_client()
        reply_ = client.post('/api/scraper-api-keys', json={}, headers={'X-CSRF-Token': csrf})
        assert reply_.status_code == 200, reply_.get_data(as_text=True)
        assert limits.stopped(limits.THEGAMESDB) is None

    def test_the_allowance_check_uses_the_free_call_and_invents_no_date(self, admin_test_client, monkeypatch):
        import routes.scraper as mod
        urls = []

        def get(url, timeout=None):
            urls.append(url)
            return reply(json_data={'remaining_monthly_allowance': 0, 'allowance_refresh_timer': 0})

        monkeypatch.setattr(mod.requests, 'get', get)
        monkeypatch.setattr(mod, 'get_saved_api_keys', lambda: {'tgdb': 'P', 'tgdb_public': 'Q'})
        client, _csrf = admin_test_client()
        data = client.get('/api/scraper-allowance/tgdb').get_json()
        assert len(urls) == 2 and all('/v1/API/Limit' in u for u in urls)
        assert data['remaining_monthly'] == 0
        assert data['reset_date'] is None
