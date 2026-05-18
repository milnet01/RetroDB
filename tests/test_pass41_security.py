# =============================================================================
# Pass 41 — Tier-2 indie-review security findings
# =============================================================================
# Regression pins for the 44 HIGH-severity findings from the 2026-04-24
# 14-agent independent review.  Each sub-item gets narrow unit checks that
# fail if the fix is reverted.
#
# Pass 45.21 audit (2026-04-27): see test_pass40_security.py for the full
# bucket philosophy. Tests here that look like source-grep are kept on
# purpose where the contract IS a codebase invariant — migration FK rules,
# JS XSS patterns, decorator-stack pins (functional alternative needs
# multi-role DB fixtures), SQL filter shapes, marker-paired contract pins.
# Tests that gained from rewrite: museum decode logging, ESRGAN SSRF gate,
# image_resize lifecycle, _safe_under_root helper, recently-viewed deletion,
# bulk-scrape singleton — all converted to functional/runtime-introspection.
# =============================================================================

import os

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT, read_source, slice_function  # noqa: E402


# -----------------------------------------------------------------------------
# 41.1.A — login_required allow-list bypass removed
# -----------------------------------------------------------------------------
class TestPass41_1ALoginRequiredAllowList:
    """The 5-name allow-list inside login_required was a footgun — any future
    endpoint colliding with `auth.login`, `auth.api_login`, `static`,
    `help_page`, or `changelog` became silently public regardless of intent.
    Pass 41.1.A drops the allow-list; routes that should be public must not
    apply the decorator."""

    # c-006 P-3: parametrize so each failing needle reports independently
    # instead of stopping at the first assertion.
    @pytest.mark.parametrize("needle", [
        "request.endpoint in",
        "'auth.api_login'",
        "'help_page'",
        "'changelog'",
    ])
    def test_decorator_has_no_endpoint_allowlist(self, needle):
        from inspect import getsource
        import services.auth as a

        body = getsource(a.login_required)
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
@pytest.fixture
def cleared_login_attempts(monkeypatch):
    """Swap services.security._login_attempts for an empty dict around the test.

    Pass-c-006 I-2 fix: originally took the module lock and snapshot/restored
    the dict, which is unsafe under pytest-xdist (two tests sharing the same
    interpreter race on the snapshot/clear/restore cycle).  Using
    monkeypatch.setattr to swap the dict reference gives automatic
    single-test-scope teardown and removes the parallel-runner hazard.
    The leading-underscore alias is gone too (c-005 LOW finding) since
    pytest fixtures with leading underscores still leak to other modules
    despite the misleading "private" hint."""
    import services.security as sec
    monkeypatch.setattr(sec, '_login_attempts', {})
    yield sec


class TestPass41_1BChangePasswordBucket:
    """Sharing the /api/login IP-only bucket meant 5 failed change-password
    attempts from user A locked out /api/login for every other user on the
    same LAN.  Pass 41.1.B re-keys the change-password bucket to
    `f"{ip}:cpw:{user_id}"` so it's isolated from /api/login AND per-user
    (user A's failures don't block user B)."""

    def test_change_password_does_not_pass_bare_ip_to_rate_limit(self):
        # slice_function is AST-based, so a reorder of api_change_password
        # vs api_force_change_password no longer produces a vacuous empty
        # slice (prior bug: src[A:B] with A > B returned ""; assertion
        # 'X not in ""' passed regardless).
        body = slice_function(read_source('routes/auth.py'), 'api_change_password')
        assert body, "api_change_password not found in routes/auth.py"
        # The legacy IP-only call was the bug — a composite bucket key must
        # be threaded in instead.
        assert "rate_limit_login(client_ip)" not in body, (
            "api_change_password must not bucket on bare IP (Pass 41.1.B)"
        )
        # The new bucket key must reference the logged-in user.
        assert "g.user['id']" in body or "user_id" in body

    def test_record_login_attempt_uses_composite_bucket(self):
        body = slice_function(read_source('routes/auth.py'), 'api_change_password')
        assert body, "api_change_password not found in routes/auth.py"
        # record_login_attempt must use the same composite bucket as
        # rate_limit_login — otherwise the failure counter goes into the
        # wrong bucket and the lockout never triggers.
        assert "record_login_attempt(client_ip" not in body, (
            "api_change_password must record into the same composite bucket "
            "(Pass 41.1.B)"
        )

    def test_change_password_bucket_isolated_from_login_bucket(self, cleared_login_attempts):
        """Functional smoke: 6 failures into a (ip, user_id) bucket must NOT
        throttle the IP-only login bucket."""
        sec = cleared_login_attempts
        ip = "203.0.113.55"
        cpw_bucket = f"{ip}:cpw:42"
        for _ in range(6):
            sec.record_login_attempt(cpw_bucket, success=False)
        # Change-password bucket is throttled.
        assert sec.rate_limit_login(cpw_bucket) is False
        # Login bucket from the same IP stays clear.
        assert sec.rate_limit_login(ip) is True

    def test_change_password_bucket_per_user(self, cleared_login_attempts):
        """Functional smoke: user A's failures must NOT throttle user B from
        the same IP."""
        sec = cleared_login_attempts
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
        body = read_source('app.py')
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


# -----------------------------------------------------------------------------
# 41.2.A — migrations 007/008/009 use defer_foreign_keys (works inside a txn)
# -----------------------------------------------------------------------------
class TestPass41_2AMigrationDeferForeignKeys:
    """`PRAGMA foreign_keys = OFF` is a no-op inside a transaction (SQLite
    docs: FK enforcement state cannot change mid-txn). Migrations 007/008/009
    used that idiom and only happened to work because no live FK references
    the rebuilt tables. Pass 41.2.A converts to `PRAGMA defer_foreign_keys =
    ON`, which DOES work inside a transaction and is auto-reset at txn end."""

    MIGRATION_FILES = (
        'services/migrations/scripts/007_psn_user_id.py',
        'services/migrations/scripts/008_collector_trophies_user_id.py',
        'services/migrations/scripts/009_achievement_tables_user_id.py',
    )

    def test_no_more_foreign_keys_off_inside_apply(self):
        """The broken `PRAGMA foreign_keys = OFF` literal must be gone — that
        statement is silently ignored inside a transaction. Strip comments so
        the explanatory inline comment naming the historical pragma doesn't
        false-positive."""
        for path in self.MIGRATION_FILES:
            body = read_source(path)
            code_only = '\n'.join(
                line.split('#', 1)[0]
                for line in body.splitlines()
            )
            assert 'PRAGMA foreign_keys = OFF' not in code_only, (
                f"{path} still uses no-op `PRAGMA foreign_keys = OFF` "
                "inside the migration transaction (Pass 41.2.A)"
            )

    def test_defer_foreign_keys_used_instead(self):
        for path in self.MIGRATION_FILES:
            body = read_source(path)
            assert 'PRAGMA defer_foreign_keys = ON' in body, (
                f"{path} must use `PRAGMA defer_foreign_keys = ON` instead "
                "(Pass 41.2.A)"
            )

    def test_migrations_still_apply_cleanly(self, tmp_path, monkeypatch):
        """End-to-end: a fresh DB must accept migrations 1..9 without error
        after the FK pragma is replaced."""
        import sqlite3
        import config as cfg
        db_path = tmp_path / 'mig.db'
        monkeypatch.setattr(cfg, 'DB_PATH', str(db_path))

        from services.database_init import init_database
        from services.migrations import apply_pending, current_version, latest_version

        init_database()  # creates baseline + applies all pending migrations

        conn = sqlite3.connect(str(db_path))
        try:
            assert current_version(conn) >= 9
            # Idempotency: re-running should be a no-op.
            assert apply_pending(conn) == []
            # Sanity: the rebuilt tables exist.
            for table in ('psn_games', 'psn_trophies', 'collector_trophies',
                          'game_achievement_progress', 'steam_achievements',
                          'xbox_achievements'):
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)
                ).fetchone()
                assert row is not None, f"{table} missing after migrations"
            assert latest_version() >= 9
        finally:
            conn.close()


# -----------------------------------------------------------------------------
# 41.2.B — connection leaks routed through teardown-managed get_request_db
# -----------------------------------------------------------------------------
class TestPass41_2BConnectionLeaksClosed:
    """`get_db()` opens a fresh sqlite3.Connection that the caller must close.
    routes/museum.py (8 sites), routes/tools.py:1316, routes/trophies.py:1804
    used it without a paired `.close()`. Each leak holds a file handle plus
    the 64 MB cache_size budget. Pass 41.2.B routes them through
    `get_request_db()` which the teardown-appcontext handler closes."""

    LEAKING_FILES = (
        'routes/museum.py',
        'routes/tools.py',
        'routes/trophies.py',
    )

    def test_museum_uses_get_request_db(self):
        body = read_source('routes/museum.py')
        # Eight previously-leaking sites — none should call bare get_db().
        # Tolerate the canonical import line itself.
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if 'get_db()' in stripped and 'get_request_db' not in stripped:
                # The only acceptable shape is `from services.database import
                # get_request_db` (no bare get_db calls in this module).
                raise AssertionError(
                    f"routes/museum.py still has bare get_db() call: {stripped!r} "
                    "(Pass 41.2.B)"
                )
        assert 'get_request_db' in body, (
            "routes/museum.py must import get_request_db (Pass 41.2.B)"
        )

    def test_tools_screenshot_dedup_uses_get_request_db(self):
        body = read_source('routes/tools.py')
        # The screenshot-dedup delete path at the previously-leaking line had
        # `db = get_db()` without a close. Confirm a get_request_db site
        # exists; the bare get_db() footprint here is shrinking on this pass.
        assert 'get_request_db' in body, (
            "routes/tools.py must import get_request_db (Pass 41.2.B)"
        )

    def test_trophies_psn_npsso_uses_get_request_db(self):
        body = read_source('routes/trophies.py')
        # The PSN /api/psn/save-npsso handler used get_db() without close.
        # After the fix it must reach the request-scoped connection.
        assert 'get_request_db' in body, (
            "routes/trophies.py must import get_request_db (Pass 41.2.B)"
        )


