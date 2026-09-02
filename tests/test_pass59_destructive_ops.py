# =============================================================================
# Pass 59.1-59.9 — destructive-operation regression pins
# =============================================================================
# Every finding here could destroy user data. None of them had a test before,
# which is why all nine survived to a shipped release: the suite stayed green
# across each fix.
#
#   59.1  clear_scraped_data must act on the rows its preview counted
#   59.2  media paths must resolve when IMAGE_PATH and STATIC_PATH are split
#   59.3  bulk edit must not carry a second copy of the appendable-field list
#   59.4  the orphan sweep must not delete a file written during the scan
#   59.5  boxart_3d must be cleared from the DB, not just unlinked
#   59.6  batch_create_m3u must honour delete_archives
#   59.7  the resize job must not upscale its own responsive variants
#   59.9  RAWG screenshots must not collide with the ones already stored
# =============================================================================

import os
import sqlite3

import pytest

from tests._util import read_source, read_module_source, slice_function


def _scraped_cols():
    """Every column clear_scraped_data() nulls, read from the module itself so
    this fixture cannot drift out of step with it."""
    from services.game_cleanup import _SCRAPED_FIELDS
    # boxart_3d is named explicitly rather than taken from _SCRAPED_FIELDS:
    # 59.5 is precisely that it was ABSENT from that tuple, so deriving the
    # column list alone would make the table lack it and every test in this
    # module error on the schema instead of failing on the behaviour.
    return tuple(dict.fromkeys(
        tuple(_SCRAPED_FIELDS) + ('boxart_3d', 'scrape_history')))


@pytest.fixture
def cleanup_db(tmp_path, monkeypatch):
    """A games table holding one scraped row and one never-scraped row."""
    db_path = tmp_path / 'roms.db'
    cols = ', '.join(f"{c} TEXT" for c in _scraped_cols())
    conn = sqlite3.connect(str(db_path))
    try:
        with conn:
            conn.execute(f"""
                CREATE TABLE games (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    rom_path TEXT,
                    system_id INTEGER,
                    scraped INTEGER DEFAULT 0,
                    {cols}
                )
            """)
            conn.execute(
                "INSERT INTO games (id, title, rom_path, system_id, scraped, "
                "genre, boxart, boxart_3d) VALUES (1, 'Scraped Game', "
                "'/roms/a.zip', 1, 1, 'Platform', '1_boxart.png', '1_3d.png')"
            )
            conn.execute(
                "INSERT INTO games (id, title, rom_path, system_id, scraped, "
                "genre, boxart) VALUES (2, 'Hand Curated', '/roms/b.zip', 1, 0, "
                "'My Genre', '2_custom.png')"
            )
    finally:
        conn.close()

    import config as _config
    monkeypatch.setattr(_config, 'DB_PATH', str(db_path))
    return db_path


def _row(db_path, game_id):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    finally:
        conn.close()


# -----------------------------------------------------------------------------
# 59.1 — the action must match the preview it is measured against
# -----------------------------------------------------------------------------
class TestClearScrapedDataHonoursScrapedFilter:
    def test_never_scraped_row_is_untouched(self, cleanup_db, monkeypatch):
        import services.game_cleanup as gc
        monkeypatch.setattr(gc, 'reset_game_title_from_filename', lambda *a, **k: None)

        cleared, _ = gc.clear_scraped_data()

        # The dialog promises preview_scraped_data()'s count; the action must
        # not exceed it. One row is scraped, so exactly one row is cleared.
        assert cleared == 1
        curated = _row(cleanup_db, 2)
        assert curated['genre'] == 'My Genre'
        assert curated['boxart'] == '2_custom.png'
        assert curated['scraped'] == 0

    def test_scraped_row_is_cleared(self, cleanup_db, monkeypatch):
        import services.game_cleanup as gc
        monkeypatch.setattr(gc, 'reset_game_title_from_filename', lambda *a, **k: None)

        gc.clear_scraped_data()

        scraped = _row(cleanup_db, 1)
        assert scraped['genre'] is None
        assert scraped['boxart'] is None
        assert scraped['scraped'] == 0

    def test_cleared_count_equals_preview(self, cleanup_db, monkeypatch):
        import services.game_cleanup as gc
        monkeypatch.setattr(gc, 'reset_game_title_from_filename', lambda *a, **k: None)

        promised = gc.preview_scraped_data()
        cleared, _ = gc.clear_scraped_data()
        assert cleared == promised

    def test_system_scoped_clear_also_honours_the_filter(self, cleanup_db, monkeypatch):
        import services.game_cleanup as gc
        monkeypatch.setattr(gc, 'reset_game_title_from_filename', lambda *a, **k: None)

        promised = gc.preview_scraped_data(system_id=1)
        cleared, _ = gc.clear_scraped_data(system_id=1)
        assert cleared == promised == 1
        assert _row(cleanup_db, 2)['genre'] == 'My Genre'


