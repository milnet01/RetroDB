"""PASS-59-246: the last untranslated screen text, and the job-queue panel's escaping."""
import re

from tests._util import read_source


def test_the_job_queue_panel_escapes_system_names():
    """A system name went into innerHTML as it was."""
    html = read_source('templates/base.html')
    assert '${data.system_name ||' not in html
    assert re.search(r"escapeHtml\(data\.system_name \|\| ", html)
    assert re.search(r"const systemName = escapeHtml\(job\.system_name", html)


def _pseudo(fn):
    import app as app_module
    from flask_babel import force_locale
    from services.i18n import PSEUDO_LOCALE
    with app_module.app.test_request_context('/'), force_locale(PSEUDO_LOCALE):
        return fn()


def test_job_errors_set_in_a_thread_are_translated_when_read():
    from services.jobs import platform_sync
    msg = platform_sync.N_('Steam API key or Steam ID not configured')
    assert msg == 'Steam API key or Steam ID not configured'       # stored as written
    assert _pseudo(lambda: platform_sync._say(msg)) != msg          # read in the reader's language
    assert platform_sync._say(msg) == msg                           # no request: as it is


def test_app_replies_are_wrapped():
    src = read_source('app.py')
    for text in ('Not found', 'Internal server error', 'Job not found or already handled',
                 'Invalid or missing CSRF token', 'No games in library',
                 'Setup has already been completed'):
        assert f"'{text}'" not in src.replace(f"_('{text}'", ''), text
    assert 'bulk scrape was interrupted' not in src.replace(
        "_('%(system)s bulk scrape was interrupted", '')


def test_setup_refuses_a_second_run_in_words_not_a_crash(app_client, monkeypatch):
    """A local `import ... as _` later in the function made `_` local, so
    this reply raised UnboundLocalError (caught by ruff F823)."""
    import app as app_module
    monkeypatch.setattr(app_module.settings_manager, 'load_settings',
                        lambda: {'setup_completed': True})
    resp = app_client.post('/api/setup', json={})
    assert resp.status_code == 403, resp.status_code


def test_library_card_text_is_wrapped():
    js = read_source('static/js/all-games-controller.js')
    for label in ('Genre', 'Series', 'Developer', 'Publisher', 'Year'):
        assert f'<span class="meta-label">{label}</span>' not in js, label
    for title in ('Bonus/Extra Disc', 'CLZ Import (No ROM file)', 'Steam Import', 'Xbox Import',
                  'PSN Import', 'Has RetroAchievements', 'Click to filter, Shift+click to exclude'):
        assert f'title="{title}"' not in js, title
    assert '(cross-mapped)`' not in js
    assert 'game #${h.game_id}' not in read_source('static/js/launch-indicator.js')


def test_wrapped_pages_render_in_the_pseudolocale(admin_test_client, monkeypatch):
    """A wrapped template breaks only when its text is translated (a bare `%`
    in a Jinja msgid, say), so render each under the pseudolocale."""
    import os
    import sqlite3
    import app as app_module
    from services.i18n import PSEUDO_LOCALE
    client, _csrf = admin_test_client()
    monkeypatch.setattr(app_module, 'get_user_settings',
                        lambda _uid: {'locale_preference': PSEUDO_LOCALE})
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    list_id = conn.execute("INSERT INTO lists (name, owner_id) VALUES ('p246', 1)").lastrowid
    conn.commit()
    try:
        pages = ['/dashboard', '/tags', '/compare', '/tools/settings', f'/list/{list_id}']
        for page in pages:
            resp = client.get(page)
            assert resp.status_code == 200, (page, resp.status_code)
            assert f'<html lang="{PSEUDO_LOCALE}' in resp.get_data(as_text=True), page
    finally:
        conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
        conn.commit()
        conn.close()


def test_setup_and_game_pages_render_in_the_pseudolocale(admin_test_client, monkeypatch):
    import os
    import sqlite3
    import app as app_module
    from services.i18n import PSEUDO_LOCALE
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT OR IGNORE INTO systems (name, folder) VALUES ('P246', 'p246')")
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p246'").fetchone()[0]
    gid = conn.execute("INSERT INTO games (system_id, title, rom_path, screenshots) "
                       "VALUES (?, 'Zelda', '/roms/p246/z.nes', 'a.webp')", (sid,)).lastrowid
    conn.commit()
    try:
        client, _csrf = admin_test_client()
        monkeypatch.setattr(app_module, 'get_user_settings',
                            lambda _uid: {'locale_preference': PSEUDO_LOCALE})
        resp = client.get(f'/game/{gid}')
        assert resp.status_code == 200
        assert f'<html lang="{PSEUDO_LOCALE}' in resp.get_data(as_text=True)
        client, _csrf = admin_test_client(settings={'setup_completed': False})
        monkeypatch.setattr(app_module, 'get_user_settings',
                            lambda _uid: {'locale_preference': PSEUDO_LOCALE})
        resp = client.get('/setup')
        assert resp.status_code == 200, resp.status_code
        assert f'<html lang="{PSEUDO_LOCALE}' in resp.get_data(as_text=True)
    finally:
        conn.execute("DELETE FROM games WHERE id = ?", (gid,))
        conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
        conn.commit()
        conn.close()


def test_template_text_is_wrapped():
    bare = {
        'templates/setup.html': ['>Welcome to RetroDB<', '>Admin Account<', "'Saving...'"],
        'templates/tags.html': ['>No Tags Yet<', "'Save Changes'"],
        'templates/list_detail.html': ['>Back to Lists<', "'Searching...'"],
        'templates/compare_games.html': ['>Select a Game<', "'No games found.'"],
        'templates/rom_tools_settings.html': ['>General Settings<', '>Save Settings<'],
        'templates/base.html': ['queue-item-title">Running<', "'Multi-System'"],
        'templates/game_detail.html': ['title="Select for hybrid scraping"'],
    }
    def unwrapped(f):
        return re.sub(r"_\('[^']*'", '', read_source(f))
    left = [f'{f}: {text}' for f, texts in bare.items() for text in texts
            if text in unwrapped(f)]
    assert left == []
