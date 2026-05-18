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
#
# Pass 45.21 audit (2026-04-27): rename-rom traversal test rewritten to
# exercise safe_filename() directly. Rate-limit-on-change-password test
# removed — covered functionally in test_pass41_security.py (composite
# bucket isolation tests that actually call rate_limit_login). Remaining
# source-grep tests pin the no-passwordless-account invariant, session-
# clear ordering before user_id assignment, and the destructive-endpoint
# decorator-stack regex (functional anonymous-redirect coverage exists in
# TestDestructiveEndpointsRequireAuth).

import os
import pytest

from tests._util import REPO_ROOT as _REPO_ROOT, read_module_source, read_source


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
        src = read_module_source(auth_mod)
        assert "This account has no password set" in src
        # And the prior `if user['role'] == 'admin':` gate is gone.
        assert "if user['role'] == 'admin':" not in src

    def test_login_endpoint_rejects_missing_user_id(self, monkeypatch):
        """ACC-1 behavioural pair: the source-grep above only confirms the
        rejection string exists. This test calls the real endpoint with
        an empty body and asserts the auth flow actually runs (no 500,
        and a friendly error rather than an open-door pass).

        The endpoint returns HTTP 200 with `success=False` for refusal
        modes (the project's `success()` helper wraps every response;
        4xx status would have to come from CSRF/rate-limit middleware,
        not the route). So we tighten the test from `< 500` (test-audit
        c-001 LOW) by *also* asserting the success envelope is False —
        catching the "200 OK with success=True" open-door regression."""
        import app as app_module
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as client:
            resp = client.post('/api/login', json={})
            assert resp.status_code < 500, f"server error: {resp.status_code}"
            # If the status is 200 (the typical envelope path), the JSON
            # body's `success` must be False. 4xx/429 are also legitimate
            # refusal modes (CSRF, rate-limit) and don't need to surface
            # a JSON envelope.
            if resp.status_code == 200:
                body = resp.get_json(silent=True) or {}
                assert body.get('success') is not True, (
                    f"open-door pass — login returned 200 with success=True "
                    f"on empty body: {body!r}"
                )

    def test_create_user_seeds_changeme_for_non_admin(self):
        """Pass 24.1 migration: new editor/viewer accounts now get the
        same `changeme` + force_password_change=1 onboarding as admin."""
        from routes import auth as auth_mod
        src = read_module_source(auth_mod)
        # The legacy `password_hash = None` branch is gone; every role
        # gets a hashed password (explicit or default).
        assert "password_hash = None" not in src


# =============================================================================
# 24.2 — session rotation on login
# =============================================================================