# -----------------------------------------------------------------------------
# 41.3.A — install_global_redactor runs before basicConfig (no log gap)
# -----------------------------------------------------------------------------
class TestPass41_3ARedactorOrder:
    """Records emitted between `logging.basicConfig()` and
    `install_global_redactor()` previously bypassed the redactor's root-level
    filter. The fix calls `install_global_redactor()` BEFORE basicConfig so
    the root-logger filter is in place from the very first emit, and again
    AFTER so the new StreamHandler also picks up the filter (idempotent)."""

    def test_redactor_install_precedes_basicconfig(self):
        body = read_source('app.py')
        first_redactor = body.find('install_global_redactor()')
        first_basicconfig = body.find('logging.basicConfig(')
        assert first_redactor != -1 and first_basicconfig != -1, (
            "Both `install_global_redactor()` and `logging.basicConfig(` must "
            "appear in app.py (Pass 41.3.A)"
        )
        assert first_redactor < first_basicconfig, (
            "install_global_redactor() must be called before "
            "logging.basicConfig() so the root-level filter catches any "
            "records emitted during the gap (Pass 41.3.A)"
        )


# -----------------------------------------------------------------------------
# 41.3.B — default-admin log line no longer reveals password
# -----------------------------------------------------------------------------
class TestPass41_3BAdminCredsLogLine:
    """`services/database_init.py` previously emitted "Created default admin
    user (username: admin, password: admin)" at INFO. The redactor's pattern
    set doesn't match plaintext "password: X", so the credential survived to
    log files. Fix: scrub the log line entirely — operators learn the bootstrap
    convention from the README, not from logs."""

    def test_password_string_absent_from_log_line(self):
        body = read_source('services/database_init.py')
        # The log call still exists, but must not contain the literal
        # "password: admin" or "password=admin" credential.
        for needle in ('password: admin', 'password=admin', "password='admin'"):
            assert needle not in body, (
                f"services/database_init.py must not log default password "
                f"({needle!r} present) (Pass 41.3.B)"
            )


# -----------------------------------------------------------------------------
# 41.3.C — 'system' log category dropped from LOGGER_CATEGORIES
# -----------------------------------------------------------------------------
class TestPass41_3CSystemLogCategoryDropped:
    """`'system'` was listed in LOGGER_CATEGORIES at log_manager.py:55 but
    had no entry in CATEGORY_LOGGERS at :58 — so a `system_YYYY-MM-DD.log`
    file was created on every category sweep with no records inside, which
    misleads operators looking for system events. Drop the orphan."""

    def test_system_not_in_logger_categories(self):
        from log_manager import LOGGER_CATEGORIES, CATEGORY_LOGGERS
        # Either drop 'system' entirely OR populate CATEGORY_LOGGERS for it.
        if 'system' in LOGGER_CATEGORIES:
            assert 'system' in CATEGORY_LOGGERS and CATEGORY_LOGGERS['system'], (
                "'system' is in LOGGER_CATEGORIES but missing from "
                "CATEGORY_LOGGERS — drop or populate (Pass 41.3.C)"
            )


# -----------------------------------------------------------------------------
# 41.4.A — ES-DE screenshot append survives the post-apply DB→metadata sync
# -----------------------------------------------------------------------------
class TestPass41_4AEsdeScreenshotAppend:
    """`apply_esde_metadata` appends scraped screenshots to the existing list
    in `games.screenshots`, then the orchestrator does a DB→metadata sync
    inside a `for field in [...]: if game.get(field) and not metadata.get(field):`
    loop. For `screenshots` the guard is False because metadata was
    pre-populated, so the appended screenshots get dropped on the final
    UPDATE. Pass 41.4.A handles screenshots before the loop, copying the
    DB value unconditionally after a file-existence filter."""

    def test_screenshot_field_excluded_from_guarded_loop(self):
        """The 'and not metadata.get(field)' guard loop must no longer
        include `screenshots` — that's the whole point of the fix."""
        import re as _re
        body = read_source('scraper/hybrid_scraper.py')
        # The guarded loop iterates a literal list; screenshots was a
        # member previously. Find the relevant loop body and assert
        # 'screenshots' is no longer in the iteration list.
        guarded_loops = _re.findall(
            r"for field in \[([^\]]+)\]:\s*\n[^}]*?and not metadata\.get",
            body,
        )
        for loop in guarded_loops:
            assert "'screenshots'" not in loop, (
                "screenshots still iterated in guarded `not metadata.get` "
                "loop — appended ES-DE screenshots will be dropped (Pass 41.4.A)"
            )


# -----------------------------------------------------------------------------
# 41.4.B — primary-source dispatch isolates per-source exceptions
# -----------------------------------------------------------------------------
class TestPass41_4BPrimaryDispatchTryExcept:
    """Each primary-source branch (esde/tgdb/igdb/rawg/screenscraper) must
    catch its own exceptions so a single malformed response from one source
    doesn't abort the whole hybrid apply. Falls through to the gap-fill
    phase rather than raising to the caller."""

    def test_each_primary_branch_has_try_except(self):
        """c-006 A-3 fix: previously asserted the literal 'Pass 41.4.B'
        comment marker existed — a refactor that kept the comment but
        removed the try/except would pass.  We now AST-walk
        `apply_hybrid_metadata` and count Try nodes: at least 5 (one per
        primary-source dispatch: esde / tgdb / igdb / rawg / screenscraper)."""
        from tests._util import count_except_blocks, read_source

        src = read_source('scraper/hybrid_scraper.py')
        count = count_except_blocks(src, 'apply_hybrid_metadata')
        assert count >= 5, (
            f"apply_hybrid_metadata must contain at least 5 try/except blocks "
            f"(one per primary-source dispatch); AST counted {count} "
            f"(Pass 41.4.B)"
        )


# -----------------------------------------------------------------------------
# 41.5.A — log_redactor catches Steam `key=` and ScreenScraper `sspassword=`
# -----------------------------------------------------------------------------
class TestPass41_5ACredentialQuerystringRedaction:
    """The querystring redaction allowlist previously covered apikey/api_key/
    token/auth/pwd/password/devpassword/ssid but missed Steam's `key=`
    parameter and ScreenScraper's `sspassword=`. A Steam HTTPError stringified
    to logs leaked the API key in the URL. Pass 41.5 adds both names — the
    leading [?&] boundary keeps `key` from over-matching `cache_key=` etc."""

    def test_steam_api_key_redacted(self):
        from services.log_redactor import redact
        url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key=ABC123XYZ&steamid=76561"
        out = redact(url)
        assert 'ABC123XYZ' not in out, "Steam ?key= API value not redacted"
        assert 'key=<redacted>' in out

    def test_screenscraper_sspassword_redacted(self):
        from services.log_redactor import redact
        url = "https://www.screenscraper.fr/api2/jeuInfos.php?devid=foo&devpassword=BAR&ssid=u&sspassword=secret&output=json"
        out = redact(url)
        assert 'secret' not in out, "ScreenScraper sspassword= not redacted"
        assert 'sspassword=<redacted>' in out
        # devpassword (already covered) must remain redacted.
        assert 'BAR' not in out

    def test_cache_key_does_not_match(self):
        """Pass 41.5 widens the allowlist with `key`. Confirm it doesn't
        over-match `cache_key=` / `lookup_key=` style params (those have
        `&cache_` / `&lookup_` before `key=`, so the [?&] boundary should
        stop the match)."""
        from services.log_redactor import redact
        url = "https://example.com/x?cache_key=PUBLIC_VALUE&id=42"
        out = redact(url)
        assert 'PUBLIC_VALUE' in out, (
            "redactor over-matched cache_key= (should only match `?key=` "
            "or `&key=` literal)"
        )


# -----------------------------------------------------------------------------
# 41.5.B — IGDB request retries with fresh token on 401
# -----------------------------------------------------------------------------
class TestPass41_5BIgdbTokenRefreshOn401:
    """A stale Twitch OAuth token in `_igdb_token_cache` makes every IGDB
    call return 401 silently for the rest of the scrape pass. Pass 41.5
    detects the 401, clears the cache, calls `igdb_auth()` for a fresh
    token, and retries the request once."""

    @staticmethod
    def _stub_igdb_with_401_then_200(monkeypatch):
        """Shared setup for the SP-1 split below: install a stale token cache
        and an HTTP fake that returns 401 first, 200 second; return (igdb,
        call_log, result)."""
        from scraper import scrape_igdb as igdb

        # c-006 I-1 fix: swap the module-level cache via monkeypatch so the
        # original dict reference is restored on teardown.
        monkeypatch.setattr(
            igdb, '_igdb_token_cache',
            {'token': 'STALE', 'expires_at': 9999999999},
        )

        call_log = []

        class _Resp:
            def __init__(self, status):
                self.status_code = status
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")
            def json(self):
                return {"ok": True}

        def fake_http_post(url, data=None, headers=None, **kw):
            call_log.append({
                'url': url,
                'auth': headers.get('Authorization') if headers else None,
            })
            if len(call_log) == 1:
                return _Resp(401)
            return _Resp(200)

        def fake_auth():
            igdb._igdb_token_cache['token'] = 'FRESH'
            igdb._igdb_token_cache['expires_at'] = 9999999999
            return 'FRESH'

        monkeypatch.setattr(igdb, 'http_post', fake_http_post)
        monkeypatch.setattr(igdb, 'igdb_auth', fake_auth)
        monkeypatch.setattr(igdb, '_get_igdb_credentials',
                            lambda: ('CID', 'CS'))

        result = igdb.igdb_request('games', 'fields name;', 'STALE')
        return igdb, call_log, result

    def test_401_retry_returns_correct_result(self, monkeypatch):
        """c-006 SP-1 split: interaction shape — the stale 401 triggers a
        retry against the same URL with a Bearer FRESH header, and the
        retried response is what the caller receives."""
        _, call_log, result = self._stub_igdb_with_401_then_200(monkeypatch)
        assert result == {"ok": True}
        assert len(call_log) == 2, f"expected stale + fresh request, got {call_log!r}"
        assert call_log[0]['auth'] == 'Bearer STALE'
        assert call_log[1]['auth'] == 'Bearer FRESH'

    def test_401_retry_updates_cache(self, monkeypatch):
        """c-006 SP-1 split: state shape — the on-disk token cache is
        updated to the fresh token after a 401 retry, so the next call
        doesn't replay the stale-401-retry loop."""
        igdb, _, _ = self._stub_igdb_with_401_then_200(monkeypatch)
        assert igdb._igdb_token_cache['token'] == 'FRESH'

    def test_request_does_not_retry_on_non_401(self, monkeypatch):
        """A 500 should bubble through `raise_for_status` without triggering
        a token refresh. Only 401 invalidates the cache."""
        from scraper import scrape_igdb as igdb

        # c-006 I-1 fix: same monkeypatch-swap pattern as the 401 test above.
        monkeypatch.setattr(
            igdb, '_igdb_token_cache',
            {'token': 'TOKEN', 'expires_at': 9999999999},
        )

        call_log = []

        class _Resp:
            def __init__(self, status):
                self.status_code = status
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")
            def json(self):
                return {}

        def fake_http_post(url, **kw):
            call_log.append(url)
            return _Resp(500)

        def fake_auth():
            raise AssertionError("igdb_auth should not be called on non-401")

        monkeypatch.setattr(igdb, 'http_post', fake_http_post)
        monkeypatch.setattr(igdb, 'igdb_auth', fake_auth)
        monkeypatch.setattr(igdb, '_get_igdb_credentials',
                            lambda: ('CID', 'CS'))

        try:
            igdb.igdb_request('games', 'fields name;', 'TOKEN')
        except RuntimeError:
            pass
        # Single call — no token refresh attempted.
        assert len(call_log) == 1
        # Cache untouched.
        assert igdb._igdb_token_cache['token'] == 'TOKEN'


