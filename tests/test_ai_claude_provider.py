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


# Web search (PASS-59-186): without it Claude answers from memory, and the
# prompt tells it to leave a sales figure blank unless one is published.
# Each search is billed, so it is a switch, off unless the user turns it on.

def test_no_search_unless_asked(monkeypatch):
    sent = _reply(monkeypatch, {'content': [{'type': 'text', 'text': '{}'}]})
    scrape_ai._call_claude('p', 'k', 'claude-haiku-5-5')
    assert 'tools' not in sent


def test_search_is_capped_per_game(monkeypatch):
    sent = _reply(monkeypatch, {'content': [{'type': 'text', 'text': '{}'}]})
    scrape_ai._call_claude('p', 'k', 'claude-haiku-5-5', web_search=True)
    assert sent['tools'] == [{'type': 'web_search_20250305', 'name': 'web_search',
                              'max_uses': scrape_ai.CLAUDE_MAX_SEARCHES}]
    assert scrape_ai.CLAUDE_MAX_SEARCHES == 5


def test_answer_is_the_text_after_the_last_search(monkeypatch):
    """Claude writes a line before each search, and citations split the
    answer into several text blocks."""
    _reply(monkeypatch, {'stop_reason': 'end_turn', 'content': [
        {'type': 'text', 'text': "I'll look up the sales."},
        {'type': 'server_tool_use', 'id': 's1', 'name': 'web_search', 'input': {'query': 'q'}},
        {'type': 'web_search_tool_result', 'tool_use_id': 's1', 'content': []},
        {'type': 'text', 'text': '{"units_sold": '},
        {'type': 'text', 'text': '"11000000"}', 'citations': [{'url': 'u'}]}]})
    raw = scrape_ai._call_claude('p', 'k', 'claude-haiku-5-5', web_search=True)
    assert raw == '{"units_sold": "11000000"}'


def test_paused_search_turn_is_continued(monkeypatch):
    calls = []
    replies = [
        {'stop_reason': 'pause_turn', 'content': [
            {'type': 'server_tool_use', 'id': 's1', 'name': 'web_search', 'input': {}}]},
        {'stop_reason': 'end_turn', 'content': [
            {'type': 'web_search_tool_result', 'tool_use_id': 's1', 'content': []},
            {'type': 'text', 'text': '{"genre": "Action"}'}]},
    ]

    class _Reply:
        status_code = 200

    def fake_post(url, json_data=None, **_kw):
        calls.append([m['role'] for m in json_data['messages']])
        return _Reply()

    monkeypatch.setattr(scrape_ai, 'http_post', fake_post)
    monkeypatch.setattr(scrape_ai, 'safe_json', lambda _r: replies[len(calls) - 1])
    raw = scrape_ai._call_claude('p', 'k', 'claude-haiku-5-5', web_search=True)
    assert raw == '{"genre": "Action"}'
    assert calls == [['user'], ['user', 'assistant']]


@pytest.mark.parametrize('saved,expected', [('on', True), ('', False), (None, False)])
def test_switch_is_read_from_the_saved_settings(saved, expected, tmp_path, monkeypatch):
    import json
    keys = {'ai_provider': 'claude', 'ai_claude_api_key': 'k'}
    if saved is not None:
        keys['ai_claude_web_search'] = saved
    path = tmp_path / 'scraper_settings.json'
    path.write_text(json.dumps({'api_keys': keys}))
    monkeypatch.setattr(scrape_ai, 'SCRAPER_SETTINGS_FILE', str(path))
    assert scrape_ai._get_active_provider()['web_search'] is expected


def test_switch_can_be_saved():
    from services.scraper_settings_validators import validate_scraper_api_keys
    ok, reason, clean = validate_scraper_api_keys({'ai_claude_web_search': 'on'})
    assert ok, reason
    assert clean['ai_claude_web_search'] == 'on'


def test_settings_page_explains_the_switch(admin_test_client, setup_complete):
    import copy
    import settings_manager
    settings = copy.deepcopy(settings_manager.DEFAULT_SETTINGS)
    settings['setup_completed'] = True
    client, _csrf = admin_test_client(settings=settings)
    page = client.get('/settings').get_data(as_text=True)
    assert 'id="apikey-ai-claude-web-search"' in page
    assert 'aria-describedby="claudeWebSearchWhy"' in page
    assert 'such as copies sold' in page
    assert "ai_claude_web_search: document.getElementById('apikey-ai-claude-web-search')" in page


@pytest.mark.parametrize('on', [True, False])
def test_ai_fill_passes_the_switch_on(on, monkeypatch):
    seen = {}

    def fake_call(prompt, api_key, model, **kw):
        seen.update(kw)
        return '{"genre": "Action"}'

    monkeypatch.setattr(scrape_ai, '_get_active_provider', lambda: {
        'provider': 'claude', 'api_key': 'k', 'model': 'm', 'web_search': on})
    monkeypatch.setattr(scrape_ai, 'rate_limit', lambda **k: None)
    monkeypatch.setattr(scrape_ai, '_call_claude', fake_call)
    scrape_ai.get_game_details(None, 'Grand Theft Auto IV', 'Microsoft Xbox 360',
                               existing_metadata={'genre': ''})
    assert seen.get('web_search', False) is on
