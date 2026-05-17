# Pass 44 — settings validators for the 5 new launch keys.

import pytest


def _ok(key, value):
    from services.settings_validators import validate_settings_value
    ok, _reason, _cleaned = validate_settings_value(key, value)
    return ok


class TestLaunchSettingsValidators:
    def test_launcher_backend_accepts_local(self):
        assert _ok('launcher_backend', 'local')

    def test_launcher_backend_accepts_remote(self):
        # Even though remote is NotImplementedError at runtime, the validator
        # accepts it — the route raises later.  Setting validators are about
        # data shape, not runtime feature gates.
        assert _ok('launcher_backend', 'remote')

    def test_launcher_backend_rejects_unknown(self):
        assert not _ok('launcher_backend', 'spaceship')

    @pytest.mark.parametrize('value,expected', [
        ('reject', True),
        ('kill_and_relaunch', True),
        ('queue', False),
    ])
    def test_launch_concurrent_same_game_enum(self, value, expected):
        assert _ok('launch_concurrent_same_game', value) is expected

    @pytest.mark.parametrize('permission', ['launch', 'view', 'edit'])
    def test_launch_required_permission_accepts_known(self, permission):
        assert _ok('launch_required_permission', permission)

    def test_launch_required_permission_rejects_unknown(self):
        assert not _ok('launch_required_permission', 'fly')

    def test_retroarch_binary_accepts_empty(self):
        assert _ok('retroarch_binary', '')

    def test_retroarch_binary_accepts_absolute_path(self):
        assert _ok('retroarch_binary', '/usr/bin/retroarch')

    def test_retroarch_binary_accepts_flatpak_run(self):
        assert _ok('retroarch_binary', 'flatpak run org.libretro.RetroArch')

    @pytest.mark.parametrize('payload', [
        '/usr/bin/retroarch; rm -rf /',
        '/usr/bin/retroarch && evil',
        'flatpak run x | sh',
    ])
    def test_retroarch_binary_rejects_command_injection(self, payload):
        assert not _ok('retroarch_binary', payload)

    def test_retroarch_cores_dir_accepts_empty(self):
        assert _ok('retroarch_cores_dir', '')

    def test_retroarch_cores_dir_accepts_path(self):
        assert _ok('retroarch_cores_dir', '/usr/lib64/libretro/')


class TestSettingsManagerHasNewKeys:
    def test_default_settings_has_all_five(self):
        import settings_manager
        for k in ('retroarch_binary', 'retroarch_cores_dir', 'launcher_backend',
                  'launch_required_permission', 'launch_concurrent_same_game'):
            assert k in settings_manager.DEFAULT_SETTINGS, k

    @pytest.mark.parametrize("k", [
        'retroarch_binary', 'retroarch_cores_dir', 'launcher_backend',
        'launch_required_permission', 'launch_concurrent_same_game',
    ])
    def test_default_value_is_valid(self, k):
        """Sanity: every default value passes its own validator (otherwise
        the import-time check in settings_validators.py would have raised).
        Parametrized so one broken default doesn't hide the others."""
        import settings_manager
        from services.settings_validators import validate_settings_value
        ok, reason, _ = validate_settings_value(k, settings_manager.DEFAULT_SETTINGS[k])
        assert ok, f"{k} default {settings_manager.DEFAULT_SETTINGS[k]!r}: {reason}"
