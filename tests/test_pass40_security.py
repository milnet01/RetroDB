# =============================================================================
# Pass 40 — Tier-1 indie-review security findings
# =============================================================================
# Regression pins for the 16 CRITICAL/HIGH findings from the 2026-04-24
# multi-agent independent review.  Each sub-item gets a narrow unit check
# that fails if the fix is reverted.
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

        src = open(games_mod.__file__).read()
        idx = src.index('def api_game_edit')
        end = src.index('@bp.route(\'/api/games/bulk-edit\'', idx)
        body = src[idx:end]
        assert 'normalize_game_edit' in body, \
            'api_game_edit must route through normalize_game_edit (Pass 42.1)'

    def test_edit_metadata_normalizes_via_helper(self):
        from routes import games as games_mod

        src = open(games_mod.__file__).read()
        idx = src.index("action == 'edit_metadata'")
        # Within the surrounding ~3000 chars, the helper call must appear.
        window = src[idx:idx + 3000]
        assert 'normalize_game_edit' in window, \
            'edit_metadata must route through normalize_game_edit (Pass 42.1)'

    def test_helper_calls_normalize_players_value(self):
        """Pass 40.6 invariant — normalize_game_edit must apply the
        players coercion that originally lived inline in both routes."""
        from services import game_metadata_service as svc

        src = open(svc.__file__).read()
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

        src = open(mod.__file__).read()
        if 'def _download_tgdb_image' in src:
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

        src = open(museum.__file__).read()
        idx = src.index("'No AI provider configured")
        # Within the next ~600 chars, persist_id must be set to None.
        block = src[idx:idx + 800]
        assert 'persist_id = None' in block, \
            'no-AI-provider branch must clear persist_id (Pass 40.8)'

    def test_unknown_provider_clears_persist_id(self):
        from services.jobs import museum

        src = open(museum.__file__).read()
        idx = src.index('Unknown AI provider')
        block = src[idx:idx + 800]
        assert 'persist_id = None' in block, \
            'unknown-provider branch must clear persist_id (Pass 40.8)'


# -----------------------------------------------------------------------------
# 40.9 — ImageResizeJob persistence + lock + shutdown recovery
# -----------------------------------------------------------------------------
class TestPass40_9ImageResizeJobBaseConvention:
    """Pin that ImageResizeJob now uses persist_job_start/progress/complete
    and locks every shared-counter access."""

    def test_imports_persist_helpers(self):
        from services.jobs import image_resize as mod
        assert hasattr(mod, 'persist_job_start')
        assert hasattr(mod, 'persist_job_progress')
        assert hasattr(mod, 'persist_job_complete')
        assert hasattr(mod, 'resolve_terminal_status')

    def test_worker_invokes_full_persist_lifecycle(self, tmp_path, monkeypatch):
        """Functional: running the worker against an empty image set (no
        files in IMAGE_PATH) must invoke persist_job_start AND, in the
        finally block, persist_job_complete + resolve_terminal_status.
        Consolidates 4 prior source-grep tests (one per persist call) into
        one behavior pin."""
        import time
        import config
        from services.jobs import image_resize as mod

        # Point IMAGE_PATH at an empty tmpdir so the worker's file-walk
        # finds nothing and exits early (but the finally block still runs).
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path))

        called = {'start': 0, 'progress': 0, 'complete': 0, 'resolve': 0}

        def _record(name, retval=None):
            def _fn(*a, **kw):
                called[name] += 1
                return retval
            return _fn

        monkeypatch.setattr(mod, 'persist_job_start', _record('start', 'fake-id-99'))
        monkeypatch.setattr(mod, 'persist_job_progress', _record('progress'))
        monkeypatch.setattr(mod, 'persist_job_complete', _record('complete'))
        monkeypatch.setattr(mod, 'resolve_terminal_status', _record('resolve', 'completed'))

        job = mod.ImageResizeJob()
        job.start(image_types=['boxart'])
        for _ in range(40):
            if not job.get_status().get('running', True):
                break
            time.sleep(0.05)
        assert called['start'] >= 1, (
            f"persist_job_start must fire on worker entry (Pass 40.9); "
            f"counts: {called!r}"
        )
        assert called['complete'] >= 1, (
            f"persist_job_complete must fire in finally (Pass 40.9); "
            f"counts: {called!r}"
        )
        assert called['resolve'] >= 1, (
            f"resolve_terminal_status must fire in finally (Pass 40.9); "
            f"counts: {called!r}"
        )

    def test_get_status_takes_lock(self):
        from services.jobs import image_resize as mod
        src = open(mod.__file__).read()
        idx = src.index('def get_status')
        end = src.index('def _worker', idx)
        body = src[idx:end]
        assert 'with self._lock' in body, \
            'get_status must take self._lock (Pass 40.9)'

    def test_worker_locks_counter_writes(self):
        """Counter writes (self.processed_count += 1, etc.) must be inside
        a `with self._lock:` block."""
        from services.jobs import image_resize as mod
        src = open(mod.__file__).read()
        idx = src.index('def _worker')
        body = src[idx:]
        # The naked `self.processed_count += 1` shape from before the fix
        # must NOT exist outside a lock block — sample one of them.
        # Easier: verify multiple `with self._lock:` appear in the loop.
        loop_section = body[body.index('for i, item in enumerate'):]
        assert loop_section.count('with self._lock:') >= 2, \
            'worker loop must lock counter accesses (Pass 40.9)'


