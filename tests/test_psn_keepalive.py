"""PSN session keep-alive (Pass 50.1).

Pins the load-bearing behaviour: the keep-alive re-arms a session that is still
valid but approaching expiry, and — per the user requirement — NEVER pings Sony
for a session whose refresh token has already expired, nor for one with plenty of
runway left. It also always uses the refresh-token-only path
(allow_npsso_fallback=False) so it can't ping with a stale NPSSO.
"""

import json
import sqlite3

import pytest

import config


@pytest.fixture(scope="module", autouse=True)
def _schema():
    # Importing app at run time builds the fresh-install schema against the
    # throwaway DB tests/conftest.py points RETRODB_DB_PATH at.
    import app  # noqa: F401


def _seed_psn(uid, npsso, refresh_expires_at):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO user_platform_tokens (user_id, platform, tokens, updated_at) "
            "VALUES (?, 'psn', ?, '') "
            "ON CONFLICT(user_id, platform) DO UPDATE SET tokens = excluded.tokens",
            (uid, json.dumps({
                "refresh_token": "rt", "access_token": "at",
                "refresh_token_expires_at": refresh_expires_at,
            })),
        )
        conn.execute(
            "INSERT INTO user_settings (user_id, psn_npsso) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET psn_npsso = excluded.psn_npsso",
            (uid, npsso),
        )
        conn.commit()
    finally:
        conn.close()


def test_keepalive_only_refreshes_in_window_sessions(monkeypatch):
    from services.jobs import psn_keepalive
    import routes.trophies as trophies

    now = 1_000_000.0
    day = 86400
    # threshold is 14 days; seed one of each state with distinct synthetic uids.
    _seed_psn(7001, "npsso-expired", now - day)        # already expired
    _seed_psn(7002, "npsso-inwindow", now + 7 * day)   # valid, within 14 days
    _seed_psn(7003, "npsso-runway", now + 40 * day)    # valid, plenty of runway

    calls = []

    def fake_create(npsso, user_id=None, allow_npsso_fallback=True):
        calls.append((user_id, allow_npsso_fallback))
        return object(), None

    monkeypatch.setattr(trophies, "create_psn_client", fake_create)
    monkeypatch.setattr(trophies, "PSNAWP_AVAILABLE", True)

    import app as app_module
    with app_module.app.app_context():
        psn_keepalive.run_psn_keepalive(now=now)

    pinged = [uid for uid, _ in calls]
    # The user's hard requirement: an expired session is NEVER pinged.
    assert 7001 not in pinged, "expired session must NOT be pinged"
    # A session with plenty of runway is left alone.
    assert 7003 not in pinged, "session far from expiry must not be pinged"
    # The in-window session IS refreshed, and only via the refresh-token path.
    assert 7002 in pinged, "in-window session should be refreshed"
    assert all(fallback is False for uid, fallback in calls if uid == 7002), \
        "keep-alive must use the refresh-token-only path (no NPSSO ping)"


def test_keepalive_skips_in_window_user_without_npsso(monkeypatch):
    from services.jobs import psn_keepalive
    import routes.trophies as trophies

    now = 2_000_000.0
    _seed_psn(7004, "", now + 5 * 86400)  # in-window but no NPSSO stored

    calls = []
    monkeypatch.setattr(
        trophies, "create_psn_client",
        lambda *a, **k: calls.append(k.get("user_id")) or (object(), None),
    )
    monkeypatch.setattr(trophies, "PSNAWP_AVAILABLE", True)

    import app as app_module
    with app_module.app.app_context():
        psn_keepalive.run_psn_keepalive(now=now)

    assert 7004 not in calls, "no NPSSO stored → can't refresh; must not call client"


def _sony_refuses(monkeypatch, status=400):
    """Answer every request as Sony's sign-in server does when it refuses."""
    from io import BytesIO
    from requests.adapters import HTTPAdapter
    from requests.models import Response

    calls = []

    def fake_send(self, request, **_kwargs):
        calls.append(request.url)
        reply = Response()
        reply.status_code = status
        reply.url = request.url
        reply.request = request
        reply.raw = BytesIO(json.dumps({
            "error": "invalid_grant",
            "error_description": "Invalid refresh token",
        }).encode())
        return reply

    monkeypatch.setattr(HTTPAdapter, "send", fake_send)
    return calls


def _stored_expiry(uid):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute(
            "SELECT tokens FROM user_platform_tokens "
            "WHERE user_id = ? AND platform = 'psn'", (uid,),
        ).fetchone()
    finally:
        conn.close()
    return json.loads(row[0])["refresh_token_expires_at"]


def test_refused_renewal_says_so_and_marks_the_session_expired(monkeypatch):
    # PASS-59-226: Sony's sign-in errors carry a string under "error". The
    # library's error class calls .get on it, which hid Sony's answer behind
    # "'str' object has no attribute 'get'" on every server start.
    import time

    import app as app_module
    from routes.trophies import create_psn_client
    from services.jobs import psn_keepalive

    now = time.time()
    _seed_psn(7005, "npsso-refused", now + 5 * 86400)
    sent = _sony_refuses(monkeypatch)

    with app_module.app.app_context():
        _client, err = create_psn_client(
            "npsso-refused", user_id=7005, allow_npsso_fallback=False,
        )
    assert "Invalid refresh token" in err
    assert "has no attribute" not in err
    # token-info now answers expired, so the dashboard banner asks for a re-link.
    assert _stored_expiry(7005) == 0

    # And the next tick leaves it alone instead of asking Sony again.
    sent.clear()
    with app_module.app.app_context():
        psn_keepalive.run_psn_keepalive()
    assert sent == []


def test_a_server_fault_does_not_end_the_session(monkeypatch):
    import time

    import app as app_module
    from routes.trophies import create_psn_client

    expiry = time.time() + 5 * 86400
    _seed_psn(7006, "npsso-outage", expiry)
    _sony_refuses(monkeypatch, status=503)

    with app_module.app.app_context():
        _client, err = create_psn_client(
            "npsso-outage", user_id=7006, allow_npsso_fallback=False,
        )
    assert err
    assert _stored_expiry(7006) == expiry
