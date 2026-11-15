"""PASS-59-311: fixes from the Settings page review (section A).

- Add User needs a first password typed by the admin; there is no default
  password, and the new user must replace it at first sign-in.
"""

import sqlite3

import config
from tests.test_pass59_248_hardening import _make_user, _signed_in_client


def _admin(monkeypatch, name, addr):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    return _signed_in_client(_make_user(name), addr)


def test_create_user_without_a_password_is_refused(setup_complete, monkeypatch):
    client, csrf = _admin(monkeypatch, 'pass59311-admin-a', '10.59.311.1')
    r = client.post('/api/users/create', headers={'X-CSRF-Token': csrf},
                    json={'username': 'pass59311-nopass', 'role': 'player'})
    assert r.status_code == 422, (r.status_code, r.get_json())
    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute("SELECT id FROM users WHERE username = 'pass59311-nopass'").fetchone()
    finally:
        conn.close()
    assert row is None


def test_created_user_must_change_the_admins_password(setup_complete, monkeypatch):
    client, csrf = _admin(monkeypatch, 'pass59311-admin-b', '10.59.311.2')
    r = client.post('/api/users/create', headers={'X-CSRF-Token': csrf},
                    json={'username': 'pass59311-typed', 'role': 'player',
                          'password': 'first-password-from-admin'})
    assert r.status_code == 200, r.get_json()
    assert 'pass59311-typed' in r.get_json()['message']
    conn = sqlite3.connect(config.DB_PATH)
    try:
        flag = conn.execute("SELECT force_password_change FROM users "
                            "WHERE username = 'pass59311-typed'").fetchone()[0]
    finally:
        conn.close()
    assert flag == 1


def _settings_page(monkeypatch, role, addr):
    import app as app_module
    import settings_manager
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    # The page reads every setting; setup_complete's stub holds only one.
    full = {**settings_manager.DEFAULT_SETTINGS, 'setup_completed': True}
    monkeypatch.setattr(settings_manager, 'load_settings', lambda: dict(full))
    client, _ = _signed_in_client(_make_user(f'pass59311-page-{role}-{addr}', role=role), addr)
    r = client.get('/settings')
    assert r.status_code == 200
    return r.get_data(as_text=True)


ADMIN_ONLY = ('id="tab-scraping"', 'id="library"', 'id="rom-naming"', 'id="backup"',
              'id="dropdowns"', 'id="notifications"', 'id="logos"', 'id="logging"',
              'id="preferredBoxartSelect"')


def test_viewer_sees_no_admin_settings(setup_complete, monkeypatch):
    html = _settings_page(monkeypatch, 'viewer', '10.59.311.3')
    assert 'id="themeSelector"' in html and 'id="languageSelect"' in html
    for marker in ADMIN_ONLY + ('id="tab-customization"', 'id="bonus-discs"'):
        assert marker not in html, marker


def test_editor_sees_the_cards_an_editor_can_use(setup_complete, monkeypatch):
    html = _settings_page(monkeypatch, 'editor', '10.59.311.4')
    assert 'id="controllers"' in html and 'id="bonus-discs"' in html
    for marker in ADMIN_ONLY:
        assert marker not in html, marker


def test_admin_still_sees_every_card(setup_complete, monkeypatch):
    html = _settings_page(monkeypatch, 'admin', '10.59.311.5')
    for marker in ADMIN_ONLY + ('id="controllers"', 'id="bonus-discs"', 'id="apikeys"'):
        assert marker in html, marker


def test_fresh_install_shows_screenscraper_on(setup_complete, monkeypatch):
    """A8: with no saved scraper settings the switch matches scraper_manager,
    which scrapes with ScreenScraper on."""
    from scraper import scraper_manager
    monkeypatch.setattr(scraper_manager, 'load_scraper_settings', lambda: {})
    html = _settings_page(monkeypatch, 'admin', '10.59.311.6')
    tag = html[html.index('id="toggle-screenscraper"'):]
    tag = tag[:tag.index('data-on-change')]
    assert ' checked ' in tag, tag
