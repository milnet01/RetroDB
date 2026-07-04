# =============================================================================
# Pass 46.3 part 2 — PyInstaller frozen-mode user-data path
# =============================================================================
# Regression pins for the BASE_DIR / BUNDLE_DIR split in config.py.
#
# In a normal `python app.py` install both roots resolve to the project
# directory and these tests confirm the dev-mode invariant.  In a frozen
# bundle BASE_DIR sits next to the launcher (writable user data) and
# BUNDLE_DIR is sys._MEIPASS (read-only bundled assets); the split is
# exercised by monkeypatching `sys.frozen` + `sys._MEIPASS` and re-importing
# config.
#
# The serve_static_image() route is the runtime fallback that lets images
# live in two roots: scraped media in BASE_DIR/static/images/ takes
# precedence; bundled defaults in BUNDLE_DIR/static/images/ act as fallback.
# =============================================================================

import importlib
import os
import sys

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT  # noqa: F401


class TestPass46_3_DevModeInvariant:
    """Outside a frozen bundle BASE_DIR and BUNDLE_DIR are the same
    directory — no behavioural change for source-zip installs."""

    def test_base_and_bundle_equal_in_dev(self):
        import config
        assert config.BASE_DIR == config.BUNDLE_DIR

    def test_static_path_under_bundle_dir(self):
        import config
        # Honour the test-harness env override but still assert the default
        # derivation when it's absent — mirrors the RETRODB_DB_PATH guard below.
        if not os.environ.get("RETRODB_STATIC_PATH"):
            assert config.STATIC_PATH == os.path.join(config.BUNDLE_DIR, "static")

    def test_image_path_under_base_dir(self):
        """IMAGE_PATH writes go to the user-data root, never the bundle."""
        import config
        if not os.environ.get("RETRODB_IMAGE_PATH"):
            assert config.IMAGE_PATH == os.path.join(config.BASE_DIR, "static", "images")

    def test_db_path_under_base_dir(self):
        """The SQLite file is user data — must live next to the launcher
        in a frozen bundle, not inside _internal/database/."""
        import config
        # Honour env override but still assert the default points at BASE_DIR.
        if not os.environ.get("RETRODB_DB_PATH"):
            assert config.DB_PATH == os.path.join(config.BASE_DIR, "database", "roms.db")


# Modules that snapshot `config.BASE_DIR` at import time. When the frozen-mode
# test rewrites BASE_DIR, every one of these must be evicted from sys.modules
# so a fresh import re-runs the path-anchoring code. Shared between the
# frozen-mode test and the reloaded_app fixture.
_CONFIG_DEPENDENT_MODULES = (
    "config", "settings_manager", "log_manager", "routes.scraper", "app",
)


@pytest.fixture
def evict_config_modules():
    """Evict every config-dependent module for the test, then RESTORE the
    original module objects on teardown.

    c-005 deferred #4 fix: extracted from the manual eviction boilerplate that
    used to live inline in test_split_takes_effect_when_frozen.

    Restore (not just pop) is critical for cross-file test isolation. Popping
    `config` and letting a later test re-`import config` mints a NEW config
    module object, while already-imported service modules
    (`services.media_cleanup`, `services.image_pipeline`, `services.database`,
    …) still hold the ORIGINAL one captured at their own import time. A later
    test that does `import config; monkeypatch.setattr(config, 'IMAGE_PATH', …)`
    then patches the wrong object and its paths silently don't take effect — the
    seed-dependent order-pollution that intermittently reddened test_pass48 /
    test_image_pipeline / test_pass35_36. Putting the exact original objects back
    keeps module identity stable across the whole suite."""
    saved = {mod: sys.modules.get(mod) for mod in _CONFIG_DEPENDENT_MODULES}
    for mod in _CONFIG_DEPENDENT_MODULES:
        sys.modules.pop(mod, None)
    yield
    for mod, obj in saved.items():
        if obj is not None:
            sys.modules[mod] = obj
        else:
            sys.modules.pop(mod, None)


class TestPass46_3_FrozenModeSplit:
    """Simulate `getattr(sys, 'frozen', False) is True` and confirm the
    split kicks in: BASE_DIR moves to dirname(sys.executable), BUNDLE_DIR
    moves to sys._MEIPASS, IMAGE_PATH stays anchored to BASE_DIR while
    STATIC_PATH follows BUNDLE_DIR."""

    def test_split_takes_effect_when_frozen(
        self, tmp_path, monkeypatch, evict_config_modules,
    ):
        launcher_dir = tmp_path / "launcher"
        meipass_dir = tmp_path / "_internal"
        launcher_dir.mkdir()
        meipass_dir.mkdir()
        fake_exe = launcher_dir / "retrodb"
        fake_exe.write_text("#!/bin/sh\n")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass_dir), raising=False)
        monkeypatch.setattr(sys, "executable", str(fake_exe))
        # Avoid the env overrides polluting the frozen-path assertions.
        monkeypatch.delenv("RETRODB_DB_PATH", raising=False)
        monkeypatch.delenv("RETRODB_STATIC_PATH", raising=False)
        monkeypatch.delenv("RETRODB_IMAGE_PATH", raising=False)

        # evict_config_modules has already popped the snapshot-prone modules
        # both before and (on teardown) after this test. Re-import config now
        # so the module-level frozen check re-runs against the patched sys.
        config = importlib.import_module("config")
        assert config.BASE_DIR == str(launcher_dir)
        assert config.BUNDLE_DIR == str(meipass_dir)
        assert config.STATIC_PATH == os.path.join(str(meipass_dir), "static")
        assert config.IMAGE_PATH == os.path.join(str(launcher_dir), "static", "images")
        assert config.DB_PATH == os.path.join(str(launcher_dir), "database", "roms.db")


