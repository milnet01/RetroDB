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


# PASS-59-239: every live-data path must sit inside the temp root, not merely
# equal its env var — an env var inherited from the shell could name the real
# library. Settings files too: a save from a route test must not reach them.
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402

from tests._util import REPO_ROOT  # noqa: E402


def _live_paths():
    import settings_manager
    import routes.scraper as routes_scraper
    from scraper import scraper_manager, scrape_ai
    return {
        "DB_PATH": config.DB_PATH,
        "IMAGE_PATH": config.IMAGE_PATH,
        "STATIC_PATH": config.STATIC_PATH,
        "settings_manager.SETTINGS_FILE": settings_manager.SETTINGS_FILE,
        "routes.scraper.SCRAPER_SETTINGS_FILE": routes_scraper.SCRAPER_SETTINGS_FILE,
        "scraper_manager.SCRAPER_SETTINGS_FILE": scraper_manager.SCRAPER_SETTINGS_FILE,
        "scrape_ai.SCRAPER_SETTINGS_FILE": scrape_ai.SCRAPER_SETTINGS_FILE,
    }


def test_every_live_path_is_inside_the_temp_root():
    root = os.path.realpath(tempfile.gettempdir())
    for name, path in _live_paths().items():
        real = os.path.realpath(path)
        assert os.path.commonpath([root, real]) == root, \
            f"{name} escapes the temp root during tests: {path}"


def test_inherited_paths_from_the_shell_are_not_trusted():
    """A shell that already set RETRODB_* paths (to anything, even the live
    library) must still get throwaway ones. The inherited paths here do not
    exist, so a regression fails without touching real files."""
    env = dict(os.environ)
    env.pop("PYTEST_XDIST_WORKER", None)
    bogus = "/nonexistent-retrodb-pass-59-239"
    env.update({
        "RETRODB_DB_PATH": f"{bogus}/roms.db",
        "RETRODB_IMAGE_PATH": f"{bogus}/static/images",
        "RETRODB_STATIC_PATH": f"{bogus}/static",
        "RETRODB_SETTINGS_FILE": f"{bogus}/settings.json",
        "RETRODB_SCRAPER_SETTINGS_FILE": f"{bogus}/scraper_settings.json",
    })
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "no:xdist", "-k", "temp_root",
         "tests/test_media_path_isolation.py"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert "1 passed" in result.stdout, result.stdout[-2000:] + result.stderr[-2000:]


def test_ci_import_smoke_isolates_every_live_path():
    with open(os.path.join(REPO_ROOT, "scripts", "ci_local.sh")) as fh:
        source = fh.read()
    smoke = source[source.index("Import smoke"):source.index("import app;")]
    for var in ("RETRODB_DB_PATH", "RETRODB_IMAGE_PATH", "RETRODB_STATIC_PATH",
                "RETRODB_SETTINGS_FILE", "RETRODB_SCRAPER_SETTINGS_FILE"):
        assert var in smoke, f"ci_local.sh import smoke does not isolate {var}"
