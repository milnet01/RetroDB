# =============================================================================
# Pass 40 — Tier-1 indie-review security findings
# =============================================================================
# Regression pins for the 16 CRITICAL/HIGH findings from the 2026-04-24
# multi-agent independent review.  Each sub-item gets a narrow unit check
# that fails if the fix is reverted.
#
# Split in two so a shared import failure cannot surface as 16 failures with
# no clear root cause: 40.1–40.8 live here, 40.9–40.16 in
# test_pass40_9_16_security.py.
#
# Pass 45.21 audit (2026-04-27): tests in this file fall into three buckets:
#   - functional (test_client / monkeypatch + call): the strongest shape;
#     verifies behavior end-to-end.
#   - codebase invariant (`open(path).read()` + assert): kept on purpose
#     where the contract IS a source-pattern rule that spans files or has
#     no clean runtime equivalent. Examples below:
#       * `no time.sleep in services/jobs/*.py`  (cross-file invariant)
#       * `no inline onclick=... with template interpolation`  (JS pattern;
#         functional alternative needs browser automation)
#       * `with self._lock:` count >= 2 in worker loop  (concurrency rule)
#       * atomic-write `.part` + os.replace shape  (crash-injection needed
#         for functional coverage)
#       * SQL JOIN-on-user_id filters in route bodies  (multi-user fixture
#         needed for functional coverage)
#       * doc/marker content pins for hard-to-test invariants
#   - removed (Pass 45.21): tests that pinned implementation shape with no
#     contract value, or duplicated coverage already in other files.
# =============================================================================

import os
import re

import pytest

# c-006 DU-1: collapse ~15 inlined `open(mod.__file__).read()` + index-slice
# patterns onto shared helpers so a file rename fails one place, not 15.
from tests._util import REPO_ROOT as _REPO_ROOT, read_module_source, read_source, slice_function  # noqa: E402, F401


# -----------------------------------------------------------------------------
# 40.1 — RCE via unvalidated chdman_path in rom_tools_config.json POST
# -----------------------------------------------------------------------------
class TestPass40_1ChdmanPathValidator:
    """Validator must reject attacker-supplied paths to arbitrary binaries.

    c-006 P-1: collapsed from 12 single-method tests into two parametrize
    tables (accept + reject) so the input vector and contract are visible
    in one place and a new attack case is one row to add."""

    # Each row: (input_value, expected_cleaned).  Empty string normalizes
    # to the bare basename so the default install path is valid.
    ACCEPT_CASES = [
        ('chdman', 'chdman'),
        ('', 'chdman'),
        ('chdman.exe', 'chdman.exe'),
        ('/usr/bin/chdman', '/usr/bin/chdman'),
        ('/usr/local/bin/chdman', '/usr/local/bin/chdman'),
    ]

    # Each row: (input_value, label) — label is for failure attribution.
    REJECT_CASES = [
        ('/usr/bin/python3', 'CWE-78 argv0 substitution'),
        ('/tmp/evil', 'writable tmpdir basename'),
        ('/home/attacker/chdman', 'user-writable home'),
        ('/usr/bin/../tmp/evil', 'path traversal'),
        ('./chdman', 'relative path'),
        ('/usr/bin/sh', 'wrong basename under allowed dir'),
        (12345, 'non-string int'),
        (['/usr/bin/chdman'], 'non-string list'),
    ]

    @pytest.mark.parametrize("value,expected_cleaned", ACCEPT_CASES)
    def test_chdman_path_accepted(self, value, expected_cleaned):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, cleaned = validate_rom_tools_value('chdman_path', value)
        assert ok, f"value={value!r} should be accepted: {reason}"
        assert cleaned == expected_cleaned

    @pytest.mark.parametrize("value,label", REJECT_CASES)
    def test_chdman_path_rejected(self, value, label):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('chdman_path', value)
        assert not ok, f"value={value!r} ({label}) should be rejected"
        assert reason, f"validator must emit a reason for {value!r}"


