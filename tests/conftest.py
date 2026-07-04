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
# DB before config/app are first imported. An explicit RETRODB_DB_PATH (CI, or a
# developer who wants a fixed path) still wins.
import tempfile  # noqa: E402
# Each pytest-xdist worker is a subprocess that inherits the master's env, so a
# path set once would be SHARED by every worker and they'd race init_database
# (UNIQUE constraint on the seeded admin). When running under xdist, key the DB
# on the worker id so each gets its own; otherwise honour a developer/CI-set
# RETRODB_DB_PATH and only mint one when none is set.
_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _xdist_worker or "RETRODB_DB_PATH" not in os.environ:
    _test_db_dir = tempfile.mkdtemp(prefix=f"retrodb-test-{_xdist_worker or 'main'}-")
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
# which a per-attribute monkeypatch does not. Keyed per xdist worker like the DB.
if _xdist_worker or "RETRODB_IMAGE_PATH" not in os.environ:
    _test_media_dir = tempfile.mkdtemp(prefix=f"retrodb-test-media-{_xdist_worker or 'main'}-")
    _test_static = os.path.join(_test_media_dir, "static")
    _test_images = os.path.join(_test_static, "images")
    for _sub in ("boxart", "boxart_3d", "screenshots", "fanart", "manuals"):
        os.makedirs(os.path.join(_test_images, _sub), exist_ok=True)
    os.makedirs(os.path.join(_test_static, "videos"), exist_ok=True)
    os.environ["RETRODB_STATIC_PATH"] = _test_static
    os.environ["RETRODB_IMAGE_PATH"] = _test_images

import pytest  # noqa: E402

# Re-export shared utilities so test files can `from tests._util import ...`
# without each one re-computing REPO_ROOT and inserting sys.path.
from tests._util import REPO_ROOT, read_source, read_module_source, slice_function, count_except_blocks  # noqa: E402,F401


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
