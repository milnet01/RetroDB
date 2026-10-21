"""Regression guard: retrodb.spec HIDDEN_IMPORTS must list every DB migration.

Indie-review 2026-06-05 found `retrodb.spec`'s hand-maintained
`_MIGRATION_SCRIPTS` list stopped at migration 011, so the PyInstaller
standalone build never bundled `012_emulators` — and since migrations load via
`importlib.import_module()` (a string import PyInstaller's static analyser can't
follow), a fresh standalone install crashed applying the missing migration.

This test cross-checks the spec's frozen-module list against the authoritative
`services.migrations.MIGRATIONS` registry so the next `013_*` added to the
registry but not the spec fails CI instead of a user's standalone install.
"""

import re
from pathlib import Path

from services.migrations import MIGRATIONS

_SPEC_PATH = Path(__file__).resolve().parent.parent / "retrodb.spec"
_PREFIX = "services.migrations.scripts."


def _spec_migration_modules():
    """Extract the `services.migrations.scripts.*` strings from retrodb.spec."""
    text = _SPEC_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"services\.migrations\.scripts\.[0-9A-Za-z_]+", text))


def test_spec_lists_every_registered_migration():
    expected = {f"{_PREFIX}{name}" for name in MIGRATIONS}
    listed = _spec_migration_modules()
    missing = expected - listed
    assert not missing, (
        "retrodb.spec HIDDEN_IMPORTS is missing migration module(s) "
        f"{sorted(missing)} — the standalone build would skip them at runtime. "
        "Add them to _MIGRATION_SCRIPTS in retrodb.spec."
    )


def test_spec_has_no_stale_migration_entries():
    expected = {f"{_PREFIX}{name}" for name in MIGRATIONS}
    listed = _spec_migration_modules()
    stale = listed - expected
    assert not stale, (
        f"retrodb.spec lists migration module(s) {sorted(stale)} that are not in "
        "services.migrations.MIGRATIONS — remove the stale entries."
    )


def test_spec_bundles_every_shipped_data_file_the_app_reads():
    """PASS-59-123: retrodb.spec bundled data/standalone_settings.json but not
    data/emulator_seeds.json, so a standalone install seeded no emulators.
    Every data/ file that is tracked in git (shipped, not written at run
    time) and that app.py / services / routes / scraper names must be in the
    spec's datas."""
    import subprocess
    root = _SPEC_PATH.parent
    tracked = set(subprocess.run(
        ['git', 'ls-files', 'data/*.json', 'data/*.yaml'], cwd=root,
        capture_output=True, text=True, check=True).stdout.split())
    code = "\n".join(
        p.read_text(encoding="utf-8")
        for pattern in ("app.py", "services/**/*.py", "routes/*.py", "scraper/*.py")
        for p in root.glob(pattern))
    read_by_app = {
        f for f in tracked
        if f.rsplit('/', 1)[1] in code and not f.startswith('data/changelog.')}
    assert 'data/emulator_seeds.json' in read_by_app, "the scan is broken"
    spec = _SPEC_PATH.read_text(encoding="utf-8")
    missing = sorted(f for f in read_by_app if f"('{f}', 'data')" not in spec)
    assert not missing, f"retrodb.spec does not bundle: {missing}"
