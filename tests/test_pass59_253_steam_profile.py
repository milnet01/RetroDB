"""PASS-59-253: a member saves their own Steam key and Steam ID in Profile,
and their Steam sync then uses them."""
import sqlite3

import pytest

import config

MEMBER = {'id': 9253, 'username': 'steam-member', 'role': 'viewer'}


@pytest.fixture
def member(admin_test_client):
    import app  # noqa: F401  (builds the throwaway DB's schema)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("INSERT OR IGNORE INTO users (id, username, role) VALUES (?, ?, ?)",
                 (MEMBER['id'], MEMBER['username'], MEMBER['role']))
    conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (MEMBER['id'],))
    conn.commit()
    client, csrf = admin_test_client(user=MEMBER)
    yield client, csrf, conn
    conn.execute("DELETE FROM user_settings WHERE user_id = ?", (MEMBER['id'],))
    conn.execute("DELETE FROM users WHERE id = ?", (MEMBER['id'],))
    conn.commit()
    conn.close()


def _save(client, csrf, **fields):
    return client.post('/api/users/settings', json=fields, headers={'X-CSRF-Token': csrf})


def test_a_member_saves_their_own_steam_key_and_id(member):
    from services.jobs.platform_sync import _get_steam_credentials
    client, csrf, conn = member
    reply = _save(client, csrf, steam_api_key='MEMBERKEY', steam_id='76561198012345678')
    assert reply.get_json()['success']
    assert _get_steam_credentials(user_id=MEMBER['id']) == ('MEMBERKEY', '76561198012345678')


def test_a_steam_id_that_is_not_a_number_is_refused(member):
    client, csrf, conn = member
    reply = _save(client, csrf, steam_id='my-vanity-name')
    assert reply.status_code == 422
    stored = conn.execute("SELECT steam_id FROM user_settings WHERE user_id = ?",
                          (MEMBER['id'],)).fetchone()[0]
    assert stored in (None, '')


def test_profile_shows_the_steam_boxes(monkeypatch):
    from tests.test_i18n import VIEWER, _settings_page
    soup = _settings_page(monkeypatch, VIEWER,
                          {'steam_api_key': 'MEMBERKEY', 'steam_id': '76561198012345678'})
    key = soup.select_one('#userSteamApiKey')
    # Only a mask of the stored key reaches the page (PASS-59-295).
    assert key['type'] == 'password' and key['value'] == '***RKEY'
    assert soup.select_one('#userSteamId')['value'] == '76561198012345678'
    assert "document.getElementById('userSteamApiKey')" in str(soup)