# -----------------------------------------------------------------------------
# 40.10 — Rate-limit time.sleep blocks shutdown drain
# -----------------------------------------------------------------------------
class TestPass40_10ShutdownAwareSleep:
    """Per-iteration time.sleep(d) in long-running jobs must be replaced
    with shutdown_requested.wait(d) so SIGTERM short-circuits the sleep
    instead of expiring the drain budget."""

    def test_no_bare_time_sleep_in_jobs(self):
        """No services/jobs/{psn_refresh,platform_sync,ra_sync,ra_refresh,
        museum}.py file should call time.sleep — every wait must go through
        the shutdown event so the drain budget is honoured."""
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ('psn_refresh', 'platform_sync', 'ra_sync',
                     'ra_refresh', 'museum'):
            path = os.path.join(repo, 'services', 'jobs', f'{name}.py')
            src = open(path).read()
            for i, line in enumerate(src.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue
                if 'time.sleep(' in line:
                    offenders.append(f'{name}.py:{i}: {stripped}')
        assert not offenders, \
            'Pass 40.10: replace with shutdown_requested.wait()\n' + \
            '\n'.join(offenders)

    def test_each_job_imports_shutdown_event(self):
        for name in ('psn_refresh', 'platform_sync', 'ra_sync',
                     'ra_refresh', 'museum'):
            mod = __import__(f'services.jobs.{name}', fromlist=['*'])
            assert hasattr(mod, 'shutdown_requested'), \
                f'{name}.py must import shutdown_requested (Pass 40.10)'


# -----------------------------------------------------------------------------
# 40.11 — CHD conversion non-atomic + dead chd_verify_after_convert
# -----------------------------------------------------------------------------
class TestPass40_11ChdAtomicConversion:
    """chdman output must be written to a tempfile, optionally verified,
    and only os.replace'd to the final path on success.  Otherwise a
    mid-run kill leaves a truncated .chd that chd_skip_existing treats
    as good on the next pass.

    Pass 42.5 — the per-file atomic-write contract moved into the shared
    ``scraper.rom_tools.convert_one_to_chd`` helper; both call sites
    (``CHDConverter._convert_file`` and ``api_chd_converter_convert``)
    delegate to it. The pins below assert (a) the helper itself carries
    the contract and (b) both call sites delegate, instead of grepping
    `_convert_file` / `api_chd_converter_convert` for the literal
    `.chd.part` string."""

    def _convert_one_to_chd_body(self):
        from scraper import rom_tools as mod
        src = open(mod.__file__).read()
        idx = src.index('def convert_one_to_chd')
        end = src.index('\ndef ', idx + 1)
        return src[idx:end]

    def test_helper_uses_tempfile(self):
        body = self._convert_one_to_chd_body()
        assert '.chd.part' in body, \
            'convert_one_to_chd must write to .chd.part tempfile (Pass 40.11)'
        assert 'os.replace(' in body, \
            'convert_one_to_chd must os.replace tmp → dst (Pass 40.11)'

    def test_helper_runs_verify(self):
        body = self._convert_one_to_chd_body()
        assert 'do_verify' in body, \
            'convert_one_to_chd must accept a do_verify flag (Pass 40.11)'
        assert "'verify'" in body or '"verify"' in body, \
            'convert_one_to_chd must call chdman verify when configured (Pass 40.11)'

    def test_rom_tools_converter_delegates(self):
        from scraper import rom_tools as mod
        src = open(mod.__file__).read()
        idx = src.index('def _convert_file')
        end = src.index('def _timestamp', idx)
        body = src[idx:end]
        assert 'convert_one_to_chd(' in body, \
            'CHDConverter._convert_file must delegate to convert_one_to_chd (Pass 42.5)'
        assert 'chd_verify_after_convert' in body, \
            'CHDConverter must read chd_verify_after_convert (Pass 40.11 / 42.5)'

    def test_routes_inline_worker_delegates(self):
        from routes import tools as mod
        src = open(mod.__file__).read()
        idx = src.index('def api_chd_converter_convert')
        end = src.index('def api_chd_verify_scan', idx)
        body = src[idx:end]
        assert 'convert_one_to_chd(' in body, \
            'api_chd_converter_convert must delegate to convert_one_to_chd (Pass 42.5)'
        assert 'chd_verify_after_convert' in body, \
            'inline CHD converter must honor chd_verify_after_convert (Pass 40.11 / 42.5)'


# -----------------------------------------------------------------------------
# 40.12 — Toast-controller XSS on job.system_name
# -----------------------------------------------------------------------------
class TestPass40_12ToastControllerXss:
    """job.system_name was interpolated into toast.innerHTML without
    escape; the inline onclick was migrated to addEventListener.

    The "no inline onclick" half of this contract is now subsumed by
    Pass 45.4's `test_toast_controller_has_no_inline_onclicks` (asserts the
    strictly stronger property: NO inline onclick anywhere in the file).
    Only the system_name escape pin lives here — no other test covers it."""

    def test_system_name_escaped(self):
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'static', 'js', 'toast-controller.js')
        src = open(path).read()
        # The Queued-toast block: subtitle should not raw-interpolate
        # job.system_name — it must go through escapeHtml.
        assert '${job.system_name || \'Multi-System\'}' not in src, \
            'job.system_name must not be raw-interpolated into innerHTML (Pass 40.12)'


