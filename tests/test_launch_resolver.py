# Pass 44 — Resolver: game_id -> LaunchContext.
import sqlite3

import pytest


@pytest.fixture
def tmpdb(monkeypatch, tmp_path):
    """An on-disk SQLite seeded with systems, games, emulators, and a real
    ROM file under a 'scan root' that the resolver will accept."""
    rom_root = tmp_path / 'roms'
    (rom_root / 'psx').mkdir(parents=True)
    rom_file = rom_root / 'psx' / 'crash.bin'
    rom_file.write_text('rom-bytes')

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, folder TEXT UNIQUE)")
    c.execute("CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT, system_id INTEGER, title TEXT, rom_path TEXT UNIQUE, emulator_override_id INTEGER, launch_args_override TEXT)")
    c.execute("CREATE TABLE bonus_discs (id INTEGER PRIMARY KEY AUTOINCREMENT, parent_game_id INTEGER, rom_path TEXT)")
    c.execute("CREATE TABLE emulators (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, binary_name TEXT, binary_path_override TEXT, args_template TEXT, is_retroarch INTEGER, description TEXT, enabled INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT)")
    c.execute("CREATE TABLE system_emulators (id INTEGER PRIMARY KEY AUTOINCREMENT, system_id INTEGER, emulator_id INTEGER, is_default INTEGER, retroarch_core TEXT, extra_args TEXT, UNIQUE(system_id, emulator_id))")
    # Seed
    c.execute("INSERT INTO systems (name, folder) VALUES ('Sony PlayStation', 'psx')")
    c.execute("INSERT INTO games (system_id, title, rom_path) VALUES (1, 'Crash', ?)", (str(rom_file),))
    c.execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch, enabled) VALUES ('DuckStation', 'duckstation-qt', '-batch \"{rom}\"', 0, 1)")
    c.execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch, enabled) VALUES ('RetroArch', 'retroarch', '-L \"{retroarch_core}\" \"{rom}\"', 1, 1)")
    c.execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) VALUES (1, 1, 1)")
    c.execute("INSERT INTO system_emulators (system_id, emulator_id, retroarch_core, is_default) VALUES (1, 2, 'mednafen_psx_hw_libretro.so', 0)")
    conn.commit()

    # Patch services.launch_resolver.query / execute (it imports from services.database)
    def _query(sql, args=(), one=False):
        cc = conn.execute(sql, args)
        rows = cc.fetchall()
        if one:
            return dict(rows[0]) if rows else None
        return [dict(r) for r in rows]

    monkeypatch.setattr('services.launch_resolver.query', _query, raising=False)

    # Cores dir + binary stubs
    cores_dir = tmp_path / 'cores'
    cores_dir.mkdir()
    (cores_dir / 'mednafen_psx_hw_libretro.so').write_bytes(b'\x7fELF')
    monkeypatch.setattr('services.launch_resolver.get_setting',
                        lambda key, default=None: {
                            'retroarch_binary':    '/usr/bin/retroarch',
                            'retroarch_cores_dir': str(cores_dir),
                        }.get(key, default))
    monkeypatch.setattr('services.launch_resolver.shutil.which',
                        lambda name: f'/usr/bin/{name}')
    monkeypatch.setattr('services.launch_resolver._allowed_rom_roots',
                        lambda: [rom_root])

    yield {'conn': conn, 'rom_file': rom_file, 'cores_dir': cores_dir}
    conn.close()


def test_default_emulator_used_when_no_override(tmpdb):
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    assert ctx.argv[0] == '/usr/bin/duckstation-qt'


def test_per_game_override_takes_precedence(tmpdb):
    tmpdb['conn'].execute("UPDATE games SET emulator_override_id = 2 WHERE id = 1")
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    assert ctx.argv[0] == '/usr/bin/retroarch'
    joined = ' '.join(ctx.argv)
    assert 'mednafen_psx_hw_libretro.so' in joined


def test_missing_emulator_raises(tmpdb, tmp_path):
    """Game with system that has no emulator mapping."""
    rom = tmp_path / 'roms' / 'jaguar'
    rom.mkdir()
    rom_path = rom / 'foo.bin'
    rom_path.write_text('x')
    tmpdb['conn'].execute("INSERT INTO systems (name, folder) VALUES ('Atari Jaguar', 'jaguar')")
    tmpdb['conn'].execute("INSERT INTO games (system_id, title, rom_path) VALUES (2, 'Foo', ?)", (str(rom_path),))
    tmpdb['conn'].commit()

    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='No emulator'):
        resolve_launch_context(game_id=2)


def test_unknown_template_var_raises(tmpdb):
    tmpdb['conn'].execute("UPDATE emulators SET args_template = ? WHERE name = 'DuckStation'",
                          ('-foo "{nonexistent}"',))
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='Unknown template variable'):
        resolve_launch_context(game_id=1)


def test_path_traversal_rom_rejected(tmpdb, tmp_path):
    """A rom_path outside the configured scan roots is rejected."""
    evil = tmp_path / 'evil.bin'
    evil.write_text('x')
    tmpdb['conn'].execute("UPDATE games SET rom_path = ? WHERE id = 1", (str(evil),))
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='outside'):
        resolve_launch_context(game_id=1)


def test_argv_is_shell_quoted_against_injection(tmpdb):
    """A rom_path with shell metacharacters must end up as a single argv token."""
    bad_dir = tmpdb['rom_file'].parent
    bad = bad_dir / 'crash; rm -rf .bin'
    bad.write_text('x')
    tmpdb['conn'].execute("UPDATE games SET rom_path = ? WHERE id = 1", (str(bad),))
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    # The bad path must appear as one argv entry, not be split on ; or spaces
    assert str(bad) in ctx.argv


def test_extra_args_auto_appended(tmpdb):
    """system_emulators.extra_args is appended when template has no token."""
    tmpdb['conn'].execute("UPDATE system_emulators SET extra_args = '-renderer vulkan' WHERE emulator_id = 1")
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    assert '-renderer' in ctx.argv and 'vulkan' in ctx.argv


def test_token_is_random_per_call(tmpdb):
    from services.launch_resolver import resolve_launch_context
    a = resolve_launch_context(game_id=1)
    b = resolve_launch_context(game_id=1)
    assert a.token != b.token


def test_disabled_emulator_raises(tmpdb):
    tmpdb['conn'].execute("UPDATE emulators SET enabled = 0 WHERE name = 'DuckStation'")
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='disabled'):
        resolve_launch_context(game_id=1)


def test_missing_rom_file_raises(tmpdb):
    """rom_path that doesn't exist on disk is rejected at launch time."""
    tmpdb['conn'].execute("UPDATE games SET rom_path = '/roms/psx/missing.bin' WHERE id = 1")
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='not found'):
        resolve_launch_context(game_id=1)
