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
    (rom_root / 'psx' / 'systeminfo.txt').write_text(
        'Supported file extensions:\n.bin .BIN .cue .chd .m3u\n')

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, folder TEXT UNIQUE)")
    c.execute("CREATE TABLE games (id INTEGER PRIMARY KEY AUTOINCREMENT, system_id INTEGER, title TEXT, rom_path TEXT UNIQUE, emulator_override_id INTEGER, launch_args_override TEXT)")
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


def test_launch_args_override_appended(tmpdb):
    """games.launch_args_override (per-game arg suffix) must be appended
    to the resolved argv. The tmpdb fixture seeds this column but no test
    previously exercised the code path that reads it (test-audit c-003
    LOW coverage_gaps)."""
    tmpdb['conn'].execute(
        "UPDATE games SET launch_args_override = '--fullscreen --no-throttle' "
        "WHERE id = 1"
    )
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    assert '--fullscreen' in ctx.argv, (
        f"launch_args_override tokens missing from argv: {ctx.argv!r}"
    )
    assert '--no-throttle' in ctx.argv


def test_disc_paths_is_retired(tmpdb):
    """PASS-59-64 §4.1: `{disc_paths}` is removed (it read a table no
    migration creates), so a template using it fails like any unknown
    variable instead of passing nothing."""
    tmpdb['conn'].execute(
        "UPDATE emulators SET args_template = ? WHERE name = 'DuckStation'",
        ('-batch "{rom}" {disc_paths}',),
    )
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='Unknown template variable'):
        resolve_launch_context(game_id=1)


def _set_template(tmpdb, template):
    tmpdb['conn'].execute(
        "UPDATE emulators SET args_template = ? WHERE name = 'DuckStation'",
        (template,))
    tmpdb['conn'].commit()


@pytest.mark.parametrize('column,table,var', [
    ('launch_args_override', 'games', 'game_extra_args'),
    ('extra_args', 'system_emulators', 'system_extra_args'),
])
def test_list_variable_expands_one_element_per_word(tmpdb, column, table, var):
    """PASS-59-64 INV-3: a token that is exactly a list variable expands
    to one argv element per word."""
    _set_template(tmpdb, '{%s} "{rom}"' % var)
    tmpdb['conn'].execute(f"UPDATE {table} SET {column} = '--a --b'")
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    assert ctx.argv[1:] == ['--a', '--b', str(tmpdb['rom_file'])]


@pytest.mark.parametrize('var', ['game_extra_args', 'system_extra_args'])
def test_empty_list_variable_expands_to_nothing(tmpdb, var):
    """PASS-59-64 INV-3: an empty list variable adds no argv element,
    not an empty-string one."""
    _set_template(tmpdb, '{%s} "{rom}"' % var)
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    assert ctx.argv[1:] == [str(tmpdb['rom_file'])]


def test_list_variable_inside_a_token_is_refused(tmpdb):
    """PASS-59-64 §4.1: a list variable inside a larger token cannot
    expand to several elements, so it is refused."""
    _set_template(tmpdb, '--opts={game_extra_args} "{rom}"')
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='game_extra_args'):
        resolve_launch_context(game_id=1)


@pytest.mark.parametrize('column,table,field', [
    ('launch_args_override', 'games', 'launch_args_override'),
    ('extra_args', 'system_emulators', 'extra_args'),
    ('args_template', 'emulators', 'args_template'),
])
def test_unbalanced_quote_names_the_field(tmpdb, column, table, field):
    """PASS-59-64 §4.1: a shlex ValueError becomes a LaunchResolutionError
    naming the field, so the route answers 422 rather than 500."""
    tmpdb['conn'].execute(f"UPDATE {table} SET {column} = ?",
                          ('--renderer "vulkan',))
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match=field):
        resolve_launch_context(game_id=1)


def test_metacharacter_rom_path_stays_one_element(tmpdb):
    """PASS-59-64 INV-5: list expansion must not re-split a scalar
    variable's value."""
    bad = tmpdb['rom_file'].parent / '$(x); y.bin'
    bad.write_text('x')
    tmpdb['conn'].execute("UPDATE games SET rom_path = ?, "
                          "launch_args_override = '--a' WHERE id = 1",
                          (str(bad),))
    tmpdb['conn'].commit()
    _set_template(tmpdb, '{game_extra_args} "{rom}"')
    from services.launch_resolver import resolve_launch_context
    ctx = resolve_launch_context(game_id=1)
    assert ctx.argv[1:] == ['--a', str(bad)]


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