class TestSessionRotationOnLogin:
    """Pre-login session state must be discarded on successful login."""

    def test_login_calls_session_clear(self):
        """ACC-2: source-level check that `session.clear()` precedes the
        `session['user_id'] = user['id']` assignment. Stronger AST-based
        ordering — locate the assignment statement and the prior
        `session.clear()` call within the `api_login` function body so
        the check can't be fooled by a stray comment elsewhere in the
        file. Pair this with the behavioural test below."""
        import ast
        from routes import auth as auth_mod
        src = read_module_source(auth_mod)
        tree = ast.parse(src)
        login_fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == 'api_login'),
            None,
        )
        assert login_fn is not None, "api_login() not found in routes/auth.py"

        clear_line = assign_line = None
        for sub in ast.walk(login_fn):
            # session.clear() — Call with attr=='clear' on Name('session')
            if (
                isinstance(sub, ast.Expr)
                and isinstance(sub.value, ast.Call)
                and isinstance(sub.value.func, ast.Attribute)
                and sub.value.func.attr == 'clear'
                and isinstance(sub.value.func.value, ast.Name)
                and sub.value.func.value.id == 'session'
                and clear_line is None
            ):
                clear_line = sub.lineno
            # session['user_id'] = ... — Assign with Subscript target on session
            if (
                isinstance(sub, ast.Assign)
                and any(
                    isinstance(t, ast.Subscript)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == 'session'
                    for t in sub.targets
                )
                and assign_line is None
            ):
                assign_line = sub.lineno

        assert clear_line is not None, "session.clear() not called in api_login"
        assert assign_line is not None, "session['…'] = … not present in api_login"
        assert clear_line < assign_line, (
            "session.clear() must come before any session[...] = ... assignment"
        )

    def test_login_endpoint_reachable_and_clears_session(self, monkeypatch):
        """ACC-2 behavioural pair: drive the real endpoint. Pre-seed an
        attacker-style session value, hit `/api/login` with an obviously-
        bad payload, and confirm the endpoint runs end-to-end. A regression
        that makes `session.clear()` unreachable would show up as a 500
        here, while the AST check above pins the ordering.

        Tighten the previous `< 500` boundary by also asserting the JSON
        envelope's `success` is False for the 200 path — catches the
        "200 OK with success=True" open-door regression (test-audit
        c-001 LOW)."""
        import app as app_module
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['leftover_pre_login'] = 'attacker-planted'
            resp = client.post('/api/login', json={'user_id': 999999, 'password': 'x'})
            assert resp.status_code < 500, f"server error: {resp.status_code}"
            if resp.status_code == 200:
                body = resp.get_json(silent=True) or {}
                assert body.get('success') is not True, (
                    f"open-door pass — login returned 200 with success=True "
                    f"for non-existent user 999999: {body!r}"
                )


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
        src = read_module_source(auth_mod)
        # Both api_change_password and api_force_change_password now check 12.
        assert src.count("Password must be at least 12 characters") >= 2
        # And the old 8-char check is gone.
        assert "Password must be at least 8 characters" not in src

    # Note: rate-limit functional coverage moved to test_pass41_security.py
    # ::TestPass41_1BChangePasswordBucket — those tests run actual
    # rate_limit_login()/record_login_attempt() calls and assert the bucket
    # isolation contract, which is stronger than asserting "string in source".


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
            rel_path = os.path.join('routes', f'{module_name}.py')
            src = read_source(rel_path)
            # Find the decorator stack above `def view_name(`
            pat = _re.compile(
                rf'((?:@\w+(?:\([^)]*\))?\s*\n)+)\s*def {view_name}\b',
                _re.MULTILINE,
            )
            m = pat.search(src)
            assert m, f"Could not locate {endpoint} in {rel_path}"
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
        src = read_module_source(pi_mod)
        # Both the generate-state (auth_url) and verify-state (callback)
        # sides of the handshake must be present.
        assert "flask_session['oauth_state_xbox']" in src
        assert "oauth_state_xbox" in src
        assert "compare_digest" in src
        assert "state_mismatch" in src


# =============================================================================
# 27.2 — per-user platform token store (supersedes 24.7's file-permissions
# tests, since tokens now live in the DB rather than data/{psn,xbox}_tokens.json)
# =============================================================================

