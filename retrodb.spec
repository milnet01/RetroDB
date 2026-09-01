# =============================================================================
# retrodb.spec — PyInstaller specification for the Standalone distribution
# =============================================================================
# Builds a self-contained binary that bundles the Python runtime + all pip
# dependencies + bundled assets (templates, static, fonts, vendor JS). End
# users on the target platform need only extract the zip and run the
# `retrodb` (or `retrodb.exe`) launcher — no Python install required.
#
# Output mode: onedir (NOT onefile). Onedir starts faster (no per-launch
# extraction), is easier to inspect, and is the recommended production
# shape per PyInstaller's own documentation.
#
# Build:    pyinstaller retrodb.spec
# Output:   dist/retrodb/  (directory containing executable + _internal/)
# Bundled:  build_dist.py --standalone wraps this output into a Standalone zip
#
# Pass 46.3 (2026-04-27) — initial spec.
# =============================================================================

import sys
from pathlib import Path

# PyInstaller injects `SPEC` (path to this file) at parse time; use it to
# anchor the project root regardless of where pyinstaller was invoked from.
PROJECT_ROOT = Path(SPECPATH).resolve()  # noqa: F821 (SPECPATH injected by PyInstaller)

# -----------------------------------------------------------------------------
# Hidden imports — modules PyInstaller's static analyser cannot follow.
# -----------------------------------------------------------------------------
# Migration scripts loaded dynamically via importlib.import_module() in
# services/migrations/__init__.py. PyInstaller can't trace string-based
# imports, so we list them explicitly. New migrations must be added here.
_MIGRATION_SCRIPTS = [
    'services.migrations.scripts.001_baseline',
    'services.migrations.scripts.002_normalize_genres',
    'services.migrations.scripts.003_normalize_pegi',
    'services.migrations.scripts.004_games_updated_at',
    'services.migrations.scripts.005_collections_owner_id',
    'services.migrations.scripts.006_per_user_platform_tokens',
    'services.migrations.scripts.007_psn_user_id',
    'services.migrations.scripts.008_collector_trophies_user_id',
    'services.migrations.scripts.009_achievement_tables_user_id',
    'services.migrations.scripts.010_user_game_views',
    'services.migrations.scripts.011_user_game_views_cascade_fk',
    'services.migrations.scripts.012_emulators',
    'services.migrations.scripts.013_fresh_install_schema_backfill',
    'services.migrations.scripts.014_games_china_rating',
]

# Some pip packages have their own runtime imports that PyInstaller's
# default hooks miss on certain platforms. Belt-and-braces.
_RUNTIME_HIDDEN = [
    # Waitress production WSGI server is launched programmatically; the
    # default analyser may not follow the dynamic command-resolution path.
    'waitress',
    'waitress.runner',
    # PSNAWP uses pyrate-limiter via a string config knob; explicit.
    'pyrate_limiter',
    # PIL plugin auto-discovery (formats are loaded lazily by name).
    'PIL.WebPImagePlugin',
    'PIL.JpegImagePlugin',
    'PIL.PngImagePlugin',
    'PIL.GifImagePlugin',
    'PIL.BmpImagePlugin',
    'PIL.TiffImagePlugin',
    'PIL.IcoImagePlugin',
    # SQLite3 row factory is part of stdlib but PyInstaller occasionally
    # misses sqlite3.dbapi2 on minimal builds.
    'sqlite3.dbapi2',
]

HIDDEN_IMPORTS = _MIGRATION_SCRIPTS + _RUNTIME_HIDDEN

