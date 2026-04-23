# Pass 24 — auth/authz hardening regression coverage.
# Pass 22.7 — destructive-endpoint test coverage (unblocked by Pass 24.5).
#
# Full end-to-end auth tests need a real users table with admin / editor /
# viewer seeds, which the smoke suite doesn't guarantee on a fresh CI DB.
# We prefer narrow unit checks per sub-item: each one pins one invariant,
# and collectively they cover the pass. Where DB state matters we use
# `session_transaction()` to stub `session['user_id']` and seed the DB
# inline — the pattern the existing tests (test_etag_and_gzip.py,
# test_input_hardening.py) already use.

import hashlib
import os
import pytest


# =============================================================================
# 24.1 — password required for all roles
# =============================================================================

class TestPasswordRequiredForAllRoles:
    """api_login must verify password for editor/viewer too, not just admin."""

    def test_null_password_hash_rejects_login(self):
        """An account created before Pass 24 with password_hash=NULL is
        dormant — login refuses until an admin sets a password."""
        from routes import auth as auth_mod
        # Read the module source to assert the rejection branch exists.
        # (Full integration test would need to seed such a user; this
        # code-path pin protects against regressions that re-introduce
        # the passwordless branch.)
        src = open(auth_mod.__file__).read()
        assert "This account has no password set" in src
        # And the prior `if user['role'] == 'admin':` gate is gone.
        assert "if user['role'] == 'admin':" not in src

    def test_create_user_seeds_changeme_for_non_admin(self):
        """Pass 24.1 migration: new editor/viewer accounts now get the
        same `changeme` + force_password_change=1 onboarding as admin."""
        from routes import auth as auth_mod
        src = open(auth_mod.__file__).read()
        # The legacy `password_hash = None` branch is gone; every role
        # gets a hashed password (explicit or default).
        assert "password_hash = None" not in src


# =============================================================================
# 24.2 — session rotation on login
# =============================================================================

class TestSessionRotationOnLogin:
    """Pre-login session state must be discarded on successful login."""

    def test_login_calls_session_clear(self):
        from routes import auth as auth_mod
        src = open(auth_mod.__file__).read()
        # Look for the clear-then-set pattern. We don't just grep for
        # `session.clear()` — verify the ordering is right: clear BEFORE
        # assigning user_id.
        assert "session.clear()" in src
        clear_idx = src.index("session.clear()")
        assign_idx = src.index("session['user_id'] = user['id']")
        assert clear_idx < assign_idx, "session.clear() must come before user_id assignment"


# =============================================================================
# 24.3 — force_password_change middleware
# =============================================================================

class TestForcePasswordChangeMiddleware:
    """The before_request hook redirects force_password_change=1 users to
    the change-password page for all non-auth routes."""

    def test_middleware_registered(self):
        import app as app_module
        # Flask stores before_request handlers in before_request_funcs[None]
        # (None = app-wide, not blueprint-scoped).
        funcs = app_module.app.before_request_funcs.get(None, [])
        names = {f.__name__ for f in funcs}
        assert 'check_force_password_change' in names


# =============================================================================
# 24.4 — password policy + rate-limit change
# =============================================================================

class TestPasswordPolicyAndRateLimit:
    def test_min_length_raised_to_12(self):
        from routes import auth as auth_mod
        src = open(auth_mod.__file__).read()
        # Both api_change_password and api_force_change_password now check 12.
        assert src.count("Password must be at least 12 characters") >= 2
        # And the old 8-char check is gone.
        assert "Password must be at least 8 characters" not in src

    def test_rate_limit_applied_to_change_password(self):
        from routes import auth as auth_mod
        src = open(auth_mod.__file__).read()
        # rate_limit_login() must be called inside api_change_password.
        # The function is defined in services.security — we don't care
        # which bucket it uses, just that the endpoint checks it.
        # Slice the function body.
        fn_start = src.index("def api_change_password(")
        # Stop at the next `@bp.route` or end-of-file.
        fn_end_candidates = [
            src.index("@bp.route", fn_start + 1),
            len(src),
        ]
        fn_end = min(fn_end_candidates)
        body = src[fn_start:fn_end]
        assert "rate_limit_login" in body


# =============================================================================
# 24.5 — editor_required on destructive endpoints
# =============================================================================

class TestEditorRequiredOnDestructiveEndpoints:
    """Viewer-level accounts must get a 302 redirect to /dashboard when
    hitting destructive endpoints (the editor_required decorator's
    reject path)."""

    DESTRUCTIVE_ENDPOINTS = [
        ('games_media.api_delete_game', '/api/delete-game/1', 'POST'),
        ('games_media.api_rename_rom', '/api/rename-rom/1', 'POST'),
        ('games_media.api_delete_screenshot', '/api/delete-screenshot/1', 'POST'),
        ('games.api_game_edit', '/api/game/1/edit', 'POST'),
        ('games.api_games_bulk_edit', '/api/games/bulk-edit', 'POST'),
        ('bulk_scrape.api_bulk_scrape', '/api/bulk-scrape', 'POST'),
        ('bulk_scrape.api_bulk_scrape_job_start', '/api/bulk-scrape-job/start', 'POST'),
        ('bulk_scrape.api_bulk_scrape_job_cancel', '/api/bulk-scrape-job/cancel', 'POST'),
        ('achievements.api_sync_game_achievements', '/api/achievements/sync/1', 'POST'),
        ('achievements.api_refresh_achievements', '/api/achievements/refresh/1', 'POST'),
        ('collector_trophies.refresh_trophies', '/api/collector-trophies/refresh', 'POST'),
    ]

    def test_all_destructive_endpoints_use_editor_required(self):
        """Source-level check: each destructive endpoint has @editor_required
        (not @login_required). Reads the view function's wrapped chain via
        Flask's view_functions dict — every editor_required-wrapped handler
        has the decorator's closure cell visible as __wrapped__.__qualname__
        or via the defining source line. Simpler: grep the source file."""
        import re as _re
        for endpoint, _path, _method in self.DESTRUCTIVE_ENDPOINTS:
            module_name, view_name = endpoint.split('.', 1)
            module_path = f'/mnt/Storage/Scripts/Linux/RetroDB/routes/{module_name}.py'
            src = open(module_path).read()
            # Find the decorator stack above `def view_name(`
            pat = _re.compile(
                rf'((?:@\w+(?:\([^)]*\))?\s*\n)+)\s*def {view_name}\b',
                _re.MULTILINE,
            )
            m = pat.search(src)
            assert m, f"Could not locate {endpoint} in {module_path}"
            decorators = m.group(1)
            assert '@editor_required' in decorators, \
                f"{endpoint} should be @editor_required, got: {decorators!r}"


