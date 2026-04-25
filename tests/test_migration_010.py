# Pass 42 — multi-emulator launch: schema migration regression coverage.
import importlib.util
import pathlib
import sqlite3

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_migration_010():
    p = _REPO_ROOT / 'services' / 'migrations' / 'scripts' / '010_emulators.py'
    spec = importlib.util.spec_from_file_location('migration_010', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_baseline_systems(conn):
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS systems (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, folder TEXT NOT NULL UNIQUE, logo TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS games (id INTEGER PRIMARY KEY AUTOINCREMENT, system_id INTEGER NOT NULL, title TEXT NOT NULL, rom_path TEXT NOT NULL UNIQUE, FOREIGN KEY(system_id) REFERENCES systems(id))")
    c.execute("INSERT INTO systems (name, folder) VALUES ('Sony PlayStation', 'psx')")
    c.execute("INSERT INTO games (system_id, title, rom_path) VALUES (1, 'Crash', '/roms/psx/crash.bin')")
    conn.commit()


def test_migration_010_creates_tables_and_columns():
    migration_010 = _load_migration_010()
    conn = sqlite3.connect(':memory:')
    _seed_baseline_systems(conn)
    migration_010.apply(conn)

    c = conn.cursor()
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'emulators' in tables
    assert 'system_emulators' in tables

    cols_games = {r[1] for r in c.execute("PRAGMA table_info(games)")}
    assert 'emulator_override_id' in cols_games
    assert 'launch_args_override' in cols_games

    cols_emu = {r[1] for r in c.execute("PRAGMA table_info(emulators)")}
    expected = {'id', 'name', 'binary_name', 'binary_path_override', 'args_template',
                'is_retroarch', 'description', 'enabled', 'created_at', 'updated_at'}
    assert expected <= cols_emu, f"Missing: {expected - cols_emu}"

    cols_se = {r[1] for r in c.execute("PRAGMA table_info(system_emulators)")}
    expected_se = {'id', 'system_id', 'emulator_id', 'is_default', 'retroarch_core', 'extra_args'}
    assert expected_se <= cols_se


def test_migration_010_is_idempotent():
    migration_010 = _load_migration_010()
    conn = sqlite3.connect(':memory:')
    _seed_baseline_systems(conn)
    migration_010.apply(conn)
    migration_010.apply(conn)

    c = conn.cursor()
    assert c.execute("SELECT COUNT(*) FROM emulators").fetchone()[0] == 0


def test_migration_010_indexes_present():
    migration_010 = _load_migration_010()
    conn = sqlite3.connect(':memory:')
    _seed_baseline_systems(conn)
    migration_010.apply(conn)

    c = conn.cursor()
    indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert 'idx_system_emulators_system' in indexes
    assert 'idx_system_emulators_default' in indexes


def test_migration_010_listed_in_loader():
    """The MIGRATIONS list must include '010_emulators' so apply_pending() picks it up."""
    from services.migrations import MIGRATIONS
    assert '010_emulators' in MIGRATIONS
    assert MIGRATIONS.index('010_emulators') == 9  # 0-indexed; 10th entry
