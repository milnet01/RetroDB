# Pass 25 — input hardening / SSRF / size caps regression coverage.
#
# Each class pins one sub-item's invariant. These are narrow unit checks —
# they're not trying to reproduce the full end-to-end flow, only to ensure
# the guard is in place and rejects the value it's supposed to reject.
#
# Split by subsystem so the Flask app import only fires where a test needs it:
#   test_input_hardening_app.py      — 25.2 reports whitelist, 25.9 rate limits
#   test_input_hardening_scrapers.py — 25.1 ES-DE path traversal, 25.7 download caps
#   test_input_hardening_museum.py   — 25.3 SSRF guard, 25.4 upload cap
#   test_input_hardening_uploads.py  — 25.5 CLZ PDF bounds, 25.6 video cap, 25.8 row caps

import pytest


# 25.2 — /api/reports system whitelist
# -------------------------------------
# The multidisc-scan endpoint now returns 400 for an unknown system.
class TestReportsSystemWhitelist:
    def test_unknown_system_returns_400(self, monkeypatch):
        import app as app_module
        # Use monkeypatch.setitem so TESTING is automatically restored after
        # the test — never leak the mutation onto the shared app.config object
        # for sibling tests (xdist-safe).
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        # Bypass the first-time-setup redirect: on a fresh CI checkout
        # `settings_manager.load_settings()` returns `setup_completed=False`
        # and `rom_path=''`, which the before-request middleware then redirects
        # to `/setup` (302), defeating the whitelist assertion below. Stub
        # both settings and `get_current_user` so the auth+setup path lets
        # the request reach the whitelist check.
        monkeypatch.setattr('app.get_current_user',
                            lambda: {'id': 1, 'username': 'admin', 'role': 'admin'})
        monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
        monkeypatch.setattr('app.settings_manager.load_settings',
                            lambda: {'setup_completed': True, 'rom_path': '/tmp'})
        client = app_module.app.test_client()
        # Inject a session that satisfies both the @login_required guard
        # (user_id present) and the @app.before_request CSRF token check
        # (_csrf_token + matching X-CSRF-Token header on POST).
        csrf_token = 'test-csrf-token'
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['_csrf_token'] = csrf_token
        resp = client.post(
            '/api/reports/multidisc-scan',
            json={'system': '../../etc'},
            headers={'X-CSRF-Token': csrf_token},
        )
        # 400 = whitelist working. If 302/403 shows up the auth/CSRF bypass
        # isn't taking — that's a setup gap to fix, not a reason to widen
        # this assertion.
        assert resp.status_code == 400


# 25.9 — Rate limits registered
# ------------------------------
class TestRateLimits:
    def test_expected_endpoints_rate_limited(self):
        """Verify limiter has entries for Pass 25.9 targets."""
        import app as app_module
        if not app_module.limiter:
            pytest.skip('flask-limiter not installed')
        # Each view must carry a registered limit under the name the limiter
        # looks up at request time. Removing the _rate_limit(...) call (or
        # discarding the wrapper, Pass 59.73) leaves the list empty.
        funcs = app_module.app.view_functions
        expected = {
            'games_hltb.api_hltb_lookup': 'hour',
            'museum.generate_system': 'hour',
            'collector_trophies.refresh_trophies': 'hour',
        }
        for endpoint, unit in expected.items():
            view = funcs[endpoint]
            name = f"{view.__module__}.{view.__name__}.{view.__name__}"
            limits = app_module.limiter.limit_manager.decorated_limits(name)
            assert limits, f"{endpoint}: no rate limit registered under {name}"
            assert any(unit in str(lim.limit) for lim in limits), (
                f"{endpoint}: limits {[str(l.limit) for l in limits]}")
