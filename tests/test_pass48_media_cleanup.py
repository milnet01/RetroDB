# =============================================================================
# Pass 48 — audit + indie-review fix-pass deferrals (Lane 6 / image pipeline)
# =============================================================================
# Regression pins for the media-pipeline cleanup bundle:
#   48.5  delete_game_images also unlinks responsive -sm/-md siblings
#   48.3  _make_responsive_variants prunes a stale variant when the primary
#         shrinks below the breakpoint
#   48.2  orphan detection matches references on basename, not substring
#   48.4  /clean honours the original preview scan-start (race window) and
#         resolves rel_path against an explicit base per media dir
# =============================================================================

import os
import time

import pytest


def _layout_nested(tmp_path, monkeypatch):
    """Normal-mode layout: IMAGE_PATH lives *under* STATIC_PATH (so safe_path,
    which validates against STATIC_PATH, accepts the image files)."""
    import config
    static = tmp_path / 'static'
    monkeypatch.setattr(config, 'STATIC_PATH', str(static))
    monkeypatch.setattr(config, 'IMAGE_PATH', str(static / 'images'))
    for sub in ('boxart', 'boxart_3d', 'screenshots', 'fanart', 'manuals'):
        (static / 'images' / sub).mkdir(parents=True, exist_ok=True)
    (static / 'videos').mkdir(parents=True, exist_ok=True)
    return static


def _layout_split(tmp_path, monkeypatch):
    """Standalone-mode layout: STATIC_PATH and IMAGE_PATH diverge (mirrors the
    PyInstaller frozen build where the bundle dir != the writable data dir)."""
    import config
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path / 'images'))
    monkeypatch.setattr(config, 'STATIC_PATH', str(tmp_path / 'static'))
    for sub in ('boxart', 'boxart_3d', 'screenshots', 'fanart', 'manuals'):
        (tmp_path / 'images' / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / 'static' / 'videos').mkdir(parents=True, exist_ok=True)


def _empty_game(**overrides):
    row = {'id': 0, 'boxart': '', 'boxart_3d': '', 'screenshots': '',
           'fanart': '', 'video': '', 'manual': ''}
    row.update(overrides)
    return row


# -----------------------------------------------------------------------------
# 48.5 — delete_game_images unlinks the responsive -sm / -md siblings
# -----------------------------------------------------------------------------
class TestPass48_5DeleteVariantSiblings:
    def test_removes_responsive_siblings(self, tmp_path, monkeypatch):
        static = _layout_nested(tmp_path, monkeypatch)
        from services import media_cleanup

        boxart_dir = static / 'images' / 'boxart'
        primary = boxart_dir / '5_boxart.png'
        sm = boxart_dir / '5_boxart-sm.png'
        md = boxart_dir / '5_boxart-md.png'
        for f in (primary, sm, md):
            f.write_bytes(b'img')

        deleted = media_cleanup.delete_game_images([_empty_game(id=5, boxart='5_boxart.png')])

        assert deleted == 3, "primary + -sm + -md must all be unlinked (Pass 48.5)"
        assert not primary.exists()
        assert not sm.exists()
        assert not md.exists()

    def test_missing_siblings_are_not_errors(self, tmp_path, monkeypatch):
        """A game whose boxart never had responsive variants still deletes
        cleanly — the absent siblings just don't count."""
        static = _layout_nested(tmp_path, monkeypatch)
        from services import media_cleanup

        primary = static / 'images' / 'boxart' / '6_boxart.png'
        primary.write_bytes(b'img')

        deleted = media_cleanup.delete_game_images([_empty_game(id=6, boxart='6_boxart.png')])
        assert deleted == 1
        assert not primary.exists()

    def test_non_variant_field_has_no_siblings(self, tmp_path, monkeypatch):
        """fanart is not a responsive-variant field — deleting it must not try
        to manufacture -sm/-md sibling deletions."""
        static = _layout_nested(tmp_path, monkeypatch)
        from services import media_cleanup

        fanart = static / 'images' / 'fanart' / '7_fanart.png'
        fanart.write_bytes(b'img')

        deleted = media_cleanup.delete_game_images([_empty_game(id=7, fanart='7_fanart.png')])
        assert deleted == 1


# -----------------------------------------------------------------------------
# 48.2 — orphan detection matches references on basename, not substring
# -----------------------------------------------------------------------------
class TestPass48_2OrphanBasenamePrecision:
    def test_substring_ref_does_not_spare_orphan(self, tmp_path, monkeypatch):
        """A file named ``1.png`` must not be treated as referenced just
        because ``21.png`` (an unrelated game's boxart) contains it as a
        substring."""
        _layout_split(tmp_path, monkeypatch)
        from services import media_cleanup

        orphan = tmp_path / 'images' / 'boxart' / '1.png'
        orphan.write_bytes(b'img')

        # game 99 references "21.png" (which is NOT on disk); "1.png" is a
        # substring of "21.png" but a different file.
        games = [_empty_game(id=99, boxart='21.png')]
        orphaned, _ = media_cleanup.find_orphaned_media(games)

        names = [o['filename'] for o in orphaned]
        assert '1.png' in names, (
            "substring-only match must no longer spare a real orphan (Pass 48.2)"
        )

    def test_basename_ref_still_protects_path_form(self, tmp_path, monkeypatch):
        """A reference stored as an absolute-ish path still protects the file
        whose basename it ends with."""
        _layout_split(tmp_path, monkeypatch)
        from services import media_cleanup

        keep = tmp_path / 'images' / 'boxart' / 'art_box.png'
        keep.write_bytes(b'img')

        games = [_empty_game(id=50, boxart='/static/images/boxart/art_box.png')]
        orphaned, _ = media_cleanup.find_orphaned_media(games)

        names = [o['filename'] for o in orphaned]
        assert 'art_box.png' not in names, (
            "basename match must keep protecting path-form references"
        )


