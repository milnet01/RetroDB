# =============================================================================
# Pass 33 + 34 — auth / session hardening + response envelope round 2
# =============================================================================
# Pass 45.21 audit (2026-04-27): converted 33.6 logout-clear (functional
# session check), 34.5 UTC log filename (functional clock-pin) to behavior
# tests. Remaining source-grep tests pin: avatar allowlist exclusion,
# password-length checks in api_update_user, force_password_change flag,
# session.clear()+CSRF rotation pattern across two functions, csrf_token
# in /api/login response shape, zombie-helpers removed (codebase invariant),
# rate-limiter raises RuntimeError on missing endpoint, asset_url
# context-processor removal — all kept because the functional alternative
# requires multi-role DB seeding or app re-init.
# =============================================================================

import os
import sys


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# -----------------------------------------------------------------------------
# 33.2 — avatar no longer in api_user_settings allowlist
# -----------------------------------------------------------------------------
def test_33_2_avatar_not_in_allowed_fields():
    src = open(os.path.join(_REPO_ROOT, 'routes', 'auth.py'), encoding='utf-8').read()
    # The allowlist string must not contain 'avatar'.
    # Extract the allowed_fields list literal and verify.
    start = src.index("allowed_fields = [")
    end = src.index("]", start)
    literal = src[start:end + 1]
    assert "'avatar'" not in literal and '"avatar"' not in literal


# -----------------------------------------------------------------------------
# 33.3 — password length enforced in api_update_user
# -----------------------------------------------------------------------------
def test_33_3_update_user_enforces_length():
    src = open(os.path.join(_REPO_ROOT, 'routes', 'auth.py'), encoding='utf-8').read()
    # Find api_update_user and confirm the 12-char check is present after the
    # new_password branch.
    start = src.index("def api_update_user")
    body = src[start:start + 3000]
    assert "len(raw_password) < 12" in body


# -----------------------------------------------------------------------------
# 33.4 — admin-reset sets force_password_change
# -----------------------------------------------------------------------------
def test_33_4_force_change_on_admin_reset():
    src = open(os.path.join(_REPO_ROOT, 'routes', 'auth.py'), encoding='utf-8').read()
    start = src.index("def api_update_user")
    body = src[start:start + 3000]
    assert "force_password_change = ?" in body
    assert "skip_force_change" in body


# -----------------------------------------------------------------------------
# 33.5 — session rotation + fresh CSRF token on password change
# -----------------------------------------------------------------------------
def test_33_5_session_rotation_on_change_password():
    src = open(os.path.join(_REPO_ROOT, 'routes', 'auth.py'), encoding='utf-8').read()
    # Both api_change_password and api_force_change_password must call
    # session.clear() after the UPDATE and mint a fresh CSRF token.
    for fn in ("api_change_password", "api_force_change_password"):
        body = src[src.index(f"def {fn}"):src.index(f"def {fn}") + 2500]
        assert "session.clear()" in body, f"{fn} missing session.clear()"
        assert "session['_csrf_token']" in body, f"{fn} missing CSRF rotation"


# -----------------------------------------------------------------------------
# 33.6 — logout wipes the whole session
# -----------------------------------------------------------------------------
def test_33_6_logout_clears_session():
    """Functional: hitting /logout must clear all session state, not just
    pop user_id. We seed an unrelated session key, log out, and verify it's
    also gone — proving session.clear() ran instead of a selective pop."""
    import app as app_module
    app_module.app.config['TESTING'] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['unrelated_key'] = 'should be wiped on logout'
    client.get('/logout', follow_redirects=False)
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
        assert 'unrelated_key' not in sess, (
            "Pass 33.6 — logout must call session.clear() to wipe ALL keys, "
            "not just session.pop('user_id')"
        )


# -----------------------------------------------------------------------------
# 33.8 — api_login returns csrf_token in success body
# -----------------------------------------------------------------------------
def test_33_8_login_returns_csrf_token():
    src = open(os.path.join(_REPO_ROOT, 'routes', 'auth.py'), encoding='utf-8').read()
    body = src[src.index("def api_login"):src.index("def logout")]
    assert "csrf_token=" in body


# -----------------------------------------------------------------------------
# 33.9 — rate limiter is OrderedDict-based
# -----------------------------------------------------------------------------
def test_33_9_rate_limiter_is_ordered_dict():
    import services.security as sec
    from collections import OrderedDict
    assert isinstance(sec._login_attempts, OrderedDict)


def test_33_9_rate_limit_functional():
    import services.security as sec

    # Reset the shared state for a deterministic test.
    with sec._lock:
        sec._login_attempts.clear()

    ip = '203.0.113.99'
    # 4 failures — still allowed.
    for _ in range(4):
        assert sec.rate_limit_login(ip) is True
        sec.record_login_attempt(ip, success=False)
    # 5th failure pushes us over MAX_ATTEMPTS=5.
    sec.record_login_attempt(ip, success=False)
    assert sec.rate_limit_login(ip) is False

    # Recorded successfully — counter clears.
    sec.record_login_attempt(ip, success=True)
    assert sec.rate_limit_login(ip) is True


