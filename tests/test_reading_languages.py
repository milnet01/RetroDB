"""Languages I can read: people who scrape choose the languages box pictures
and game names are picked in (scraper/ss_regions.reading_languages)."""
from tests.test_i18n import ADMIN, VIEWER, _authed_client, _settings_page

EDITOR = {'id': 3, 'username': 'editor', 'role': 'editor'}


def _save(monkeypatch, user, codes):
    saved = []
    client, headers = _authed_client(monkeypatch, user=user)
    monkeypatch.setattr('routes.auth.execute', lambda sql, params: saved.append(params))
    resp = client.post('/api/users/settings', json={'read_languages': codes}, headers=headers)
    return resp, saved


def test_an_editor_saves_languages_once_each(monkeypatch):
    resp, saved = _save(monkeypatch, EDITOR, ['en', 'de', 'en'])
    assert resp.status_code == 200
    assert saved == [['en,de', 3]]


def test_an_empty_list_means_the_screen_language(monkeypatch):
    resp, saved = _save(monkeypatch, ADMIN, [])
    assert resp.status_code == 200
    assert saved == [['', 1]]


def test_someone_who_cannot_scrape_is_refused(monkeypatch):
    resp, saved = _save(monkeypatch, VIEWER, ['en'])
    assert resp.status_code == 403
    assert saved == []


def test_an_unknown_language_is_refused(monkeypatch):
    for bad in (['xx'], 'en', [1]):
        resp, saved = _save(monkeypatch, ADMIN, bad)
        assert resp.status_code == 422, bad
        assert saved == []


def test_account_tab_ticks_the_screen_language_when_none_is_chosen(monkeypatch):
    page = _settings_page(monkeypatch, ADMIN, {'locale_preference': 'de'})
    ticked = [i['value'] for i in page.select('#readLanguages input[checked]')]
    assert ticked == ['de']


def test_account_tab_ticks_the_chosen_languages(monkeypatch):
    page = _settings_page(monkeypatch, ADMIN,
                          {'locale_preference': 'en', 'read_languages': 'en,fr'})
    assert [i['value'] for i in page.select('#readLanguages input[checked]')] == ['en', 'fr']


def test_account_tab_hides_the_choice_from_someone_who_cannot_scrape(monkeypatch):
    page = _settings_page(monkeypatch, VIEWER, {'locale_preference': 'en'})
    assert page.select('#languageSelect')      # the Account tab did render
    assert page.select('#readLanguages') == []