class TestPass46_3_DependentModulesFollowConfig:
    """settings_manager, log_manager, and routes.scraper must derive their
    on-disk paths from config.BASE_DIR — not from a local
    dirname(__file__) snapshot — so they track the writable user-data root
    in a frozen bundle."""

    def test_settings_manager_anchored_to_config_base_dir(self):
        import config
        import settings_manager
        assert settings_manager.SETTINGS_FILE == os.path.join(
            config.BASE_DIR, "data", "settings.json"
        )

    def test_log_manager_anchored_to_config_base_dir(self):
        import config
        import log_manager
        assert log_manager.LOGS_DIR == os.path.join(config.BASE_DIR, "logs")

    def test_scraper_settings_file_anchored_to_config_base_dir(self):
        import config
        from routes import scraper
        assert scraper.SCRAPER_SETTINGS_FILE == os.path.join(
            config.BASE_DIR, "data", "scraper_settings.json"
        )


@pytest.fixture
def reloaded_app(monkeypatch):
    """Re-import config + app with overridable IMAGE_PATH / bundle root,
    then restore both module bindings on teardown.

    c-006 FX-1 fix: the prior TestPass46_3_StaticImageRoute.client fixture
    duplicated manual `sys.modules.pop` + `importlib.import_module` blocks
    inside two of its three tests.  Centralising the eviction-and-reload
    pattern here removes the duplication and makes the teardown order
    explicit (app before config, both before re-import) so a flaky run
    can't leave a half-loaded module behind."""

    def _reload(image_path, bundle_root=None):
        sys.modules.pop("app", None)
        sys.modules.pop("config", None)
        config = importlib.import_module("config")
        monkeypatch.setattr(config, "IMAGE_PATH", str(image_path))
        app_mod = importlib.import_module("app")
        bundle_dir = (
            str(bundle_root) if bundle_root is not None
            else os.path.join(config.STATIC_PATH, "images")
        )
        monkeypatch.setattr(app_mod, "_BUNDLE_IMAGE_DIR", bundle_dir)
        return app_mod

    saved_app = sys.modules.get("app")
    saved_config = sys.modules.get("config")

    yield _reload

    # Restore the ORIGINAL module objects (not a fresh re-import) so their
    # identity is preserved for later tests. A fresh `import config` here would
    # diverge from the object already-imported service modules hold, silently
    # defeating their `monkeypatch.setattr(config, …)` — see evict_config_modules.
    for mod, obj in (("app", saved_app), ("config", saved_config)):
        if obj is not None:
            sys.modules[mod] = obj
        else:
            sys.modules.pop(mod, None)


class TestPass46_3_StaticImageRoute:
    """The /static/images/<path> route serves from BASE_DIR first, falls
    back to BUNDLE_DIR. In dev mode both roots are the same directory so
    we exercise the fallback by routing IMAGE_PATH at a temp dir while
    leaving BUNDLE_DIR/static/images at the real bundled tree."""

    def test_user_dir_takes_precedence(self, tmp_path, reloaded_app):
        """A file present in BASE_DIR/static/images must shadow any same-
        named file in BUNDLE_DIR/static/images — scraped content wins."""
        user_root = tmp_path / "user" / "static" / "images"
        bundle_root = tmp_path / "bundle" / "static" / "images"
        user_root.mkdir(parents=True)
        bundle_root.mkdir(parents=True)
        (user_root / "shared.png").write_bytes(b"USER_VERSION")
        (bundle_root / "shared.png").write_bytes(b"BUNDLE_VERSION")

        app_mod = reloaded_app(user_root, bundle_root)
        r = app_mod.app.test_client().get("/static/images/shared.png")
        assert r.status_code == 200
        assert r.data == b"USER_VERSION"

    def test_falls_back_to_bundle_when_user_missing(self, tmp_path, reloaded_app):
        """placeholder.png present in the bundle image dir; the empty user dir
        forces the route to fall through to BUNDLE_DIR/static/images/.

        Uses an explicit bundle_root (like test_user_dir_takes_precedence) rather
        than the real repo static tree, so the test is hermetic and doesn't
        depend on config.STATIC_PATH — which the harness now isolates to a temp
        dir to keep the media-cleanup tests off the operator's real files."""
        empty_user_images = tmp_path / "user" / "static" / "images"
        bundle_root = tmp_path / "bundle" / "static" / "images"
        empty_user_images.mkdir(parents=True)
        bundle_root.mkdir(parents=True)
        (bundle_root / "placeholder.png").write_bytes(b"BUNDLE_PLACEHOLDER")
        app_mod = reloaded_app(empty_user_images, bundle_root)
        r = app_mod.app.test_client().get("/static/images/placeholder.png")
        assert r.status_code == 200
        assert r.data == b"BUNDLE_PLACEHOLDER"

    def test_returns_404_when_neither_root_has_file(self, tmp_path, reloaded_app):
        empty_user_images = tmp_path / "static" / "images"
        empty_user_images.mkdir(parents=True)
        app_mod = reloaded_app(empty_user_images)
        r = app_mod.app.test_client().get("/static/images/totally/missing.png")
        assert r.status_code == 404