# -----------------------------------------------------------------------------
# 33.10 — SecretRedactor handles dict args (post-render)
# -----------------------------------------------------------------------------
def test_33_10_redactor_handles_dict_args():
    import logging
    from services.log_redactor import SecretRedactor

    record = logging.LogRecord(
        name='test', level=logging.INFO, pathname='x.py', lineno=1,
        msg="body=%r",
        args=({'access_token': 'AAAAABBBBBCCCCCDDDDDEEEEEFFFFFGGGGG'},),
        exc_info=None,
    )
    SecretRedactor().filter(record)
    rendered = record.getMessage() if record.args else record.msg
    assert 'AAAAABBBBBCCCCCDDDDD' not in rendered
    assert '<redacted>' in rendered


def test_33_10_hex_rule_no_longer_clobbers_git_sha():
    from services.log_redactor import redact

    # A bare 40-char git SHA in the middle of a log line must NOT be
    # replaced any more — the hex rule is now gated to a named-secret
    # context.
    sha = 'f901a8f6bd7156f8a12d9912cbeefdead1234567'
    msg = f"Commit {sha} rolled out"
    assert sha in redact(msg)

    # A 40-char hex after `hash=` IS still redacted.
    msg2 = f"hash={sha}"
    assert sha not in redact(msg2)
    assert '<redacted-hex>' in redact(msg2)


# -----------------------------------------------------------------------------
# 34.3 — zombie helpers removed
# -----------------------------------------------------------------------------
def test_34_3_app_zombie_helpers_removed():
    src = open(os.path.join(_REPO_ROOT, 'app.py'), encoding='utf-8').read()
    assert 'def log_to_category' not in src
    # system_log MAY appear as the name inside the deletion comment; check
    # that no function is defined.
    assert '\ndef system_log(' not in src


def test_34_3_log_manager_zombie_helpers_removed():
    src = open(os.path.join(_REPO_ROOT, 'log_manager.py'), encoding='utf-8').read()
    for name in ('get_scraping_log_files', 'log_scraping', 'log_rom_tools', 'log_rom_reports'):
        assert f'def {name}(' not in src, f'{name} should have been removed'


# -----------------------------------------------------------------------------
# 34.4 — rate limiter lookup raises on missing endpoint
# -----------------------------------------------------------------------------
def test_34_4_rate_limiter_helper_hard_fails():
    """The helper exists and fails loud when endpoint is missing. We can't
    easily import app.py twice, so rely on a source-level check.
    """
    src = open(os.path.join(_REPO_ROOT, 'app.py'), encoding='utf-8').read()
    assert 'def _rate_limit(' in src
    assert "raise RuntimeError" in src[src.index("def _rate_limit("):src.index("def _rate_limit(") + 1500]


# -----------------------------------------------------------------------------
# 34.5 — log rollover uses UTC
# -----------------------------------------------------------------------------
def test_34_5_log_filename_uses_utc(monkeypatch):
    """Functional: get_log_filename must produce the same date stamp
    regardless of the local timezone — i.e. it derives the date from UTC."""
    from datetime import datetime, timezone, timedelta
    import log_manager

    # Pin the wall-clock to a moment that's on different sides of midnight
    # in different timezones — 2026-04-27T23:30:00+00:00 is still 2026-04-27
    # in UTC but 2026-04-28 in UTC+02:00.
    fixed_utc = datetime(2026, 4, 27, 23, 30, 0, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                # Local time at UTC+02:00 would render as next-day midnight.
                return fixed_utc.astimezone(timezone(timedelta(hours=2))).replace(tzinfo=None)
            return fixed_utc.astimezone(tz)

    monkeypatch.setattr(log_manager, 'datetime', _FixedDateTime)
    fname = log_manager.get_log_filename('test')
    assert '2026-04-27' in fname, (
        f"Log filename must use UTC date (expected 2026-04-27 from "
        f"23:30 UTC); got {fname!r}"
    )


# -----------------------------------------------------------------------------
# 34.6 — asset_url single source of truth
# -----------------------------------------------------------------------------
def test_34_6_asset_url_not_in_inject_config():
    src = open(os.path.join(_REPO_ROOT, 'app.py'), encoding='utf-8').read()
    # inject_config should not emit asset_url via the context-processor dict.
    # Our Pass 34.6 comment lives where the dict entry used to be.
    inject_start = src.index("def inject_config")
    inject_body = src[inject_start:inject_start + 3000]
    # Comment present = removal landed.
    assert "Pass 34.6" in inject_body
    # And the bare key mapping is gone.
    assert "'asset_url': asset_url" not in inject_body


# -----------------------------------------------------------------------------
# 33.1 — ProxyFix env-gated
# -----------------------------------------------------------------------------
def test_33_1_proxyfix_wired_under_flag():
    src = open(os.path.join(_REPO_ROOT, 'app.py'), encoding='utf-8').read()
    assert "RETRODB_TRUST_PROXY" in src
    assert "ProxyFix(app.wsgi_app" in src