# -----------------------------------------------------------------------------
# 59.5 — boxart_3d was unlinked from disk but left naming the deleted file
# -----------------------------------------------------------------------------
class TestBoxart3dIsClearedFromTheDb:
    def test_boxart_3d_is_nulled(self, cleanup_db, monkeypatch):
        import services.game_cleanup as gc
        monkeypatch.setattr(gc, 'reset_game_title_from_filename', lambda *a, **k: None)

        gc.clear_scraped_data()

        # delete_game_images() unlinks the 3D boxart and its -sm/-md siblings,
        # so leaving the column set is a dangling reference site-wide.
        assert _row(cleanup_db, 1)['boxart_3d'] is None

    def test_boxart_3d_is_declared_scraped(self):
        from services.game_cleanup import _SCRAPED_FIELDS
        assert 'boxart_3d' in _SCRAPED_FIELDS


# -----------------------------------------------------------------------------
# 59.2 — a frozen build splits IMAGE_PATH and STATIC_PATH across two trees
# -----------------------------------------------------------------------------
def _split_layout(tmp_path, monkeypatch):
    """The PyInstaller shape: STATIC_PATH in the read-only bundle, IMAGE_PATH
    beside the launcher. Deliberately NOT nested -- nesting them is what hid
    this defect, since safe_path then accepted every image by accident."""
    import config
    bundle = tmp_path / 'bundle' / 'static'
    data = tmp_path / 'data' / 'static' / 'images'
    monkeypatch.setattr(config, 'STATIC_PATH', str(bundle))
    monkeypatch.setattr(config, 'IMAGE_PATH', str(data))
    for sub in ('boxart', 'boxart_3d', 'screenshots', 'fanart', 'manuals'):
        (data / sub).mkdir(parents=True, exist_ok=True)
    (bundle / 'videos').mkdir(parents=True, exist_ok=True)
    return bundle, data


class TestMediaPathsResolveOnASplitLayout:
    def test_existing_boxart_is_not_reported_missing(self, tmp_path, monkeypatch):
        _bundle, data = _split_layout(tmp_path, monkeypatch)
        (data / 'boxart' / '1_boxart.png').write_bytes(b'x')

        from services.media_cleanup import find_missing_media_refs
        game = {'id': 1, 'title': 'Sonic', 'boxart': '1_boxart.png',
                'boxart_3d': '', 'screenshots': '', 'fanart': '',
                'video': '', 'manual': ''}
        affected, _guarded = find_missing_media_refs([game])

        # Before the fix every image resolved to None and the whole library
        # was reported missing, so "clear missing media references" NULLed
        # every media column in one click.
        assert affected == []

    def test_resolver_accepts_an_image_under_image_path(self, tmp_path, monkeypatch):
        _bundle, data = _split_layout(tmp_path, monkeypatch)
        (data / 'boxart' / '1_boxart.png').write_bytes(b'x')

        from services.game_media_service import resolve_media_path
        resolved = resolve_media_path('1_boxart.png', 'boxart')
        assert resolved is not None
        assert os.path.exists(resolved)

    def test_traversal_is_still_refused(self, tmp_path, monkeypatch):
        _split_layout(tmp_path, monkeypatch)
        from services.game_media_service import resolve_media_path
        assert resolve_media_path('../../../etc/passwd', 'boxart') is None


