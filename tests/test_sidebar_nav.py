"""Pass 53.3 — the slimmed sidebar.

The five trophy/achievement links became one "Achievements" link whose pages
share a tab strip, and the link reopens the tab last used. ROM Reports moved
from its own sidebar link into ROM Tools, as one more tool tab. No two sidebar
links share an icon.
"""

import pytest
from bs4 import BeautifulSoup

import app as app_module

app = app_module.app

# The four trophy pages that render without per-system data. The
# RetroAchievements tab's page needs a system with RA games, so it is pinned
# by test_achievement_system_page_has_the_tabs instead.
TROPHY_PAGES = ['/trophies', '/psn-trophies', '/steam-achievements', '/xbox-achievements']
TOOL_PAGES = ['/tools/archive-scanner', '/tools/chd-converter', '/tools/chd-verify',
              '/tools/duplicate-finder', '/tools/multi-disc-organizer',
              '/tools/screenshot-dedup', '/tools/screenshot-review', '/tools/settings']


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 1, 'username': 'admin', 'role': 'admin'})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': '/tmp'})
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['user_id'] = 1
    return c


def _soup(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f'{path} -> {resp.status_code}'
    return BeautifulSoup(resp.get_data(as_text=True), 'html.parser')


def _sidebar_links(soup):
    return soup.select('nav.sidebar-nav a.nav-item')


def _achievements_link(soup):
    links = [a for a in _sidebar_links(soup)
             if a.select_one('.nav-text').get_text(strip=True) == 'Achievements']
    assert len(links) == 1, 'expected exactly one Achievements sidebar link'
    return links[0]


def test_sidebar_has_no_per_platform_trophy_or_reports_links(client):
    hrefs = {a['href'] for a in _sidebar_links(_soup(client, '/help'))}
    gone = {'/trophies', '/psn-trophies', '/steam-achievements',
            '/xbox-achievements', '/reports'}
    assert not hrefs & gone, f'sidebar still links {sorted(hrefs & gone)}'


def test_sidebar_icons_are_unique(client):
    icons = [a.select_one('.nav-icon').get_text(strip=True)
             for a in _sidebar_links(_soup(client, '/help'))]
    dupes = sorted({i for i in icons if icons.count(i) > 1})
    assert not dupes, f'icons used twice: {dupes}'


def test_achievements_link_defaults_to_retroachievements(client):
    assert _achievements_link(_soup(client, '/help'))['href'] == '/achievements'


@pytest.mark.parametrize('page', TROPHY_PAGES)
def test_achievements_link_reopens_the_last_tab(client, page):
    client.get(page)
    assert _achievements_link(_soup(client, '/help'))['href'] == page


@pytest.mark.parametrize('page', TROPHY_PAGES)
def test_trophy_page_has_the_tabs_and_highlights_achievements(client, page):
    soup = _soup(client, page)
    tabs = soup.select('nav.achievement-tabs a.tool-tab')
    assert [t.select_one('.tab-label').get_text(strip=True) for t in tabs] == [
        'RetroAchievements', 'RPCS3', 'PSN', 'Steam', 'Xbox']
    active = [t['href'] for t in tabs if t.get('aria-current') == 'page']
    assert active == [page]
    assert _achievements_link(soup).get('aria-current') == 'page'


def test_achievement_system_page_has_the_tabs():
    src = open('templates/achievements_system.html', encoding='utf-8').read()
    assert "achievement_tabs('retroachievements')" in src


def test_no_retroachievements_games_opens_the_rpcs3_tab(client, monkeypatch):
    monkeypatch.setattr('routes.achievements.query', lambda *a, **k: None)
    resp = client.get('/achievements')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/trophies')


@pytest.mark.parametrize('page', TOOL_PAGES + ['/reports'])
def test_rom_tool_pages_list_rom_reports(client, page):
    soup = _soup(client, page)
    tabs = soup.select('nav.tool-tabs a.tool-tab')
    assert '/reports' in [t['href'] for t in tabs]
    active = [t['href'] for t in tabs if t.get('aria-current') == 'page']
    assert active == [page]


def test_reports_page_highlights_rom_tools(client):
    links = _sidebar_links(_soup(client, '/reports'))
    active = [a.select_one('.nav-text').get_text(strip=True)
              for a in links if a.get('aria-current') == 'page']
    assert active == ['ROM Tools']


def test_rom_tools_hub_has_a_rom_reports_card(client):
    soup = _soup(client, '/tools/')
    assert soup.select_one('a.tool-card[href="/reports"]') is not None


def test_achievements_redirect_script_runs_under_the_csp(client, monkeypatch):
    # /achievements answers with an inline script that reopens the last
    # system; without the request's nonce the CSP blocks it and the page
    # stays blank on "Redirecting...".
    monkeypatch.setattr('routes.achievements.query', lambda *a, **k: {'id': 7})
    resp = client.get('/achievements')
    assert resp.status_code == 200
    csp = resp.headers['Content-Security-Policy']
    nonce = csp.split("'nonce-", 1)[1].split("'", 1)[0]
    script = BeautifulSoup(resp.get_data(as_text=True), 'html.parser').script
    assert script.get('nonce') == nonce
