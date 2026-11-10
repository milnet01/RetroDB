"""PASS-59-295: My Profile never sends a stored key back to the browser.

The RetroAchievements key, PSN NPSSO and Steam key were rendered whole into
the Settings page. They now show as the Scraping tab's keys do, `***<last4>`,
and a save or a PSN test that echoes that mask keeps the stored key.
"""
import sqlite3

import pytest

import config

UID = 1  # ADMIN_STUB_USER's id (tests/conftest.py)
KEYS = {
    'ra_api_key': 'ra-secret-key-1234',  # gitleaks:allow — synthetic test value
    'psn_npsso': 'npsso-secret-token-abcd',  # gitleaks:allow — synthetic test value
    'steam_api_key': 'steam-secret-key-wxyz',  # gitleaks:allow — synthetic test value
}
MASKS = {'ra_api_key': '***1234', 'psn_npsso': '***abcd', 'steam_api_key': '***wxyz'}


@pytest.fixture(scope='module', autouse=True)
def _schema():
    import app  # noqa: F401  (builds the throwaway DB's schema)


@pytest.fixture
def stored_keys():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO user_settings (user_id, ra_api_key, psn_npsso, steam_api_key) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
            "ra_api_key = excluded.ra_api_key, psn_npsso = excluded.psn_npsso, "
            "steam_api_key = excluded.steam_api_key",
            (UID, KEYS['ra_api_key'], KEYS['psn_npsso'], KEYS['steam_api_key']))
        conn.commit()
    finally:
        conn.close()
    return KEYS


def _stored():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute(
            "SELECT ra_api_key, psn_npsso, steam_api_key FROM user_settings "
            "WHERE user_id = ?", (UID,)).fetchone()
        return dict(zip(KEYS, row))
    finally:
        conn.close()


def test_settings_page_shows_masks_not_keys(stored_keys, admin_test_client, monkeypatch):
    import app as app_module
    from settings_manager import DEFAULT_SETTINGS
    client, _csrf = admin_test_client(
        settings={**DEFAULT_SETTINGS, 'setup_completed': True})
    monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: dict(stored_keys))
    resp = client.get('/settings')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    for field, key in stored_keys.items():
        assert key not in html, field
        assert f'value="{MASKS[field]}"' in html, field


def test_settings_api_returns_masks_not_keys(stored_keys, admin_test_client):
    client, _csrf = admin_test_client()
    settings = client.get('/api/users/settings').get_json()['settings']
    for field in KEYS:
        assert settings[field] == MASKS[field]


def test_saving_the_masks_keeps_the_stored_keys(stored_keys, admin_test_client):
    client, csrf = admin_test_client()
    resp = client.post('/api/users/settings', headers={'X-CSRF-Token': csrf},
                       json=dict(MASKS))
    assert resp.status_code == 200
    assert _stored() == stored_keys


def test_clearing_a_box_still_clears_its_key(stored_keys, admin_test_client):
    client, csrf = admin_test_client()
    client.post('/api/users/settings', headers={'X-CSRF-Token': csrf},
                json={**MASKS, 'steam_api_key': ''})
    assert _stored() == {**stored_keys, 'steam_api_key': ''}


def test_psn_test_with_the_mask_uses_the_stored_token(stored_keys, admin_test_client,
                                                      monkeypatch):
    import routes.trophies as trophies
    seen = []

    def fake_client(npsso, use_cache=True):
        seen.append(npsso)
        return None, 'stop here'
    monkeypatch.setattr(trophies, 'create_psn_client', fake_client)

    client, csrf = admin_test_client()
    client.post('/api/psn/save-npsso', headers={'X-CSRF-Token': csrf},
                json={'npsso': MASKS['psn_npsso'], 'username': ''})
    assert seen == [stored_keys['psn_npsso']]
