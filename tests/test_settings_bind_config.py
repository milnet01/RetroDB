"""The saved `server_port` setting must actually reach the bind.

Before this, `server_port`, `server_host` and `debug_mode` were validated,
stored and reported as restart-required, and then nothing ever read them —
`requires_restart()` promised a restart would apply a value that no restart
could apply.  These tests pin both halves of the fix:

  * `server_port` is now a real tier in the resolver app.py binds with, below
    the environment and above the 5000 default.
  * `server_host` / `debug_mode` are gone from the settings surface entirely,
    so nothing claims a restart will apply them.  They stay environment-only
    because `debug_mode` would let a settings request enable the Werkzeug
    interactive debugger (a Python console in the browser).

Every test that touches settings.json points SETTINGS_FILE at a tmp_path and
clears the module cache — the operator's real settings file is never read or
written here.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings_manager  # noqa: E402
from server_port import resolve_server_port, saved_server_port  # noqa: E402
from services.settings_validators import known_keys, validate_settings_value  # noqa: E402


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point settings_manager at a throwaway settings.json."""
    path = tmp_path / 'settings.json'

    def _write(payload):
        path.write_text(json.dumps(payload) if isinstance(payload, dict) else payload,
                        encoding='utf-8')
        settings_manager._invalidate_cache()
        return path

    monkeypatch.setattr(settings_manager, 'SETTINGS_FILE', str(path))
    settings_manager._invalidate_cache()
    yield _write
    settings_manager._invalidate_cache()


# ---------------------------------------------------------------------------
# The saved port reaches the bind
# ---------------------------------------------------------------------------

def test_saved_port_is_what_the_server_would_bind(settings_file):
    """The defect, stated directly: save a port, and that is what binds."""
    settings_file({'server_port': 5099})
    assert resolve_server_port(env={}, use_saved=True) == 5099


def test_saved_port_is_ignored_without_use_saved(settings_file):
    """config.py calls the resolver at import, where reading settings would be
    a circular import.  That call must stay on the env-only path."""
    settings_file({'server_port': 5099})
    assert resolve_server_port(env={}) == 5000


def test_environment_still_beats_the_saved_port(settings_file):
    """An external process manager must not be overridden by a stored value."""
    settings_file({'server_port': 5099})
    assert resolve_server_port(env={'PORT': '5998'}, use_saved=True) == 5998
    assert resolve_server_port(env={'RETRODB_PORT': '8080'}, use_saved=True) == 8080


def test_saved_port_may_be_privileged(settings_file):
    """1-65535 on this channel: a human choosing 80 for their own machine is
    their call.  Deliberately wider than PORT's 1024-65535."""
    settings_file({'server_port': 80})
    assert resolve_server_port(env={}, use_saved=True) == 80
    assert validate_settings_value('server_port', 80)[0] is True


# ---------------------------------------------------------------------------
# ...but never at the cost of booting
# ---------------------------------------------------------------------------

def test_corrupt_settings_file_does_not_stop_the_server(settings_file):
    # settings_manager.load_settings() already logs the parse failure and
    # falls back to DEFAULT_SETTINGS, so the tier yields the 5000 default
    # rather than None.  Either way the contract is the outcome: the server
    # boots on 5000 and nothing propagates out of the resolver.
    settings_file('{ this is not json')
    assert resolve_server_port(env={}, use_saved=True) == 5000


def test_invalid_saved_port_falls_back_instead_of_raising(settings_file):
    settings_file({'server_port': 99999})
    assert saved_server_port() is None
    assert resolve_server_port(env={}, use_saved=True) == 5000


def test_unreadable_settings_file_does_not_stop_the_server(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_manager, 'SETTINGS_FILE',
                        str(tmp_path / 'nope' / 'settings.json'))
    settings_manager._invalidate_cache()
    # No file at all -> defaults -> 5000, and nothing raised.
    assert resolve_server_port(env={}, use_saved=True) == 5000


def test_environment_port_survives_an_unloadable_settings_file(settings_file):
    """The port the environment gave us must never depend on settings.json."""
    settings_file('{ broken')
    assert resolve_server_port(env={'PORT': '5998'}, use_saved=True) == 5998


# ---------------------------------------------------------------------------
# The retired keys are gone from the surface
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('key', ['server_host', 'debug_mode'])
def test_retired_key_is_not_a_default(key):
    assert key not in settings_manager.DEFAULT_SETTINGS


@pytest.mark.parametrize('key', ['server_host', 'debug_mode'])
def test_retired_key_is_rejected_by_the_api(key):
    assert key not in known_keys()
    ok, reason, _ = validate_settings_value(key, '0.0.0.0')
    assert not ok
    assert reason == 'unknown setting key'


@pytest.mark.parametrize('key', ['server_host', 'debug_mode'])
def test_retired_key_no_longer_promises_a_restart(key):
    """The actual defect: a false promise in requires_restart()."""
    assert key not in settings_manager.RESTART_REQUIRED_SETTINGS
    assert settings_manager.requires_restart([key]) is False


def test_server_port_still_promises_a_restart_and_now_means_it():
    assert 'server_port' in settings_manager.RESTART_REQUIRED_SETTINGS
    assert settings_manager.requires_restart(['server_port']) is True


def test_every_restart_required_key_is_a_real_setting():
    """No key may claim a restart applies it unless it is on the surface."""
    for key in settings_manager.RESTART_REQUIRED_SETTINGS:
        assert key in settings_manager.DEFAULT_SETTINGS, key
        assert key in known_keys(), key


# ---------------------------------------------------------------------------
# An existing settings.json holding the retired keys degrades quietly
# ---------------------------------------------------------------------------

def test_stale_retired_keys_are_dropped_not_fatal(settings_file):
    """A settings.json written by an older version still loads; the dead keys
    are dropped rather than carried forward or failing the whole load."""
    settings_file({
        'server_host': '0.0.0.0',
        'server_port': 5099,
        'debug_mode': True,
        'items_per_page': 25,
    })
    loaded = settings_manager.load_settings()
    assert 'server_host' not in loaded
    assert 'debug_mode' not in loaded
    # The live keys around them survive untouched.
    assert loaded['server_port'] == 5099
    assert loaded['items_per_page'] == 25
