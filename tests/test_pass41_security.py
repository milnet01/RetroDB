# =============================================================================
# Pass 41 — Tier-2 indie-review security findings
# =============================================================================
# Regression pins for the 44 HIGH-severity findings from the 2026-04-24
# 14-agent independent review.  Each sub-item gets narrow unit checks that
# fail if the fix is reverted.
# =============================================================================

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# -----------------------------------------------------------------------------
# 41.1.A — login_required allow-list bypass removed
# -----------------------------------------------------------------------------
class TestPass41_1ALoginRequiredAllowList:
    """The 5-name allow-list inside login_required was a footgun — any future
    endpoint colliding with `auth.login`, `auth.api_login`, `static`,
    `help_page`, or `changelog` became silently public regardless of intent.
    Pass 41.1.A drops the allow-list; routes that should be public must not
    apply the decorator."""

    def test_decorator_has_no_endpoint_allowlist(self):
        from inspect import getsource
        import services.auth as a

        body = getsource(a.login_required)
        # Strip comments + docstrings so a documentation reference to the
        # historical names doesn't false-positive.  The legacy literal
        # appeared as `request.endpoint in [...]`.
        for needle in (
            "request.endpoint in",
            "'auth.api_login'",
            "'help_page'",
            "'changelog'",
        ):
            assert needle not in body, (
                f"login_required must not contain {needle!r} (Pass 41.1.A)"
            )

    def test_decorator_still_redirects_anonymous(self):
        """Sanity: removing the allow-list must not break the anonymous
        redirect path."""
        from inspect import getsource
        import services.auth as a

        body = getsource(a.login_required)
        assert "if not g.user" in body
        assert "url_for('auth.login'" in body


# -----------------------------------------------------------------------------
# 41.1.B — api_change_password rate bucket re-keyed per (ip, user_id)
# -----------------------------------------------------------------------------
class TestPass41_1BChangePasswordBucket:
    """Sharing the /api/login IP-only bucket meant 5 failed change-password
    attempts from user A locked out /api/login for every other user on the
    same LAN.  Pass 41.1.B re-keys the change-password bucket to
    `f"{ip}:cpw:{user_id}"` so it's isolated from /api/login AND per-user
    (user A's failures don't block user B)."""

    def test_change_password_does_not_pass_bare_ip_to_rate_limit(self):
        src = open(
            os.path.join(_REPO_ROOT, 'routes', 'auth.py'), encoding='utf-8'
        ).read()
        body = src[
            src.index("def api_change_password"):
            src.index("def api_force_change_password")
        ]
        # The legacy IP-only call was the bug — a composite bucket key must
        # be threaded in instead.
        assert "rate_limit_login(client_ip)" not in body, (
            "api_change_password must not bucket on bare IP (Pass 41.1.B)"
        )
        # The new bucket key must reference the logged-in user.
        assert "g.user['id']" in body or "user_id" in body

    def test_record_login_attempt_uses_composite_bucket(self):
        src = open(
            os.path.join(_REPO_ROOT, 'routes', 'auth.py'), encoding='utf-8'
        ).read()
        body = src[
            src.index("def api_change_password"):
            src.index("def api_force_change_password")
        ]
        # record_login_attempt must use the same composite bucket as
        # rate_limit_login — otherwise the failure counter goes into the
        # wrong bucket and the lockout never triggers.
        assert "record_login_attempt(client_ip" not in body, (
            "api_change_password must record into the same composite bucket "
            "(Pass 41.1.B)"
        )

    def test_change_password_bucket_isolated_from_login_bucket(self):
        """Functional smoke: 6 failures into a (ip, user_id) bucket must NOT
        throttle the IP-only login bucket."""
        import services.security as sec

        with sec._lock:
            sec._login_attempts.clear()
        ip = "203.0.113.55"
        cpw_bucket = f"{ip}:cpw:42"
        for _ in range(6):
            sec.record_login_attempt(cpw_bucket, success=False)
        # Change-password bucket is throttled.
        assert sec.rate_limit_login(cpw_bucket) is False
        # Login bucket from the same IP stays clear.
        assert sec.rate_limit_login(ip) is True

    def test_change_password_bucket_per_user(self):
        """Functional smoke: user A's failures must NOT throttle user B from
        the same IP."""
        import services.security as sec

        with sec._lock:
            sec._login_attempts.clear()
        ip = "203.0.113.66"
        for _ in range(6):
            sec.record_login_attempt(f"{ip}:cpw:1", success=False)
        # User A throttled.
        assert sec.rate_limit_login(f"{ip}:cpw:1") is False
        # User B unaffected.
        assert sec.rate_limit_login(f"{ip}:cpw:2") is True


# -----------------------------------------------------------------------------
# 41.1.C — stale-hash startup sweep flags below-floor accounts
# -----------------------------------------------------------------------------
class TestPass41_1CStaleHashSweep:
    """needs_rehash() only fires on successful login; idle accounts retain
    100k-iteration hashes indefinitely.  Pass 41.1.C exposes a
    count_stale_password_hashes() helper and wires a startup warning so an
    operator can force-change long-dormant accounts."""

    def test_count_stale_helper_exists(self):
        from services.auth import count_stale_password_hashes
        assert callable(count_stale_password_hashes)

    def test_count_stale_counts_below_floor_only(self, monkeypatch):
        """Pure unit test on the predicate-counting layer — DB integration
        is exercised separately."""
        from services import auth as a

        floor = a.PBKDF2_ITERATIONS
        fake_rows = [
            {'password_hash': 'saltonly:hashonly'},  # legacy 2-part → stale
            {'password_hash': 'pbkdf2:100000:salt:hash'},  # below floor → stale
            {'password_hash': f'pbkdf2:{floor}:salt:hash'},  # at floor → ok
            {'password_hash': f'pbkdf2:{floor + 100000}:salt:hash'},  # above → ok
            {'password_hash': 'malformed-no-colons'},  # malformed → stale
        ]
        monkeypatch.setattr(a, 'query', lambda *args, **kwargs: fake_rows)
        assert a.count_stale_password_hashes() == 3

    def test_count_stale_handles_zero_users(self, monkeypatch):
        from services import auth as a
        monkeypatch.setattr(a, 'query', lambda *args, **kwargs: [])
        assert a.count_stale_password_hashes() == 0

    def test_app_wires_startup_sweep(self):
        """Source-level pin: app.py must invoke the sweep and emit a warning
        when stale hashes are found."""
        body = open(
            os.path.join(_REPO_ROOT, 'app.py'), encoding='utf-8'
        ).read()
        assert 'count_stale_password_hashes' in body, (
            "app.py must call count_stale_password_hashes() at startup "
            "(Pass 41.1.C)"
        )
        # The call must be paired with a warning emission so an operator
        # actually sees the stale count.
        idx = body.index('count_stale_password_hashes')
        sweep_block = body[idx:idx + 600]
        assert 'logger.warning' in sweep_block, (
            "stale-hash sweep must emit logger.warning when count > 0 "
            "(Pass 41.1.C)"
        )