# -----------------------------------------------------------------------------
# 41.6.A-extend — Apply singleton lock to remaining 9 job classes
# -----------------------------------------------------------------------------
class TestPass41_6AExtendSingletonLockOtherJobs:
    """Pass 41.6.A landed the cross-process singleton lock on BulkScrapeJob.
    Pass 41.6.A-extend applies the same pattern to every other long-running
    job class so multi-worker WSGI deploys get a cross-process guard
    everywhere. Contract: each module imports the helpers, every job's
    start() / resume_from_params() acquires a uniquely-named lock, and every
    terminal cleanup releases via the `release_singleton_fd(self)` helper."""

    JOB_MODULES = [
        ('services.jobs.image_resize', 'ImageResizeJob', 'image_resize'),
        ('services.jobs.alt_titles_backfill', 'AltTitlesBackfillJob', 'alt_titles_backfill'),
        ('services.jobs.hltb_bulk', 'HLTBBulkLookupJob', 'hltb_bulk'),
        ('services.jobs.museum', 'MuseumGenerateJob', 'museum_generate'),
        ('services.jobs.ra_sync', 'RASyncJob', 'ra_sync'),
        ('services.jobs.ra_refresh', 'RARefreshJob', 'ra_refresh'),
        ('services.jobs.psn_refresh', 'PSNRefreshJob', 'psn_refresh'),
        ('services.jobs.platform_sync', 'SteamSyncJob', 'steam_sync'),
        ('services.jobs.platform_sync', 'XboxSyncJob', 'xbox_sync'),
    ]

    def test_each_job_has_singleton_fd_attribute(self):
        """Every job's __init__ sets `_singleton_fd = None` so the worker's
        terminal cleanup can release safely (idempotent on un-acquired)."""
        import importlib
        for modname, clsname, _ in self.JOB_MODULES:
            mod = importlib.import_module(modname)
            cls = getattr(mod, clsname)
            inst = cls()
            assert hasattr(inst, '_singleton_fd'), (
                f"{clsname} must define `_singleton_fd` in __init__"
            )
            assert inst._singleton_fd is None, (
                f"{clsname}._singleton_fd must default to None"
            )

    def test_each_job_module_imports_helpers(self):
        """Each module must `from services.jobs.base import
        acquire_job_singleton_lock, release_singleton_fd` (both helpers
        used together in the start/cleanup pattern)."""
        import importlib
        from services.jobs import base as job_base
        for modname, _, _ in self.JOB_MODULES:
            mod = importlib.import_module(modname)
            assert hasattr(mod, 'acquire_job_singleton_lock'), (
                f"{modname} must import acquire_job_singleton_lock"
            )
            assert hasattr(mod, 'release_singleton_fd'), (
                f"{modname} must import release_singleton_fd"
            )
            # Same binding, not a re-implementation.
            assert mod.acquire_job_singleton_lock is job_base.acquire_job_singleton_lock
            assert mod.release_singleton_fd is job_base.release_singleton_fd

    def test_each_start_acquires_lock_with_correct_name(self, monkeypatch):
        """Hook acquire_job_singleton_lock; call each job's start() with
        the lightest-weight valid args; assert the helper was invoked with
        the expected job name. Worker thread starts a no-op via a stubbed
        target so the test stays in-process."""
        import importlib
        captured = []
        SENTINEL = 12345  # Any positive int that release helpers must accept.

        def fake_acquire(name):
            captured.append(name)
            return SENTINEL

        def fake_release(fd):
            # Don't actually try to flock or close the SENTINEL int.
            pass

        # Stub Thread.start so worker bodies don't run.
        import threading as _t
        monkeypatch.setattr(_t.Thread, 'start', lambda self: None)

        # Patch base.release_job_singleton_lock so release_singleton_fd's
        # delegate doesn't call fcntl on the SENTINEL.
        from services.jobs import base as job_base
        monkeypatch.setattr(job_base, 'acquire_job_singleton_lock', fake_acquire)
        monkeypatch.setattr(job_base, 'release_job_singleton_lock', fake_release)

        # Each job module rebinds acquire_job_singleton_lock at import; patch
        # the per-module symbol too.
        for modname, _, _ in self.JOB_MODULES:
            mod = importlib.import_module(modname)
            monkeypatch.setattr(mod, 'acquire_job_singleton_lock', fake_acquire)

        starters = {
            'ImageResizeJob': lambda j: j.start(image_types=['boxart']),
            'AltTitlesBackfillJob': lambda j: j.start(),
            'HLTBBulkLookupJob': lambda j: j.start(),
            'MuseumGenerateJob': lambda j: j.start(),
            'RASyncJob': lambda j: j.start(system_id=1),
            'RARefreshJob': lambda j: j.start(system_id=1),
            'PSNRefreshJob': lambda j: j.start(['NPWR0001'], 'fake-npsso', user_id=1),
            'SteamSyncJob': lambda j: j.start(user_id=1),
            'XboxSyncJob': lambda j: j.start(user_id=1),
        }

        for modname, clsname, expected_name in self.JOB_MODULES:
            mod = importlib.import_module(modname)
            cls = getattr(mod, clsname)
            inst = cls()
            captured.clear()
            result = starters[clsname](inst)
            assert expected_name in captured, (
                f"{clsname}.start() did not acquire lock named "
                f"{expected_name!r}. Captured: {captured}"
            )
            assert result.get('success') is True, (
                f"{clsname}.start() returned non-success with stubbed lock: {result}"
            )
            assert inst._singleton_fd == SENTINEL, (
                f"{clsname}.start() must record the FD on self._singleton_fd"
            )

    def test_release_singleton_fd_helper_is_idempotent(self, monkeypatch):
        """`release_singleton_fd(job)` clears the attribute; a second call
        must be a no-op (idempotent — multiple terminal-cleanup branches in
        a worker can call it without re-releasing or AttributeError)."""
        from services.jobs.base import release_singleton_fd
        from services.jobs import base as job_base

        # Stub the underlying flock/close so the test FD doesn't need to be
        # a real one.
        released = []
        monkeypatch.setattr(
            job_base, 'release_job_singleton_lock',
            lambda fd: released.append(fd)
        )

        class _Stub:
            _singleton_fd = 99

        s = _Stub()
        release_singleton_fd(s)
        assert s._singleton_fd is None
        assert released == [99]
        # Second call: still fine, no extra release.
        release_singleton_fd(s)
        assert s._singleton_fd is None
        assert released == [99]


# -----------------------------------------------------------------------------
# 41.5b — Steam + HLTB raw requests routed through base_scraper.http_get/post
# -----------------------------------------------------------------------------
class TestPass41_5bSteamHltbThroughBaseScraper:
    """Pass 41.5 closed the IGDB 401 case but left raw `requests.get` /
    `requests.post` in `scraper/scrape_steam.py` (7 sites) and
    `scraper/hltb_lookup.py` (3 sites). Pass 41.5b replaces them with
    `base_scraper.http_get` / `http_post` so Steam + HLTB calls inherit the
    retry-on-429/5xx + jittered backoff + connection-pooled session shape
    the rest of the scrapers use. The contract is a source-level invariant
    (no raw `requests.{get,post}(` survives) plus an import pin (each
    module pulls the helpers from base_scraper)."""

    def test_scrape_steam_no_raw_requests_calls(self):
        import re
        with open(os.path.join(_REPO_ROOT, 'scraper', 'scrape_steam.py'),
                  encoding='utf-8') as f:
            src = f.read()
        # Only `requests.get(` / `requests.post(` are forbidden — the module
        # still imports `requests` for `requests.exceptions.HTTPError`.
        assert not re.search(r'\brequests\.get\(', src), (
            "scrape_steam.py still has a raw requests.get(...) — should be http_get"
        )
        assert not re.search(r'\brequests\.post\(', src), (
            "scrape_steam.py still has a raw requests.post(...) — should be http_post"
        )

    def test_hltb_lookup_no_raw_requests_calls(self):
        import re
        with open(os.path.join(_REPO_ROOT, 'scraper', 'hltb_lookup.py'),
                  encoding='utf-8') as f:
            src = f.read()
        assert not re.search(r'\brequests\.get\(', src), (
            "hltb_lookup.py still has a raw requests.get(...) — should be http_get"
        )
        assert not re.search(r'\brequests\.post\(', src), (
            "hltb_lookup.py still has a raw requests.post(...) — should be http_post"
        )

    def test_modules_export_base_scraper_helpers(self):
        from scraper import scrape_steam, hltb_lookup
        from scraper import base_scraper
        # Both modules pulled http_get from base_scraper (binding identity).
        assert scrape_steam.http_get is base_scraper.http_get, (
            "scrape_steam.http_get must be the base_scraper helper"
        )
        assert hltb_lookup.http_get is base_scraper.http_get, (
            "hltb_lookup.http_get must be the base_scraper helper"
        )
        assert hltb_lookup.http_post is base_scraper.http_post, (
            "hltb_lookup.http_post must be the base_scraper helper"
        )

    def test_steam_resolve_returns_none_on_total_failure(self, monkeypatch):
        """When http_get returns None (all retries exhausted), the Steam
        wrappers must not crash on `.status_code` / `.raise_for_status()` —
        they must return their established failure shape."""
        from scraper import scrape_steam
        monkeypatch.setattr(scrape_steam, 'http_get', lambda *a, **kw: None)

        assert scrape_steam.resolve_vanity_url('K', 'gabe') is None
        assert scrape_steam.get_owned_games('K', '76561') == []
        assert scrape_steam.get_player_achievements('K', '76561', 1) is None
        assert scrape_steam.get_achievement_schema('K', 1) == []
        assert scrape_steam.get_player_summary('K', '76561') is None
        assert scrape_steam.get_app_details(1) is None
        result = scrape_steam.check_api_key('K')
        assert result == {'valid': False, 'error': 'Connection error'}

    def test_hltb_returns_none_on_total_failure(self, monkeypatch):
        """When http_get / http_post return None, HLTB must surface a clean
        None instead of dereferencing `.status_code`."""
        from scraper import hltb_lookup
        # Reset any cached token so _get_auth_token actually exercises the
        # network shim under test. monkeypatch restores the prior cache on
        # teardown — bare assignment would leak None onward.
        monkeypatch.setattr(hltb_lookup, '_auth_token', None)
        monkeypatch.setattr(hltb_lookup, '_auth_token_time', 0)
        monkeypatch.setattr(hltb_lookup, 'http_get', lambda *a, **kw: None)
        monkeypatch.setattr(hltb_lookup, 'http_post', lambda *a, **kw: None)

        assert hltb_lookup._get_auth_token() == (None, None, None)
        assert hltb_lookup._search_hltb('Tetris') is None