def test_rom_of_a_type_the_system_does_not_list_is_refused(tmpdb):
    """PASS-59-95: the launcher hands the emulator only a file whose type is
    on its system's systeminfo.txt list, the list the library scan uses."""
    cfg = tmpdb['rom_file'].parent / 'crash.cfg'
    cfg.write_text('not a rom')
    tmpdb['conn'].execute("UPDATE games SET rom_path = ? WHERE id = 1", (str(cfg),))
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match=r"\.cfg"):
        resolve_launch_context(game_id=1)


def test_rom_type_check_ignores_case(tmpdb):
    upper = tmpdb['rom_file'].parent / 'CRASH.CHD'
    upper.write_text('rom')
    tmpdb['conn'].execute("UPDATE games SET rom_path = ? WHERE id = 1", (str(upper),))
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    assert resolve_launch_context(game_id=1).argv[-1] == str(upper)


def test_rom_in_a_subfolder_uses_its_system_list(tmpdb):
    """Multi-disc games keep discs in a subfolder; the list is the system
    folder's, one level above."""
    sub = tmpdb['rom_file'].parent / 'Crash (Disc 1)'
    sub.mkdir()
    disc = sub / 'disc.cue'
    disc.write_text('cue')
    tmpdb['conn'].execute("UPDATE games SET rom_path = ? WHERE id = 1", (str(disc),))
    tmpdb['conn'].commit()
    from services.launch_resolver import resolve_launch_context
    assert resolve_launch_context(game_id=1).argv[-1] == str(disc)


def test_missing_type_list_is_refused_naming_the_file(tmpdb):
    """PASS-59-95, user decision 2026-10-15: no list, no launch."""
    info = tmpdb['rom_file'].parent / 'systeminfo.txt'
    info.unlink()
    from services.launch_resolver import resolve_launch_context
    from services.launcher.base import LaunchResolutionError
    with pytest.raises(LaunchResolutionError, match='systeminfo.txt'):
        resolve_launch_context(game_id=1)


def _fullscreen_db(tmpdb, template, binary_name='duckstation-qt', choice=None):
    conn = tmpdb['conn']
    conn.execute("CREATE TABLE IF NOT EXISTS emulator_setting_choices (id INTEGER PRIMARY KEY, "
                 "emulator_id INTEGER, scope TEXT, scope_id INTEGER, setting TEXT, value TEXT)")
    conn.execute("UPDATE emulators SET args_template = ?, binary_name = ? WHERE id = 1",
                 (template, binary_name))
    if choice:
        conn.execute("INSERT INTO emulator_setting_choices (emulator_id, scope, scope_id, "
                     "setting, value) VALUES (1, 'system', 1, 'fullscreen', ?)", (choice,))
    conn.commit()


def test_inv17_fullscreen_flag_follows_the_system_choice(tmpdb):
    """PASS-59-91 INV-17: {fullscreen_flag} is a list variable."""
    from services.launch_resolver import resolve_launch_context
    _fullscreen_db(tmpdb, '-batch {fullscreen_flag} "{rom}"', choice='off')
    argv = resolve_launch_context(game_id=1).argv
    assert '-nofullscreen' in argv and '' not in argv


def test_inv17_fullscreen_flag_defaults_on(tmpdb):
    from services.launch_resolver import resolve_launch_context
    _fullscreen_db(tmpdb, '-batch {fullscreen_flag} "{rom}"')
    assert '-fullscreen' in resolve_launch_context(game_id=1).argv


def test_inv17_no_flag_emulator_gets_no_element(tmpdb):
    from services.launch_resolver import resolve_launch_context
    _fullscreen_db(tmpdb, '-b {fullscreen_flag} -e "{rom}"', binary_name='dolphin-emu')
    argv = resolve_launch_context(game_id=1).argv
    assert argv[1:] == ['-b', '-e', str(tmpdb['rom_file'])]
