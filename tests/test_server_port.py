"""Unit tests for server_port.resolve_server_port — the PORT contract.

Three exhaustive, mutually exclusive cases (valid / absent / invalid) plus the
PORT-beats-RETRODB_PORT precedence.  The whole point of the module is that
"absent" and "invalid" are different: absence falls through to the next source,
a malformed value raises so the caller can exit non-zero.  A silent fallback to
5000 for a tool that asked for 80 is the defect these tests pin.

`env` is passed explicitly (never monkeypatched into os.environ) so a stray
PORT in the developer's own shell cannot change what these assert.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server_port import DEFAULT_PORT, resolve_server_port  # noqa: E402


# ---------------------------------------------------------------------------
# Case 2 — PORT present and valid
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('5999', 5999),
    ('1024', 1024),     # low boundary, inclusive
    ('65535', 65535),   # high boundary, inclusive
])
def test_valid_port_is_used(raw, expected):
    assert resolve_server_port(env={'PORT': raw}) == expected


# ---------------------------------------------------------------------------
# Case 3 — PORT absent (unset or empty).  Existing behaviour, unchanged.
# ---------------------------------------------------------------------------

def test_unset_falls_back_to_default():
    assert resolve_server_port(env={}) == DEFAULT_PORT == 5000


def test_empty_string_is_absence_not_a_bad_value():
    assert resolve_server_port(env={'PORT': ''}) == 5000


def test_empty_port_still_falls_through_to_retrodb_port():
    # Empty means absent, so the next source in the chain gets its turn.
    assert resolve_server_port(env={'PORT': '', 'RETRODB_PORT': '8080'}) == 8080


def test_caller_default_wins_over_the_baked_in_5000():
    # app.py passes config.SERVER_PORT so a hand-edited config.py still works.
    assert resolve_server_port(default=5001, env={}) == 5001


# ---------------------------------------------------------------------------
# Case 4 — PORT present but invalid.  Must raise, never silently fall back.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw', [
    'abc',
    '[abc]',
    '80.5',
    ' ',            # whitespace is a malformed value, not an absence
    '8080abc',
])
def test_non_numeric_port_raises(raw):
    with pytest.raises(ValueError) as excinfo:
        resolve_server_port(env={'PORT': raw})
    assert 'not a valid port number' in str(excinfo.value)


@pytest.mark.parametrize('raw', ['80', '0', '-1', '1023', '65536', '99999'])
def test_out_of_range_port_raises(raw):
    with pytest.raises(ValueError) as excinfo:
        resolve_server_port(env={'PORT': raw})
    assert 'out of range' in str(excinfo.value)


@pytest.mark.parametrize('raw', ['abc', '[abc]', '80'])
def test_error_message_names_the_variable_and_the_value_verbatim(raw):
    with pytest.raises(ValueError) as excinfo:
        resolve_server_port(env={'PORT': raw})
    msg = str(excinfo.value)
    assert 'PORT=' in msg
    assert raw in msg, f'message must quote the offending value: {msg}'


def test_invalid_port_does_not_fall_through_to_a_valid_retrodb_port():
    # The specific lie this contract exists to prevent: a caller that asked
    # for a bad port must be told, not quietly handed a different one.
    with pytest.raises(ValueError):
        resolve_server_port(env={'PORT': 'abc', 'RETRODB_PORT': '8080'})


# ---------------------------------------------------------------------------
# Case 5 — precedence: PORT -> RETRODB_PORT -> default
# ---------------------------------------------------------------------------

def test_port_beats_retrodb_port():
    assert resolve_server_port(env={'PORT': '5998', 'RETRODB_PORT': '8080'}) == 5998


def test_retrodb_port_used_when_port_absent():
    assert resolve_server_port(env={'RETRODB_PORT': '8080'}) == 8080


def test_retrodb_port_invalid_raises_naming_itself():
    with pytest.raises(ValueError) as excinfo:
        resolve_server_port(env={'RETRODB_PORT': 'abc'})
    assert 'RETRODB_PORT=' in str(excinfo.value)
    assert 'abc' in str(excinfo.value)


def test_retrodb_port_keeps_the_privileged_range_port_does_not():
    """Deliberate asymmetry — do NOT "unify" these two ranges.

    RETRODB_PORT is hand-typed by the operator, so it keeps the same 1-65535
    that services/settings_validators.py::_port_validator allows the settings
    UI.  PORT is machine-facing and gets 1024-65535 strictly.
    """
    assert resolve_server_port(env={'RETRODB_PORT': '80'}) == 80
    with pytest.raises(ValueError):
        resolve_server_port(env={'PORT': '80'})


# ---------------------------------------------------------------------------
# Trap A — `import config` must never raise on a bad value.  A subprocess, so
# the real import path is exercised without polluting this session's modules.
# ---------------------------------------------------------------------------

def _config_port(**env_overrides):
    """Return `config.SERVER_PORT` as seen by a fresh interpreter."""
    import os
    env = {k: v for k, v in os.environ.items() if k not in ('PORT', 'RETRODB_PORT')}
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, '-c', 'import config; print(config.SERVER_PORT)'],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f'importing config raised:\n{proc.stderr}'
    return int(proc.stdout.strip())


def test_config_import_survives_a_malformed_port():
    # app.py's __main__ is what reports the error; the import itself must not
    # traceback, because the launcher and the whole test suite do it too.
    assert _config_port(PORT='abc') == 5000


def test_config_import_honours_a_valid_port():
    assert _config_port(PORT='5999') == 5999


def test_config_import_honours_retrodb_port_unchanged():
    assert _config_port(RETRODB_PORT='8080') == 8080


# ---------------------------------------------------------------------------
# The CLI the start scripts use for their banner / browser-open URL.
# ---------------------------------------------------------------------------

def _cli(**env_overrides):
    import os
    env = {k: v for k, v in os.environ.items() if k not in ('PORT', 'RETRODB_PORT')}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, 'server_port.py'],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60,
    )


def test_cli_prints_the_resolved_port():
    proc = _cli(PORT='5999')
    assert proc.returncode == 0
    assert proc.stdout.strip() == '5999'


def test_cli_prints_the_default_when_absent():
    proc = _cli()
    assert proc.returncode == 0
    assert proc.stdout.strip() == '5000'


def test_cli_exits_non_zero_and_names_the_bad_value():
    proc = _cli(PORT='[abc]')
    assert proc.returncode != 0
    assert proc.stdout.strip() == '', 'a failed resolve must print no port'
    assert '[abc]' in proc.stderr