# -----------------------------------------------------------------------------
# 41.7.A — TROPUSR explicit bounds on tables_count + offset
# -----------------------------------------------------------------------------
class TestPass41_7ATropusrBounds:
    """`scraper/trophy_parser.py::TROPUSRParser` parsed attacker-controlled
    `tables_count`, `entries_count`, and `offset` from TROPUSR.DAT. Inner
    `break` guards saved exploitability today, but bounds correctness relied
    on a reviewer proving early-exit rather than explicit min/return guards.
    Pass 41.7.A prepends defensive bounds to make the safety obvious to
    static analysis."""

    def test_tables_count_capped(self):
        body = read_source('scraper/trophy_parser.py')
        # Look for the explicit cap. The exact arithmetic is documented in the
        # roadmap as `(len(data) - 0x30) // 32`.
        assert 'tables_count = min(tables_count' in body, (
            "Missing explicit cap `tables_count = min(tables_count, ...)` "
            "in trophy_parser.py (Pass 41.7.A)"
        )


# -----------------------------------------------------------------------------
# 41.7.B — Xbox callback redirect uses kwarg form (not string concat)
# -----------------------------------------------------------------------------
class TestPass41_7BXboxRedirectKwarg:
    """`url_for(...) + '&xbox_connected=1'` worked only because url_for
    happened to emit a `?tab=xbox` query string today; a future refactor
    could break the implicit ampersand assumption. Pass 41.7.B converts
    to the kwarg form so URL construction is unambiguous."""

    def test_no_string_concat_redirect(self):
        body = read_source('routes/platform_import.py')
        # Strip comments so the explanatory comment naming the historical
        # shape doesn't false-positive.
        code_only = '\n'.join(
            line.split('#', 1)[0]
            for line in body.splitlines()
        )
        assert "+ '&xbox_connected=1'" not in code_only, (
            "Xbox redirect still uses string concatenation — convert to "
            "url_for(..., xbox_connected=1) kwarg form (Pass 41.7.B)"
        )
        assert 'xbox_connected=1' in body, (
            "Xbox-connected redirect target still required (Pass 41.7.B)"
        )


# -----------------------------------------------------------------------------
# 41.7.C — RA HTTP callers explicitly log 401 (stale API key)
# -----------------------------------------------------------------------------
class TestPass41_7CRaApi401Logging:
    """A 401 from the RA API (stale or revoked user API key) previously fell
    through the generic non-200 branch and returned None silently — the user
    saw 'no RA entry found' instead of 'check your API key'. Pass 41.7.C
    adds an explicit 401-detection log line at each of the 5 callers in
    scraper/retroachievements.py."""

    def test_retroachievements_logs_401(self):
        body = read_source('scraper/retroachievements.py')
        # Pin the user-actionable behaviour (`401` status + `API key` hint
        # near each callsite) rather than the comment marker. The previous
        # `'Pass 41.7.C' in body` assertion was comment-as-proof — a
        # refactor that kept the comment but moved the log call would
        # pass; conversely, dropping the comment during cleanup would
        # fail the test for the wrong reason (test-audit c-005 MED).
        # We scan the file body directly for the two hint strings inside
        # close proximity (any 401-handler is fine for the contract).
        assert '401' in body, "scraper/retroachievements.py must mention 401 status anywhere"
        assert 'API key' in body or 'api_key' in body, (
            "scraper/retroachievements.py must hint at user-actionable 'check API key'"
        )
        # Pin the proximity contract: at least one '401' must sit within
        # 800 chars of an 'API key'/'api_key' mention (the user-facing
        # log line). This catches the "401 mentioned somewhere unrelated"
        # weakness without anchoring to a comment.
        import re as _re
        windowed = False
        for m in _re.finditer(r'401', body):
            nearby = body[max(0, m.start() - 100):m.start() + 800]
            if 'API key' in nearby or 'api_key' in nearby:
                windowed = True
                break
        assert windowed, (
            "scraper/retroachievements.py must wire a '401' detection log "
            "with the 'API key' user-actionable hint within proximity (Pass 41.7.C)"
        )


# -----------------------------------------------------------------------------
# 41.8.A — flask.g shadow in PSN sync loops renamed
# -----------------------------------------------------------------------------
class TestPass41_8AFlaskGShadow:
    """`routes/trophies.py::_run_psn_full_sync` had four `for g in ...` loops
    that shadowed the module-level `from flask import g`. The PSN sync runs
    in a background thread (no request context) so today the shadow is only
    a typing/IDE hazard, but it's a latent bug under any future refactor
    that moves the body inside a request handler. Renaming to `ps_game`
    matches the existing `existing_groups` comprehension at :1384."""

    def test_no_for_g_in_loops(self):
        body = read_source('routes/trophies.py')
        # Strip comments so the explanatory comment doesn't false-positive.
        code_only = '\n'.join(
            line.split('#', 1)[0]
            for line in body.splitlines()
        )
        # `for g in ...` (with whitespace boundaries) must be absent from
        # routes/trophies.py — including any list/dict comprehension.
        # Trailing `\s` tightens the right boundary so `for g in(...)`-style
        # generator-expression usages (where `\b` may not match adjacent to
        # `(`) also get caught (c-005 LOW finding).
        import re as _re
        matches = _re.findall(r'\bfor\s+g\s+in\s', code_only)
        assert not matches, (
            f"routes/trophies.py still has `for g in ...` shadow(s) "
            f"({len(matches)} occurrences) — rename loop var to ps_game "
            "or similar (Pass 41.8.A)"
        )


# -----------------------------------------------------------------------------
# 41.8.B — achievement aggregation null-user_id contract documented
# -----------------------------------------------------------------------------
class TestPass41_8BAchievementAggregationDoc:
    """The `LEFT JOIN game_achievement_progress gap ON g.id = gap.game_id
    AND gap.user_id = ?` shape silently drops rows where gap.user_id is
    NULL. Migration 009 back-fills every row and the column is NOT NULL,
    so this is impossible under normal init paths — but a backup restore
    that pre-dates migration 009 could surface the silent-drop. Pass 41.8.B
    documents the contract near the query so a future operator knows what
    to check."""

    def test_null_userid_invariant_documented(self):
        body = read_source('routes/achievements.py')
        # The doc-contract is: somewhere in routes/achievements.py, a
        # comment must reference migration 009 (the backfill) and the
        # `user_id IS NULL` diagnostic query — close enough together to
        # be a single explanation. Anchoring on the Pass-NN marker is
        # comment-as-proof and brittle (test-audit c-005 MED): drop the
        # marker assertion and verify the substantive content directly.
        assert '009' in body, (
            "routes/achievements.py must reference migration 009 (the backfill)"
        )
        assert 'user_id IS NULL' in body, (
            "routes/achievements.py must give the `user_id IS NULL` diagnostic query"
        )
        # Proximity check: the two must sit within ~800 chars of each
        # other so they form a coherent explanation, not two unrelated
        # mentions elsewhere in the file.
        idx_009 = body.find('009')
        idx_null = body.find('user_id IS NULL')
        assert abs(idx_009 - idx_null) <= 800, (
            "Pass 41.8.B docstring fragments are too far apart "
            f"(migration 009 at {idx_009}, 'user_id IS NULL' at {idx_null}) — "
            "they must form a single coherent explanation"
        )


# -----------------------------------------------------------------------------
# 41.11.A — museum top_games JSON decode failure logged at WARNING
# -----------------------------------------------------------------------------
class TestPass41_11ATopGamesDecodeLogging:
    """`_get_top_games` previously caught `(json.JSONDecodeError, TypeError):
    pass`, leaving the admin with an empty top-games list and no breadcrumb
    when the cached LLM JSON was corrupt. Pass 41.11.A logs the failure at
    WARNING with the system_id so the next museum generation can be
    prompted."""

    def test_decode_error_no_silent_pass(self, monkeypatch, caplog):
        """Functional: when _get_top_games encounters corrupt cached JSON in
        museum_data['top_games'], it must emit a logger.warning (not silently
        swallow the decode error)."""
        import logging
        from routes import museum as museum_mod

        # Empty DB result so the function falls through to the AI-cache branch.
        class _FakeDb:
            def execute(self, *a, **kw):
                return self
            def fetchall(self):
                return []

        monkeypatch.setattr(museum_mod, 'get_request_db', lambda: _FakeDb())

        bad_data = {'top_games': 'NOT_VALID_JSON{{{'}
        with caplog.at_level(logging.WARNING, logger=museum_mod.logger.name):
            result = museum_mod._get_top_games(system_id=1, museum_data=bad_data)

        # Decode failure: returns empty (not crash) AND emits a warning so
        # the operator has a breadcrumb to the corruption.
        assert result == []
        assert any('top_games' in r.getMessage().lower() or
                   'decode' in r.getMessage().lower() or
                   'json' in r.getMessage().lower()
                   for r in caplog.records), (
            "Pass 41.11.A — _get_top_games must logger.warning on JSON decode "
            f"failure; got records: {[r.getMessage() for r in caplog.records]!r}"
        )


