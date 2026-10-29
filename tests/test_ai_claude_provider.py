"""Claude as the AI provider (PASS-59-186): the newest models, and a request
the 5.5 models accept. Sonnet 5.5 answers 400 to `temperature`, and Haiku 5.5
and Opus 5.5 say to omit it (platform.claude.com model pages, 2026-10-29)."""

import re

from tests._util import read_source

from scraper import scrape_ai


def test_default_is_haiku_5_5():
    claude = scrape_ai.PROVIDERS['claude']
    assert claude['default_model'] == 'claude-haiku-5-5'
    assert set(claude['models']) == {
        'claude-haiku-5-5', 'claude-sonnet-5-5', 'claude-opus-5-5'}


def test_settings_dropdown_lists_the_same_models():
    html = read_source('templates/_settings_tabs/scraping.html')
    block = html.split('id="apikey-ai-claude-model"', 1)[1].split('</select>', 1)[0]
    assert set(re.findall(r'<option value="([^"]+)"', block)) == set(
        scrape_ai.PROVIDERS['claude']['models'])


def test_request_sends_no_sampling_parameters(monkeypatch):
    sent = {}

    class _Reply:
        status_code = 200

    def fake_post(url, json_data=None, **_kw):
        sent.update(json_data)
        return _Reply()

    monkeypatch.setattr(scrape_ai, 'http_post', fake_post)
    monkeypatch.setattr(scrape_ai, 'safe_json',
                        lambda _r: {'content': [{'type': 'text', 'text': '{}'}]})
    assert scrape_ai._call_claude('prompt', 'key', 'claude-haiku-5-5') == '{}'
    assert sent['model'] == 'claude-haiku-5-5'
    assert not {'temperature', 'top_p', 'top_k'} & set(sent)


def _reply(monkeypatch, body):
    sent = {}

    class _Reply:
        status_code = 200

    def fake_post(url, json_data=None, **_kw):
        sent.update(json_data)
        return _Reply()

    monkeypatch.setattr(scrape_ai, 'http_post', fake_post)
    monkeypatch.setattr(scrape_ai, 'safe_json', lambda _r: body)
    return sent


def test_text_after_a_thinking_block_is_read(monkeypatch):
    """The 5.5 models think by default, so the reply can open with a
    thinking block that has no text (Haiku 5.5 migration guide)."""
    _reply(monkeypatch, {'stop_reason': 'end_turn', 'content': [
        {'type': 'thinking', 'thinking': '', 'signature': 'x'},
        {'type': 'text', 'text': '{"genre": "Action"}'}]})
    assert scrape_ai._call_claude('p', 'k', 'claude-haiku-5-5') == '{"genre": "Action"}'


def test_reply_cut_off_before_text_is_none(monkeypatch):
    _reply(monkeypatch, {'stop_reason': 'max_tokens', 'content': [
        {'type': 'thinking', 'thinking': '', 'signature': 'x'}]})
    assert scrape_ai._call_claude('p', 'k', 'claude-haiku-5-5') is None


def test_request_keeps_thinking_short_with_room_to_answer(monkeypatch):
    """Effort is the thinking control all three 5.5 models accept; thinking
    counts toward max_tokens, so 2048 could end before the answer."""
    sent = _reply(monkeypatch, {'content': [{'type': 'text', 'text': '{}'}]})
    scrape_ai._call_claude('p', 'k', 'claude-opus-5-5')
    assert sent['output_config'] == {'effort': 'low'}
    assert sent['max_tokens'] >= 8192
    assert 'thinking' not in sent  # Sonnet and Opus 5.5 answer 400 to "disabled"


import pytest


@pytest.mark.parametrize('status,word', [(401, 'key'), (402, 'credit'), (429, 'limit')])
def test_key_test_reports_a_refused_key(status, word, admin_test_client, setup_complete,
                                        monkeypatch):
    """The AI key test said success whatever the provider answered, so a
    Gemini 402 (no credit) looked like a working key (PASS-59-189)."""
    import routes.scraper as rs

    class _Reply:
        status_code = status
        headers = {}

    monkeypatch.setattr(scrape_ai, '_get_active_provider', lambda: {
        'provider': 'claude', 'api_key': 'k', 'model': 'claude-haiku-5-5', 'project_id': ''})
    monkeypatch.setattr(rs.requests, 'post', lambda *a, **k: _Reply())
    client, _csrf = admin_test_client()
    body = client.get('/api/scraper-allowance/ai').get_json()
    assert body['success'] is False
    assert word in body['error'].lower()


def test_settings_page_has_the_key_test_button(admin_test_client, setup_complete):
    import copy
    import settings_manager
    settings = copy.deepcopy(settings_manager.DEFAULT_SETTINGS)
    settings['setup_completed'] = True
    client, _csrf = admin_test_client(settings=settings)
    page = client.get('/settings').get_data(as_text=True)
    assert 'id="testAiKeyBtn"' in page and 'data-on-click="testAiKey"' in page
    assert 'window.testAiKey = testAiKey' in page
    assert 'The key works: {provider} answered, using {model}.' in page
