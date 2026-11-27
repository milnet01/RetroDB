"""PASS-59-342: each person can turn the scan lines off.

The choice is user_settings.hide_scanlines, saved through /api/users/settings,
and every page then carries body.scanlines-off, which the CSS hides the lines
with.
"""
import os
import sqlite3

import pytest

import config

UID = 1  # ADMIN_STUB_USER's id (tests/conftest.py)


@pytest.fixture(scope='module', autouse=True)
def _schema():
    import app  # noqa: F401  (builds the throwaway DB's schema)


def _stored():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute("SELECT hide_scanlines FROM user_settings WHERE user_id = ?", (UID,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


@pytest.fixture
def client(admin_test_client):
    client, csrf = admin_test_client()
    yield client, {'X-CSRF-Token': csrf}
    client.post('/api/users/settings', json={'hide_scanlines': False}, headers={'X-CSRF-Token': csrf})


def test_the_switch_saves_for_the_person(client):
    c, headers = client
    assert c.post('/api/users/settings', json={'hide_scanlines': True}, headers=headers).status_code == 200
    assert _stored() == 1
    assert c.post('/api/users/settings', json={'hide_scanlines': False}, headers=headers).status_code == 200
    assert _stored() == 0


@pytest.mark.parametrize('bad', ['yes', 1, None])
def test_only_true_or_false_is_saved(client, bad):
    c, headers = client
    resp = c.post('/api/users/settings', json={'hide_scanlines': bad}, headers=headers)
    assert resp.status_code == 422


@pytest.mark.parametrize('hidden', [True, False])
def test_every_page_carries_the_choice(admin_test_client, monkeypatch, hidden):
    import app as app_module
    import settings_manager
    real_settings = app_module.get_user_settings  # the fixture stubs it to None
    client, csrf = admin_test_client(settings=dict(settings_manager.DEFAULT_SETTINGS, setup_completed=True))
    monkeypatch.setattr(app_module, 'get_user_settings', real_settings)
    headers = {'X-CSRF-Token': csrf}
    try:
        client.post('/api/users/settings', json={'hide_scanlines': hidden}, headers=headers)
        resp = client.get('/settings')
        html = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert ('class="scanlines-off"' in html) == hidden
        assert ('id="scanlinesToggle" checked' in html) == (not hidden)
    finally:
        client.post('/api/users/settings', json={'hide_scanlines': False}, headers=headers)


def test_the_css_hides_the_lines():
    from tests._util import REPO_ROOT
    css = open(os.path.join(REPO_ROOT, 'static', 'css', 'effects', 'backgrounds.css'), encoding='utf-8').read()
    assert 'body.scanlines-off::after {\n    display: none;' in css
