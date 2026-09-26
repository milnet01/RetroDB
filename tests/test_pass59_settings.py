"""Pass 59.42 and 59.46: settings writes must not destroy settings.

59.42 — `load_settings()` returned DEFAULT_SETTINGS when an existing
settings.json could not be read, and every persist path is load-modify-save,
so the next save wrote defaults over the user's file.

59.46 — the Settings UI ships an Engine naming row and `get_system_type()`
returns 'engine', but the validator rejected the key, and the 400 discarded
the sibling settings posted with it.

Every test points SETTINGS_FILE at a tmp_path; the real file is never touched.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings_manager  # noqa: E402
from services.settings_validators import validate_settings_value  # noqa: E402


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = tmp_path / 'settings.json'
    monkeypatch.setattr(settings_manager, 'SETTINGS_FILE', str(path))
    settings_manager._invalidate_cache()
    yield path
    settings_manager._invalidate_cache()


# ---------------------------------------------------------------------------
# 59.42 — an unreadable file is never overwritten with defaults
# ---------------------------------------------------------------------------

def test_save_after_a_corrupt_read_keeps_the_original(settings_path):
    original = '{"rom_path": "/my/roms", "default_region": "Europe"'  # truncated JSON
    settings_path.write_text(original, encoding='utf-8')

    settings = settings_manager.load_settings()
    assert settings['rom_path'] != '/my/roms'  # defaults came back
    settings['items_per_page'] = 48
    settings_manager.save_settings(settings)

    kept = list(settings_path.parent.glob('settings.json.corrupt-*'))
    assert len(kept) == 1, "the unreadable file was overwritten, not kept"
    assert kept[0].read_text(encoding='utf-8') == original


def test_save_after_a_transient_read_failure_is_refused(settings_path, monkeypatch):
    good = {'rom_path': '/my/roms', 'default_region': 'Europe'}
    settings_path.write_text(json.dumps(good), encoding='utf-8')

    real_load = json.load
    monkeypatch.setattr(settings_manager.json, 'load',
                        lambda *a, **k: (_ for _ in ()).throw(OSError('EMFILE')))
    settings = settings_manager.load_settings()
    monkeypatch.setattr(settings_manager.json, 'load', real_load)

    assert settings_manager.save_settings(settings) is False
    assert json.loads(settings_path.read_text(encoding='utf-8')) == good
    # The next load reads the real file again.
    assert settings_manager.load_settings()['rom_path'] == '/my/roms'


def test_a_missing_file_still_saves_normally(settings_path):
    settings = settings_manager.load_settings()
    settings['items_per_page'] = 48
    assert settings_manager.save_settings(settings) is True
    assert json.loads(settings_path.read_text(encoding='utf-8'))['items_per_page'] == 48


# ---------------------------------------------------------------------------
# 59.46 — the Engine naming row is a real system type
# ---------------------------------------------------------------------------

def test_engine_naming_row_is_accepted():
    ok, err, cleaned = validate_settings_value(
        'naming_convention', {'console': ['region'], 'engine': ['year']})
    assert ok, err
    assert cleaned['engine'] == ['year']


def test_engine_has_a_default_naming_row():
    assert 'engine' in settings_manager.DEFAULT_SETTINGS['naming_convention']


def test_every_system_type_has_a_naming_row():
    """The allowlist, the defaults and get_system_type() must agree."""
    from services import game_utils
    from services.settings_validators import _ALLOWED_NAMING_SYSTEM_TYPES
    returned = {game_utils.get_system_type(f) for f in
                ('snes', next(iter(game_utils.COMPUTER_SYSTEMS)),
                 next(iter(game_utils.HANDHELD_SYSTEMS)),
                 next(iter(game_utils.ENGINE_SYSTEMS)))}
    assert returned == _ALLOWED_NAMING_SYSTEM_TYPES
    assert set(settings_manager.DEFAULT_SETTINGS['naming_convention']) == returned
