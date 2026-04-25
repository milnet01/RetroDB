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