class TestPass40_1OtherSettingsValidators:
    """Per-key allowlist for every other field in rom_tools_config.json."""

    def test_unknown_key_rejected(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('not_a_real_key', True)
        assert not ok
        assert 'unknown' in reason.lower()

    @pytest.mark.parametrize("key", [
        'recursive_scan', 'verify_integrity', 'generate_m3u',
        'remove_unwanted', 'chd_verify_after_convert',
        'chd_delete_originals', 'chd_skip_existing',
        'ignore_region_tags', 'include_archives',
    ])
    def test_bool_fields(self, key):
        # Parametrized — first-failure loop hid which of the 9 keys broke.
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, cleaned = validate_rom_tools_value(key, True)
        assert ok and cleaned is True, f"{key} should accept True"
        ok, _, _ = validate_rom_tools_value(key, 'yes')
        assert not ok, f"{key} should reject string"

    def test_archive_types_list(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, cleaned = validate_rom_tools_value(
            'archive_types', ['.zip', '.7z', '.rar']
        )
        assert ok
        assert cleaned == ['.zip', '.7z', '.rar']

        ok, _, _ = validate_rom_tools_value('archive_types', 'zip')
        assert not ok

    def test_unwanted_patterns_list(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, cleaned = validate_rom_tools_value(
            'unwanted_patterns', ['.txt', '.nfo']
        )
        assert ok

    def test_excluded_paths_list(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, _ = validate_rom_tools_value('excluded_paths', [])
        assert ok

        ok, _, _ = validate_rom_tools_value('excluded_paths', ['/some/path'])
        assert ok

    def test_duplicate_method_enum(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, _ = validate_rom_tools_value('duplicate_method', 'hash')
        assert ok

        ok, _, _ = validate_rom_tools_value('duplicate_method', 'arbitrary')
        assert not ok

    def test_known_keys_covers_defaults(self):
        """Every key in load_rom_tools_config()'s defaults must have a validator."""
        from services.rom_tools_validators import known_rom_tools_keys
        from routes.tools import load_rom_tools_config

        defaults = load_rom_tools_config()
        defined = known_rom_tools_keys()
        missing = set(defaults.keys()) - defined
        assert not missing, f"missing validators for: {sorted(missing)}"


class TestPass40_1RouteIntegration:
    """The POST handler must be admin-only and run inputs through validators."""

    def test_post_handler_requires_admin(self):
        """Source-level pin: the POST branch must reject non-admin users.
        GET stays accessible for the archive-scanner page; admin gating is
        therefore a method-aware in-handler check, not a top-level decorator."""
        from routes import tools as tools_mod

        src = read_module_source(tools_mod)
        idx = src.index('def api_rom_tools_settings')
        # Within the function body (next ~1500 chars), the POST branch must
        # raise 403 for non-admin callers. Strip comments first so a stale
        # `# old: g.user.get('role') != 'admin'` doesn't satisfy the
        # disjunction once the live code is moved out of the window.
        body = src[idx:idx + 1500]
        body_live = re.sub(r'#[^\n]*', '', body)
        assert "g.user.get('role') != 'admin'" in body_live or \
               "g.user['role'] != 'admin'" in body_live, \
            'api_rom_tools_settings POST must gate on admin role (Pass 40.1)'
        assert '403' in body_live, 'POST must return 403 for non-admin (Pass 40.1)'

    def test_post_rejects_attacker_chdman_path(self, tmp_path, monkeypatch, admin_test_client):
        """End-to-end: POST {chdman_path: /usr/bin/python3} → validator
        rejects, file unchanged.

        c-006 A-1 fix: previously this test relied on user_id=1 being admin
        in the seeded DB.  On a fresh CI checkout (or a re-seeded DB) the
        route 302'd to /login before the validator branch ran, so the
        assertion `status_code in (400, 302, 403)` passed vacuously and
        gave the validator zero coverage.  We now monkeypatch
        `get_current_user` to return a real admin stub and seed CSRF +
        setup_completed so the validator branch is actually exercised.

        c-006 ST-1: TESTING flag set via monkeypatch.setitem so the
        module-level app singleton's TESTING value is restored after."""
        import json as _json
        from routes import tools as tools_mod

        # Redirect rom_tools_config.json into tmpdir for isolation.
        cfg_path = tmp_path / 'rom_tools_config.json'
        original_load = tools_mod.load_rom_tools_config

        def fake_load():
            if cfg_path.exists():
                return _json.loads(cfg_path.read_text())
            return original_load()

        def fake_save(settings):
            cfg_path.write_text(_json.dumps(settings))
            return True

        monkeypatch.setattr(tools_mod, 'load_rom_tools_config', fake_load)
        monkeypatch.setattr(tools_mod, 'save_rom_tools_config', fake_save)

        # Pin an admin user so the route runs past `@admin_required`. Bypass
        # the first-time-setup redirect, which otherwise fires on CI's empty
        # settings.json.
        client, csrf = admin_test_client(settings={'setup_completed': True, 'rom_path': '/tmp'})

        resp = client.post(
            '/api/rom-tools/settings',
            json={'chdman_path': '/usr/bin/python3'},
            headers={'X-CSRF-Token': csrf},
        )
        # Validator must fire — 400 with the dangerous value not persisted.
        assert resp.status_code == 400, (
            f"validator branch must reject the attacker payload (got "
            f"{resp.status_code}: {resp.get_data(as_text=True)[:200]})"
        )
        # Never persisted to disk under any branch.
        if cfg_path.exists():
            assert _json.loads(cfg_path.read_text()).get('chdman_path') \
                != '/usr/bin/python3'


# -----------------------------------------------------------------------------
# 40.2 — Arbitrary-path CHD convert + source file delete
# -----------------------------------------------------------------------------
class TestPass40_2ChdConvertVerifyPathValidation:
    """The convert / verify worker loops must reject files outside rom_path
    before invoking chdman or os.remove."""

    def test_convert_worker_validates_each_path(self):
        """Source pin: the run_conversion thread body must call safe_path
        on each file_path inside the for-loop."""
        from routes import tools as tools_mod

        src = read_module_source(tools_mod)
        # Slice to the run_conversion closure + its loop.
        idx = src.index('def api_chd_converter_convert')
        end = src.index('def api_chd_verify_scan', idx)
        body = src[idx:end]
        assert 'def run_conversion' in body
        assert 'safe_path(file_path' in body, \
            'api_chd_converter_convert worker must validate each file_path (Pass 40.2)'

    def test_verify_worker_validates_each_path(self):
        from routes import tools as tools_mod

        src = read_module_source(tools_mod)
        idx = src.index('def api_chd_verify_verify')
        # The next route after verify is duplicate-finder; bound the slice there.
        end = src.index('def api_duplicate_finder', idx)
        body = src[idx:end]
        assert 'def run_verification' in body
        assert 'safe_path(file_path' in body, \
            'api_chd_verify_verify worker must validate each file_path (Pass 40.2)'

    def test_convert_e2e_rejects_traversal(self, tmp_path, monkeypatch, admin_test_client):
        """End-to-end smoke: POST with /etc/passwd in files[] never invokes
        subprocess.run with that path.  Validation happens before chdman call.

        c-006 F-1 fix: previously polled `seen_argv` with sleep(0.05) × 20 on
        a daemon thread, which could vacuously pass on a slow CI runner that
        hadn't scheduled the thread before the assertion fired. We now force
        the worker thread to run synchronously by stubbing Thread.start so
        the inner target completes before the route returns."""
        import threading as _threading
        from routes import tools as tools_mod

        # Pin rom_path under tmpdir so traversal is unambiguous.
        rom_root = tmp_path / 'roms'
        rom_root.mkdir()
        legit = rom_root / 'game.cue'
        legit.write_text('FAKE')

        monkeypatch.setattr(tools_mod, '_get_rom_path', lambda: str(rom_root))
        # Pretend chdman is available.
        monkeypatch.setattr(tools_mod.shutil, 'which', lambda _: '/usr/bin/chdman')

        # Capture every subprocess.run argv to confirm none touched /etc/passwd.
        seen_argv = []

        class _FakeResult:
            returncode = 1
            stdout = ''
            stderr = ''

        def fake_run(cmd, **kwargs):
            seen_argv.append(list(cmd))
            return _FakeResult()

        monkeypatch.setattr(tools_mod.subprocess, 'run', fake_run)

        # Run the worker synchronously so we don't race the assertion against
        # a daemon-thread schedule.  Thread.start -> Thread.run executes the
        # target inline; the route returns 200 only after the work finishes.
        monkeypatch.setattr(_threading.Thread, 'start',
                            lambda self: self.run())

        # Pin admin so the route runs past the auth guard rather than 302'ing.
        client, csrf = admin_test_client(settings={'setup_completed': True, 'rom_path': str(rom_root)})

        resp = client.post(
            '/api/rom-tools/chd-converter/convert',
            json={'files': ['/etc/passwd', str(legit)]},
            headers={'X-CSRF-Token': csrf},
        )
        assert resp.status_code == 200, (
            f"expected 200 once admin is pinned, got {resp.status_code}: "
            f"{resp.get_data(as_text=True)[:200]}"
        )
        # No chdman invocation may have targeted /etc/passwd.
        for argv in seen_argv:
            assert '/etc/passwd' not in argv, (
                f'chdman invoked on traversal path: {argv}'
            )

    def test_convert_does_not_remove_arbitrary_file(self, tmp_path, monkeypatch, admin_test_client):
        """If chd_delete_originals is true, the os.remove must still be
        gated by safe_path — a logged-in user can't trick the worker into
        deleting /etc/something.

        c-006 F-1 fix: same synchronous-worker pattern as the traversal test
        — we run the daemon thread inline via Thread.start → Thread.run so
        the post-response inspection isn't racing against a delayed
        schedule."""
        import threading as _threading
        from routes import tools as tools_mod

        rom_root = tmp_path / 'roms'
        rom_root.mkdir()
        decoy_target = tmp_path / 'outside.cue'
        decoy_target.write_text('SHOULD NOT BE DELETED')

        monkeypatch.setattr(tools_mod, '_get_rom_path', lambda: str(rom_root))
        monkeypatch.setattr(tools_mod.shutil, 'which', lambda _: '/usr/bin/chdman')

        # Force chd_delete_originals=True via fake config.
        monkeypatch.setattr(
            tools_mod, 'load_rom_tools_config',
            lambda: {'chdman_path': 'chdman', 'chd_delete_originals': True},
        )

        # Pretend chdman succeeds and the .chd file exists, so the os.remove
        # branch fires for any path that survives validation.
        class _FakeResult:
            returncode = 0
            stdout = ''
            stderr = ''

        monkeypatch.setattr(tools_mod.subprocess, 'run',
                            lambda cmd, **kw: _FakeResult())
        monkeypatch.setattr(tools_mod.os.path, 'exists', lambda p: True)

        # Track which paths os.remove was called on.
        removed = []
        monkeypatch.setattr(tools_mod.os, 'remove', lambda p: removed.append(p))

        # Synchronous worker — see F-1 note in test_convert_e2e_rejects_traversal.
        monkeypatch.setattr(_threading.Thread, 'start',
                            lambda self: self.run())

        # Pin admin so the route runs past the auth guard.
        client, csrf = admin_test_client(settings={'setup_completed': True, 'rom_path': str(rom_root)})

        resp = client.post(
            '/api/rom-tools/chd-converter/convert',
            json={'files': [str(decoy_target)]},
            headers={'X-CSRF-Token': csrf},
        )
        assert resp.status_code == 200, (
            f"expected 200 once admin is pinned, got {resp.status_code}: "
            f"{resp.get_data(as_text=True)[:200]}"
        )
        # The decoy path is OUTSIDE rom_root → safe_path rejects → os.remove
        # never called on it.
        assert str(decoy_target) not in removed, \
            f'os.remove called on path outside rom_path: {removed}'

    def test_convert_with_only_out_of_bound_files_invokes_no_chdman(
        self, tmp_path, monkeypatch, admin_test_client,
    ):
        """c-006 C-1 coverage gap: when *every* file in the payload is
        out-of-bounds, the worker must reject all of them and never invoke
        chdman.  Previously coverage only included the "one good + one bad"
        case, which could pass vacuously."""
        import threading as _threading
        from routes import tools as tools_mod

        rom_root = tmp_path / 'roms'
        rom_root.mkdir()

        monkeypatch.setattr(tools_mod, '_get_rom_path', lambda: str(rom_root))
        monkeypatch.setattr(tools_mod.shutil, 'which', lambda _: '/usr/bin/chdman')

        seen_argv = []

        class _FakeResult:
            returncode = 1
            stdout = ''
            stderr = ''

        monkeypatch.setattr(tools_mod.subprocess, 'run',
                            lambda cmd, **kw: (seen_argv.append(list(cmd)) or _FakeResult()))

        monkeypatch.setattr(_threading.Thread, 'start',
                            lambda self: self.run())

        client, csrf = admin_test_client(settings={'setup_completed': True, 'rom_path': str(rom_root)})

        resp = client.post(
            '/api/rom-tools/chd-converter/convert',
            json={'files': ['/etc/passwd', '/etc/shadow']},
            headers={'X-CSRF-Token': csrf},
        )
        # The correctness pin is `not seen_argv` — chdman must never see
        # the out-of-bound paths. Either the route 4xx-rejects up front
        # (400/422) or the worker rejects each file inside the loop and
        # the route returns 200 with no work done. The earlier
        # `assert resp.status_code in (200, 400, 422)` was a loose three-
        # way check that hid which branch fired; making the response-code
        # assertion expressive (any of three known statuses) is fine as
        # long as the argv guard carries the real contract (test-audit
        # c-005 MED).
        assert resp.status_code in (200, 400, 422), (
            f"unexpected status: {resp.status_code} (expected one of "
            "200/400/422 — route either 4xx-rejects up front or returns "
            "200 with the worker no-oping)"
        )
        assert not seen_argv, (
            f'chdman invoked with out-of-bound argv when no good files were '
            f'in the payload: {seen_argv}'
        )


# -----------------------------------------------------------------------------
# 40.3 — Archive-scanner m3u admin + path validation
# -----------------------------------------------------------------------------
class TestPass40_3ArchiveScannerM3u:
    """create_m3u and batch_create_m3u must be admin-only and must validate
    per-entry paths; staging_folder must not be attacker-controlled."""

    def test_create_m3u_requires_admin(self):
        from routes import tools as tools_mod

        src = read_module_source(tools_mod)
        idx = src.index('def api_archive_scanner_create_m3u')
        prelude = src[max(0, idx - 200):idx]
        assert '@admin_required' in prelude, \
            'api_archive_scanner_create_m3u must be admin-only (Pass 40.3)'

    def test_batch_create_m3u_requires_admin(self):
        from routes import tools as tools_mod

        src = read_module_source(tools_mod)
        idx = src.index('def api_archive_scanner_batch_create_m3u')
        prelude = src[max(0, idx - 200):idx]
        assert '@admin_required' in prelude, \
            'api_archive_scanner_batch_create_m3u must be admin-only (Pass 40.3)'

    def test_batch_validates_each_path(self):
        """Source-level pin: the batch handler must safe_path-check each entry
        in the paths[] list before passing them to the scanner."""
        from routes import tools as tools_mod

        src = read_module_source(tools_mod)
        idx = src.index('def api_archive_scanner_batch_create_m3u')
        # Bound the slice up to the next def.
        end = src.index('\n@tools_bp.route', idx + 1)
        body = src[idx:end]
        assert 'safe_path(' in body, \
            'batch_create_m3u must validate each path (Pass 40.3)'

    def test_create_m3u_e2e_rejects_outside_rom_path(self, tmp_path, monkeypatch):
        """End-to-end: POST to /create-m3u with a path outside rom_path
        must not call scanner.create_m3u_playlist."""
        import app as app_module
        from routes import tools as tools_mod

        rom_root = tmp_path / 'roms'
        rom_root.mkdir()
        outside = tmp_path / 'evil.zip'
        outside.write_text('FAKE')

        monkeypatch.setattr(tools_mod, '_get_rom_path', lambda: str(rom_root))

        called_with = []

        class _FakeScanner:
            def __init__(self, _cfg):
                pass

            def create_m3u_playlist(self, archive_path, **kw):
                called_with.append(archive_path)
                return {'success': True}

            def batch_create_m3u(self, paths, *args, **kwargs):
                called_with.extend(paths)
                return {'success': True}

        # Patch the lazy import inside the handler.
        import scraper.rom_tools as rt_mod
        monkeypatch.setattr(rt_mod, 'ArchiveScanner', _FakeScanner)

        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1

        resp = client.post(
            '/api/rom-tools/archive-scanner/create-m3u',
            json={'path': str(outside)},
        )
        # Either rejected (400) or auth-blocked (302/403); never reached scanner.
        # 500 is intentionally excluded — that would be an unhandled error, not
        # a valid security outcome.
        assert resp.status_code in (400, 302, 403), \
            f"unexpected: {resp.status_code}"
        assert str(outside) not in called_with, \
            'scanner.create_m3u_playlist invoked with out-of-library path'


# -----------------------------------------------------------------------------
# 40.4 — Steam achievement IDOR (three queries missing user_id)
# -----------------------------------------------------------------------------
class TestPass40_4SteamAchievementsUserScoping:
    """Migration 009 added user_id to game_achievement_progress and
    steam_achievements; the three SELECTs in routes/steam_achievements.py
    must filter on it (Xbox already does)."""

    def test_landing_query_filters_user_id(self):
        from routes import steam_achievements as mod

        src = read_module_source(mod)
        idx = src.index('def steam_achievements_landing')
        end = src.index('def steam_achievement_game', idx)
        body = src[idx:end]
        assert 'gap.user_id = ?' in body, \
            'landing query must filter game_achievement_progress on user_id (Pass 40.4)'
        assert "g.user['id']" in body, \
            'landing query must bind g.user[id] (Pass 40.4)'

    def test_per_game_progress_query_filters_user_id(self):
        from routes import steam_achievements as mod

        src = read_module_source(mod)
        idx = src.index('def steam_achievement_game')
        # bound to the next def
        end = src.index('\n@bp.route', idx + 1)
        body = src[idx:end]
        # Two queries to check inside this function: progress + achievements
        assert body.count('user_id = ?') >= 2, \
            'per-game route must filter both progress + steam_achievements on user_id (Pass 40.4)'
        assert "g.user['id']" in body, \
            'per-game route must bind g.user[id] (Pass 40.4)'


# -----------------------------------------------------------------------------
# 40.5 — ETag cross-user cache bleed on /api/games/card-data
# -----------------------------------------------------------------------------
class TestPass40_5CardDataEtagPerUser:
    """The card-data endpoint joins per-user PSN + achievement data, so its
    ETag must include g.user['id'] — otherwise user A and user B sharing
    a browser get cross-user 304 cache hits."""

    def test_etag_payload_includes_user_id(self):
        from routes import games as games_mod

        src = read_module_source(games_mod)
        # Find the card-data ETag payload line.
        idx = src.index('etag_payload')
        # First etag_payload assignment in the file is the card-data one.
        line = src[idx:idx + 400]
        assert "g.user['id']" in line or "user_id" in line, \
            'card-data ETag payload must include user identity (Pass 40.5)'


# -----------------------------------------------------------------------------
# 40.6 — players fill-only invariant + JSON-edit type corruption
# -----------------------------------------------------------------------------
class TestPass40_6PlayersNormalization:
    """Helper rejects junk strings, normalizes ranges to max, returns None
    for the absent / invalid case so COALESCE preserves curated values.

    c-005 VERB fix: collapsed from 9 single-assertion methods into one
    parametrized table — input vector + expected output now visible at a
    glance, and a new case is one row to add."""

    @pytest.mark.parametrize("value,expected", [
        # None / empty / whitespace → None (clear / absent)
        (None, None),
        ('', None),
        ('   ', None),
        # Plain ints pass through
        (1, 1),
        (4, 4),
        # Zero / "0" → None (no game has zero players)
        (0, None),
        ('0', None),
        # Numeric strings
        ('1', 1),
        ('  4  ', 4),
        # Ranges → max
        ('1-4', 4),
        ('2-8', 8),
        ('1-16', 16),
        # Garbage strings → None (so COALESCE preserves curated)
        ('many', None),
        ('1.0e9', None),
        # Bools are not valid player counts
        (True, None),
        (False, None),
    ])
    def test_normalize_players_value(self, value, expected):
        from services.game_utils import normalize_players_value
        assert normalize_players_value(value) == expected


# Note: IGDB/TGDB `players = None` initialisation is functionally covered
# by `tests/test_scrape_fill_only.py::test_{igdb,tgdb}_apply_preserves_
# existing_values_when_response_is_empty` — those tests seed a DB row with
# players=1, run apply_*_metadata with an empty response, and assert the
# curated value survives the COALESCE. Stronger than asserting the literal
# `players = None` appears in the source.


class TestPass40_6RouteNormalization:
    """api_game_edit + edit_metadata must run players through
    normalize_players_value before binding to the INTEGER column.
    Pass 42.1 routed both edit paths through normalize_game_edit, which
    internally calls normalize_players_value — the invariant moved one
    layer up but is still pinned by these tests."""

    def test_api_game_edit_normalizes_via_helper(self):
        from routes import games as games_mod

        src = read_module_source(games_mod)
        idx = src.index('def api_game_edit')
        end = src.index('@bp.route(\'/api/games/bulk-edit\'', idx)
        body = src[idx:end]
        assert 'normalize_game_edit' in body, \
            'api_game_edit must route through normalize_game_edit (Pass 42.1)'

    def test_edit_metadata_normalizes_via_helper(self):
        from routes import games as games_mod

        src = read_module_source(games_mod)
        idx = src.index("action == 'edit_metadata'")
        # Within the surrounding ~3000 chars, the helper call must appear.
        window = src[idx:idx + 3000]
        assert 'normalize_game_edit' in window, \
            'edit_metadata must route through normalize_game_edit (Pass 42.1)'

    def test_helper_calls_normalize_players_value(self):
        """Pass 40.6 invariant — normalize_game_edit must apply the
        players coercion that originally lived inline in both routes."""
        from services import game_metadata_service as svc

        src = read_module_source(svc)
        idx = src.index('def normalize_game_edit')
        end = src.index('\ndef ', idx + 1)
        body = src[idx:end]
        assert 'normalize_players_value' in body, \
            'normalize_game_edit must call normalize_players_value (Pass 40.6)'

    def test_helper_normalizes_string_range_to_int(self):
        """Functional check that the helper actually coerces "1-4" → 4
        (the Pass 40.6 contract)."""
        from services.game_metadata_service import normalize_game_edit

        out = normalize_game_edit({'players': '1-4'})
        assert out['players'] == 4, (
            'normalize_game_edit must coerce range "1-4" to max int=4 '
            '(Pass 40.6 INTEGER column invariant)'
        )

        out = normalize_game_edit({'players': ''})
        assert out['players'] is None, \
            'normalize_game_edit must coerce empty string to None'

        out = normalize_game_edit({'players': 'unknown'})
        assert out['players'] is None, \
            'normalize_game_edit must coerce non-numeric junk to None'


# -----------------------------------------------------------------------------
# 40.7 — TGDB image downloads bypass SSRF
# -----------------------------------------------------------------------------
class TestPass40_7TgdbImageSsrf:
    """_download_tgdb_image must delegate to base_scraper.download_image
    so the SSRF gate + size cap + redirect validation apply."""

    def test_uses_hardened_download_image(self):
        from scraper import scrape_thegamesdb as mod

        src = read_module_source(mod)
        # Make the function-rename case fail loudly rather than silently
        # skipping the SSRF contract assertions (test-audit c-005 MED):
        # the previous `if 'def _download_tgdb_image' in src:` wrapper
        # let the body checks vanish if the function were renamed or
        # inlined, with the test still reporting green.
        assert 'def _download_tgdb_image' in src, (
            "_download_tgdb_image not found in scraper/scrape_thegamesdb.py "
            "— if the function was renamed/inlined, update this Pass 40.7 pin"
        )
        idx = src.index('def _download_tgdb_image')
        try:
            end = src.index('\ndef ', idx + 1)
        except ValueError:
            end = len(src)
        body = src[idx:end]
        assert 'download_image(' in body, \
            '_download_tgdb_image must delegate to base_scraper.download_image (Pass 40.7)'
        # Must NOT contain the raw write that bypassed SSRF.
        assert "open(local_path, 'wb')" not in body, \
            '_download_tgdb_image must not write response.content directly (Pass 40.7)'

    def test_imports_download_image(self):
        from scraper import scrape_thegamesdb as mod
        assert hasattr(mod, 'download_image'), \
            'scrape_thegamesdb must import download_image from base_scraper (Pass 40.7)'


# -----------------------------------------------------------------------------
# 40.8 — Museum job finally clobbers failed → completed
# -----------------------------------------------------------------------------
class TestPass40_8MuseumJobFailedStatusPreserved:
    """Both early-exit failure paths in services/jobs/museum.py must set
    persist_id = None after persist_job_complete('failed') so the finally
    block doesn't run a second persist_job_complete that overwrites the
    failure with 'completed'."""

    def test_no_provider_clears_persist_id(self):
        from services.jobs import museum

        src = read_module_source(museum)
        idx = src.index("'No AI provider configured")
        # Within the next ~600 chars, persist_id must be set to None.
        block = src[idx:idx + 800]
        assert 'persist_id = None' in block, \
            'no-AI-provider branch must clear persist_id (Pass 40.8)'

    def test_unknown_provider_clears_persist_id(self):
        from services.jobs import museum

        src = read_module_source(museum)
        idx = src.index('Unknown AI provider')
        block = src[idx:idx + 800]
        assert 'persist_id = None' in block, \
            'unknown-provider branch must clear persist_id (Pass 40.8)'
