# Pass 44 — emulator seed loader.
import importlib.util
import pathlib
import sqlite3

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT_STR

_REPO_ROOT = pathlib.Path(_REPO_ROOT_STR)


_SEEDS_PATH = str(_REPO_ROOT / 'data' / 'emulator_seeds.json')


@pytest.fixture(scope="module")
def db():
    """In-memory DB with baseline systems + the new emulator tables already applied.

    Module-scoped: schema setup is read-only relative to test logic (no test
    in this file mutates the schema), so running the 012_emulators.py
    migration once per module is enough. The `seeded_db` fixture stays
    function-scoped because it writes seed data."""
    conn = sqlite3.connect(':memory:')
    c = conn.cursor()
    c.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, folder TEXT UNIQUE)")
    c.execute("INSERT INTO systems (name, folder) VALUES ('Sony PlayStation', 'psx')")
    c.execute("INSERT INTO systems (name, folder) VALUES ('Sony PlayStation 2', 'ps2')")
    p = _REPO_ROOT / 'services' / 'migrations' / 'scripts' / '012_emulators.py'
    spec = importlib.util.spec_from_file_location('m012', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.apply(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(db):
    """`db` with emulator seed data loaded — common setup for three tests
    that previously each repeated the seed call inline."""
    from services.emulator_seeder import seed_emulators_from_file
    seed_emulators_from_file(db, _SEEDS_PATH)
    return db


def test_seeder_inserts_emulators(seeded_db):
    c = seeded_db.cursor()
    rows = c.execute("SELECT name FROM emulators ORDER BY name").fetchall()
    names = {r[0] for r in rows}
    assert 'RetroArch' in names
    assert 'DuckStation' in names
    assert 'PCSX2' in names


def test_seeder_inserts_system_emulators(seeded_db):
    c = seeded_db.cursor()
    psx_default = c.execute("""
        SELECT e.name FROM system_emulators se
        JOIN emulators e ON e.id = se.emulator_id
        JOIN systems s ON s.id = se.system_id
        WHERE s.folder = 'psx' AND se.is_default = 1
    """).fetchone()
    assert psx_default[0] == 'DuckStation'


def test_seeder_skips_unknown_system_folders(seeded_db):
    c = seeded_db.cursor()
    cnt = c.execute("""
        SELECT COUNT(*) FROM system_emulators se
        JOIN systems s ON s.id = se.system_id
        WHERE s.folder = 'wiiu'
    """).fetchone()[0]
    assert cnt == 0


def test_seeder_is_idempotent(db):
    """The intent is 'running seed twice doesn't double-insert' — assert
    count equality before/after the second run, not a hardcoded literal
    that breaks every time someone adds an emulator to the seed file."""
    from services.emulator_seeder import seed_emulators_from_file

    seed_emulators_from_file(db, _SEEDS_PATH)
    c = db.cursor()
    emu_before = c.execute("SELECT COUNT(*) FROM emulators").fetchone()[0]
    se_before = c.execute("SELECT COUNT(*) FROM system_emulators").fetchone()[0]
    # Sanity floor — seed file isn't empty.
    assert emu_before > 0

    seed_emulators_from_file(db, _SEEDS_PATH)
    emu_after = c.execute("SELECT COUNT(*) FROM emulators").fetchone()[0]
    se_after = c.execute("SELECT COUNT(*) FROM system_emulators").fetchone()[0]

    assert emu_after == emu_before
    assert se_after == se_before
