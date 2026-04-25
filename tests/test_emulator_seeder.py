# Pass 42 — emulator seed loader.
import importlib.util
import pathlib
import sqlite3

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def db():
    """In-memory DB with baseline systems + the new emulator tables already applied."""
    conn = sqlite3.connect(':memory:')
    c = conn.cursor()
    c.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, folder TEXT UNIQUE)")
    c.execute("INSERT INTO systems (name, folder) VALUES ('Sony PlayStation', 'psx')")
    c.execute("INSERT INTO systems (name, folder) VALUES ('Sony PlayStation 2', 'ps2')")
    p = _REPO_ROOT / 'services' / 'migrations' / 'scripts' / '010_emulators.py'
    spec = importlib.util.spec_from_file_location('m010', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.apply(conn)
    yield conn
    conn.close()


def test_seeder_inserts_emulators(db):
    from services.emulator_seeder import seed_emulators_from_file
    seed_emulators_from_file(db, str(_REPO_ROOT / 'data' / 'emulator_seeds.json'))

    c = db.cursor()
    rows = c.execute("SELECT name FROM emulators ORDER BY name").fetchall()
    names = {r[0] for r in rows}
    assert 'RetroArch' in names
    assert 'DuckStation' in names
    assert 'PCSX2' in names


def test_seeder_inserts_system_emulators(db):
    from services.emulator_seeder import seed_emulators_from_file
    seed_emulators_from_file(db, str(_REPO_ROOT / 'data' / 'emulator_seeds.json'))

    c = db.cursor()
    psx_default = c.execute("""
        SELECT e.name FROM system_emulators se
        JOIN emulators e ON e.id = se.emulator_id
        JOIN systems s ON s.id = se.system_id
        WHERE s.folder = 'psx' AND se.is_default = 1
    """).fetchone()
    assert psx_default[0] == 'DuckStation'


def test_seeder_skips_unknown_system_folders(db):
    from services.emulator_seeder import seed_emulators_from_file
    seed_emulators_from_file(db, str(_REPO_ROOT / 'data' / 'emulator_seeds.json'))

    c = db.cursor()
    cnt = c.execute("""
        SELECT COUNT(*) FROM system_emulators se
        JOIN systems s ON s.id = se.system_id
        WHERE s.folder = 'wiiu'
    """).fetchone()[0]
    assert cnt == 0


def test_seeder_is_idempotent(db):
    from services.emulator_seeder import seed_emulators_from_file
    path = str(_REPO_ROOT / 'data' / 'emulator_seeds.json')
    seed_emulators_from_file(db, path)
    seed_emulators_from_file(db, path)

    c = db.cursor()
    n_emu = c.execute("SELECT COUNT(*) FROM emulators").fetchone()[0]
    n_se = c.execute("SELECT COUNT(*) FROM system_emulators").fetchone()[0]
    assert n_emu == 12
    # 2 mappings for psx + 1 for ps2; others skipped because folder absent
    assert n_se == 3
