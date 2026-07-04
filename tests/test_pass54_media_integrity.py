# =============================================================================
# Pass 54 — Media integrity & DB maintenance
# =============================================================================
# Regression pins for:
#   54.1  media_dir_is_healthy mass-missing guard — a gone/empty media dir
#         (unmounted drive / bulk deletion) must NOT be treated as a batch of
#         stale per-file references.
#   54.2  find_missing_media_refs / clear_missing_media_refs — the "clear DB
#         entries for missing media files" maintenance action, guarded by 54.1.
# =============================================================================

import pytest


def _nested_layout(tmp_path, monkeypatch):
    """IMAGE_PATH under STATIC_PATH so safe_path (validated against STATIC_PATH)
    accepts the media files. Creates every media subdir, all empty."""
    import config
    static = tmp_path / 'static'
    monkeypatch.setattr(config, 'STATIC_PATH', str(static))
    monkeypatch.setattr(config, 'IMAGE_PATH', str(static / 'images'))
    for sub in ('boxart', 'boxart_3d', 'screenshots', 'fanart', 'manuals'):
        (static / 'images' / sub).mkdir(parents=True, exist_ok=True)
    (static / 'videos').mkdir(parents=True, exist_ok=True)
    return static


def _game(**over):
    row = {'id': 1, 'title': 'Sonic', 'boxart': '', 'boxart_3d': '',
           'screenshots': '', 'fanart': '', 'video': '', 'manual': ''}
    row.update(over)
    return row


# -----------------------------------------------------------------------------
# 54.1 — media_dir_is_healthy
# -----------------------------------------------------------------------------
class TestMediaDirIsHealthy:
    def test_missing_dir_is_unhealthy(self, tmp_path):
        from services.media_cleanup import media_dir_is_healthy
        assert media_dir_is_healthy(str(tmp_path / 'nope')) is False

    def test_empty_dir_is_unhealthy(self, tmp_path):
        from services.media_cleanup import media_dir_is_healthy
        d = tmp_path / 'boxart'
        d.mkdir()
        assert media_dir_is_healthy(str(d)) is False

    def test_populated_dir_is_healthy(self, tmp_path):
        from services.media_cleanup import media_dir_is_healthy
        d = tmp_path / 'boxart'
        d.mkdir()
        (d / '1_boxart.png').write_bytes(b'x')
        assert media_dir_is_healthy(str(d)) is True


# -----------------------------------------------------------------------------
# 54.2 — find_missing_media_refs (the preview + guard logic)
# -----------------------------------------------------------------------------
class TestFindMissingMediaRefs:
    def test_present_file_is_not_flagged(self, tmp_path, monkeypatch):
        static = _nested_layout(tmp_path, monkeypatch)
        (static / 'images' / 'boxart' / '1_boxart.png').write_bytes(b'x')
        from services.media_cleanup import find_missing_media_refs
        affected, guarded = find_missing_media_refs([_game(boxart='1_boxart.png')])
        assert affected == []
        assert guarded == []

    def test_missing_file_in_healthy_dir_is_clearable(self, tmp_path, monkeypatch):
        static = _nested_layout(tmp_path, monkeypatch)
        # Directory stays healthy because ANOTHER game's boxart is present.
        (static / 'images' / 'boxart' / '2_boxart.png').write_bytes(b'x')
        from services.media_cleanup import find_missing_media_refs
        affected, guarded = find_missing_media_refs([_game(id=1, boxart='1_boxart.png')])
        assert len(affected) == 1
        assert affected[0]['id'] == 1
        assert affected[0]['fields'] == [{'field': 'boxart', 'value': '1_boxart.png'}]
        assert guarded == []

    def test_mass_missing_dir_is_guarded_not_cleared(self, tmp_path, monkeypatch):
        # boxart dir exists but is EMPTY — the unmounted-drive / bulk-delete
        # signal. The ref must be preserved (guarded), never offered for clear.
        _nested_layout(tmp_path, monkeypatch)
        from services.media_cleanup import find_missing_media_refs
        affected, guarded = find_missing_media_refs([_game(id=1, boxart='1_boxart.png')])
        assert affected == []
        assert guarded == [{'field': 'boxart', 'count': 1}]

    def test_screenshots_flagged_only_when_all_gone(self, tmp_path, monkeypatch):
        static = _nested_layout(tmp_path, monkeypatch)
        ss = static / 'images' / 'screenshots'
        # Keep the dir healthy with an unrelated file so the guard doesn't fire.
        (ss / '9_ss.png').write_bytes(b'x')
        from services.media_cleanup import find_missing_media_refs

        # Every referenced screenshot gone -> whole column is clearable.
        aff, _ = find_missing_media_refs([_game(id=1, screenshots='1_a.png, 1_b.png')])
        assert aff and aff[0]['fields'] == [
            {'field': 'screenshots', 'value': '1_a.png, 1_b.png'}
        ]

        # One of the two present -> partial, not flagged (a single NULL can't
        # express a partial prune; the scraper fill-path handles that).
        (ss / '1_a.png').write_bytes(b'x')
        aff2, _ = find_missing_media_refs([_game(id=1, screenshots='1_a.png, 1_b.png')])
        assert aff2 == []


# -----------------------------------------------------------------------------
# 54.2 — clear_missing_media_refs against the real (throwaway) test DB
# -----------------------------------------------------------------------------
class TestClearMissingMediaRefs:
    def test_clears_stale_ref_and_honours_guard(self, tmp_path, monkeypatch):
        static = _nested_layout(tmp_path, monkeypatch)
        # boxart dir healthy (unrelated file present); the referenced file gone.
        (static / 'images' / 'boxart' / '9999_boxart.png').write_bytes(b'x')
        # fanart dir left EMPTY -> the fanart ref must be guarded, not cleared.

        import app  # noqa: F401 — triggers schema init against RETRODB_DB_PATH
        from services.database import get_db, query
        from services.media_cleanup import clear_missing_media_refs

        conn = get_db()
        # Skip FK enforcement for this isolated insert — we don't depend on a
        # seeded system row; the test is about media-ref clearing, not FKs.
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO games (id, system_id, rom_path, title, boxart, fanart) "
            "VALUES (7001, 1, '/x/pass54.zip', 'Pass54 G', "
            "'7001_boxart.png', '7001_fanart.png')"
        )
        conn.commit()
        conn.close()

        cleared, game_count, guarded = clear_missing_media_refs()

        row = query("SELECT boxart, fanart FROM games WHERE id = 7001")[0]
        assert row['boxart'] is None, "stale boxart ref (healthy dir) must be cleared"
        assert row['fanart'] == '7001_fanart.png', \
            "fanart ref must be preserved — its dir is empty (mass-missing guard)"
        assert cleared >= 1
        assert {'field': 'fanart', 'count': 1} in guarded
