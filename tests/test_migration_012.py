# Pass 44 — multi-emulator launch: schema migration regression coverage.
import contextlib
import importlib.util
import pathlib
import sqlite3

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_migration_012():
    p = _REPO_ROOT / 'services' / 'migrations' / 'scripts' / '012_emulators.py'
    spec = importlib.util.spec_from_file_location('migration_012', p)
    if spec is None:
        # Without this guard the next line raises an unhelpful
        # `AttributeError: 'NoneType' object has no attribute
        # 'create_module'` from importlib internals.
        raise FileNotFoundError(f"Migration file not found: {p}")
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


def test_migration_012_creates_tables_and_columns():
    migration_012 = _load_migration_012()
    with contextlib.closing(sqlite3.connect(':memory:')) as conn:
        _seed_baseline_systems(conn)
        migration_012.apply(conn)

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


def test_migration_012_is_idempotent():
    migration_012 = _load_migration_012()
    with contextlib.closing(sqlite3.connect(':memory:')) as conn:
        _seed_baseline_systems(conn)
        migration_012.apply(conn)
        migration_012.apply(conn)

        c = conn.cursor()
        assert c.execute("SELECT COUNT(*) FROM emulators").fetchone()[0] == 0


def test_migration_012_indexes_present():
    migration_012 = _load_migration_012()
    with contextlib.closing(sqlite3.connect(':memory:')) as conn:
        _seed_baseline_systems(conn)
        migration_012.apply(conn)

        c = conn.cursor()
        indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert 'idx_system_emulators_system' in indexes
        assert 'idx_system_emulators_default' in indexes


def test_migration_012_listed_in_loader():
    """The MIGRATIONS list must include '012_emulators' so apply_pending() picks
    it up, and it must immediately follow 011_user_game_views_cascade_fk.
    Asserting the relative position (rather than a hardcoded index 11) lets new
    migrations land before 011 without flipping this test red."""
    from services.migrations import MIGRATIONS
    assert '012_emulators' in MIGRATIONS
    assert MIGRATIONS.index('012_emulators') == \
        MIGRATIONS.index('011_user_game_views_cascade_fk') + 1
