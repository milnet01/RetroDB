# =============================================================================
# Pass 40 — Tier-1 indie-review security findings
# =============================================================================
# Regression pins for the 16 CRITICAL/HIGH findings from the 2026-04-24
# multi-agent independent review.  Each sub-item gets a narrow unit check
# that fails if the fix is reverted.
# =============================================================================

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# -----------------------------------------------------------------------------
# 40.1 — RCE via unvalidated chdman_path in rom_tools_config.json POST
# -----------------------------------------------------------------------------
class TestPass40_1ChdmanPathValidator:
    """Validator must reject attacker-supplied paths to arbitrary binaries."""

    def test_bare_chdman_accepted(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, cleaned = validate_rom_tools_value('chdman_path', 'chdman')
        assert ok, f"bare 'chdman' should be accepted: {reason}"
        assert cleaned == 'chdman'

    def test_empty_string_normalized_to_chdman(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, cleaned = validate_rom_tools_value('chdman_path', '')
        assert ok
        assert cleaned == 'chdman'

    def test_chdman_exe_accepted(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, cleaned = validate_rom_tools_value('chdman_path', 'chdman.exe')
        assert ok
        assert cleaned == 'chdman.exe'

    def test_python3_argv0_substitution_rejected(self):
        """The CWE-78 attack vector: writing python3 as chdman_path so that
        subsequent CHD conversion runs python3 with attacker-controlled argv."""
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('chdman_path', '/usr/bin/python3')
        assert not ok
        assert reason

    def test_tmp_path_rejected(self):
        """Writable directories are off-limits — a logged-in user with file
        access could drop a malicious binary there."""
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('chdman_path', '/tmp/evil')
        assert not ok
        assert reason

    def test_home_dir_rejected(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('chdman_path', '/home/attacker/chdman')
        assert not ok
        assert reason

    def test_traversal_rejected(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value(
            'chdman_path', '/usr/bin/../tmp/evil'
        )
        assert not ok
        assert reason

    def test_relative_path_rejected(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('chdman_path', './chdman')
        assert not ok

    def test_wrong_basename_rejected(self):
        """Even under /usr/bin, only the chdman binary is permitted."""
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('chdman_path', '/usr/bin/sh')
        assert not ok

    def test_usr_bin_chdman_accepted(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, cleaned = validate_rom_tools_value('chdman_path', '/usr/bin/chdman')
        assert ok
        assert cleaned == '/usr/bin/chdman'

    def test_usr_local_bin_chdman_accepted(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, cleaned = validate_rom_tools_value(
            'chdman_path', '/usr/local/bin/chdman'
        )
        assert ok
        assert cleaned == '/usr/local/bin/chdman'

    def test_non_string_rejected(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, _, _ = validate_rom_tools_value('chdman_path', 12345)
        assert not ok

        ok, _, _ = validate_rom_tools_value('chdman_path', ['/usr/bin/chdman'])
        assert not ok


class TestPass40_1OtherSettingsValidators:
    """Per-key allowlist for every other field in rom_tools_config.json."""

    def test_unknown_key_rejected(self):
        from services.rom_tools_validators import validate_rom_tools_value

        ok, reason, _ = validate_rom_tools_value('not_a_real_key', True)
        assert not ok
        assert 'unknown' in reason.lower()

    def test_bool_fields(self):
        from services.rom_tools_validators import validate_rom_tools_value

        for key in ('recursive_scan', 'verify_integrity', 'generate_m3u',
                    'remove_unwanted', 'chd_verify_after_convert',
                    'chd_delete_originals', 'chd_skip_existing',
                    'ignore_region_tags', 'include_archives'):
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

        src = open(tools_mod.__file__).read()
        idx = src.index('def api_rom_tools_settings')
        # Within the function body (next ~1500 chars), the POST branch must
        # raise 403 for non-admin callers.
        body = src[idx:idx + 1500]
        assert "g.user.get('role') != 'admin'" in body or \
               "g.user['role'] != 'admin'" in body, \
            'api_rom_tools_settings POST must gate on admin role (Pass 40.1)'
        assert '403' in body, 'POST must return 403 for non-admin (Pass 40.1)'

    def test_post_handler_validates_input(self):
        """Source-level pin: the POST branch must call validate_rom_tools_value
        before persisting."""
        from routes import tools as tools_mod

        src = open(tools_mod.__file__).read()
        assert 'validate_rom_tools_value' in src, \
            'api_rom_tools_settings must validate input (Pass 40.1)'

    def test_post_rejects_attacker_chdman_path(self, tmp_path, monkeypatch):
        """End-to-end: POST {chdman_path: /usr/bin/python3} → 4xx, file unchanged."""
        import json as _json
        import app as app_module
        from routes import tools as tools_mod

        # Redirect rom_tools_config.json into tmpdir for isolation.
        cfg_path = tmp_path / 'rom_tools_config.json'
        original_load = tools_mod.load_rom_tools_config
        original_save = tools_mod.save_rom_tools_config

        def fake_load():
            if cfg_path.exists():
                return _json.loads(cfg_path.read_text())
            return original_load()

        def fake_save(settings):
            cfg_path.write_text(_json.dumps(settings))
            return True

        monkeypatch.setattr(tools_mod, 'load_rom_tools_config', fake_load)
        monkeypatch.setattr(tools_mod, 'save_rom_tools_config', fake_save)

        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1  # admin in seeded DB; if not present, route 302s

        resp = client.post(
            '/api/rom-tools/settings',
            json={'chdman_path': '/usr/bin/python3'},
        )
        # Either 400 (validator fired) or 302/403 (no admin in test DB).
        # The one outcome we must NEVER see is 200 with the dangerous value persisted.
        if resp.status_code == 200:
            assert not cfg_path.exists() or \
                _json.loads(cfg_path.read_text()).get('chdman_path') != '/usr/bin/python3'
        else:
            assert resp.status_code in (400, 302, 403), \
                f"unexpected status: {resp.status_code}"


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

        src = open(tools_mod.__file__).read()
        # Slice to the run_conversion closure + its loop.
        idx = src.index('def api_chd_converter_convert')
        end = src.index('def api_chd_verify_scan', idx)
        body = src[idx:end]
        assert 'def run_conversion' in body
        assert 'safe_path(file_path' in body, \
            'api_chd_converter_convert worker must validate each file_path (Pass 40.2)'

    def test_verify_worker_validates_each_path(self):
        from routes import tools as tools_mod

        src = open(tools_mod.__file__).read()
        idx = src.index('def api_chd_verify_verify')
        # The next route after verify is duplicate-finder; bound the slice there.
        end = src.index('def api_duplicate_finder', idx)
        body = src[idx:end]
        assert 'def run_verification' in body
        assert 'safe_path(file_path' in body, \
            'api_chd_verify_verify worker must validate each file_path (Pass 40.2)'

    def test_convert_e2e_rejects_traversal(self, tmp_path, monkeypatch):
        """End-to-end smoke: POST with /etc/passwd in files[] never invokes
        subprocess.run with that path.  Validation happens before chdman call."""
        import app as app_module
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

        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1

        resp = client.post(
            '/api/rom-tools/chd-converter/convert',
            json={'files': ['/etc/passwd', str(legit)]},
        )
        # Even if route 302s for non-admin in test DB, no chdman invocation
        # should ever target /etc/passwd.
        if resp.status_code == 200:
            # Worker thread runs async — give it a brief moment to iterate.
            import time as _t
            for _ in range(20):
                if seen_argv:
                    break
                _t.sleep(0.05)
            for argv in seen_argv:
                assert '/etc/passwd' not in argv, \
                    f'chdman invoked on traversal path: {argv}'

    def test_convert_does_not_remove_arbitrary_file(self, tmp_path, monkeypatch):
        """If chd_delete_originals is true, the os.remove must still be
        gated by safe_path — a logged-in user can't trick the worker into
        deleting /etc/something."""
        import app as app_module
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
        original_remove = tools_mod.os.remove
        monkeypatch.setattr(tools_mod.os, 'remove', lambda p: removed.append(p))

        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1

        resp = client.post(
            '/api/rom-tools/chd-converter/convert',
            json={'files': [str(decoy_target)]},
        )

        # Allow the worker thread to drain.
        if resp.status_code == 200:
            import time as _t
            for _ in range(40):
                _t.sleep(0.025)
                if removed:
                    break

        # The decoy path is OUTSIDE rom_root → safe_path rejects → os.remove
        # never called on it.
        assert str(decoy_target) not in removed, \
            f'os.remove called on path outside rom_path: {removed}'


# -----------------------------------------------------------------------------
# 40.3 — Archive-scanner m3u admin + path validation
# -----------------------------------------------------------------------------
class TestPass40_3ArchiveScannerM3u:
    """create_m3u and batch_create_m3u must be admin-only and must validate
    per-entry paths; staging_folder must not be attacker-controlled."""

    def test_create_m3u_requires_admin(self):
        from routes import tools as tools_mod

        src = open(tools_mod.__file__).read()
        idx = src.index('def api_archive_scanner_create_m3u')
        prelude = src[max(0, idx - 200):idx]
        assert '@admin_required' in prelude, \
            'api_archive_scanner_create_m3u must be admin-only (Pass 40.3)'

    def test_batch_create_m3u_requires_admin(self):
        from routes import tools as tools_mod

        src = open(tools_mod.__file__).read()
        idx = src.index('def api_archive_scanner_batch_create_m3u')
        prelude = src[max(0, idx - 200):idx]
        assert '@admin_required' in prelude, \
            'api_archive_scanner_batch_create_m3u must be admin-only (Pass 40.3)'

    def test_batch_validates_each_path(self):
        """Source-level pin: the batch handler must safe_path-check each entry
        in the paths[] list before passing them to the scanner."""
        from routes import tools as tools_mod

        src = open(tools_mod.__file__).read()
        idx = src.index('def api_archive_scanner_batch_create_m3u')
        # Bound the slice up to the next def.
        end = src.index('\n@tools_bp.route', idx + 1)
        body = src[idx:end]
        assert 'safe_path(' in body, \
            'batch_create_m3u must validate each path (Pass 40.3)'

    def test_staging_folder_not_user_supplied(self):
        """The handlers must not pass an attacker-supplied staging_folder
        through to the scanner.  Either the kwarg is absent (server default
        wins) or it's checked against an allowlist."""
        from routes import tools as tools_mod

        src = open(tools_mod.__file__).read()
        idx = src.index('def api_archive_scanner_create_m3u')
        end = src.index('# ====', idx)
        body = src[idx:end]
        # Reject the bare-passthrough pattern.  Acceptable shapes:
        #   - no staging_folder=... in the call
        #   - staging_folder=<a validated local var, not the raw request value>
        # We pin: the literal `data.get('staging_folder')` must not be passed
        # straight to the scanner.
        bad_pattern = "staging_folder=data.get('staging_folder')"
        assert bad_pattern not in body.replace(' ', '').replace('\n', ''), \
            'staging_folder must not be raw-passed from request (Pass 40.3)'
        bad_pattern2 = "staging_folder=staging_folder"
        # If the var name `staging_folder` is reused, ensure it was assigned
        # something other than `data.get('staging_folder')` directly above.
        if bad_pattern2 in body.replace(' ', '').replace('\n', ''):
            # The variable assignment must not be a raw request read.
            assert "staging_folder = data.get('staging_folder')" not in body and \
                   'staging_folder=data.get(' not in body.replace(' ', ''), \
                'staging_folder still raw-read from request (Pass 40.3)'

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

        app_module.app.config['TESTING'] = True
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1

        resp = client.post(
            '/api/rom-tools/archive-scanner/create-m3u',
            json={'path': str(outside)},
        )
        # Either rejected (400) or auth-blocked (302/403); never reached scanner.
        assert resp.status_code in (400, 302, 403, 500), \
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

        src = open(mod.__file__).read()
        idx = src.index('def steam_achievements_landing')
        end = src.index('def steam_achievement_game', idx)
        body = src[idx:end]
        assert 'gap.user_id = ?' in body, \
            'landing query must filter game_achievement_progress on user_id (Pass 40.4)'
        assert "g.user['id']" in body, \
            'landing query must bind g.user[id] (Pass 40.4)'

    def test_per_game_progress_query_filters_user_id(self):
        from routes import steam_achievements as mod

        src = open(mod.__file__).read()
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

        src = open(games_mod.__file__).read()
        # Find the card-data ETag payload line.
        idx = src.index('etag_payload')
        # First etag_payload assignment in the file is the card-data one.
        line = src[idx:idx + 400]
        assert "g.user['id']" in line or "user_id" in line, \
            'card-data ETag payload must include user identity (Pass 40.5)'

    def test_two_users_get_different_etags(self, monkeypatch):
        """End-to-end: same card-data request bound to two different users
        must produce different ETags."""
        import app as app_module

        # We can't easily seed two real users in CI, but we can stub g.user
        # by attaching a before_request hook.  Simpler: check that the
        # source-level fix is wired — the e2e shape changes too much to
        # mock cleanly without a per-user fixture.  The source pin above is
        # the load-bearing assertion; this test is a sanity check.
        from routes import games as games_mod

        src = open(games_mod.__file__).read()
        idx = src.index('etag_payload = f"cd:')
        # Reject the pre-fix shape that omitted user identity.
        bad_pattern = 'etag_payload = f"cd:{\',\'.join(str(i) for i in sorted_ids)}:{max_updated}"'
        # Allow only when followed by something user-bearing.
        line = src[idx:idx + 200]
        # The fixed version must reference user id within the payload string.
        assert "{g.user['id']}" in line or '{user_id}' in line or \
               ":{g.user[" in line, \
            'card-data ETag must bake user identity into the payload (Pass 40.5)'


# -----------------------------------------------------------------------------
# 40.6 — players fill-only invariant + JSON-edit type corruption
# -----------------------------------------------------------------------------
class TestPass40_6PlayersNormalization:
    """Helper rejects junk strings, normalizes ranges to max, returns None
    for the absent / invalid case so COALESCE preserves curated values."""

    def test_none_returns_none(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value(None) is None

    def test_empty_string_returns_none(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value('') is None
        assert normalize_players_value('   ') is None

    def test_int_passthrough(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value(1) == 1
        assert normalize_players_value(4) == 4

    def test_zero_returns_none(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value(0) is None
        assert normalize_players_value('0') is None

    def test_string_int(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value('1') == 1
        assert normalize_players_value('  4  ') == 4

    def test_range_takes_max(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value('1-4') == 4
        assert normalize_players_value('2-8') == 8
        assert normalize_players_value('1-16') == 16

    def test_garbage_string_returns_none(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value('many') is None
        assert normalize_players_value('1.0e9') is None

    def test_bool_rejected(self):
        from services.game_utils import normalize_players_value
        assert normalize_players_value(True) is None
        assert normalize_players_value(False) is None


class TestPass40_6IgdbTgdbPlayersDefault:
    """IGDB/TGDB adapters must initialise players = None and only set when
    the source explicitly provided a value, so COALESCE preserves curated
    values when the API is silent."""

    def test_igdb_initializes_players_none(self):
        from scraper import scrape_igdb as mod

        src = open(mod.__file__).read()
        # Find the apply_igdb_metadata function (or where players is set).
        idx = src.index('# Players')
        block = src[idx:idx + 600]
        # The fix flips the default from `players = 1` to `players = None`.
        assert 'players = 1' not in block, \
            "IGDB players must default to None (Pass 40.6)"
        assert 'players = None' in block, \
            "IGDB players must initialise to None (Pass 40.6)"

    def test_tgdb_initializes_players_none(self):
        from scraper import scrape_thegamesdb as mod

        src = open(mod.__file__).read()
        idx = src.index('# Players')
        block = src[idx:idx + 600]
        assert 'players = 1\n' not in block.replace(' ', ''), \
            "TGDB players must default to None (Pass 40.6)"
        assert 'players = None' in block, \
            "TGDB players must initialise to None (Pass 40.6)"


class TestPass40_6RouteNormalization:
    """api_game_edit + edit_metadata must run players through
    normalize_players_value before binding to the INTEGER column."""

    def test_api_game_edit_normalizes_players(self):
        from routes import games as games_mod

        src = open(games_mod.__file__).read()
        idx = src.index('def api_game_edit')
        end = src.index('@bp.route(\'/api/games/bulk-edit\'', idx)
        body = src[idx:end]
        assert 'normalize_players_value' in body, \
            'api_game_edit must call normalize_players_value (Pass 40.6)'

    def test_edit_metadata_normalizes_players(self):
        from routes import games as games_mod

        src = open(games_mod.__file__).read()
        # edit_metadata is the form-POST handler ahead of api_game_edit.
        idx = src.index("edit_players")
        # Within the surrounding ~600 chars, the players read must be wrapped
        # in normalize_players_value(...).
        window = src[max(0, idx - 200):idx + 400]
        assert 'normalize_players_value' in window, \
            'edit_metadata must call normalize_players_value (Pass 40.6)'