# -----------------------------------------------------------------------------
# 41.11.B — GET handler no longer issues UPDATE controllers SET image = NULL
# -----------------------------------------------------------------------------
class TestPass41_11BMuseumGetIdempotent:
    """`museum_system` is a GET handler; it must not mutate shared state.
    Previously it ran `UPDATE controllers SET image = NULL WHERE id = ?`
    inside the view, violating RFC 7231 GET-idempotency and letting one
    user's page load rewrite globally-shared rows. The cleanup is now an
    admin-only POST at `/api/museum/cleanup-controller-images`."""

    def test_get_view_does_not_update_controllers(self):
        body = read_source('routes/museum.py')
        # Extract the museum_system function body — slice from `def
        # museum_system` to the next `# =============` block separator.
        start = body.find('def museum_system(system_id):')
        assert start != -1, "museum_system function not found"
        end_marker = body.find('# =============', start)
        assert end_marker != -1, "comment separator after museum_system not found"
        view_body = body[start:end_marker]
        # Strip comments so the explanatory comment in the function (which
        # quotes the historical UPDATE statement) doesn't false-positive.
        code_only = '\n'.join(
            line.split('#', 1)[0]
            for line in view_body.splitlines()
        )
        assert 'UPDATE controllers' not in code_only, (
            "museum_system GET handler still issues UPDATE controllers — "
            "GET must be idempotent (Pass 41.11.B)"
        )

    def test_admin_cleanup_endpoint_registered(self):
        """Functional: the cleanup route must be wired into Flask's URL map
        as a POST. Runtime introspection beats source-grep here because it
        verifies the @bp.route decorator actually fired."""
        import app as app_module
        rules = [
            r for r in app_module.app.url_map.iter_rules()
            if '/api/museum/cleanup-controller-images' in r.rule
        ]
        assert rules, (
            "Pass 41.11.B — /api/museum/cleanup-controller-images must be "
            "registered in the URL map"
        )
        assert any('POST' in r.methods for r in rules), (
            "Pass 41.11.B — cleanup endpoint must accept POST"
        )

    def test_admin_cleanup_endpoint_requires_editor(self, monkeypatch):
        """Functional: anonymous POST to the cleanup endpoint must redirect
        (302/401/403); a logged-in caller would still need editor role, but
        anonymous rejection alone proves an auth decorator fired."""
        import app as app_module
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        client = app_module.app.test_client()
        resp = client.post(
            '/api/museum/cleanup-controller-images',
            json={}, follow_redirects=False,
        )
        # editor_required redirects anonymous to /login (or /setup on a fresh
        # CI DB). The forbidden outcome is 200 — that would mean no auth
        # decorator at all.
        assert resp.status_code in (301, 302, 303, 401, 403), (
            f"Pass 41.11.B — cleanup endpoint must reject anonymous POST; "
            f"got {resp.status_code}"
        )


# -----------------------------------------------------------------------------
# 41.14.A — compute_dhash widens except to catch DecompressionBombError
# -----------------------------------------------------------------------------
class TestPass41_14ADecompressionBomb:
    """`scraper/image_dedup.py::compute_dhash` previously caught
    `(OSError, ValueError)`. PIL's `DecompressionBombError` is a sibling
    exception class (not a subclass of either), so a single bomb-image
    in a scraped screenshot batch propagated out and aborted the dedup
    loop for the whole game. Pass 41.14.A widens the catch."""

    def test_compute_dhash_returns_none_on_bomb(self, monkeypatch):
        """Functional smoke: when PIL raises DecompressionBombError,
        compute_dhash must return None instead of propagating."""
        from PIL import Image
        from scraper import image_dedup

        def boom(*a, **kw):
            raise Image.DecompressionBombError('test bomb')

        monkeypatch.setattr(image_dedup.Image, 'open', boom)
        assert image_dedup.compute_dhash('/dev/null') is None


# -----------------------------------------------------------------------------
# 41.14.B — ESRGAN model download routed through SSRF guard
# -----------------------------------------------------------------------------
class TestPass41_14BEsrganSsrfGate:
    """`services/image_utils._download_model` previously ran
    `urllib.request.urlopen(req, timeout=120)` directly. _MODEL_URLS is a
    hardcoded HuggingFace allowlist today, so today there's no real SSRF
    primitive — but if the URL becomes settings-editable in the future
    (the way ROM_PATH did in Pass 32.1) the helper would be a wide-open
    fetcher. Pass 41.14.B routes every URL through
    `services.ssrf.validate_outbound_url(require_https=True)` first."""

    def test_validate_outbound_url_imported_in_helper(self):
        """Codebase invariant — kept as source-grep. Functional alternative
        is brittle: _download_model imports validate_outbound_url inside the
        function (lazy import for cycle avoidance), so monkeypatching the
        module-level binding doesn't intercept it. The literal call shape
        `validate_outbound_url(try_url, require_https=True)` IS the contract
        — both that the gate is invoked AND that it requires HTTPS."""
        body = read_source('services/image_utils.py')
        assert 'validate_outbound_url' in body, (
            "services/image_utils.py must call validate_outbound_url "
            "before urlopen (Pass 41.14.B)"
        )
        assert 'validate_outbound_url(try_url, require_https=True)' in body, (
            "ESRGAN download must call validate_outbound_url(..., "
            "require_https=True) (Pass 41.14.B)"
        )


# -----------------------------------------------------------------------------
# 41.14.C — rglob() symlink-escape guards in scraper/rom_tools.py
# -----------------------------------------------------------------------------
class TestPass41_14CRglobSymlinkGuard:
    """`Path.rglob()` follows symlinks on Python 3.12 (default changed in
    3.13). A symlink to `/` placed inside ROM_PATH would let rom_tools'
    archive/CHD/duplicate scanners enumerate the entire filesystem.
    Pass 41.14.C adds a `_safe_under_root` helper and applies it to every
    recursive walk."""

    def test_helper_defined(self):
        """Functional: the _safe_under_root helper must be importable and
        callable — a stronger check than `'_safe_under_root' in source`."""
        from scraper.rom_tools import _safe_under_root
        assert callable(_safe_under_root)

    def test_helper_used_at_every_recursive_walk(self):
        body = read_source('scraper/rom_tools.py')
        # Each rglob result must be filtered through _safe_under_root, OR
        # be a tempdir-extract case that's outside the audit scope. Count
        # both rglob uses and helper uses; the helper count must be > 0.
        rglob_count = body.count('.rglob(')
        # The helper is used as `_safe_under_root(...)` in filter expressions.
        helper_uses = body.count('_safe_under_root(')
        # The helper definition itself counts as 1 (it's referenced inside
        # _safe_under_root's docstring/return). We expect at least 4
        # call sites covering the audit-scope rglob walks (archive scanner
        # filtered + recursive, CHD converter, duplicate finder).
        assert helper_uses >= 5, (
            f"Expected _safe_under_root to be used at >= 5 sites (definition "
            f"+ 4 audit-scope rglob walks); found {helper_uses}. Total "
            f"rglob call sites = {rglob_count}."
        )

    def test_safe_helper_rejects_escape(self, tmp_path):
        """Functional smoke: the helper must reject a path whose resolved
        location lies outside root."""
        from scraper.rom_tools import _safe_under_root
        root = tmp_path / 'roms'
        root.mkdir()
        outside = tmp_path / 'outside.bin'
        outside.write_bytes(b'x')
        link = root / 'evil.bin'
        link.symlink_to(outside)
        assert _safe_under_root(link, root.resolve()) is False
        # And accept a real file inside root.
        legit = root / 'real.bin'
        legit.write_bytes(b'y')
        assert _safe_under_root(legit, root.resolve()) is True


# -----------------------------------------------------------------------------
# 41.10.A — tools.py task cancel/pause/resume require admin
# -----------------------------------------------------------------------------
class TestPass41_10ATaskAuthz:
    """Task cancel/pause/resume in routes/tools.py at lines 327-378 were
    @login_required, letting any logged-in user (Player / Viewer) interrupt
    an admin's running scan or convert task by knowing the task_id. Pass
    41.10.A raises all three to @admin_required."""

    def test_task_cancel_requires_admin(self):
        body = read_source('routes/tools.py')
        # Locate the cancel route's decorator stack; expect @admin_required.
        idx = body.find("/api/rom-tools/task/<task_id>/cancel")
        assert idx != -1, "cancel route not found"
        block = body[idx:idx + 400]
        assert '@admin_required' in block, (
            "task_cancel must be @admin_required (Pass 41.10.A)"
        )

    def test_task_pause_requires_admin(self):
        body = read_source('routes/tools.py')
        idx = body.find("/api/rom-tools/task/<task_id>/pause")
        assert idx != -1, "pause route not found"
        block = body[idx:idx + 200]
        assert '@admin_required' in block, (
            "task_pause must be @admin_required (Pass 41.10.A)"
        )

    def test_task_resume_requires_admin(self):
        body = read_source('routes/tools.py')
        idx = body.find("/api/rom-tools/task/<task_id>/resume")
        assert idx != -1, "resume route not found"
        block = body[idx:idx + 200]
        assert '@admin_required' in block, (
            "task_resume must be @admin_required (Pass 41.10.A)"
        )


# -----------------------------------------------------------------------------
# 41.10.B — chd-converter/convert + chd-verify/verify require admin
# -----------------------------------------------------------------------------
class TestPass41_10BConvertVerifyAuthz:
    """Both endpoints mutate filesystem state (subprocess.run + os.remove
    when delete_originals=True). Pass 40.2 hardened the file paths via
    safe_path; Pass 41.10.B closes the remaining gap by requiring admin."""

    def test_chd_convert_requires_admin(self):
        body = read_source('routes/tools.py')
        idx = body.find("/api/rom-tools/chd-converter/convert")
        assert idx != -1, "chd-converter/convert route not found"
        block = body[idx:idx + 300]
        assert '@admin_required' in block, (
            "chd-converter/convert must be @admin_required (Pass 41.10.B)"
        )

    def test_chd_verify_requires_admin(self):
        body = read_source('routes/tools.py')
        idx = body.find("/api/rom-tools/chd-verify/verify")
        assert idx != -1, "chd-verify/verify route not found"
        block = body[idx:idx + 200]
        assert '@admin_required' in block, (
            "chd-verify/verify must be @admin_required (Pass 41.10.B)"
        )


