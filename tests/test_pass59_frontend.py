"""Pass 59.30-59.40 — the browser/JS findings from the 2026-09-01 review.

Most of these are browser behaviour, so the pins here are the server-side
half: the rendered HTML, the JSON a page consumes, the route map a page's
fetch() calls must resolve against, and the extracted i18n keys. Where the
defect lives only in a JS source file, the pin reads that file with comment
lines stripped, so a comment naming the old pattern cannot satisfy it.
"""
import re
from pathlib import Path

import pytest

from tests._util import delete_rows, read_source

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / 'templates'
JS = ROOT / 'static' / 'js'

_CSRF_TOKEN = 'tok'


def _code(path):
    """Source with `//` and `#`-comment-only lines removed."""
    return '\n'.join(
        line for line in Path(path).read_text(encoding='utf-8').splitlines()
        if not line.lstrip().startswith(('//', '#', '*', '/*'))
    )


def _template_files():
    return sorted(TEMPLATES.rglob('*.html'))


def _page_js_files():
    return sorted(p for p in JS.glob('*.js') if '.bundle.' not in p.name)


@pytest.fixture
def admin_client(monkeypatch):
    import app as app_module
    user = {'id': 1, 'username': 'admin', 'role': 'admin'}
    monkeypatch.setattr('app.get_current_user', lambda: user)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': '/nonexistent'})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF_TOKEN
    return client


@pytest.fixture
def list_with_game():
    """A list holding one game whose title and cover name carry an apostrophe."""
    import uuid
    from services.database import execute, query
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('Pass59 System', f'pass59-{uuid.uuid4().hex}'))
    game_id = execute(
        "INSERT INTO games (system_id, title, rom_path, boxart) VALUES (?, ?, ?, ?)",
        (sys_id, "Assassin's Creed", 'pass59/ac.iso', "Assassin's Creed.png"))
    list_id = execute("INSERT INTO lists (name, owner_id) VALUES (?, ?)", ('Pass59 List', 1))
    execute("INSERT INTO list_games (list_id, game_id, position) VALUES (?, ?, 1)",
            (list_id, game_id))
    yield {'list_id': list_id, 'game_id': game_id}
    delete_rows(('lists', list_id), ('games', game_id), ('systems', sys_id))
    assert query("SELECT 1 FROM games WHERE id = ?", (game_id,), one=True) is None


# ---------------------------------------------------------------------------
# 59.30 / 59.39 — every literal API path the browser calls must exist
# ---------------------------------------------------------------------------

# A file here is known-dead and filed separately; its calls are not live.
_KNOWN_DEAD_JS = {
    'trophies.js',  # loaded by no template — Pass 59.78
}

_CALL = re.compile(
    r"""(?:fetch|API\.(?:get|post|postForm|put|delete))\(\s*([`'"])(/api/[^`'"]*)\1(\s*\+)?""")


def test_every_browser_api_call_hits_a_registered_route():
    """Pass 59.30 — the CLZ page posted to a route that did not exist.

    Generalised: collect every literal `/api/...` path passed to fetch() or
    API.* in templates and page JS, and require a url_map rule matching it.
    `${...}` and `{{ ... }}` segments match any path segment; a literal ending
    in `/` followed by `+` is a concatenated id.
    """
    import app as app_module
    rules = [re.compile('^' + re.sub(r'<[^>]+>', '[^/]+', r.rule) + '$')
             for r in app_module.app.url_map.iter_rules()]
    files = [p for p in _template_files() + _page_js_files() if p.name not in _KNOWN_DEAD_JS]
    missing = []
    for path in files:
        src = path.read_text(encoding='utf-8')
        for m in _CALL.finditer(src):
            url = m.group(2).split('?')[0]
            url = re.sub(r'\$\{[^}]*\}', 'X', url)
            url = re.sub(r'\{\{.*?\}\}', 'X', url)
            if m.group(3) and url.endswith('/'):
                url += 'X'
            if not any(r.match(url) for r in rules):
                line = src[:m.start()].count('\n') + 1
                missing.append(f'{path.relative_to(ROOT)}:{line} {m.group(2)}')
    assert not missing, 'browser calls with no matching route:\n  ' + '\n  '.join(missing)


# ---------------------------------------------------------------------------
# 59.31 — list-detail covers and System column
# ---------------------------------------------------------------------------

