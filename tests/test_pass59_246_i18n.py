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