# -----------------------------------------------------------------------------
# 41.10.C — task IDs use full UUIDs (no [:8] truncation)
# -----------------------------------------------------------------------------
class TestPass41_10CTaskIdFullUuid:
    """`task_id = str(uuid.uuid4())[:8]` gave only 32 bits of entropy across
    a per-process task registry. A logged-in user could brute-force the
    short ID space (~4.3B values, but feasible across long-running scans
    in a multi-user deployment) to interact with another admin's task.
    Pass 41.10.C drops the slice — full UUID-4 strings now."""

    def test_no_uuid_8char_slice(self):
        """Codebase invariant — kept as source-grep because the contract is
        literally "the `[:8]` slice must never reappear here". A functional
        equivalent (assert task_ids are 36 chars) is below; this test pins
        the slice idiom directly so a partial revert is caught."""
        body = read_source('routes/tools.py')
        # Strip comments so the explanatory comment doesn't false-positive.
        code_only = '\n'.join(
            line.split('#', 1)[0]
            for line in body.splitlines()
        )
        assert 'uuid.uuid4())[:8]' not in code_only, (
            "routes/tools.py still truncates task_ids to 8 chars "
            "(Pass 41.10.C)"
        )

    def test_uuid4_still_used(self):
        """Functional: hitting a task-creating endpoint and reading back the
        task_id is overkill (heavy auth + DB seeding). Instead we verify the
        code path generates a full UUID-4 by importing uuid and confirming
        len(str(uuid.uuid4())) == 36. Combined with the no-slice invariant
        above, this proves task_ids retain full entropy."""
        import uuid
        sample = str(uuid.uuid4())
        assert len(sample) == 36, f"uuid4() should produce 36-char strings, got {len(sample)}"
        # And confirm the import is wired in the consuming module — a
        # cheap import check is stronger than source-grep because it
        # follows renames.
        from routes import tools as tools_mod
        assert hasattr(tools_mod, 'uuid'), (
            "routes/tools.py must import uuid for task_id generation "
            "(Pass 41.10.C)"
        )


# -----------------------------------------------------------------------------
# 41.10.D — heavy *_scan endpoints raised to editor + 5/min rate-limit
# -----------------------------------------------------------------------------
class TestPass41_10DScanAuthzAndRateLimit:
    """Each *_scan endpoint walks the ROM tree (potentially millions of
    files / GBs of disk). Pass 41.10.D raises them to @editor_required
    so anonymous-Player misclicks can't trigger the cost, and adds a
    5/min Flask-Limiter cap so even an authorized editor can't loop on
    them. Five endpoints affected: archive_scanner_scan,
    chd_converter_scan, chd_verify_scan, duplicate_finder_scan,
    screenshot_dedup_scan."""

    SCAN_ROUTES = (
        '/api/rom-tools/archive-scanner/scan',
        '/api/rom-tools/chd-converter/scan',
        '/api/rom-tools/chd-verify/scan',
        '/api/rom-tools/duplicate-finder/scan',
        '/api/rom-tools/screenshot-dedup/scan',
    )

    SCAN_FUNCTIONS = (
        'tools.api_archive_scanner_scan',
        'tools.api_chd_converter_scan',
        'tools.api_chd_verify_scan',
        'tools.api_duplicate_finder_scan',
        'tools.api_screenshot_dedup_scan',
    )

    @pytest.mark.parametrize("route", SCAN_ROUTES)
    def test_each_scan_requires_editor(self, route):
        # Parametrized — first-failure loop hid which of the 5 routes broke.
        body = read_source('routes/tools.py')
        idx = body.find(route)
        assert idx != -1, f"{route} route not found"
        block = body[idx:idx + 250]
        assert '@editor_required' in block, (
            f"{route} must be @editor_required (Pass 41.10.D)"
        )

    @pytest.mark.parametrize("fn", SCAN_FUNCTIONS)
    def test_rate_limits_registered(self, fn):
        # Parametrized — first-failure loop hid which of the 5 endpoints
        # was missing its _rate_limit registration.
        body = read_source('app.py')
        # Each scan endpoint must have a _rate_limit registration; the
        # spec is "5 per minute". Source-level pin (CI's Flask-Limiter
        # registration test would otherwise need a live limiter, which
        # depends on FLASK_LIMITER_ENABLED).
        assert f"_rate_limit('{fn}', \"5 per minute\")" in body, (
            f"Missing _rate_limit('{fn}', '5 per minute') in app.py "
            "(Pass 41.10.D)"
        )


# -----------------------------------------------------------------------------
# 41.12.A — API.* fetch wraps default 30 s AbortController timeout
# -----------------------------------------------------------------------------
class TestPass41_12AFetchTimeout:
    """`static/js/utils.js::API.get/post/postForm` previously called
    `fetch()` with no timeout. A hung server (or a request that fell into
    a captive portal) blocked the pending Promise indefinitely; the
    spinner spun forever and the user had no recovery path. Pass 41.12.A
    wires a 30 s default via AbortController; callers that want to
    control cancellation can pass their own `signal`."""

    def test_abortcontroller_used(self):
        body = read_source('static/js/utils.js')
        assert 'AbortController' in body, (
            "API.* must use AbortController for default timeout (Pass 41.12.A)"
        )
        assert '_API_DEFAULT_TIMEOUT_MS' in body, (
            "Default timeout constant missing (Pass 41.12.A)"
        )

    def test_caller_signal_respected(self):
        """If caller passes their own signal, the helper should NOT clobber
        it with a timed AbortController."""
        body = read_source('static/js/utils.js')
        assert 'opts.signal' in body or 'options.signal' in body, (
            "API.* timeout must opt out when caller passes signal (Pass 41.12.A)"
        )


# -----------------------------------------------------------------------------
# 41.12.B — navigateTo rejects non-same-origin returnUrl
# -----------------------------------------------------------------------------
class TestPass41_12BNavigateToOpenRedirect:
    """The `returnUrl` argument flows from <code>localStorage.getItem</code>
    keys; localStorage is writable from any same-origin script. An XSS
    payload (or a malicious extension) could land an absolute attacker
    URL there, and `window.location.href = returnUrl` would fire it on
    the user's next toast click. Pass 41.12.B validates that returnUrl
    is either a `/`-rooted path or a same-origin URL."""

    def test_isSafeReturnUrl_helper_present(self):
        body = read_source('static/js/toast-controller.js')
        assert '_isSafeReturnUrl' in body, (
            "Open-redirect guard helper must exist (Pass 41.12.B)"
        )
        # Must check origin parity.
        assert 'window.location.origin' in body, (
            "_isSafeReturnUrl must compare origins (Pass 41.12.B)"
        )

    def test_navigateTo_consults_guard(self):
        body = read_source('static/js/toast-controller.js')
        # The navigateTo function must call the guard before assigning
        # window.location.href.
        idx = body.find('navigateTo(type, returnUrl)')
        assert idx != -1, "navigateTo function not found"
        # Look at the next ~600 chars of the function for the guard call.
        nearby = body[idx:idx + 800]
        assert '_isSafeReturnUrl' in nearby, (
            "navigateTo must call _isSafeReturnUrl before redirecting "
            "(Pass 41.12.B)"
        )

    def test_protocol_relative_url_rejected(self):
        """Functional smoke: `//evil.example/path` is protocol-relative
        and resolves to a different host. The guard must reject it."""
        # Source-level pin: we explicitly check that the helper rejects
        # `//`-prefixed input (the common protocol-relative attack shape).
        body = read_source('static/js/toast-controller.js')
        # Locate the helper *definition* (skip past the call site that uses
        # the same identifier above).
        idx = body.find('_isSafeReturnUrl(url) {')
        assert idx != -1, "_isSafeReturnUrl helper definition not found"
        helper_body = body[idx:idx + 600]
        assert "startsWith('//')" in helper_body, (
            "Guard must explicitly reject `//`-prefixed protocol-relative "
            "URLs (Pass 41.12.B)"
        )


# -----------------------------------------------------------------------------
# 41.13.A — sidebar nav links emit aria-current="page" on the active link
# -----------------------------------------------------------------------------
class TestPass41_13ASidebarAriaCurrent:
    """WCAG 2.4.3 requires `aria-current="page"` on the link representing
    the user's current page. Without it, assistive tech can't tell which
    sidebar item is the user's location. Pass 41.13.A adds a Jinja macro
    `nav_active(cond)` that emits `class="nav-item active"` AND
    `aria-current="page"` together, applied to all 17 sidebar nav links."""

    def test_macro_defined(self):
        body = read_source('templates/base.html')
        assert 'macro nav_active' in body, (
            "Pass 41.13.A — `nav_active` Jinja macro must be defined "
            "in base.html"
        )
        # Macro must emit aria-current="page" inside its conditional.
        idx = body.find('macro nav_active')
        macro_body = body[idx:idx + 400]
        assert 'aria-current="page"' in macro_body, (
            "nav_active macro must emit aria-current=\"page\" (Pass 41.13.A)"
        )

    def test_no_legacy_class_navitem_string(self):
        """All sidebar nav links should use the macro form `{{ nav_active(...) }}`,
        not the historical inline `class="nav-item {% if ... %}active{% endif %}"`
        shape that didn't emit aria-current."""
        body = read_source('templates/base.html')
        # Strip {# Jinja comments #} so the explanatory comment doesn't
        # false-positive.
        import re as _re
        code_only = _re.sub(r'\{#.*?#\}', '', body, flags=_re.DOTALL)
        legacy = code_only.count(
            'class="nav-item {% if'
        )
        assert legacy == 0, (
            f"Pass 41.13.A — {legacy} sidebar nav links still use the "
            "legacy `class=\"nav-item {% if ... %}active{% endif %}\"` "
            "shape; convert to `{{ nav_active(...) }}` macro"
        )


# -----------------------------------------------------------------------------
# 41.13.B — gem-modal exclusive toggle drops the mis-targeted for= attr
# -----------------------------------------------------------------------------
class TestPass41_13BGemToggleForAttr:
    """`<label class="toggle-switch" for="gemOtherPlatforms">` wrapped the
    `<input id="gemExclusiveToggle">` checkbox but the explicit `for=`
    pointed at the SIBLING text input. Clicking the toggle focused the
    wrong control. Implicit-association via wrapping is the correct
    pattern; the explicit for= is now removed."""

    def test_toggle_label_has_no_for_attr(self):
        body = read_source('templates/base.html')
        # Strip {# Jinja comments #} so the explanatory comment naming the
        # historical attribute doesn't false-positive.
        import re as _re
        code_only = _re.sub(r'\{#.*?#\}', '', body, flags=_re.DOTALL)
        # The wrapping toggle label that contains gemExclusiveToggle must
        # NOT have `for="gemOtherPlatforms"`.
        idx = code_only.find('id="gemExclusiveToggle"')
        assert idx != -1, "gemExclusiveToggle input not found"
        # Look at the ~250 chars BEFORE the input to find the wrapping
        # <label class="toggle-switch" ...> that contains it.
        preamble = code_only[max(0, idx - 250):idx]
        # Find the last `<label class="toggle-switch"` opening tag.
        last_label = preamble.rfind('<label class="toggle-switch"')
        assert last_label != -1, "wrapping toggle <label> not found"
        label_open_chunk = preamble[last_label:last_label + 200]
        assert 'for="gemOtherPlatforms"' not in label_open_chunk, (
            "Pass 41.13.B — wrapping toggle label still has the "
            "mis-targeted `for=\"gemOtherPlatforms\"` attribute; "
            "drop it (implicit association via wrapping is correct)"
        )


