# =============================================================================
# Safety net: the test process must NEVER resolve media paths to the operator's
# real scraped-media tree.
# =============================================================================
# The media-cleanup helpers (find_orphaned_media / clean_orphaned_files /
# delete_game_images) DELETE files under IMAGE_PATH / STATIC_PATH. A per-attribute
# `monkeypatch.setattr(config, 'IMAGE_PATH', tmp)` can be silently defeated by
# module-eviction pollution (test_pass46), and once was — an orphan sweep then
# deleted a live ~5500-game media library. conftest now hard-pins these roots to
# throwaway dirs via RETRODB_IMAGE_PATH / RETRODB_STATIC_PATH (read at config
# import time, survives a config re-import). These tests fail loudly if that
# isolation ever regresses.
# =============================================================================

import os

import config


def _production_image_root():
    """The path the app would use in production (no env override)."""
    return os.path.join(config.BASE_DIR, "static", "images")


def test_image_path_is_env_isolated():
    assert os.environ.get("RETRODB_IMAGE_PATH"), \
        "conftest must pin RETRODB_IMAGE_PATH before config import"
    assert config.IMAGE_PATH == os.environ["RETRODB_IMAGE_PATH"]
    assert config.IMAGE_PATH != _production_image_root(), \
        "IMAGE_PATH must NOT point at the real scraped-media tree during tests"


def test_static_path_is_env_isolated():
    assert os.environ.get("RETRODB_STATIC_PATH"), \
        "conftest must pin RETRODB_STATIC_PATH before config import"
    assert config.STATIC_PATH == os.environ["RETRODB_STATIC_PATH"]


def test_media_cleanup_module_sees_isolated_root():
    """The module that actually deletes files must read the isolated root even
    through its own `import config` reference — the exact object a defeated
    monkeypatch would leave pointing at production."""
    from services import media_cleanup
    assert media_cleanup.config.IMAGE_PATH == os.environ["RETRODB_IMAGE_PATH"]
    assert media_cleanup.config.IMAGE_PATH != _production_image_root()


def test_find_orphaned_media_scans_only_isolated_dirs():
    """Even with an EMPTY game list — the worst case that marks every file an
    orphan — a scan must find nothing real, because the roots are isolated."""
    from services import media_cleanup
    orphaned, total = media_cleanup.find_orphaned_media([])
    for entry in orphaned:
        assert entry["path"].startswith(os.environ["RETRODB_STATIC_PATH"]), \
            f"orphan scan escaped the isolated root: {entry['path']}"
