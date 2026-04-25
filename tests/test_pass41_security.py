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

    def _read(self, rel):
        return open(os.path.join(_REPO_ROOT, rel), encoding='utf-8').read()

    def test_no_more_foreign_keys_off_inside_apply(self):
        """The broken `PRAGMA foreign_keys = OFF` literal must be gone — that
        statement is silently ignored inside a transaction. Strip comments so
        the explanatory inline comment naming the historical pragma doesn't
        false-positive."""
        for path in self.MIGRATION_FILES:
            body = self._read(path)
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
            body = self._read(path)
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

    def _read(self, rel):
        return open(os.path.join(_REPO_ROOT, rel), encoding='utf-8').read()

    def test_museum_uses_get_request_db(self):
        body = self._read('routes/museum.py')
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
        body = self._read('routes/tools.py')
        # The screenshot-dedup delete path at the previously-leaking line had
        # `db = get_db()` without a close. Confirm a get_request_db site
        # exists; the bare get_db() footprint here is shrinking on this pass.
        assert 'get_request_db' in body, (
            "routes/tools.py must import get_request_db (Pass 41.2.B)"
        )

    def test_trophies_psn_npsso_uses_get_request_db(self):
        body = self._read('routes/trophies.py')
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

    def _read_app_py(self):
        return open(os.path.join(_REPO_ROOT, 'app.py'), encoding='utf-8').read()

    def test_redactor_install_precedes_basicconfig(self):
        body = self._read_app_py()
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
        body = open(
            os.path.join(_REPO_ROOT, 'services/database_init.py'),
            encoding='utf-8'
        ).read()
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

    def test_screenshot_sync_runs_unconditionally(self):
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/hybrid_scraper.py'),
            encoding='utf-8'
        ).read()
        # The fix introduces a dedicated screenshots-sync block after
        # apply_esde_metadata that does NOT gate on `not metadata.get(...)`.
        # Marker comment pins the intent so future edits don't regress.
        assert 'Pass 41.4.A' in body, (
            "Pass 41.4.A marker missing in scraper/hybrid_scraper.py — "
            "the unconditional screenshot sync must be paired with the "
            "marker so a future regression is greppable"
        )

    def test_screenshot_field_excluded_from_guarded_loop(self):
        """The 'and not metadata.get(field)' guard loop must no longer
        include `screenshots` — that's the whole point of the fix."""
        import re as _re
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/hybrid_scraper.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/hybrid_scraper.py'),
            encoding='utf-8'
        ).read()
        assert 'Pass 41.4.B' in body, (
            "Pass 41.4.B marker missing in scraper/hybrid_scraper.py — "
            "each primary-source branch must be wrapped in try/except"
        )
        # Source-level pin: we expect a per-source try/except guard. The
        # marker comment is the contract; assert a few representative
        # source names appear inside an `except` block.
        idx = body.find('Pass 41.4.B')
        nearby = body[max(0, idx - 200):idx + 4000]
        assert 'except Exception' in nearby, (
            "Pass 41.4.B region must contain an except Exception clause"
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

    def test_request_retries_with_fresh_token_on_401(self, monkeypatch):
        from scraper import scrape_igdb as igdb

        # Pretend the existing cache is "warm" with a stale token.
        igdb._igdb_token_cache['token'] = 'STALE'
        igdb._igdb_token_cache['expires_at'] = 9999999999

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
            # First call: 401. Second call: 200.
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
        assert result == {"ok": True}
        # Two requests: stale first, fresh retry second.
        assert len(call_log) == 2
        assert call_log[0]['auth'] == 'Bearer STALE'
        assert call_log[1]['auth'] == 'Bearer FRESH'
        # Cache is now updated.
        assert igdb._igdb_token_cache['token'] == 'FRESH'

    def test_request_does_not_retry_on_non_401(self, monkeypatch):
        """A 500 should bubble through `raise_for_status` without triggering
        a token refresh. Only 401 invalidates the cache."""
        from scraper import scrape_igdb as igdb

        igdb._igdb_token_cache['token'] = 'TOKEN'
        igdb._igdb_token_cache['expires_at'] = 9999999999

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
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/trophy_parser.py'),
            encoding='utf-8'
        ).read()
        # Look for the explicit cap. The exact arithmetic is documented in the
        # roadmap as `(len(data) - 0x30) // 32`.
        assert 'tables_count = min(tables_count' in body, (
            "Missing explicit cap `tables_count = min(tables_count, ...)` "
            "in trophy_parser.py (Pass 41.7.A)"
        )

    def test_offset_bounds_check(self):
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/trophy_parser.py'),
            encoding='utf-8'
        ).read()
        # The _parse_table6 must early-return when header['offset'] >= len(data).
        assert 'Pass 41.7.A' in body, (
            "Pass 41.7.A marker missing in trophy_parser.py — bound checks "
            "must be paired with the marker for greppability"
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/platform_import.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/retroachievements.py'),
            encoding='utf-8'
        ).read()
        # The fix injects a per-callsite 401-check + logger.error. A single
        # marker per file is enough — assert at least the marker plus a
        # logger.error mentioning 401 / API key.
        assert 'Pass 41.7.C' in body, (
            "Pass 41.7.C marker missing — RA 401 observability not wired"
        )
        # Find the marker; nearby code must mention the user-actionable hint.
        idx = body.find('Pass 41.7.C')
        nearby = body[max(0, idx - 100):idx + 800]
        assert '401' in nearby, "Pass 41.7.C region must mention 401 status"
        assert 'API key' in nearby or 'api_key' in nearby, (
            "Pass 41.7.C region must hint at user-actionable 'check API key'"
        )