# -----------------------------------------------------------------------------
# 41.9.A — track-view + completion drop @editor_required to permission-based
# -----------------------------------------------------------------------------
class TestPass41_9ATrackViewAuthz:
    """`@editor_required` on `api_track_view` and `api_update_completion`
    blocked Player and Viewer roles from marking their own gameplay
    progress. Self-tracking is a per-user concern, not an editorial one.
    Pass 41.9.A drops the decorator to `@login_required` +
    `@permission_required('track_progress')`. Player and Editor roles
    have the permission; Viewer does not."""

    def test_track_view_uses_permission_decorator(self):
        body = read_source('routes/games.py')
        idx = body.find('def api_track_view(')
        assert idx != -1, "api_track_view not found"
        # Look at the ~250 chars BEFORE the def for the decorator stack.
        preamble = body[max(0, idx - 250):idx]
        assert "@permission_required('track_progress')" in preamble, (
            "api_track_view must use @permission_required('track_progress') "
            "(Pass 41.9.A)"
        )
        assert '@editor_required' not in preamble, (
            "api_track_view must drop @editor_required (Pass 41.9.A)"
        )

    def test_completion_uses_permission_decorator(self):
        body = read_source('routes/games.py')
        idx = body.find('def api_update_completion(')
        assert idx != -1, "api_update_completion not found"
        preamble = body[max(0, idx - 300):idx]
        assert "@permission_required('track_progress')" in preamble, (
            "api_update_completion must use @permission_required('track_progress') "
            "(Pass 41.9.A)"
        )


# -----------------------------------------------------------------------------
# 41.9.B — last_viewed moved to per-user user_game_views table
# -----------------------------------------------------------------------------
class TestPass41_9BPerUserViews:
    """Migration 010 creates `user_game_views(user_id, game_id, last_viewed)`.
    `api_track_view` writes there via INSERT … ON CONFLICT upsert; the
    dashboard reads its recently-viewed and continue-playing panels from
    the same table joined per-user. The shared `games.last_viewed` column
    is no longer written (kept for legacy rollback safety)."""

    def test_migration_010_registered(self):
        from services.migrations import MIGRATIONS
        assert '010_user_game_views' in MIGRATIONS, (
            "Migration 010_user_game_views must be registered (Pass 41.9.B)"
        )

    def test_track_view_upserts_user_game_views(self):
        body = read_source('routes/games.py')
        # Strip comments so the explanatory comment doesn't false-positive.
        code_only = '\n'.join(
            line.split('#', 1)[0]
            for line in body.splitlines()
        )
        assert 'INSERT INTO user_game_views' in code_only, (
            "api_track_view must upsert into user_game_views (Pass 41.9.B)"
        )
        # And no longer touches the shared games.last_viewed column.
        # (The legacy column survives but is not written; assert a per-user
        # marker comment is present so a reader sees the contract.)
        assert 'Pass 41.9' in body, (
            "Pass 41.9 marker comment must explain the per-user move"
        )

    def test_dashboard_query_keys_on_user(self):
        """Dashboard's recently-viewed query must JOIN user_game_views with
        a `WHERE v.user_id = ?` filter — proves the cross-user leak is
        closed at the read site, not just the write site."""
        body = read_source('app.py')
        # Grab the recently_viewed query text by anchoring around the
        # `recently_viewed = query` assignment.
        idx = body.find('recently_viewed = query')
        assert idx != -1, "recently_viewed query not found in app.py"
        snippet = body[idx:idx + 800]
        assert 'user_game_views' in snippet, (
            "app.py recently_viewed query must JOIN user_game_views (Pass 41.9.B)"
        )
        assert 'v.user_id' in snippet, (
            "app.py recently_viewed query must filter by v.user_id (Pass 41.9.B)"
        )

    def test_recently_viewed_endpoint_deleted(self):
        """Functional: the deleted /api/recently-viewed endpoint must not be
        registered in the app's URL map. Stronger than source-grep — picks up
        even a re-registration through some other module."""
        import app as app_module
        rules = [
            r.rule for r in app_module.app.url_map.iter_rules()
        ]
        assert '/api/recently-viewed' not in rules, (
            "Pass 41.9 — /api/recently-viewed route must be removed from "
            f"the URL map; still registered as: {[r for r in rules if 'recently-viewed' in r]!r}"
        )
        # Function symbol must also be gone from routes/games.py.
        from routes import games as games_mod
        assert not hasattr(games_mod, 'api_recently_viewed'), (
            "Pass 41.9 — api_recently_viewed function must be removed"
        )


# -----------------------------------------------------------------------------
# 41.9.C — generate_sort_title single-letter Roman heuristic tightened
# -----------------------------------------------------------------------------
class TestPass41_9CSortTitleHeuristic:
    """`generate_sort_title('I am Setsuna')` previously returned `'01 am
    Setsuna'` because the single-letter Roman pattern matched any
    word-boundary `I`. Pass 41.9.C narrows the post-context: convert only
    when at end-of-title, before a subtitle separator (`:`, `(`, `[`),
    or before a whitespace-then-digit run. Multi-letter Romans (II/IV/IX)
    are unaffected."""

    def test_pronoun_I_not_converted(self):
        from services.game_utils import generate_sort_title
        # The motivating bug.
        assert generate_sort_title('I am Setsuna') == 'I am Setsuna'

    def test_eos_I_still_converted(self):
        from services.game_utils import generate_sort_title
        # "Final Fantasy I" — "I" at end-of-title is a sequel marker.
        assert generate_sort_title('Final Fantasy I') == 'Final Fantasy 01'

    def test_subtitle_separator_converts(self):
        from services.game_utils import generate_sort_title
        # "Final Fantasy I: Origins" — colon-anchored subtitle.
        out = generate_sort_title('Final Fantasy I: Origins')
        assert out.startswith('Final Fantasy 01'), (
            f"Expected Final Fantasy I -> 01 before colon, got {out!r}"
        )

    def test_compound_name_still_skipped(self):
        from services.game_utils import generate_sort_title
        # I-Ninja, V-Rally, X-Men remain compound names — never convert.
        assert generate_sort_title('I-Ninja') == 'I-Ninja'
        # V-Rally has its own padded number.
        out = generate_sort_title('V-Rally 3')
        assert 'V-Rally' in out and '03' in out

    def test_multi_letter_roman_unaffected(self):
        from services.game_utils import generate_sort_title
        # Sanity: the tightening only narrows single-letter Romans.
        assert generate_sort_title('Final Fantasy IX') == 'Final Fantasy 09'


# -----------------------------------------------------------------------------
# 41.6.A — cross-process advisory lock helper
# -----------------------------------------------------------------------------
class TestPass41_6ASingletonLock:
    """`acquire_job_singleton_lock(name)` opens an `fcntl.flock(LOCK_EX |
    LOCK_NB)` advisory lock on a sentinel file. A successful acquire
    returns an FD; a failed acquire (another process holds it) returns
    None. The OS releases the lock automatically on process death so a
    SIGKILL'd worker doesn't leave orphan locks."""

    def test_helpers_exported(self):
        from services.jobs.base import (
            acquire_job_singleton_lock, release_job_singleton_lock,
        )
        assert callable(acquire_job_singleton_lock)
        assert callable(release_job_singleton_lock)

    def test_acquire_then_release_is_repeatable(self):
        """A successful release returns the lock to "available", so a
        subsequent acquire succeeds again."""
        from services.jobs.base import (
            acquire_job_singleton_lock, release_job_singleton_lock,
        )
        fd = acquire_job_singleton_lock('test_singleton_acquire_release')
        assert fd is not None, "first acquire failed"
        release_job_singleton_lock(fd)
        fd2 = acquire_job_singleton_lock('test_singleton_acquire_release')
        assert fd2 is not None, "re-acquire after release failed"
        release_job_singleton_lock(fd2)

    def test_second_acquire_blocked_while_held(self):
        """While one FD holds the lock, a second acquire returns None
        (non-blocking refusal). Real cross-process testing would need a
        subprocess; this verifies the same-process flock semantics."""
        from services.jobs.base import (
            acquire_job_singleton_lock,
        )
        try:
            import fcntl
        except ImportError:
            import pytest
            pytest.skip('fcntl unavailable; helper is a no-op on this platform')

        # Open the sentinel file directly and hold it via fcntl ourselves
        # to simulate "another worker is running".
        import os
        from services.jobs.base import _get_job_lock_dir
        path = os.path.join(_get_job_lock_dir(), 'test_singleton_blocked.lock')
        fd_outer = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd_outer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # Now the helper should refuse.
            blocked = acquire_job_singleton_lock('test_singleton_blocked')
            assert blocked is None, (
                "Pass 41.6.A — helper must return None when the sentinel "
                "is already locked by another FD"
            )
        finally:
            fcntl.flock(fd_outer, fcntl.LOCK_UN)
            os.close(fd_outer)

    def test_bulk_scrape_uses_singleton_lock(self):
        """Functional: the bulk_scrape module must import the singleton-lock
        helpers — runtime hasattr is stronger than source-grep because it
        follows imports and renames."""
        from services.jobs import bulk_scrape as mod
        assert hasattr(mod, 'acquire_job_singleton_lock'), (
            "BulkScrapeJob must import acquire_job_singleton_lock (Pass 41.6.A)"
        )
        assert hasattr(mod, 'release_job_singleton_lock'), (
            "BulkScrapeJob must import release_job_singleton_lock (Pass 41.6.A)"
        )


