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


# --- Section D -------------------------------------------------------------

def _scraping_tab(html):
    return html[html.index('id="tab-scraping"'):html.index('id="tab-data"')]


def _checked_strictness(tab):
    found = re.findall(r'<input[^>]*name="matchStrictness"[^>]*>', tab)
    return [re.search(r'value="(\w+)"', tag).group(1) for tag in found if ' checked' in tag], found


def test_match_filter_is_three_plain_choices(setup_complete, monkeypatch):
    """D: Strict / Normal / Loose replace the score box, its table and the
    criteria switch; the default score is Normal and no Custom shows."""
    from scraper import scraper_manager
    monkeypatch.setattr(scraper_manager, 'load_scraper_settings', lambda: {})
    tab = _scraping_tab(_settings_page(monkeypatch, 'admin', '10.59.311.21'))
    checked, found = _checked_strictness(tab)
    assert [re.search(r'value="(\w+)"', t).group(1) for t in found] == ['strict', 'normal', 'loose']
    assert checked == ['normal']
    for gone in ('id="matchMinScore"', 'Use advanced criteria', 'Score Range'):
        assert gone not in tab, gone


def test_an_earlier_own_score_shows_as_custom(setup_complete, monkeypatch):
    from scraper import scraper_manager
    monkeypatch.setattr(scraper_manager, 'load_scraper_settings',
                        lambda: {'minimum_match_score': 250, 'match_mode': 'score'})
    tab = _scraping_tab(_settings_page(monkeypatch, 'admin', '10.59.311.22'))
    assert _checked_strictness(tab)[0] == ['custom']
    monkeypatch.setattr(scraper_manager, 'load_scraper_settings',
                        lambda: {'minimum_match_score': 200, 'match_mode': 'criteria'})
    tab = _scraping_tab(_settings_page(monkeypatch, 'admin', '10.59.311.23'))
    assert _checked_strictness(tab)[0] == ['custom']


def test_my_profile_has_one_save_and_named_saves(setup_complete, monkeypatch):
    """D: one Save per card, and each card's Save names what it saves."""
    html = _settings_page(monkeypatch, 'admin', '10.59.311.24')
    profile = html[html.index('id="profile"'):html.index('id="appearance"')]
    assert profile.count('data-on-click="saveUserSettings"') == 1
    for gone in ('psnQuickSaveAndTest', 'data-on-click="xboxSaveKey"', 'Save My Settings'):
        assert gone not in profile, gone
    assert 'Save Scraper Settings' in _scraping_tab(html)


def test_change_password_says_how_long_and_asks_twice(setup_complete, monkeypatch):
    html = _settings_page(monkeypatch, 'viewer', '10.59.311.25')
    assert 'id="confirmNewPassword"' in html
    assert 'At least 12 characters' in html


def test_controllers_have_their_own_page(setup_complete, monkeypatch):
    """C: Controllers left Settings > Customization for /controllers."""
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    html = _settings_page(monkeypatch, 'editor', '10.59.311.26')
    custom = html[html.index('id="tab-customization"'):]
    assert 'href="/controllers"' in custom
    assert 'id="controllerLibrary"' not in html and 'function loadControllers' not in html
    client, _ = _signed_in_client(_make_user('pass59311-ctrl-ed', role='editor'), '10.59.311.27')
    page = client.get('/controllers')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    for marker in ('id="controllerLibrary"', 'id="systemControllersGrid"',
                   'id="editControllerModal"', 'function loadControllers'):
        assert marker in body, marker
    client, _ = _signed_in_client(_make_user('pass59311-ctrl-vw', role='viewer'), '10.59.311.28')
    assert client.get('/controllers').status_code == 302


def test_ai_model_lists_carry_no_prices(setup_complete, monkeypatch):
    """D: prices go out of date, so the model lists name models only."""
    tab = _scraping_tab(_settings_page(monkeypatch, 'admin', '10.59.311.29'))
    assert 'per 1M tokens' not in tab and 'value="claude-haiku-5-5"' in tab


def test_retroachievements_words_say_what_each_part_is_for(setup_complete, monkeypatch):
    """D: My Profile says what the key and the password sign-in each do; API
    Keys says whose key wins (auth.get_user_ra_credentials,
    platform_sync._get_steam_credentials)."""
    html = _settings_page(monkeypatch, 'admin', '10.59.311.30')
    profile = html[html.index('id="profile"'):html.index('id="appearance"')]
    assert 'show your achievements' in profile and 'unlock achievements while you play' in profile
    keys = html[html.index('id="apikeys"'):]
    assert 'used only for someone who has not added their own' in keys
    assert 'used only for an admin who has not added their own' in keys


def test_plain_words_on_scraping_and_data(setup_complete, monkeypatch):
    """D: TheGamesDB's keys and description, and what Clear Scraped Data does."""
    html = _settings_page(monkeypatch, 'admin', '10.59.311.31')
    for gone in ('Primary online scraper', 'Public API Key', 'Private API Key',
                 'Per-IP rate limit', 'images, etc.)'):
        assert gone not in html, gone
    assert 'TheGamesDB — Main key' in html and 'TheGamesDB — Backup key' in html
    assert 'Also delete the picture and video files' in html


def test_plain_words_on_the_emulators_page(setup_complete, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    client, _ = _signed_in_client(_make_user('pass59311-emu'), '10.59.311.32')
    html = client.get('/settings/emulators').get_data(as_text=True)
    for gone in ('prefixes', 'Flatpak sandbox', 'Binary path override', 'Args template',
                 'placeholder="/mnt/Emulators"'):
        assert gone not in html, gone
    for new in ('Program location', 'Command-line options (advanced)', '/home/you/Emulators'):
        assert new in html, new