def test_list_detail_renders_cover_path_and_system(admin_client, list_with_game):
    resp = admin_client.get(f"/list/{list_with_game['list_id']}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # The cover resolves under /static/images/boxart/, not relative to /list/<id>.
    assert "/static/images/boxart/Assassin&#39;s%20Creed.png" in html
    assert 'Pass59 System' in html


def test_list_games_api_carries_system_name(admin_client, list_with_game):
    resp = admin_client.get(f"/api/lists/{list_with_game['list_id']}/games")
    games = resp.get_json()['games']
    assert games and games[0]['system_name'] == 'Pass59 System'


# ---------------------------------------------------------------------------
# 59.33 / 59.34 — attribute escaping and values inside inline handlers
# ---------------------------------------------------------------------------

def test_list_detail_remove_button_carries_title_as_data(admin_client, list_with_game):
    """Pass 59.34 — `'{{ title|e }}'` inside onclick decodes `&#39;` to a real
    quote before the JS parses, so an apostrophe broke the Remove button."""
    html = admin_client.get(f"/list/{list_with_game['list_id']}").get_data(as_text=True)
    assert 'data-title="Assassin&#39;s Creed"' in html
    assert 'confirmRemoveGame(%d, this.dataset.title)' % list_with_game['game_id'] in html


def test_no_template_defines_its_own_escape_helper():
    """Pass 59.33 — five templates redefined escapeHtml without quote escaping,
    replacing the utils.js version on those pages; three defined an escapeAttr
    that escaped for JS, not HTML."""
    offenders = [str(p.relative_to(ROOT)) for p in _template_files()
                 if re.search(r'function\s+escape(Html|Attr)\s*\(', p.read_text(encoding='utf-8'))]
    assert not offenders, offenders


_HANDLER = re.compile(r'\son[a-z]+="([^"]*)"')
# Escaping idioms that do not survive an HTML attribute: the attribute value is
# entity-decoded before the JS inside it is parsed.
_UNSAFE_IN_HANDLER = re.compile(
    r"""'\{\{(?![^}]*url_for\(|\s*href\s*\}\}|\s*user\.role\s*\}\})"""   # Jinja value in a JS string
    r"""|'\$\{\s*escape(?:Html|Attr)\("""                                  # escapeHtml/escapeAttr in a JS string
    r"""|\.replace\(/'/g""")                                               # quote-only JS escaping


def test_no_untrusted_value_inside_a_js_string_in_a_handler():
    offenders = []
    for path in _template_files():
        for i, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for attr in _HANDLER.findall(line):
                if _UNSAFE_IN_HANDLER.search(attr):
                    offenders.append(f'{path.relative_to(ROOT)}:{i}')
    assert not offenders, 'move the value into a data- attribute:\n  ' + '\n  '.join(offenders)


def test_no_hand_quoted_jinja_value_in_script():
    """Pass 59.32 — a Jinja value in JS must be `|tojson`, not `'{{ x }}'`."""
    offenders = []
    for path in _template_files():
        src = path.read_text(encoding='utf-8')
        for block in re.findall(r'<script\b[^>]*>(.*?)</script>', src, re.S):
            for m in re.finditer(r"""['"]\{\{(?![^}]*tojson)[^}]*\}\}['"]""", block):
                offenders.append(f'{path.relative_to(ROOT)}: {m.group(0)}')
    assert not offenders, offenders


def test_semgrep_template_rules_are_enabled():
    """Pass 59.32 — both waivers rested on anchors that did not say what they
    claimed; the rules are back on, with reviewed sites annotated inline."""
    excludes = (ROOT / '.semgrep-excludes.txt').read_text(encoding='utf-8')
    active = {line.strip() for line in excludes.splitlines()
              if line.strip() and not line.lstrip().startswith('#')}
    assert 'generic.html-templates.security.var-in-script-tag.var-in-script-tag' not in active
    assert ('python.flask.security.xss.audit.template-unescaped-with-safe.'
            'template-unescaped-with-safe') not in active


# ---------------------------------------------------------------------------
# 59.35 — one owner for the settings page
# ---------------------------------------------------------------------------

def test_settings_page_js_no_longer_shadows_the_inline_script():
    src = _code(JS / 'settings-page.js')
    for dead in ('TabController', 'UserManager', 'ScraperConfig', 'SettingsPage',
                 'window.switchSettingsTab'):
        assert dead not in src, dead
    assert 'NormalizationManager' in src


def test_settings_tab_switch_rejects_an_unknown_tab():
    """A stale `settingsActiveTab` used to strip `.active` from every panel."""
    src = _code(TEMPLATES / 'settings.html')
    body = src[src.index('function switchSettingsTab('):]
    body = body[:body.index('\n}\n')]
    guard = body.index("document.getElementById('tab-' + tabId)")
    assert guard < body.index("classList.remove('active')")
    assert 'openSettingsFromHash' in src and "addEventListener('hashchange'" in src


# ---------------------------------------------------------------------------
# 59.36 — shortcut labels reach the catalog
# ---------------------------------------------------------------------------

def test_shortcut_labels_are_extractable_msgids():
    from services.js_i18n_strings import JS_I18N_KEYS
    for msgid in ('Go to Dashboard', 'Focus search box', 'Show keyboard shortcuts',
                  'Navigation', 'Game Page'):
        assert msgid in JS_I18N_KEYS, msgid


# ---------------------------------------------------------------------------
# 59.37 — job-state icons
# ---------------------------------------------------------------------------

def test_job_state_is_the_icon_key_not_the_fallback():
    """`getThemedIcon(type, 'paused')` passed the state as the fallback, so a
    paused, complete or queued toast always showed the running icon."""
    src = _code(JS / 'toast-controller.js')
    assert not re.search(r"getThemedIcon\([^()]*,\s*'(paused|complete|queued)'\)", src)
    for state in ('paused', 'complete', 'queued'):
        assert f"getThemedIcon('{state}')" in src


# ---------------------------------------------------------------------------
# 59.38 — the theme follows the user
# ---------------------------------------------------------------------------

def test_user_theme_rejects_an_unknown_value(admin_client, monkeypatch):
    from services.database import execute, query
    execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (1)")
    headers = {'X-CSRF-Token': _CSRF_TOKEN}
    bad = admin_client.post('/api/users/settings', json={'theme_preference': '"</script>'},
                            headers=headers).get_json()
    assert bad['success'] is False
    ok = admin_client.post('/api/users/settings', json={'theme_preference': 'matrix'},
                           headers=headers).get_json()
    assert ok['success'] is True
    row = query("SELECT theme_preference FROM user_settings WHERE user_id = 1", one=True)
    assert row['theme_preference'] == 'matrix'


@pytest.mark.parametrize('stored, expected', [
    ('bladerunner', '|| "bladerunner"'),
    ('default', '|| null'),          # the column's schema default
    ('"</script>', '|| null'),       # a value written before validation existed
])
def test_fouc_block_falls_back_to_the_users_saved_theme(admin_client, monkeypatch, stored, expected):
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {'theme_preference': stored})
    html = admin_client.get('/help').get_data(as_text=True)
    fouc = html[html.index("localStorage.getItem('retrodb-theme')"):][:120]
    assert expected in fouc


