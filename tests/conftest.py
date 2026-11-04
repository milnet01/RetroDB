"""Top-level pytest configuration."""

from __future__ import annotations

# Force Qt's offscreen QPA platform before anything imports QApplication.
# RetroDB is a Flask web app and doesn't pull in Qt today, but adding
# the safe default here makes it impossible for a future Qt-using
# test (or a transitive import that creates a QApplication at import
# time) to flash a real top-level window onto the desktop hosting the
# test runner. `setdefault` lets a CI override
# (e.g. QT_QPA_PLATFORM=minimal) still win.
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Isolate the test database from the operator's real library DB.
# `app.py` runs ensure_user_tables() + init_database() (schema migrations) and
# the emulator seeder against config.DB_PATH at IMPORT time — not under
# `if __name__ == '__main__'` — and many test modules `import app` (directly or
# via the app_client fixture). config.DB_PATH defaults to database/roms.db, so
# without this every `pytest` run (and the ci_local.sh pre-push gate) would run
# migrations + seeding against the real library. Point it at a fresh throwaway
# DB before config/app are first imported.
#
# A RETRODB_* path inherited from the shell is NEVER honoured (PASS-59-239): it
# could name the live library. Each process — every pytest-xdist worker
# included — mints its own temp dirs, so workers never share a DB and race
# init_database (UNIQUE constraint on the seeded admin).
import tempfile  # noqa: E402
_proc = os.environ.get("PYTEST_XDIST_WORKER") or "main"
_test_db_dir = tempfile.mkdtemp(prefix=f"retrodb-test-{_proc}-")
os.environ["RETRODB_DB_PATH"] = os.path.join(_test_db_dir, "roms.db")

# Isolate the scraped-media roots from the operator's real files, for the SAME
# reason (and the same way) as the DB above. The media-cleanup helpers
# (find_orphaned_media / clean_orphaned_files / delete_game_images) DELETE files
# under IMAGE_PATH / STATIC_PATH. Tests monkeypatch those config attrs to a
# tmp dir, but a monkeypatch can be silently defeated by module-eviction
# pollution (see test_pass46_frozen_paths) — and when it is, an orphan sweep
# scans the REAL image tree and deletes every file not matching its fake game
# list. That once wiped a live ~5500-game library. Pointing IMAGE_PATH /
# STATIC_PATH at throwaway dirs via env BEFORE config is imported makes the real
# media tree physically unreachable from the test process no matter what — the
# env override is read at config import time and survives a config re-import,
# which a per-attribute monkeypatch does not.
_test_media_dir = tempfile.mkdtemp(prefix=f"retrodb-test-media-{_proc}-")
_test_static = os.path.join(_test_media_dir, "static")
_test_images = os.path.join(_test_static, "images")
for _sub in ("boxart", "boxart_3d", "screenshots", "fanart", "game_logos", "boxart_back", "manuals"):
    os.makedirs(os.path.join(_test_images, _sub), exist_ok=True)
os.makedirs(os.path.join(_test_static, "videos"), exist_ok=True)
os.environ["RETRODB_STATIC_PATH"] = _test_static
os.environ["RETRODB_IMAGE_PATH"] = _test_images

# The settings files, too: a route test that saves settings must not write the
# operator's data/settings.json or data/scraper_settings.json.
_test_data = os.path.join(_test_media_dir, "data")
os.makedirs(_test_data, exist_ok=True)
os.environ["RETRODB_SETTINGS_FILE"] = os.path.join(_test_data, "settings.json")
os.environ["RETRODB_SCRAPER_SETTINGS_FILE"] = os.path.join(_test_data, "scraper_settings.json")