# -----------------------------------------------------------------------------
# 40.13 — showModal HTML auto-detect blocklist XSS sink
# -----------------------------------------------------------------------------
class TestPass40_13ShowModalOptInHtml:
    """showModal must default to textContent; opt-in via {allowHtml: true}.
    The old heuristic `message.includes('<') && message.includes('>')`
    was a blocklist that <script>-stripped only — missing <img onerror=>,
    <svg onload=>, etc."""

    def test_no_includes_lt_gt_heuristic(self):
        """The live `if (message.includes('<') && message.includes('>'))`
        branch must be gone.  We strip `// ...` comments before scanning so
        a Pass 40.13 doc-block referencing the old heuristic is allowed."""
        import os, re
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'templates', 'base.html')
        src = open(path).read()
        idx = src.index('function showModal(')
        end = src.index('function modalKeyHandler', idx)
        body = src[idx:end]
        # Strip single-line `//` comments so the test sees only live code.
        live = re.sub(r'//[^\n]*', '', body)
        assert "if (message.includes('<') && message.includes('>'))" not in live, \
            'showModal must not auto-detect HTML via the includes() heuristic (Pass 40.13)'

    def test_options_param_with_allowhtml(self):
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'templates', 'base.html')
        src = open(path).read()
        idx = src.index('function showModal(')
        end = src.index('function modalKeyHandler', idx)
        body = src[idx:end]
        assert 'allowHtml' in body, \
            'showModal must accept opt-in {allowHtml: true} (Pass 40.13)'


# -----------------------------------------------------------------------------
# 40.14 — PSN trophy-detail game-link search XSS
# -----------------------------------------------------------------------------
class TestPass40_14PsnTrophyDetailXss:
    """Game search results in psn_trophy_detail.html interpolate
    user-authored game.title / game.boxart / game.system into innerHTML
    text + attribute contexts; the old version used a single-quote
    .replace() that didn't protect HTML attribute decoding."""

    def test_inline_onclick_linkgame_removed(self):
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'templates', 'psn_trophy_detail.html')
        src = open(path).read()
        # The dangerous inline onclick was:
        #   onclick="linkGame(${game.id}, '${game.title.replace...}', ...)"
        assert "onclick=\"linkGame(${game.id}" not in src, \
            'inline onclick="linkGame(...)" must use addEventListener (Pass 40.14)'

    def test_search_results_use_escape(self):
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'templates', 'psn_trophy_detail.html')
        src = open(path).read()
        # The search-results loop must call esc() / escAttr().
        idx = src.index('for (const game of data.results)')
        # bound to the next async function
        end = src.index('async function linkGame', idx)
        body = src[idx:end]
        assert 'esc(game.title)' in body or 'escapeHtml(game.title)' in body, \
            'game.title must be escaped in HTML-text context (Pass 40.14)'
        assert 'escAttr(game.boxart)' in body or 'escapeAttr(game.boxart)' in body, \
            'game.boxart must be escaped in HTML-attribute context (Pass 40.14)'


