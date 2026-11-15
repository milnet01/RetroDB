"""PASS-59-189: a refused AI request stops the AI, and the user is told why."""

from unittest.mock import MagicMock

import pytest

from scraper import scrape_ai
from scraper import service_limits as limits


def reply(status):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = {}
    return r


@pytest.fixture
def posts(monkeypatch):
    """The AI's HTTP calls, answered with the status the test sets."""
    sent = []
    answer = {'status': 200}

    def post(url, **_kwargs):
        sent.append(url)
        return reply(answer['status'])

    monkeypatch.setattr(scrape_ai, 'http_post', post)
    return sent, answer


@pytest.fixture
def app_context_for_i18n():
    from flask import Flask
    from flask_babel import Babel
    app = Flask(__name__)
    Babel(app)
    with app.test_request_context('/'):
        yield


class TestStops:
    @pytest.mark.parametrize('status, reason', [
        (401, limits.KEY_REJECTED),
        (403, limits.KEY_REJECTED),
        (402, limits.PAYMENT_NEEDED),
        (429, limits.LIMIT_REACHED),
    ])
    def test_a_refusal_stops_that_provider(self, posts, status, reason):
        _sent, answer = posts
        answer['status'] = status
        assert scrape_ai._call_gemini('prompt', 'key', 'model') is None
        assert limits.stopped(limits.GEMINI)['reason'] == reason
        assert limits.stopped(limits.CLAUDE) is None

    @pytest.mark.parametrize('status', [200, 400, 500])
    def test_other_replies_do_not_stop_it(self, posts, status):
        _sent, answer = posts
        answer['status'] = status
        scrape_ai._call_openai('prompt', 'key', 'model')
        assert limits.stopped(limits.OPENAI) is None

    @pytest.mark.parametrize('call, provider', [
        (scrape_ai._call_gemini, limits.GEMINI),
        (scrape_ai._call_openai, limits.OPENAI),
        (scrape_ai._call_claude, limits.CLAUDE),
    ])
    def test_a_stopped_provider_is_not_asked(self, posts, call, provider):
        sent, _answer = posts
        limits.stop(provider, 3600, limits.PAYMENT_NEEDED)
        assert call('prompt', 'key', 'model') is None
        assert sent == []


class TestWords:
    def test_each_refusal_says_what_to_check(self, app_context_for_i18n):
        from services.service_stop_text import stop_sentences
        limits.stop(limits.GEMINI, 3600, limits.PAYMENT_NEEDED)
        limits.stop(limits.CLAUDE, 3600, limits.KEY_REJECTED)
        said = stop_sentences(limits.AI_SOURCES)
        assert len(said) == 2
        assert 'Gemini' in said[0] and 'payment' in said[0]
        assert 'Claude' in said[1] and 'Settings' in said[1]


class TestRoutes:
    def test_job_statuses_carry_the_ai_stop(self, admin_test_client):
        limits.stop(limits.GEMINI, 3600, limits.PAYMENT_NEEDED)
        client, _csrf = admin_test_client()
        for url in ('/api/bulk-scrape-job/status', '/api/ai-fill-bulk/status'):
            stops = client.get(url).get_json()['service_stops']
            assert any('Gemini' in s for s in stops), url

    def test_ai_fill_says_why_it_got_nothing(self, admin_test_client, monkeypatch):
        import services.ai_fill as ai_fill
        monkeypatch.setattr(ai_fill, 'load_game', lambda game_id: {'id': game_id})
        monkeypatch.setattr(ai_fill, 'fill_game', lambda game: None)
        limits.stop(limits.GEMINI, 3600, limits.PAYMENT_NEEDED)
        client, csrf = admin_test_client()
        data = client.post('/api/game/1/ai-fill', headers={'X-CSRF-Token': csrf}).get_json()
        assert 'Gemini' in data['error'] and 'payment' in data['error']
