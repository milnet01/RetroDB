"""PASS-59-311: fixes from the Settings page review (section A).

- Add User needs a first password typed by the admin; there is no default
  password, and the new user must replace it at first sign-in.
"""

import re
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
              'id="dropdowns"', 'id="logos"', 'id="logging"', 'id="display"',
              'id="preferredBoxartSelect"')


def _account_tab(html):
    start = html.index('id="tab-account"')
    end = html.find('id="tab-', start + 1)
    return html[start:end if end != -1 else None]


def test_viewer_sees_no_admin_settings(setup_complete, monkeypatch):
    html = _settings_page(monkeypatch, 'viewer', '10.59.311.3')
    for marker in ADMIN_ONLY + ('id="tab-customization"', 'id="bonus-discs"', 'id="tab-library"'):
        assert marker not in html, marker


def test_personal_settings_sit_on_the_account_tab(setup_complete, monkeypatch):
    """Section C: Theme, Language and message times are each person's own."""
    account = _account_tab(_settings_page(monkeypatch, 'viewer', '10.59.311.9'))
    for marker in ('id="themeSelector"', 'id="languageSelect"', 'id="backgroundMotionToggle"',
                   'id="notifTimeoutSuccess"', 'id="notifTimeoutError"'):
        assert marker in account, marker


def _timeouts_on_page(html):
    block = html[html.index('window.NOTIFICATION_TIMEOUTS'):]
    block = block[:block.index('}')]
    return {k: int(re.search(rf'{k}: (\d+)', block).group(1))
            for k in ('success', 'info', 'warning', 'error')}


def _household_times(monkeypatch):
    import app as app_module
    import settings_manager
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    household = {**settings_manager.DEFAULT_SETTINGS, 'setup_completed': True,
                 'notification_timeouts': {'success': 4, 'info': 4, 'warning': 6, 'error': 9}}
    monkeypatch.setattr(settings_manager, 'load_settings', lambda: dict(household))


def test_message_times_are_each_persons_own(setup_complete, monkeypatch):
    _household_times(monkeypatch)
    mine, csrf = _signed_in_client(_make_user('pass59311-times-a', role='viewer'), '10.59.311.7')
    other, _ = _signed_in_client(_make_user('pass59311-times-b', role='viewer'), '10.59.311.8')
    own = {'success': 10, 'info': 12, 'warning': 20, 'error': 60}
    r = mine.post('/api/users/settings', headers={'X-CSRF-Token': csrf},
                  json={'notification_timeouts': own})
    assert r.status_code == 200, r.get_json()
    assert _timeouts_on_page(mine.get('/settings').get_data(as_text=True)) == own
    # Someone who set none keeps the household's times.
    assert _timeouts_on_page(other.get('/settings').get_data(as_text=True)) == \
        {'success': 4, 'info': 4, 'warning': 6, 'error': 9}


def test_message_times_outside_one_to_sixty_are_refused(setup_complete, monkeypatch):
    _household_times(monkeypatch)
    client, csrf = _signed_in_client(_make_user('pass59311-times-c', role='viewer'), '10.59.311.10')
    for bad in ({'success': 0}, {'error': 61}, {'loud': 5}, {'info': '5'}, 'ten'):
        r = client.post('/api/users/settings', headers={'X-CSRF-Token': csrf},
                        json={'notification_timeouts': bad})
        assert r.status_code == 422, (bad, r.status_code, r.get_json())
    assert _timeouts_on_page(client.get('/settings').get_data(as_text=True)) == \
        {'success': 4, 'info': 4, 'warning': 6, 'error': 9}


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


def test_removed_and_moved_cards(setup_complete, monkeypatch):
    """Sections B and C: what left the page, and where the moved parts went."""
    html = _settings_page(monkeypatch, 'admin', '10.59.311.11')
    for gone in ('id="stats"', 'id="esde"', 'id="importLogosBtn"', 'id="scanTrophiesBtn"',
                 'id="support"', "Changes to ROM path require a restart"):
        assert gone not in html, gone
    library = html[html.index('id="tab-library"'):html.index('id="tab-scraping"')]
    assert library.count('data-on-click="savePathSettings"') == 1
    for box in ('romPathInput', 'esdeGamelistsInput', 'esdeMediaInput', 'rpcs3TrophyInput'):
        assert f'id="{box}"' in library, box
    system = html[html.index('id="tab-system"'):]
    assert 'data-on-click="calculateStorage"' in system and 'Database Location' in system
    assert '/help#troubleshooting' in system


def test_viewer_gets_only_the_account_tab(setup_complete, monkeypatch):
    html = _settings_page(monkeypatch, 'viewer', '10.59.311.12')
    for tab in ('library', 'scraping', 'data', 'customization', 'system'):
        assert f'id="tab-{tab}"' not in html, tab


def test_server_port_box_unless_the_start_command_sets_it(setup_complete, monkeypatch):
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('RETRODB_PORT', raising=False)
    html = _settings_page(monkeypatch, 'admin', '10.59.311.13')
    assert 'id="serverPortInput"' in html
    monkeypatch.setenv('PORT', '5123')
    html = _settings_page(monkeypatch, 'admin', '10.59.311.14')
    assert 'id="serverPortInput"' not in html
    assert '5123' in html and '(PORT)' in html


def test_help_page_carries_support_development(setup_complete, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    client, _ = _signed_in_client(_make_user('pass59311-help', role='viewer'), '10.59.311.15')
    html = client.get('/help').get_data(as_text=True)
    assert 'id="support"' in html and 'github.com/sponsors/milnet01' in html
