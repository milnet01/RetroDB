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
from collections import OrderedDict

import pytest

# REPO_ROOT/sys.path setup is centralised in tests/_util.py (test-audit DUP-1).
from tests._util import REPO_ROOT, read_source, slice_function


# -----------------------------------------------------------------------------
# 33.1 — ProxyFix env-gated
# -----------------------------------------------------------------------------
def test_33_1_proxyfix_wired_under_flag():
    src = read_source('app.py')
    assert "RETRODB_TRUST_PROXY" in src
    assert "ProxyFix(app.wsgi_app" in src


# -----------------------------------------------------------------------------
# 33.2 — avatar no longer in api_user_settings allowlist
# -----------------------------------------------------------------------------
def test_33_2_avatar_not_in_allowed_fields():
    import ast

    src = read_source(os.path.join('routes', 'auth.py'))
    # Parse the AST and find the `allowed_fields = [...]` assignment
    # inside api_user_settings. AST-level extraction so a nested `]`
    # inside the list (or an `'avatar'` mention in a surrounding
    # comment / docstring) can't false-trigger the check
    # (test-audit ACCURACY fix). The previous `src.index("]", ...)`
    # window terminated at the first `]` which was fine for the list
    # literal, but slicing the whole function body matched stray
    # comment text.
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == 'api_user_settings'),
        None,
    )
    assert fn is not None, "api_user_settings not found in routes/auth.py"
    allowed_fields = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'allowed_fields':
                    allowed_fields = node.value
                    break
        if allowed_fields is not None:
            break
    assert allowed_fields is not None, \
        "allowed_fields = [...] assignment not found in api_user_settings"
    assert isinstance(allowed_fields, ast.List), \
        f"expected allowed_fields to be a list literal, got {type(allowed_fields).__name__}"
    field_names = {
        elt.value for elt in allowed_fields.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    assert 'avatar' not in field_names, (
        f"avatar must not be in api_user_settings.allowed_fields "
        f"(got: {sorted(field_names)})"
    )


# -----------------------------------------------------------------------------
# 33.3 — password length enforced in api_update_user
# -----------------------------------------------------------------------------
def test_33_3_update_user_enforces_length():
    src = read_source(os.path.join('routes', 'auth.py'))
    # AST-slice api_update_user so a future growth past the old `+3000`
    # window can't silently truncate the body and false-pass the check
    # (test-audit ERROR-HANDLING fix).
    body = slice_function(src, 'api_update_user')
    assert body, "api_update_user not found in routes/auth.py"
    assert "len(raw_password) < 12" in body


# -----------------------------------------------------------------------------
# 33.4 — admin-reset sets force_password_change
# -----------------------------------------------------------------------------
def test_33_4_force_change_on_admin_reset():
    src = read_source(os.path.join('routes', 'auth.py'))
    body = slice_function(src, 'api_update_user')
    assert body, "api_update_user not found in routes/auth.py"
    assert "force_password_change = ?" in body
    assert "skip_force_change" in body


# -----------------------------------------------------------------------------
# 33.5 — session rotation + fresh CSRF token on password change
# -----------------------------------------------------------------------------
@pytest.mark.parametrize('fn', ['api_change_password', 'api_force_change_password'])
def test_33_5_session_rotation_on_change_password(fn):
    """Each function gets its own test node so pytest's output names the
    failing branch explicitly (test-audit SPLIT-4)."""
    src = read_source(os.path.join('routes', 'auth.py'))
    body = slice_function(src, fn)
    assert body, f"{fn} not found in routes/auth.py"
    assert "session.clear()" in body, f"{fn} missing session.clear()"
    assert "session['_csrf_token']" in body, f"{fn} missing CSRF rotation"


# -----------------------------------------------------------------------------
# 33.6 — logout wipes the whole session
# -----------------------------------------------------------------------------
def test_33_6_logout_clears_session(monkeypatch):
    """Functional: hitting /logout must clear all session state, not just
    pop user_id. We seed an unrelated session key, log out, and verify it's
    also gone — proving session.clear() ran instead of a selective pop.

    Use `monkeypatch.setitem` for the TESTING flag so the shared app
    singleton's config is restored on test exit (test-audit ISO-3)."""
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
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
    """Anchor to the exact return-construction (`csrf_token=_ensure_csrf`)
    so the assertion can't pass from a `csrf_token=None` assignment, a
    comment, or an unrelated variable name (test-audit ASSERT-4)."""
    src = read_source(os.path.join('routes', 'auth.py'))
    body = src[src.index("def api_login"):src.index("def logout")]
    # The success() call hands back the freshly-minted token explicitly —
    # this is the line that wires the value into the JSON envelope.
    assert "csrf_token=_ensure_csrf" in body, (
        "api_login must return the minted token via "
        "`return success(..., csrf_token=_ensure_csrf)` so clients can "
        "refresh a pre-login token without an extra GET round-trip"
    )


# -----------------------------------------------------------------------------
# 33.9 — rate limiter is OrderedDict-based
# -----------------------------------------------------------------------------
def test_33_9_rate_limiter_is_ordered_dict():
    import services.security as sec
    assert isinstance(sec._login_attempts, OrderedDict)


def test_33_9_rate_limit_functional(monkeypatch):
    """The rate-limiter must trip after MAX_ATTEMPTS=5 failures and reset
    on a successful login.

    Swap in a fresh OrderedDict for the duration of the test so the inline
    `.clear()` is no longer needed and post-test state can't leak into
    subsequent tests (test-audit ISO-2).
    """
    import services.security as sec

    monkeypatch.setattr(sec, '_login_attempts', OrderedDict())

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
    src = read_source('app.py')
    assert 'def log_to_category' not in src
    # system_log MAY appear as the name inside the deletion comment; check
    # that no function is defined.
    assert '\ndef system_log(' not in src


def test_34_3_log_manager_zombie_helpers_removed():
    src = read_source('log_manager.py')
    for name in ('get_scraping_log_files', 'log_scraping', 'log_rom_tools', 'log_rom_reports'):
        assert f'def {name}(' not in src, f'{name} should have been removed'


# -----------------------------------------------------------------------------
# 34.4 — rate limiter lookup raises on missing endpoint
# -----------------------------------------------------------------------------
def test_34_4_rate_limiter_helper_hard_fails():
    """The helper exists and fails loud when endpoint is missing. We can't
    easily import app.py twice, so rely on a source-level check.
    """
    src = read_source('app.py')
    body = slice_function(src, '_rate_limit')
    assert body, "_rate_limit not found in app.py"
    assert "raise RuntimeError" in body


# -----------------------------------------------------------------------------
# 34.5 — log rollover uses UTC
# -----------------------------------------------------------------------------
def test_34_5_log_filename_uses_utc(monkeypatch):
    """Functional: get_log_filename must produce the same date stamp
    regardless of the local timezone — i.e. it derives the date from UTC.

    The fake datetime subclass overrides `now`, `utcnow`, AND `today` so
    the test still pins the contract even if `get_log_filename` is ever
    refactored to call a different entry point (test-audit FLAKY-1).
    `freezegun` would be a cleaner one-stop substitute but isn't a project
    dependency.
    """
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

        @classmethod
        def utcnow(cls):
            # Naive UTC clock — matches stdlib's deprecated utcnow shape.
            return fixed_utc.replace(tzinfo=None)

        @classmethod
        def today(cls):
            # `today()` historically returns local midnight; reflect the
            # +02:00 skew we use for `now(None)` so test stays internally
            # consistent.
            return fixed_utc.astimezone(timezone(timedelta(hours=2))).replace(tzinfo=None)

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
    src = read_source('app.py')
    # inject_config should not emit asset_url via the context-processor dict.
    inject_body = slice_function(src, 'inject_config')
    assert inject_body, "inject_config not found in app.py"
    # The bare key mapping must be gone — this is the load-bearing
    # contract. (Previous version also asserted a comment marker; that
    # was comment-as-proof and got removed in the test-audit fix-pass.)
    assert "'asset_url': asset_url" not in inject_body
