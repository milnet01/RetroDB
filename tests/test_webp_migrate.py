# Tests for the FU.3 bulk JPEG/PNG → WebP migration job. Pins the in-place
# conversion contract: only legacy formats are touched, the DB filename is
# updated atomically with the on-disk swap, originals are removed only after
# the new file verifies, and the disk-space precheck refuses to proceed when
# free space is tight. Tests use sqlite3 directly to avoid pulling in the
# full Flask app context.

import io
import os
import sqlite3
import threading

import pytest
from PIL import Image

import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_games_table(db_path):
    """Create a games table that matches the columns the migrator touches."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            boxart TEXT,
            boxart_3d TEXT,
            fanart TEXT,
            screenshots TEXT,
            manual TEXT
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def webp_env(tmp_path, monkeypatch):
    """Stand up an isolated DB + image tree under tmp_path and point config at it.

    `test_pass46_frozen_paths` evicts `config` from `sys.modules` mid-suite,
    so by the time this fixture runs there are two distinct `config` module
    objects in play: the one this test file imported at load time (still
    referenced by every `import config` that happened before eviction —
    e.g. `services.jobs.base.config`) and a fresh copy in `sys.modules`
    (returned by any `import config` after eviction — e.g. inside
    `_build_work_list`). Patch both so DB_PATH / IMAGE_PATH stay coherent
    no matter which side of the eviction the consumer was loaded on.
    """
    import sys as _sys
    import services.jobs.base as _jobs_base
    import services.image_utils as _image_utils

    db_path = tmp_path / 'retrodb.db'
    image_path = str(tmp_path / 'images')

    targets = {id(config): config}
    for mod in (_sys.modules.get('config'), _jobs_base.config, _image_utils.__dict__.get('config')):
        if mod is not None:
            targets[id(mod)] = mod
    for mod in targets.values():
        monkeypatch.setattr(mod, 'DB_PATH', str(db_path), raising=False)
        monkeypatch.setattr(mod, 'IMAGE_PATH', image_path, raising=False)

    for sub in ('boxart', 'boxart_3d', 'fanart', 'screenshots'):
        (tmp_path / 'images' / sub).mkdir(parents=True)

    _seed_games_table(db_path)

    def write_image(subdir, name, *, fmt='JPEG', size=(800, 1120)):
        path = tmp_path / 'images' / subdir / name
        Image.new('RGB', size, color=(120, 80, 200)).save(path, format=fmt)
        return path

    def insert_game(**columns):
        cols = ['title'] + list(columns.keys())
        vals = ['Test Game'] + list(columns.values())
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            f"INSERT INTO games ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
            vals,
        )
        conn.commit()
        game_id = cur.lastrowid
        conn.close()
        return game_id

    def read_game(game_id):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        conn.close()
        return dict(row)

    return {
        'tmp': tmp_path,
        'db_path': db_path,
        'write_image': write_image,
        'insert_game': insert_game,
        'read_game': read_game,
    }


# ---------------------------------------------------------------------------
# _build_work_list — filter behavior
# ---------------------------------------------------------------------------


class TestBuildWorkList:
    """Worklist construction pins what we touch and what we leave alone."""

    def test_collects_jpeg_and_png_drops_webp_and_missing(self, webp_env):
        from services.jobs.webp_migrate import _build_work_list

        webp_env['write_image']('boxart', 'a.jpg', fmt='JPEG')
        webp_env['write_image']('boxart', 'b.webp', fmt='WEBP')  # already WebP — skip
        webp_env['write_image']('boxart_3d', 'c.png', fmt='PNG')

        # Stale DB pointer (no file on disk) — must NOT enter the worklist.
        webp_env['insert_game'](boxart='gone.jpg')
        webp_env['insert_game'](boxart='a.jpg')
        webp_env['insert_game'](boxart='b.webp', boxart_3d='c.png')

        items, in_scope_bytes = _build_work_list()

        filenames = sorted(it['filename'] for it in items)
        assert filenames == ['a.jpg', 'c.png']
        assert in_scope_bytes > 0

    def test_screenshots_csv_split_per_entry(self, webp_env):
        from services.jobs.webp_migrate import _build_work_list

        webp_env['write_image']('screenshots', 's1.jpg', fmt='JPEG')
        webp_env['write_image']('screenshots', 's2.png', fmt='PNG')
        webp_env['write_image']('screenshots', 's3.webp', fmt='WEBP')
        webp_env['insert_game'](screenshots='s1.jpg,s2.png,s3.webp')

        items, _ = _build_work_list()
        per_entry = sorted(it['filename'] for it in items if it['column'] == 'screenshots')
        assert per_entry == ['s1.jpg', 's2.png'], \
            "comma-split should emit one item per legacy-format entry; .webp skipped"


# ---------------------------------------------------------------------------
# _migrate_one — atomicity contract
# ---------------------------------------------------------------------------


class TestMigrateOne:
    """Per-file migration: DB swap + disk swap must be in lock-step."""

    def test_converts_jpeg_updates_db_deletes_original(self, webp_env):
        from services.jobs.webp_migrate import _build_work_list, _migrate_one

        webp_env['write_image']('boxart', 'g.jpg', fmt='JPEG')
        game_id = webp_env['insert_game'](boxart='g.jpg')

        items, _ = _build_work_list()
        assert len(items) == 1
        status, saved = _migrate_one(items[0])
        assert status == 'converted'
        assert saved >= 0

        # On disk: .webp exists, .jpg is gone.
        assert (webp_env['tmp'] / 'images' / 'boxart' / 'g.webp').exists()
        assert not (webp_env['tmp'] / 'images' / 'boxart' / 'g.jpg').exists()
        # DB: boxart points at the new filename.
        assert webp_env['read_game'](game_id)['boxart'] == 'g.webp'

    def test_screenshots_csv_swap_targets_one_entry(self, webp_env):
        """CSV migration must touch only the matched entry; siblings stay
        byte-for-byte. A naive `REPLACE(screenshots, 'a.jpg', 'a.webp')` would
        also clobber the substring `a.jpg` inside e.g. `extra.jpg` — pin
        against that by including a near-collision."""
        from services.jobs.webp_migrate import _build_work_list, _migrate_one

        webp_env['write_image']('screenshots', 'a.jpg', fmt='JPEG')
        webp_env['write_image']('screenshots', 'extra.jpg', fmt='JPEG')
        webp_env['write_image']('screenshots', 'b.webp', fmt='WEBP')
        game_id = webp_env['insert_game'](screenshots='a.jpg,b.webp,extra.jpg')

        items, _ = _build_work_list()
        # Migrate only the 'a.jpg' entry.
        for it in items:
            if it['filename'] == 'a.jpg':
                status, _ = _migrate_one(it)
                assert status == 'converted'

        row = webp_env['read_game'](game_id)
        # Order preserved, only `a.jpg` rewritten, `extra.jpg` left alone.
        assert row['screenshots'] == 'a.webp,b.webp,extra.jpg'

    def test_existing_webp_target_is_treated_as_resume(self, webp_env):
        """If `<stem>.webp` already exists (e.g. partial prior pass), the
        migrator should adopt it: point the DB at the existing .webp and
        remove the stale `.jpg`. Don't re-encode."""
        from services.jobs.webp_migrate import _build_work_list, _migrate_one

        webp_env['write_image']('boxart', 'h.jpg', fmt='JPEG')
        # Pre-create the .webp target. Distinct content lets us check that
        # the migrator *did not* overwrite it.
        webp_path = webp_env['tmp'] / 'images' / 'boxart' / 'h.webp'
        Image.new('RGB', (100, 140), color=(0, 200, 0)).save(webp_path, format='WEBP')
        pre_existing_bytes = webp_path.read_bytes()

        game_id = webp_env['insert_game'](boxart='h.jpg')
        items, _ = _build_work_list()
        status, _ = _migrate_one(items[0])

        assert status == 'converted'
        assert not (webp_env['tmp'] / 'images' / 'boxart' / 'h.jpg').exists()
        assert webp_path.read_bytes() == pre_existing_bytes, \
            'resume path must not re-encode an already-present .webp'
        assert webp_env['read_game'](game_id)['boxart'] == 'h.webp'

    def test_verification_failure_keeps_original_and_db(self, webp_env, monkeypatch):
        """If the new .webp does not pass PIL verify(), the original and DB
        column must stay untouched — we'd rather leak a partial output (which
        media-cleanup will GC) than leave a dangling DB pointer."""
        from services import image_utils
        from services.jobs import webp_migrate as mod

        webp_env['write_image']('boxart', 'k.jpg', fmt='JPEG')
        game_id = webp_env['insert_game'](boxart='k.jpg')

        # Force the verification path to fail by writing garbage in place of
        # the standardize-saved bytes. _migrate_one re-imports _save_image
        # from services.image_utils, so monkey-patch at the source.
        def _broken_save(img, path):
            with open(path, 'wb') as f:
                f.write(b'not a webp')

        monkeypatch.setattr(image_utils, '_save_image', _broken_save)

        items, _ = mod._build_work_list()
        status, _ = mod._migrate_one(items[0])
        assert status == 'failed'

        assert (webp_env['tmp'] / 'images' / 'boxart' / 'k.jpg').exists(), \
            'original must survive a failed conversion'
        assert webp_env['read_game'](game_id)['boxart'] == 'k.jpg', \
            'DB must not be updated when verification fails'

    def test_boxart_variants_regenerated_after_conversion(self, webp_env):
        """Boxart-family conversions must clean up old `-sm` / `-md` siblings
        and rebuild them against the new .webp so card srcset stays current."""
        from services.jobs.webp_migrate import _build_work_list, _migrate_one

        webp_env['write_image']('boxart', 'v.jpg', fmt='JPEG', size=(800, 1120))
        # Pre-existing legacy variants. The migrator should kill these.
        webp_env['write_image']('boxart', 'v-sm.jpg', fmt='JPEG', size=(160, 224))
        webp_env['write_image']('boxart', 'v-md.jpg', fmt='JPEG', size=(320, 448))
        webp_env['insert_game'](boxart='v.jpg')

        items, _ = _build_work_list()
        # `_build_work_list` walks DB rows only, so the variants are not in
        # `items` (no DB pointer references them) — but the migrator's
        # post-step should still clean them up.
        status, _ = _migrate_one(items[0])
        assert status == 'converted'

        boxart_dir = webp_env['tmp'] / 'images' / 'boxart'
        assert not (boxart_dir / 'v-sm.jpg').exists()
        assert not (boxart_dir / 'v-md.jpg').exists()
        # New variants regenerated against the .webp primary.
        assert (boxart_dir / 'v-sm.webp').exists()
        assert (boxart_dir / 'v-md.webp').exists()


