"""PASS-59-111: saving a NEW NPSSO signs in with it at once.

Before, create_psn_client tried the cached session first, so a pasted token
went unused until the old session expired, and "Save & Test" reported the
old session's success. A token Sony refuses must not replace a working one.
No network call is made: PSNAWP is replaced by a fake.
"""
import json
import sqlite3
import time
from types import SimpleNamespace

import pytest

import config

UID = 1  # ADMIN_STUB_USER's id (tests/conftest.py)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    import app  # noqa: F401  (builds the throwaway DB's schema)


def _seed(npsso):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO user_platform_tokens (user_id, platform, tokens, updated_at) "
            "VALUES (?, 'psn', ?, '') "
            "ON CONFLICT(user_id, platform) DO UPDATE SET tokens = excluded.tokens",
            (UID, json.dumps({"refresh_token": "old-session", "access_token": "at",
                              "refresh_token_expires_at": time.time() + 9 * 86400})))
        conn.execute(
            "INSERT INTO user_settings (user_id, psn_npsso) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET psn_npsso = excluded.psn_npsso",
            (UID, npsso))
        conn.commit()
    finally:
        conn.close()


def _stored():
    conn = sqlite3.connect(config.DB_PATH)
    try:
        npsso = conn.execute("SELECT psn_npsso FROM user_settings WHERE user_id = ?",
                             (UID,)).fetchone()[0]
        row = conn.execute("SELECT tokens FROM user_platform_tokens "
                           "WHERE user_id = ? AND platform = 'psn'", (UID,)).fetchone()
        return npsso, (json.loads(row[0]).get("refresh_token") if row else None)
    finally:
        conn.close()


@pytest.fixture
def fake_sony(monkeypatch):
    """Sony accepts any NPSSO except 'refused'; a fresh sign-in gives a
    session named after the NPSSO it came from."""
    import routes.trophies as trophies

    class FakePSN:
        def __init__(self, npsso):
            self.npsso = npsso
            self.authenticator = SimpleNamespace(token_response=None)

        def me(self):
            if self.authenticator.token_response is None:  # fresh sign-in
                if self.npsso == "refused":
                    raise trophies.PSNAWPAuthenticationError("refused")
                self.authenticator.token_response = {
                    "refresh_token": f"session-from-{self.npsso}",
                    "refresh_token_expires_at": time.time() + 60 * 86400}
            return SimpleNamespace(online_id="tester")

    monkeypatch.setattr(trophies, "PSNAWP", FakePSN)


def _save(admin_test_client, npsso):
    client, csrf = admin_test_client()
    return client.post("/api/psn/save-npsso", headers={"X-CSRF-Token": csrf},
                       json={"npsso": npsso, "username": "tester"})


def test_a_new_token_starts_a_new_session(admin_test_client, fake_sony):
    _seed("old-token")
    resp = _save(admin_test_client, "new-token")
    assert resp.get_json()["success"] is True
    assert _stored() == ("new-token", "session-from-new-token")


def test_a_refused_new_token_keeps_the_working_one(admin_test_client, fake_sony):
    _seed("old-token")
    resp = _save(admin_test_client, "refused")
    assert resp.get_json()["success"] is False
    assert _stored() == ("old-token", "old-session")


def test_saving_the_same_token_keeps_the_session(admin_test_client, fake_sony):
    _seed("old-token")
    resp = _save(admin_test_client, "old-token")
    assert resp.get_json()["success"] is True
    assert _stored() == ("old-token", "old-session")


def test_settings_save_with_a_new_token_drops_the_old_session(admin_test_client):
    _seed("old-token")
    client, csrf = admin_test_client()
    client.post("/api/users/settings", headers={"X-CSRF-Token": csrf},
                json={"psn_npsso": "new-token"})
    assert _stored() == ("new-token", None)


def test_settings_save_with_the_same_token_keeps_the_session(admin_test_client):
    _seed("old-token")
    client, csrf = admin_test_client()
    client.post("/api/users/settings", headers={"X-CSRF-Token": csrf},
                json={"psn_npsso": "old-token", "timezone": "UTC"})
    assert _stored() == ("old-token", "old-session")