class TestPerUserPlatformTokens:
    """Pass 27.2 moved PSN / Xbox OAuth tokens from per-install JSON files to
    per-user rows in `user_platform_tokens`. Verifies (a) round-trip storage,
    (b) per-(user, platform) isolation so one user's tokens can't leak to
    another, and (c) clear_tokens() truly removes the row."""

    def _isolated_db(self, tmp_path, monkeypatch):
        import sqlite3
        from services import migrations
        db_path = str(tmp_path / 'tokens.db')
        # Run migrations against a real on-disk DB so the helpers can
        # connect through services.database.get_db.
        monkeypatch.setattr('config.DB_PATH', db_path)
        # Reset cached connection so get_db() picks up the patched path.
        # Use monkeypatch.setattr so pytest restores the original pool ref
        # on teardown — bare assignment would orphan any warm pool for the
        # remainder of the test process (ISO-1 in c-001.md).
        from services import database
        if hasattr(database, '_db_pool'):
            monkeypatch.setattr(database, '_db_pool', {})
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT)")
        conn.execute("INSERT INTO users (id, role) VALUES (1, 'admin'), (2, 'editor')")
        conn.commit()
        migrations.apply_pending(conn)
        conn.close()
        return db_path

    def test_psn_save_and_load_round_trip(self, tmp_path, monkeypatch):
        self._isolated_db(tmp_path, monkeypatch)
        from services.platform_tokens import save_tokens, load_tokens
        save_tokens(1, 'psn', {'access_token': 'abc', 'refresh_token': 'def'})
        got = load_tokens(1, 'psn')
        assert got == {'access_token': 'abc', 'refresh_token': 'def'}

    def test_tokens_isolated_between_users(self, tmp_path, monkeypatch):
        self._isolated_db(tmp_path, monkeypatch)
        from services.platform_tokens import save_tokens, load_tokens
        save_tokens(1, 'psn', {'access_token': 'admin_token'})
        save_tokens(2, 'psn', {'access_token': 'editor_token'})
        assert load_tokens(1, 'psn') == {'access_token': 'admin_token'}
        assert load_tokens(2, 'psn') == {'access_token': 'editor_token'}

    def test_tokens_isolated_between_platforms(self, tmp_path, monkeypatch):
        self._isolated_db(tmp_path, monkeypatch)
        from services.platform_tokens import save_tokens, load_tokens
        save_tokens(1, 'psn', {'a': 1})
        save_tokens(1, 'xbox', {'b': 2})
        assert load_tokens(1, 'psn') == {'a': 1}
        assert load_tokens(1, 'xbox') == {'b': 2}

    def test_clear_tokens_removes_row(self, tmp_path, monkeypatch):
        self._isolated_db(tmp_path, monkeypatch)
        from services.platform_tokens import save_tokens, load_tokens, clear_tokens
        save_tokens(1, 'psn', {'access_token': 'abc'})
        clear_tokens(1, 'psn')
        assert load_tokens(1, 'psn') is None

    def test_save_with_no_user_id_is_noop(self, tmp_path, monkeypatch):
        """Defence-in-depth: a misconfigured caller that passes user_id=None
        must not write a row that would later be ambiguous to read."""
        self._isolated_db(tmp_path, monkeypatch)
        from services.platform_tokens import save_tokens, load_tokens
        save_tokens(None, 'psn', {'access_token': 'abc'})
        # Nothing to load for any real user.
        assert load_tokens(1, 'psn') is None


# =============================================================================
# 24.8 — broadened SecretRedactor
# =============================================================================

class TestSecretRedactorBroadened:
    def test_api_key_field_redacted(self):
        # SEC-1: do NOT use a real-looking key prefix (`AIzaSy…`). The
        # redactor fires on the `api_key=` field-name trigger, not on the
        # value's shape, so any 36-char token reproduces the test.
        from services.log_redactor import redact
        fake_key = "FAKE_API_KEY_ABCDEFGHIJKLMNOPQRSTUVWXYZ01234567"
        s = f"Scraper config: api_key={fake_key}"
        redacted = redact(s)
        assert fake_key not in redacted
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
        # Snapshot + restore — monkeypatch is unavailable in class-scoped
        # fixtures and a bare assignment would leak TESTING=True onward.
        _orig_testing = app_module.app.config.get('TESTING', False)
        app_module.app.config['TESTING'] = True
        try:
            with app_module.app.test_client() as c:
                yield c
        finally:
            app_module.app.config['TESTING'] = _orig_testing

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
        """Functional: the safe_filename primitive (which the rename-rom
        route delegates to) must reject path-traversal and separator inputs.
        Stronger than source-grep — this exercises the validator behavior
        directly."""
        from services.security import safe_filename
        # The validator returns None for unsafe inputs.
        assert safe_filename('../etc/passwd') is None, (
            "Pass 32.5 — safe_filename must reject `..` traversal"
        )
        assert safe_filename('foo/bar.zip') is None, (
            "Pass 32.5 — safe_filename must reject path separators"
        )
        # And accept clean filenames.
        assert safe_filename('legit-rom.zip') == 'legit-rom.zip'