# -----------------------------------------------------------------------------
# 59.4 — a file written DURING the scan must survive the sweep
# -----------------------------------------------------------------------------
class TestOrphanSweepDeleteTimeGuard:
    def test_file_written_during_the_scan_is_not_deleted(self, tmp_path, monkeypatch):
        _bundle, data = _split_layout(tmp_path, monkeypatch)
        victim = data / 'boxart' / 'fresh.png'
        victim.write_bytes(b'x')

        scan_started_at = os.stat(victim).st_mtime - 5  # scan began before the write

        from services.media_cleanup import clean_orphaned_files
        # scan_mtime EQUALS the current mtime -- the exact shape the old guard
        # missed, because it compared current-vs-recorded rather than against
        # the scan start. docs/specs/image-pipeline.md §10 item 3 states the
        # rule as `stat.st_mtime <= scan_started_at`.
        deleted, _errors, _freed = clean_orphaned_files([{
            'path': str(victim),
            'mtime': os.stat(victim).st_mtime,
            'scan_started_at': scan_started_at,
        }])

        assert victim.exists(), "a file written during the scan was deleted"
        assert deleted == 0

    def test_genuinely_old_orphan_is_still_deleted(self, tmp_path, monkeypatch):
        _bundle, data = _split_layout(tmp_path, monkeypatch)
        stale = data / 'boxart' / 'stale.png'
        stale.write_bytes(b'x')
        old = os.stat(stale).st_mtime
        os.utime(stale, (old - 100, old - 100))

        from services.media_cleanup import clean_orphaned_files
        deleted, _errors, _freed = clean_orphaned_files([{
            'path': str(stale),
            'mtime': os.stat(stale).st_mtime,
            'scan_started_at': old,  # scan began after the file was last written
        }])

        assert not stale.exists()
        assert deleted == 1


# -----------------------------------------------------------------------------
# 59.3 / 59.7 / 59.9 — pins on code that is inline in a long method or in JS
# -----------------------------------------------------------------------------
class TestBulkEditHasNoSecondFieldList:
    def test_client_does_not_carry_its_own_appendable_list(self):
        src = read_source('static/js/bulk-edit.js')
        # The server (routes/games.py) is the authority and re-validates every
        # field. A second copy here drifted and silently lost 'perspective'
        # and 'dimension', so ticking Append REPLACED them instead.
        assert 'APPENDABLE_FIELDS' not in src

    def test_server_still_validates_the_field(self):
        src = read_source('routes/games.py')
        assert 'safe_field in appendable_fields' in src

    def test_modal_toggles_are_all_server_appendable(self):
        import re
        modal = read_source('templates/_bulk_edit_modal.html')
        server = read_source('routes/games.py')
        listed = re.search(r"appendable_fields = \[(.*?)\]", server, re.S).group(1)
        allowed = set(re.findall(r"'([a-z_]+)'", listed))
        rendered = set(re.findall(
            r"class=\"bulk-append-toggle\" data-field=\"([a-z_]+)\"", modal))
        assert rendered, "no append toggles found -- selector drifted"
        assert rendered <= allowed, (
            f"modal offers Append for fields the server will not append: "
            f"{sorted(rendered - allowed)}"
        )


class TestResizeJobSkipsItsOwnVariants:
    def test_variant_suffixes_are_excluded_from_the_file_list(self):
        import services.jobs.image_resize as mod
        src = slice_function(read_module_source(mod), '_worker')
        assert '_RESPONSIVE_VARIANTS.get(img_type' in src
        assert 'stem.endswith(variant_suffixes)' in src

    def test_suffixes_are_not_a_second_hardcoded_copy(self):
        import services.jobs.image_resize as mod
        src = read_module_source(mod)
        assert "'-sm'" not in src and '"-sm"' not in src, (
            "hardcoded variant suffix -- derive it from _RESPONSIVE_VARIANTS "
            "so the two cannot drift"
        )


class TestRawgScreenshotsDoNotCollide:
    def test_rawg_loop_offsets_and_skips_existing(self):
        import scraper.metadata_merger as mod
        src = slice_function(read_module_source(mod), 'apply_rawg_to_metadata')
        # Mirrors the IGDB / TGDB / ScreenScraper loops. Fixed indices meant a
        # re-scrape overwrote a stored screenshot, dedup then deleted it as a
        # duplicate of itself, and the name stayed in games.screenshots.
        assert 'start_num = len(existing_ss) + 1' in src
        assert '_rawg_ss{start_num + i}' in src
        assert 'filename in existing_ss or os.path.exists(local_path)' in src


class TestBatchM3uHonoursDeleteArchives:
    def test_move_flag_is_passed_through(self):
        import scraper.rom_tools as mod
        src = slice_function(read_module_source(mod), 'batch_create_m3u')
        # Previously called create_m3u_playlist(archive_path) with neither
        # parameter, so move_to_staging defaulted True and every batch run
        # moved the user's originals regardless of the caller's choice.
        assert 'move_to_staging=delete_archives' in src
        assert 'staging_folder=staging_folder' in src

    def test_redundant_second_move_is_gone(self):
        import scraper.rom_tools as mod
        src = slice_function(read_module_source(mod), 'batch_create_m3u')
        assert 'shutil.move' not in src, (
            "the batch must not re-do the move create_m3u_playlist already did"
        )
        assert 'result.get("archive_moved")' in src