# ---------------------------------------------------------------------------
# Job lifecycle — disk-space guard, status payload
# ---------------------------------------------------------------------------


class TestWebPMigrateJobLifecycle:
    """End-to-end worker pass + status snapshot + disk-space guard."""

    def test_disk_space_guard_refuses_when_too_little_free(self, webp_env, monkeypatch):
        """If `shutil.disk_usage(...).free < 2 * in_scope_bytes`, the job
        must surface an error and skip the conversion loop entirely."""
        from services.jobs import webp_migrate as mod
        from collections import namedtuple

        webp_env['write_image']('boxart', 'g.jpg', fmt='JPEG')
        webp_env['insert_game'](boxart='g.jpg')

        FakeUsage = namedtuple('DiskUsage', ['total', 'used', 'free'])
        monkeypatch.setattr(
            mod.shutil, 'disk_usage', lambda _: FakeUsage(0, 0, 1)
        )

        # Stub the persist helpers so we don't touch the persistence DB.
        monkeypatch.setattr(mod, 'persist_job_start', lambda *a, **kw: 'fake-id')
        monkeypatch.setattr(mod, 'persist_job_progress', lambda *a, **kw: None)
        monkeypatch.setattr(mod, 'persist_job_complete', lambda *a, **kw: None)
        monkeypatch.setattr(mod, 'resolve_terminal_status', lambda *a, **kw: 'completed')
        monkeypatch.setattr(mod, 'acquire_job_singleton_lock', lambda _: 0)
        monkeypatch.setattr(mod, 'release_singleton_fd', lambda *_a, **_kw: None)

        done = threading.Event()
        original_finally = mod.WebPMigrateJob._worker

        def _run_and_signal(self):
            try:
                return original_finally(self)
            finally:
                done.set()
        monkeypatch.setattr(mod.WebPMigrateJob, '_worker', _run_and_signal)

        job = mod.WebPMigrateJob()
        job.start()
        assert done.wait(timeout=5.0)
        status = job.get_status()
        assert status['error_message'] is not None
        assert 'free disk' in status['error_message'].lower()
        # No conversion happened.
        assert (webp_env['tmp'] / 'images' / 'boxart' / 'g.jpg').exists()

    def test_status_snapshot_holds_lock(self):
        """get_status reads every shared counter under self._lock to avoid
        torn reads against a running worker (Pass 40.9 convention)."""
        import inspect
        from services.jobs.webp_migrate import WebPMigrateJob

        src = inspect.getsource(WebPMigrateJob.get_status)
        assert 'with self._lock' in src