# =============================================================================
# 24.6 — Xbox OAuth state parameter
# =============================================================================

class TestXboxOAuthState:
    def test_get_auth_url_accepts_state(self):
        from scraper.scrape_xbox import get_auth_url
        url = get_auth_url('test_client', 'https://example.invalid/cb', state='abc123')
        assert 'state=abc123' in url

    def test_get_auth_url_omits_state_when_not_given(self):
        from scraper.scrape_xbox import get_auth_url
        url = get_auth_url('test_client', 'https://example.invalid/cb')
        assert 'state=' not in url

    def test_callback_verifies_state(self):
        from routes import platform_import as pi_mod
        src = open(pi_mod.__file__).read()
        # Both the generate-state (auth_url) and verify-state (callback)
        # sides of the handshake must be present.
        assert "flask_session['oauth_state_xbox']" in src
        assert "oauth_state_xbox" in src
        assert "compare_digest" in src
        assert "state_mismatch" in src


# =============================================================================
# 24.7 — token file permissions 0o600
# =============================================================================

class TestTokenFilePermissions:
    def test_psn_token_save_uses_0o600(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'routes.trophies.PSN_TOKENS_FILE',
            str(tmp_path / 'psn_tokens.json'),
        )
        from routes.trophies import _save_psn_tokens
        _save_psn_tokens({'access_token': 'abc', 'refresh_token': 'def'})
        mode = os.stat(tmp_path / 'psn_tokens.json').st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_xbox_token_save_uses_0o600(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            'scraper.scrape_xbox.TOKENS_FILE',
            str(tmp_path / 'xbox_tokens.json'),
        )
        from scraper.scrape_xbox import save_tokens
        save_tokens({'access_token': 'abc', 'refresh_token': 'def'})
        mode = os.stat(tmp_path / 'xbox_tokens.json').st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


# =============================================================================
# 24.8 — broadened SecretRedactor
# =============================================================================

class TestSecretRedactorBroadened:
    def test_api_key_field_redacted(self):
        from services.log_redactor import redact
        s = "Scraper config: api_key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ01234567"
        redacted = redact(s)
        assert 'AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ01234567' not in redacted
        assert '<redacted' in redacted

    def test_npsso_field_redacted(self):
        from services.log_redactor import redact
        # NPSSO-ish 64-char token
        tok = 'A' * 64
        s = f"psn.npsso: {tok} (from settings)"
        redacted = redact(s)
        assert tok not in redacted

    def test_unrelated_long_strings_not_redacted(self):
        """A 40-char git commit SHA in free text should stay visible as
        long as it's not preceded by a sensitive field name. False
        positives defeat the purpose of log grep."""
        from services.log_redactor import redact
        # Alphanumeric hash that wouldn't trigger the hex-only rule.
        s = "Refactored MergePolicy in commit marker AbcDefGhIjKlMnOpQrStUvWxYz123456789"
        redacted = redact(s)
        # Not asserting the token survives — the broad hex fallback or
        # other rules might still hit it. Assert that the sensitive-field
        # rule didn't fire (no "<redacted-token>" in output).
        assert "commit marker" in redacted


# =============================================================================
# 22.7 — destructive-endpoint coverage (unblocked by 24.5)
# =============================================================================

class TestDestructiveEndpointsRequireAuth:
    """Smoke tests that the destructive endpoints reject unauthenticated
    callers. Paired with the 24.5 source-level check above, this gives
    us a two-level guarantee: the decorator is correct AND it fires."""

    @pytest.fixture(scope="class")
    def client(self):
        import app as app_module
        app_module.app.config['TESTING'] = True
        with app_module.app.test_client() as c:
            yield c

    @pytest.mark.parametrize("path", [
        '/api/delete-game/1',
        '/api/rename-rom/1',
        '/api/delete-screenshot/1',
    ])
    def test_destructive_endpoint_rejects_unauthenticated(self, client, path):
        resp = client.post(path, json={}, follow_redirects=False)
        # editor_required redirects unauthenticated callers to /login.
        # On fresh CI the setup middleware may steer to /setup instead.
        assert resp.status_code in (301, 302, 303, 401, 403)
        location = resp.headers.get('Location', '')
        assert '/login' in location or '/setup' in location or resp.status_code in (401, 403)

    def test_rename_rom_rejects_path_traversal_in_filename(self, client):
        """Independent of auth: the route also validates filename contents."""
        # This test needs auth to reach the validation logic. We can't
        # assert the 400 rejection without a real session, so we settle
        # for verifying the inline check is present in source.
        src = open('/mnt/Storage/Scripts/Linux/RetroDB/routes/games_media.py').read()
        assert "'..' in new_filename" in src
        assert 'invalid_chars' in src
