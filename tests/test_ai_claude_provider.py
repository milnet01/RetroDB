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
                        lambda _r: {'content': [{'text': '{}'}]})
    assert scrape_ai._call_claude('prompt', 'key', 'claude-haiku-5-5') == '{}'
    assert sent['model'] == 'claude-haiku-5-5'
    assert not {'temperature', 'top_p', 'top_k'} & set(sent)