def test_theme_is_saved_per_user():
    src = _code(JS / 'theme.js')
    assert "API.post('/api/users/settings', { theme_preference: theme })" in src
    assert "API.post('/api/settings'" not in src


# ---------------------------------------------------------------------------
# 59.39 / 59.40 — dead code removed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('path, name', [
    ('main.js', 'performGlobalSearch'),
    ('main.js', 'searchGame'),
    ('main.js', 'displayScraperResults'),
    ('game-modals.js', 'updateGameCardInPage'),
])
def test_dead_function_is_gone(path, name):
    assert not re.search(rf'\b{name}\b', _code(JS / path))


def test_dashboard_job_card_reads_only_real_status_keys():
    """Pass 59.82: the dashboard's checkJobs() showed its card when
    `data.status` was 'running', but the bulk-scrape status has no `status`
    key, so the card never appeared. Every key it reads must be one
    get_status() returns."""
    from services.jobs.bulk_scrape import BulkScrapeJob
    src = read_source('templates/dashboard.html')
    body = src[src.index('function checkJobs()'):src.index('checkJobs();')]
    read = set(re.findall(r'\bdata\.([a-z_]+)', body))
    real = set(BulkScrapeJob().get_status()) | {'success'}
    assert read and read <= real, f"keys the endpoint never returns: {sorted(read - real)}"


def test_job_polling_does_not_start_without_a_session(app_client, setup_complete):
    """Pass 59.84: the toast controller polled every job-status endpoint on
    the login page, and each poll logged a 401 in the console. The page
    now says whether anyone is logged in, and init() skips polling if not."""
    html = app_client.get('/login').get_data(as_text=True)
    assert 'window.IS_LOGGED_IN = false' in html
    src = read_source('static/js/toast-controller.js')
    init = src[src.index('    init() {'):src.index('    cleanupOldCompletionKeys()')]
    guard = init.index('IS_LOGGED_IN')
    assert guard < init.index('this.startPolling()')
    assert guard < init.index('this.restoreSavedState()')