# Refuse to run at all if config resolves any of them outside the temp root —
# e.g. a config.py copied from an older config.example.py, which lacks the
# settings-file overrides.
import config as _config  # noqa: E402
_temp_root = os.path.realpath(tempfile.gettempdir())
for _name in ("DB_PATH", "IMAGE_PATH", "STATIC_PATH", "SETTINGS_FILE", "SCRAPER_SETTINGS_FILE"):
    _path = getattr(_config, _name, None)
    if not _path or os.path.commonpath([_temp_root, os.path.realpath(_path)]) != _temp_root:
        raise SystemExit(
            f"conftest: config.{_name} is {_path!r}, outside the temp root; refusing to run "
            "tests against live data. If config.py is older than config.example.py, "
            "copy the new path lines across.")

import pytest  # noqa: E402

# Re-export shared utilities so test files can `from tests._util import ...`
# without each one re-computing REPO_ROOT and inserting sys.path.
from tests._util import REPO_ROOT, read_source, read_module_source, slice_function, count_except_blocks  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def _migrated_test_db():
    """Give the throwaway test DB its full schema before any test runs.

    Without this, a test that reads a table (e.g. removed_screenshots) passed
    only when some earlier test had imported `app`, which migrates on import;
    run alone or in another order, it failed (PASS-59-229). Same order as app.py.
    """
    from services.database_init import ensure_user_tables, init_database
    ensure_user_tables()
    init_database()


@pytest.fixture(autouse=True)
def _no_service_limits_between_tests():
    """A stop or pace in one test must not reach the next, or slow the suite."""
    from scraper import service_limits
    service_limits.clear()
    service_limits._pace.clear()
    yield
    service_limits.clear()


@pytest.fixture
def app_client(monkeypatch):
    """Function-scoped Flask test client with TESTING=True restored on teardown.

    Replaces the verbatim per-module 'client' fixture inlined in
    test_routes_smoke.py and test_security_headers.py. Function-scoped (not
    module-scoped) so monkeypatch is available — the consolidated pattern
    matches every other client-needing test in the suite.
    """
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    yield app_module.app.test_client()


@pytest.fixture
def setup_complete(monkeypatch):
    """Neutralise the first-run setup gate for tests that assert on later layers.

    `app.check_first_time_setup` redirects EVERY request to /setup while no
    settings file marks setup done. It runs before any route decorator, so a
    test aiming at the auth layer never reaches it on a fresh tree.

    This is environment-sensitive in the worst way: `data/settings.json` is
    gitignored, so a developer checkout has one and a fresh clone does not.
    Without this stub such a test passes locally and fails in CI, which is
    exactly how the auth-guard assertions here reached main red.
    """
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': '/tmp'})


ADMIN_STUB_USER = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
ADMIN_STUB_CSRF = 'admin-stub-csrf-token'


@pytest.fixture
def admin_test_client(monkeypatch):
    """Factory for a Flask test client signed in as a stub admin.

    Call it as `client, csrf = admin_test_client()`. It stubs, in one place,
    what route-level tests otherwise inlined one by one:
      - `app.get_current_user` returns the stub user (no DB user lookup);
      - `app.get_user_settings` returns None;
      - `settings_manager.load_settings` reports setup as done, so the
        first-run gate does not 302 every request to /setup;
      - `app.config['TESTING']` is True;
      - the session carries `user_id` and a CSRF token, which is returned
        for the `X-CSRF-Token` header.

    Keyword arguments:
      settings — what load_settings returns (default {'setup_completed': True});
      user     — the stub user dict (default ADMIN_STUB_USER).

    Every patch goes through monkeypatch, so all are undone at teardown.
    """
    import app as app_module
    import settings_manager as _settings_manager

    def _make(*, settings=None, user=None):
        stub_user = dict(user if user is not None else ADMIN_STUB_USER)
        stub_settings = dict(settings if settings is not None
                             else {'setup_completed': True})
        monkeypatch.setattr(app_module, 'get_current_user', lambda: stub_user)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: dict(stub_settings))
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = stub_user['id']
            sess['_csrf_token'] = ADMIN_STUB_CSRF
        return client, ADMIN_STUB_CSRF

    return _make