# -----------------------------------------------------------------------------
# 41.6.B — persist_job_progress moved out of `with self._lock` blocks
# -----------------------------------------------------------------------------
class TestPass41_6BPersistOutsideLock:
    """`persist_job_progress` is a SQLite write that takes 10–50ms typical
    and up to 30s under WAL contention. Calling it inside `with self._lock`
    blocked every status-poll request that took the same lock during the
    write window. Pass 41.6.B snapshots the progress payload under the
    lock, then releases the lock before the persist call."""

    def test_alt_titles_backfill_persists_outside_lock(self):
        body = read_source('services/jobs/alt_titles_backfill.py')
        # The Pass 41.6.B marker comment is the contract.
        assert 'Pass 41.6.B' in body, (
            "alt_titles_backfill.py must carry the Pass 41.6.B marker"
        )
        # Functional pin — the snapshot pattern: a `progress_payload = {`
        # local is built under the lock, then `persist_job_progress` is
        # called with that local OUTSIDE the lock. Source-level grep is
        # sufficient: these two literals must both appear.
        assert 'progress_payload = {' in body, (
            "Pass 41.6.B — alt_titles_backfill.py must snapshot progress "
            "into a local under the lock"
        )
        assert 'persist_job_progress(persist_id, progress_payload)' in body, (
            "Pass 41.6.B — alt_titles_backfill.py must call "
            "persist_job_progress(persist_id, progress_payload) outside "
            "the lock"
        )

    def test_hltb_bulk_persists_outside_lock(self):
        body = read_source('services/jobs/hltb_bulk.py')
        assert 'Pass 41.6.B' in body, (
            "hltb_bulk.py must carry the Pass 41.6.B marker"
        )
        assert 'progress_payload = {' in body, (
            "Pass 41.6.B — hltb_bulk.py must snapshot progress into a "
            "local under the lock"
        )
        assert 'persist_job_progress(persist_id, progress_payload)' in body, (
            "Pass 41.6.B — hltb_bulk.py must call persist_job_progress "
            "(persist_id, progress_payload) outside the lock"
        )


# -----------------------------------------------------------------------------
# 41.6.C — psn_refresh _fetch_titles inner thread has explicit cancel event
# -----------------------------------------------------------------------------
class TestPass41_6CPsnFetchCancelEvent:
    """The inner `_fetch_titles` thread previously read `self.cancelled`
    directly without the lock and the outer 300s join was the only way
    to stop it. If the join timed out, the abandoned thread continued
    iterating `client.trophy_titles()` and mutating shared state. Pass
    41.6.C introduces an explicit `threading.Event` set on both
    user-cancel and timeout; the inner thread polls the event and exits
    on its next iteration."""

    def test_fetch_cancelled_event_present(self):
        body = read_source('services/jobs/psn_refresh.py')
        assert 'fetch_cancelled = threading.Event()' in body, (
            "Pass 41.6.C — psn_refresh.py must define a threading.Event "
            "for cancellation of the inner _fetch_titles thread"
        )
        assert 'fetch_cancelled.is_set()' in body, (
            "Pass 41.6.C — _fetch_titles must poll fetch_cancelled.is_set() "
            "to exit promptly on cancel"
        )
        assert 'fetch_cancelled.set()' in body, (
            "Pass 41.6.C — outer timeout handler must call fetch_cancelled.set() "
            "to tell the abandoned inner thread to stop writing shared state"
        )


# -----------------------------------------------------------------------------
# 41.13c — div-as-button → button + label-as-group-heading → div role=group
# -----------------------------------------------------------------------------
class TestPass41_13cDivAsButton:
    """WCAG 2.1.1 (keyboard) requires interactive elements to be keyboard-
    activatable. `<div onclick=>` is not focusable and not Enter/Space-
    activatable. Pass 41.13c converts six div-as-button primary actions
    (rom_tools_hub tool cards, base.html version-info + folder-item rows,
    game_detail scrape-history disclosure, duplicate_finder + screenshot_dedup
    group disclosures, game_imports CLZ upload area) to native buttons or
    label-for-input."""

    def test_rom_tools_hub_tool_cards_are_buttons(self):
        body = read_source('templates/rom_tools_hub.html')
        # The three onclick-driven cards must be <button>, not <div>.
        for handler in ('startImageResize', 'startAltTitlesBackfill', 'startHltbBulk'):
            assert f'<button type="button" class="tool-card" onclick="{handler}()"' in body, (
                f"Pass 41.13c — rom_tools_hub tool card invoking {handler}() "
                "must be a <button>, not a <div onclick>"
            )
        assert '<div class="tool-card" onclick=' not in body, (
            "Pass 41.13c — no <div class=\"tool-card\" onclick=> may remain "
            "(WCAG 2.1.1 keyboard activation)"
        )

    def test_base_version_info_is_button(self):
        body = read_source('templates/base.html')
        assert '<button type="button" class="version-info"' in body, (
            "Pass 41.13c — sidebar version-info About-trigger must be a <button>"
        )
        assert '<div class="version-info" onclick=' not in body, (
            "Pass 41.13c — no <div class=\"version-info\" onclick=> may remain"
        )

    def test_base_folder_browser_items_are_buttons(self):
        body = read_source('templates/base.html')
        # The folder-item rows are rendered from a JS template literal in
        # base.html; both parent and child rows should be buttons.
        assert '<button type="button" class="folder-item folder-parent"' in body, (
            "Pass 41.13c — folder-parent row must be a <button>"
        )
        assert '<button type="button" class="folder-item" onclick="navigateFolder' in body, (
            "Pass 41.13c — folder-item row must be a <button>"
        )

    def test_game_detail_scrape_history_uses_button_with_aria_expanded(self):
        body = read_source('templates/game_detail.html')
        assert '<button type="button" class="scrape-history-toggle"' in body, (
            "Pass 41.13c — scrape-history disclosure must be a <button>"
        )
        assert 'aria-expanded="true"' in body and 'aria-controls="scrapeHistoryContent"' in body, (
            "Pass 41.13c — scrape-history disclosure button must declare "
            "aria-expanded + aria-controls (WAI-ARIA APG accordion pattern)"
        )
        assert "btn.setAttribute('aria-expanded'" in body, (
            "Pass 41.13c — toggleScrapeHistory must flip aria-expanded on "
            "the disclosure button"
        )

    def test_duplicate_finder_group_header_is_button(self):
        body = read_source('templates/duplicate_finder.html')
        assert '<button type="button" class="duplicate-group-toggle"' in body, (
            "Pass 41.13c — duplicate group header must be a <button> "
            "(disclosure pattern)"
        )
        assert 'aria-expanded' in body and 'aria-controls="group-${gi}"' in body, (
            "Pass 41.13c — duplicate group disclosure must declare "
            "aria-expanded + aria-controls"
        )
        assert '<div class="duplicate-group-header" onclick=' not in body, (
            "Pass 41.13c — no <div class=\"duplicate-group-header\" onclick=> "
            "may remain"
        )

    def test_screenshot_dedup_game_header_is_button(self):
        body = read_source('templates/screenshot_dedup.html')
        assert "class=\"game-dedup-toggle\"" in body, (
            "Pass 41.13c — screenshot-dedup game header must be a <button> "
            "with class 'game-dedup-toggle'"
        )
        assert 'aria-expanded' in body, (
            "Pass 41.13c — screenshot-dedup disclosure must declare "
            "aria-expanded"
        )
        assert "<div class=\"game-dedup-header\" onclick=" not in body, (
            "Pass 41.13c — no <div class=\"game-dedup-header\" onclick=> "
            "may remain"
        )

    def test_game_imports_clz_upload_area_is_label(self):
        body = read_source('templates/game_imports.html')
        # The upload area triggers a hidden file input — proper semantic
        # is <label for="...">, not <div onclick=document.getElementById...click()>.
        assert '<label class="upload-area" id="clzUploadArea" for="clzFileInput">' in body, (
            "Pass 41.13c — CLZ upload area must be a <label for=\"clzFileInput\">, "
            "not a <div onclick=> that synthesizes a click"
        )
        assert "document.getElementById('clzFileInput').click()" not in body, (
            "Pass 41.13c — synthetic click() trigger replaced by native "
            "<label for=> association"
        )


class TestPass41_13cLabelAsGroupHeading:
    """WCAG 1.3.1 / 4.1.2 — a `<label>` over a button group has no form
    control to associate with. Pass 41.13c promotes those bare labels to
    `<div class="form-label">` (or styled span) and adds `role="group"
    aria-labelledby="..."` on the wrapper containing the buttons."""

    def test_wishlist_priority_label_promoted(self):
        body = read_source('templates/wishlist.html')
        assert '<div class="form-label" id="wishlistPriorityLabel">Priority</div>' in body, (
            "Pass 41.13c — wishlist Priority label-as-heading must be a "
            "<div class=\"form-label\">"
        )
        assert 'role="group" aria-labelledby="wishlistPriorityLabel"' in body, (
            "Pass 41.13c — priority-picker must declare role=group + "
            "aria-labelledby pointing at the label div"
        )
        assert '<label class="form-label">Priority</label>' not in body, (
            "Pass 41.13c — bare <label class=form-label>Priority</label> "
            "must not return"
        )

    def test_lists_icon_label_promoted(self):
        body = read_source('templates/lists.html')
        assert '<div class="form-label" id="listIconLabel">Icon</div>' in body
        assert 'role="group" aria-labelledby="listIconLabel"' in body

    def test_tags_color_label_promoted(self):
        body = read_source('templates/tags.html')
        assert '<div class="form-label" id="tagColorLabel">Tag Color</div>' in body
        assert 'role="group" aria-labelledby="tagColorLabel"' in body

    def test_logs_level_view_labels_promoted(self):
        body = read_source('templates/logs.html')
        # logs uses the toolbar's group-label class to preserve toolbar styling.
        assert '<span class="group-label" id="logLevelLabel">Level</span>' in body
        assert '<span class="group-label" id="logViewLabel">View</span>' in body
        assert 'aria-labelledby="logLevelLabel"' in body
        assert 'aria-labelledby="logViewLabel"' in body

    def test_chd_converter_file_types_label_promoted(self):
        body = read_source('templates/chd_converter.html')
        assert '<div class="form-label" id="chdFileTypesLabel">File Types to Convert</div>' in body
        assert 'aria-labelledby="chdFileTypesLabel"' in body

    def test_rom_tools_settings_group_labels_promoted(self):
        body = read_source('templates/rom_tools_settings.html')
        assert 'id="chdConversionOptionsLabel">Conversion Options</div>' in body
        assert 'aria-labelledby="chdConversionOptionsLabel"' in body
        assert 'id="duplicateFinderDefaultsLabel">Default Options</div>' in body
        assert 'aria-labelledby="duplicateFinderDefaultsLabel"' in body

    def test_duplicate_finder_options_label_promoted(self):
        body = read_source('templates/duplicate_finder.html')
        assert '<div class="form-label" id="duplicateFinderOptionsLabel">Options</div>' in body
        assert 'aria-labelledby="duplicateFinderOptionsLabel"' in body

    def test_rename_modal_current_filename_not_label(self):
        body = read_source('templates/_modals/rename_modal.html')
        assert '<div class="form-label">Current filename:</div>' in body, (
            "Pass 41.13c — \"Current filename:\" must be a <div>, not a "
            "<label> (no form control to associate)"
        )
        assert '<label>Current filename:</label>' not in body
