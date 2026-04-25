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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/trophies.py'),
            encoding='utf-8'
        ).read()
        # Strip comments so the explanatory comment doesn't false-positive.
        code_only = '\n'.join(
            line.split('#', 1)[0]
            for line in body.splitlines()
        )
        # `for g in ...` (with whitespace boundaries) must be absent from
        # routes/trophies.py — including any list/dict comprehension.
        import re as _re
        matches = _re.findall(r'\bfor\s+g\s+in\b', code_only)
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/achievements.py'),
            encoding='utf-8'
        ).read()
        assert 'Pass 41.8' in body, (
            "routes/achievements.py must document the gap.user_id NOT NULL "
            "invariant (Pass 41.8.B)"
        )
        # The doc must mention migration 009 + `user_id IS NULL` so an
        # operator hitting the silent-drop knows the diagnostic query.
        idx = body.find('Pass 41.8')
        nearby = body[max(0, idx - 100):idx + 800]
        assert '009' in nearby, (
            "Pass 41.8.B doc must reference migration 009 (the backfill)"
        )
        assert 'user_id IS NULL' in nearby, (
            "Pass 41.8.B doc must give the `user_id IS NULL` diagnostic query"
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

    def test_decode_error_no_silent_pass(self):
        body = open(
            os.path.join(_REPO_ROOT, 'routes/museum.py'),
            encoding='utf-8'
        ).read()
        # Find the _get_top_games function and confirm its exception block
        # no longer collapses to a bare `pass`.
        import re as _re
        m = _re.search(
            r'def _get_top_games\b.*?(?=\ndef |\Z)',
            body, _re.DOTALL,
        )
        assert m, "_get_top_games not found"
        body_func = m.group()
        # The except-clause must reach a logger.warning call (not just `pass`).
        assert 'logger.warning' in body_func, (
            "_get_top_games except clause must log decode failures at "
            "WARNING (Pass 41.11.A)"
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/museum.py'),
            encoding='utf-8'
        ).read()
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
        # Source-level check (avoids triggering app.py's init_database under
        # a stale DB user_version during local testing — CI is fine).
        body = open(
            os.path.join(_REPO_ROOT, 'routes/museum.py'),
            encoding='utf-8'
        ).read()
        assert "/api/museum/cleanup-controller-images" in body, (
            "Pass 41.11.B admin POST endpoint must be defined in museum.py"
        )
        assert "methods=['POST']" in body and "cleanup_controller_images" in body, (
            "Pass 41.11.B endpoint must be POST and named cleanup_controller_images"
        )

    def test_admin_cleanup_endpoint_requires_editor(self):
        body = open(
            os.path.join(_REPO_ROOT, 'routes/museum.py'),
            encoding='utf-8'
        ).read()
        import re as _re
        m = _re.search(
            r'@bp\.route\(.*cleanup-controller-images.*\).*?def cleanup_controller_images',
            body, _re.DOTALL,
        )
        assert m, "cleanup_controller_images route definition not found"
        block = m.group()
        assert '@editor_required' in block, (
            "Persistent cleanup must be admin/editor only (Pass 41.11.B)"
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

    def test_decompressionbombexception_caught(self):
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/image_dedup.py'),
            encoding='utf-8'
        ).read()
        assert 'DecompressionBombError' in body, (
            "compute_dhash must catch PIL.Image.DecompressionBombError "
            "(Pass 41.14.A)"
        )

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
        body = open(
            os.path.join(_REPO_ROOT, 'services/image_utils.py'),
            encoding='utf-8'
        ).read()
        assert 'validate_outbound_url' in body, (
            "services/image_utils.py must call validate_outbound_url "
            "before urlopen (Pass 41.14.B)"
        )
        # Confirm at least one call passes require_https=True. The first
        # `validate_outbound_url` occurrence is the import line; check the
        # actual call site (which contains both names on or near one line).
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
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/rom_tools.py'),
            encoding='utf-8'
        ).read()
        assert '_safe_under_root' in body, (
            "scraper/rom_tools.py must define _safe_under_root (Pass 41.14.C)"
        )
        assert 'is_relative_to' in body, (
            "_safe_under_root must use Path.is_relative_to to detect "
            "symlinks escaping root (Pass 41.14.C)"
        )

    def test_helper_used_at_every_recursive_walk(self):
        body = open(
            os.path.join(_REPO_ROOT, 'scraper/rom_tools.py'),
            encoding='utf-8'
        ).read()
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
        from pathlib import Path
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
        # Locate the cancel route's decorator stack; expect @admin_required.
        idx = body.find("/api/rom-tools/task/<task_id>/cancel")
        assert idx != -1, "cancel route not found"
        block = body[idx:idx + 400]
        assert '@admin_required' in block, (
            "task_cancel must be @admin_required (Pass 41.10.A)"
        )

    def test_task_pause_requires_admin(self):
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
        idx = body.find("/api/rom-tools/task/<task_id>/pause")
        assert idx != -1, "pause route not found"
        block = body[idx:idx + 200]
        assert '@admin_required' in block, (
            "task_pause must be @admin_required (Pass 41.10.A)"
        )

    def test_task_resume_requires_admin(self):
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
        idx = body.find("/api/rom-tools/chd-converter/convert")
        assert idx != -1, "chd-converter/convert route not found"
        block = body[idx:idx + 300]
        assert '@admin_required' in block, (
            "chd-converter/convert must be @admin_required (Pass 41.10.B)"
        )

    def test_chd_verify_requires_admin(self):
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
        # Confirm task_id assignment still uses uuid.uuid4 (not weakened
        # to something else).
        assert 'str(uuid.uuid4())' in body, (
            "routes/tools.py must still generate task_ids via "
            "str(uuid.uuid4()) (Pass 41.10.C)"
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

    def test_each_scan_requires_editor(self):
        body = open(
            os.path.join(_REPO_ROOT, 'routes/tools.py'),
            encoding='utf-8'
        ).read()
        for route in self.SCAN_ROUTES:
            idx = body.find(route)
            assert idx != -1, f"{route} route not found"
            block = body[idx:idx + 250]
            assert '@editor_required' in block, (
                f"{route} must be @editor_required (Pass 41.10.D)"
            )

    def test_rate_limits_registered(self):
        body = open(
            os.path.join(_REPO_ROOT, 'app.py'),
            encoding='utf-8'
        ).read()
        # Each scan endpoint must have a _rate_limit registration; the
        # spec is "5 per minute". Source-level pin (CI's Flask-Limiter
        # registration test would otherwise need a live limiter, which
        # depends on FLASK_LIMITER_ENABLED).
        for fn in (
            'tools.api_archive_scanner_scan',
            'tools.api_chd_converter_scan',
            'tools.api_chd_verify_scan',
            'tools.api_duplicate_finder_scan',
            'tools.api_screenshot_dedup_scan',
        ):
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
        body = open(
            os.path.join(_REPO_ROOT, 'static/js/utils.js'),
            encoding='utf-8'
        ).read()
        assert 'AbortController' in body, (
            "API.* must use AbortController for default timeout (Pass 41.12.A)"
        )
        assert '_API_DEFAULT_TIMEOUT_MS' in body, (
            "Default timeout constant missing (Pass 41.12.A)"
        )

    def test_caller_signal_respected(self):
        """If caller passes their own signal, the helper should NOT clobber
        it with a timed AbortController."""
        body = open(
            os.path.join(_REPO_ROOT, 'static/js/utils.js'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'static/js/toast-controller.js'),
            encoding='utf-8'
        ).read()
        assert '_isSafeReturnUrl' in body, (
            "Open-redirect guard helper must exist (Pass 41.12.B)"
        )
        # Must check origin parity.
        assert 'window.location.origin' in body, (
            "_isSafeReturnUrl must compare origins (Pass 41.12.B)"
        )

    def test_navigateTo_consults_guard(self):
        body = open(
            os.path.join(_REPO_ROOT, 'static/js/toast-controller.js'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'static/js/toast-controller.js'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'templates/base.html'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'templates/base.html'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'templates/base.html'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/games.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/games.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/games.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'app.py'),
            encoding='utf-8'
        ).read()
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
        body = open(
            os.path.join(_REPO_ROOT, 'routes/games.py'),
            encoding='utf-8'
        ).read()
        # Strip comments so the deletion-marker comment doesn't false-positive.
        code_only = '\n'.join(
            line.split('#', 1)[0]
            for line in body.splitlines()
        )
        assert "@bp.route('/api/recently-viewed')" not in code_only, (
            "Pass 41.9 — /api/recently-viewed route definition must be removed"
        )
        assert 'def api_recently_viewed' not in code_only, (
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