# -----------------------------------------------------------------------------
# Data files — non-Python assets that must be bundled alongside the binary.
# -----------------------------------------------------------------------------
# (source, dest) tuples — source is relative to SPECPATH, dest is the path
# inside the bundle (relative to the executable's MEIPASS root at runtime).
#
# CRITICAL: bundle ONLY app-shipped assets, NOT user-scraped media. A naive
# ('static', 'static') sweeps in static/images/{boxart,boxart_3d,fanart,
# screenshots,manuals,trophies} (scraped media, ~50 GB on a populated
# install) and static/videos/ (~17 GB), bloating dist/retrodb to 67+ GB and
# stalling the build. The whitelist below mirrors build_dist.py's
# INCLUDE_IMAGE_DIRS / EXCLUDE_STATIC_DIRS logic.
DATAS = [
    ('templates', 'templates'),
    # Static — explicit per-subdir whitelist (NOT recursive 'static').
    ('static/asset_manifest.json', 'static'),
    ('static/css', 'static/css'),
    ('static/fonts', 'static/fonts'),
    ('static/js', 'static/js'),
    ('static/images/placeholder.png', 'static/images'),
    # Bundled-with-app image dirs (logos, controller renders, rating icons).
    ('static/images/hardware', 'static/images/hardware'),
    ('static/images/ratings', 'static/images/ratings'),
    ('static/images/systems', 'static/images/systems'),
    ('static/images/avatars', 'static/images/avatars'),
    # App icon assets (favicon + launcher/exe icons). Small; shipped so the
    # running app can serve the favicon and the Linux zip can pin a .desktop.
    ('packaging/icons', 'packaging/icons'),
    # User-scraped: boxart, boxart_3d, fanart, screenshots, manuals, trophies,
    # static/videos/ — explicitly NOT bundled. Live in the writable image
    # dir at runtime; populated by the scraper.
    ('data/changelog.yaml', 'data'),
    # Per-locale changelog translations (Pass 43.6) — the /changelog route merges
    # these over changelog.yaml by version; bundle them or non-English users see
    # English release notes. (help.<locale>.html ride the templates/ dir above.)
    # Globbed, not hand-listed: the set grew 9 -> 20 at Pass 56 and Pass 56.2
    # plans four more, and a stale hand-list ships English notes for every
    # locale added after it was written (it had drifted to 6 of 20 by v3.23.1).
    # 'changelog.*.yaml' needs a locale segment, so changelog.yaml above is not
    # matched twice.
    *[(p.relative_to(PROJECT_ROOT).as_posix(), 'data')
      for p in sorted((PROJECT_ROOT / 'data').glob('changelog.*.yaml'))],
    # i18n catalogs (Pass 43.1) — .po/.mo are committed and have no build step
    # on the user's machine, so the bundle must carry them or it ships with no
    # translations (the dropdown would collapse to English-only).
    ('translations', 'translations'),
    # docs/ is deliberately NOT bundled. The comment here used to read "docs
    # the help-page route reads from disk", and that was never true: the help
    # route renders templates/help.<locale>.html (app.py::help_page), a
    # TEMPLATE, and no runtime code opens anything under docs/ at all.
    #
    # Shipping the directory wholesale put maintainer-only material into every
    # standalone bundle -- and, because PyInstaller's directory form takes the
    # whole tree with no per-file filter, it swept in docs/psn-npsso.env, a
    # real PSN NPSSO credential. That file is gitignored and is excluded from
    # the source ZIPs by name (build_dist.py EXCLUDE_FILES), so the source path
    # was safe and only this one leaked. Verified in a bundle built 2026-04-27:
    # dist/retrodb/_internal/docs/psn-npsso.env was byte-identical to the live
    # file. gitleaks could not catch it -- the file is untracked, so it is
    # absent from the `git ls-files` set a secret scan is scoped to.
    #
    # If a doc ever genuinely needs to ship, add that FILE, never the tree.
    # Note: HLTB lookups go through the live API at runtime — no dataset
    # bundled. rom_tools_config.json / settings.json / scraper_settings.json
    # are user-editable and live in the writable data dir, not bundled.
]

# -----------------------------------------------------------------------------
# Module exclusions — keep the binary lean.
# -----------------------------------------------------------------------------
# Things pip-installed alongside RetroDB that we know aren't actually used
# at runtime. Each exclusion saves anywhere from a few hundred KB to ~50 MB
# (matplotlib, tkinter).
EXCLUDES = [
    # Test harness — never needed in production.
    'pytest',
    'pytest_asyncio',
    'pytest_qt',
    '_pytest',
    # Dev tooling.
    'black',
    'mypy',
    'ruff',
    # Unused stdlib UI toolkits — onnxruntime occasionally pulls hints to them.
    'tkinter',
    'turtle',
    # Heavy plotting / scientific stacks not used by the app.
    'matplotlib',
    'pandas',
    'IPython',
    'jupyter',
    # PyInstaller's own runtime is not needed at runtime.
    'PyInstaller',
]


a = Analysis(
    ['app.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,  # 0 = preserve docstrings; 1 strips asserts, 2 strips docstrings
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='retrodb',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,        # Stripping symbols often breaks onnxruntime; keep them.
    upx=False,          # UPX compresses but onnxruntime + numpy SO files dislike it.
    console=True,       # Yes — RetroDB prints startup banner + log lines.
    # Neon-gamepad exe/taskbar icon. PyInstaller selects .ico on Windows and
    # .icns on macOS from this list; ignored on Linux (the .desktop carries
    # the icon there). Generated by scripts/render_icons.py.
    icon=[str(PROJECT_ROOT / 'packaging' / 'icons' / 'retrodb.ico'),
          str(PROJECT_ROOT / 'packaging' / 'icons' / 'retrodb.icns')],
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='retrodb',
)