# -----------------------------------------------------------------------------
# 48.4-B — rel_path resolves against an explicit per-dir base
# -----------------------------------------------------------------------------
class TestPass48_4BRelPathBase:
    def test_images_rel_path_matches_container_form_when_paths_diverge(self, tmp_path, monkeypatch):
        """With STATIC_PATH and IMAGE_PATH diverging (standalone build), a DB
        value stored in ``images/<sub>/<file>`` container form must still match
        the on-disk file — i.e. rel_path is built against dirname(IMAGE_PATH),
        not inferred from a 'static' substring test."""
        _layout_split(tmp_path, monkeypatch)
        from services import media_cleanup

        f = tmp_path / 'images' / 'boxart' / 'kept.png'
        f.write_bytes(b'img')

        games = [_empty_game(id=3, boxart='images/boxart/kept.png')]
        orphaned, _ = media_cleanup.find_orphaned_media(games)

        names = [o['filename'] for o in orphaned]
        assert 'kept.png' not in names, (
            "container-form reference must match via rel_base (Pass 48.4)"
        )


# -----------------------------------------------------------------------------
# 48.4-A — /clean honours the original preview scan-start (race window)
# -----------------------------------------------------------------------------
class TestPass48_4ACleanPreviewWindow:
    def test_override_skips_files_modified_since_preview(self, tmp_path, monkeypatch):
        _layout_split(tmp_path, monkeypatch)
        from services import media_cleanup

        boxart_dir = tmp_path / 'images' / 'boxart'
        old = boxart_dir / '10_old.png'      # orphaned well before the preview
        fresh = boxart_dir / '11_fresh.png'  # written during preview→clean
        old.write_bytes(b'old')
        fresh.write_bytes(b'fresh')

        now = time.time()
        os.utime(str(old), (now - 1000, now - 1000))
        os.utime(str(fresh), (now, now))

        games = [_empty_game(id=1)]
        orphaned, _ = media_cleanup.find_orphaned_media(games)
        assert {o['filename'] for o in orphaned} == {'10_old.png', '11_fresh.png'}

        # Preview happened 500s ago; only files untouched since then may go.
        deleted, errors, freed = media_cleanup.clean_orphaned_files(
            orphaned, scan_started_override=now - 500
        )
        assert deleted == 1
        assert errors == 0
        assert not old.exists(), "pre-preview orphan should be deleted"
        assert fresh.exists(), "file modified since preview must survive (Pass 48.4)"

    def test_no_override_preserves_legacy_behaviour(self, tmp_path, monkeypatch):
        """Without an override, an unmodified orphan still deletes (the 45.7
        path is unchanged)."""
        _layout_split(tmp_path, monkeypatch)
        from services import media_cleanup

        target = tmp_path / 'images' / 'boxart' / '12_orphan.png'
        target.write_bytes(b'orphan')

        orphaned, _ = media_cleanup.find_orphaned_media([_empty_game(id=1)])
        deleted, errors, freed = media_cleanup.clean_orphaned_files(orphaned)
        assert deleted == 1
        assert not target.exists()


# -----------------------------------------------------------------------------
# 48.3 — _make_responsive_variants prunes a stale variant when primary shrinks
# -----------------------------------------------------------------------------
class TestPass48_3PruneStaleVariant:
    def _png(self, path, width, height=100):
        from PIL import Image
        Image.new('RGB', (width, height), (10, 20, 30)).save(str(path))

    def test_prunes_stale_variant_on_shrink(self, tmp_path):
        from services import image_utils

        primary = tmp_path / 'card.png'
        self._png(primary, width=100)  # below both sm(160) and md(320) targets

        # Stale siblings left over from a previous, larger original.
        stale_sm = tmp_path / 'card-sm.png'
        stale_md = tmp_path / 'card-md.png'
        self._png(stale_sm, width=160)
        self._png(stale_md, width=320)

        image_utils._make_responsive_variants(str(primary), 'boxart')

        assert not stale_sm.exists(), "stale -sm must be pruned (Pass 48.3)"
        assert not stale_md.exists(), "stale -md must be pruned (Pass 48.3)"

    def test_creates_variants_when_primary_is_larger(self, tmp_path):
        from PIL import Image
        from services import image_utils

        primary = tmp_path / 'big.png'
        self._png(primary, width=400)  # larger than both breakpoints

        image_utils._make_responsive_variants(str(primary), 'boxart')

        sm = tmp_path / 'big-sm.png'
        md = tmp_path / 'big-md.png'
        assert sm.exists() and md.exists()
        with Image.open(str(sm)) as img:
            assert img.size[0] == 160
        with Image.open(str(md)) as img:
            assert img.size[0] == 320


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