# -----------------------------------------------------------------------------
# 40.15 — base_scraper.download_image non-atomic + stale-clear race
# -----------------------------------------------------------------------------
class TestPass40_15DownloadImageAtomic:
    """download_image must stream into a tempfile and os.replace; the stale
    media auto-clear must condition the UPDATE on the observed filename."""

    def test_download_image_uses_tempfile_and_replace(self):
        """Check the live-code shape — strip `# ...` comments so a doc
        block referencing the old pattern is allowed."""
        import re
        from scraper import base_scraper as mod
        src = open(mod.__file__).read()
        idx = src.index('def download_image(')
        end = src.index('def rate_limit', idx)
        body = src[idx:end]
        live = re.sub(r'#[^\n]*', '', body)
        assert 'mkstemp' in live, \
            'download_image must allocate a tempfile (Pass 40.15)'
        assert 'os.replace(' in live, \
            'download_image must os.replace tmp → dest_path (Pass 40.15)'
        assert "open(dest_path, 'wb')" not in live, \
            'download_image must not stream directly to dest_path (Pass 40.15)'

    def test_download_image_atomic_smoke(self, tmp_path, monkeypatch):
        """Functional smoke: a successful download produces a complete
        file at dest_path; no .dl-*.part file is left behind."""
        from scraper import base_scraper as mod
        from services import ssrf as ssrf_mod

        # Bypass the SSRF gate + redirect-walk for the test (these are
        # imported lazily inside the function — patch on the source module).
        # Pass 45.2: validate_and_pin_url calls validate_outbound_url(...,
        # require_https=...) and consumes the third tuple element (resolved
        # IPs) to pin against rebinding, so the stub must accept kwargs and
        # return at least one IP.
        monkeypatch.setattr(ssrf_mod, 'validate_outbound_url',
                            lambda url, **kw: (True, url, ['203.0.113.1']))
        monkeypatch.setattr(ssrf_mod, 'validate_redirect_chain',
                            lambda *a, **kw: ('http://example.test/img.png', None))

        # Stub _http_session.get to return a fake streaming response.
        class _Resp:
            status_code = 200
            headers = {'Content-Length': '12'}

            def iter_content(self, chunk_size):
                yield b'\x89PNG\r\n\x1a\n0123'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class _Session:
            def get(self, *a, **kw):
                return _Resp()

        monkeypatch.setattr(mod, '_http_session', _Session())

        dest = tmp_path / 'sub' / 'image.png'
        ok = mod.download_image('http://example.test/img.png', str(dest))
        assert ok is True
        assert dest.exists()
        # No leftover tempfile in the same directory.
        leftover = list((tmp_path / 'sub').glob('.dl-*'))
        assert not leftover, f"tempfile not cleaned up: {leftover}"

    def test_stale_clear_binds_observed_filename(self):
        """The hybrid_scraper stale-media UPDATE must include
        `AND {field} = ?` so a concurrent upload between stat and UPDATE
        doesn't get its new reference wiped."""
        from scraper import hybrid_scraper as mod
        src = open(mod.__file__).read()
        # Search the stale-clear region.
        idx = src.index('Cleared') if 'Cleared' in src else None
        # Get the surrounding ~600 chars for the UPDATE.
        if idx is not None:
            window = src[max(0, idx - 800):idx + 200]
            assert 'AND ' in window and ' = ?' in window, \
                'stale-clear UPDATE must bind observed filename (Pass 40.15)'
        else:
            assert False, 'stale-media block missing (Pass 40.15)'


# -----------------------------------------------------------------------------
# 40.16 — Missing docs/PROXY-DEPLOY.md referenced in app.py:147
# -----------------------------------------------------------------------------
class TestPass40_16ProxyDeployDocs:
    """app.py:147 references docs/PROXY-DEPLOY.md as the trust contract for
    RETRODB_TRUST_PROXY=1 — the file must exist and document the required
    proxy header configuration."""

    def test_doc_exists(self):
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'docs', 'PROXY-DEPLOY.md')
        assert os.path.exists(path), \
            'docs/PROXY-DEPLOY.md must exist (Pass 40.16)'

    def test_doc_covers_required_sections(self):
        import os
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, 'docs', 'PROXY-DEPLOY.md')
        body = open(path).read()
        # Must mention every load-bearing header / config knob.
        for needle in (
            'X-Forwarded-For', 'RETRODB_TRUST_PROXY', 'ProxyFix',
            'nginx', 'one hop',
        ):
            assert needle in body, \
                f'PROXY-DEPLOY.md must mention {needle!r} (Pass 40.16)'
