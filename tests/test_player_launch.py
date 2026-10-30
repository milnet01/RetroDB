# PASS-59-64 §4.4–4.6 — the bundled player: profile, argv, kept in-game
# changes and one session at a time. No real player runs here; a stub child
# stands in for it.
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.test_launch_resolver import tmpdb  # noqa: F401  (fixture)


@pytest.fixture
def playerdb(tmpdb, tmp_path, monkeypatch):  # noqa: F811
    """tmpdb with the player row as PSX's default and its core installed,
    the profile under tmp_path, and the user's BIOS folder stubbed."""
    conn = tmpdb['conn']
    binary = tmp_path / 'retrodb-player'
    binary.write_text('#!/bin/sh\n')
    binary.chmod(0o755)
    tmpdb['binary'] = str(binary)
    conn.execute("ALTER TABLE emulators ADD COLUMN is_player INTEGER NOT NULL DEFAULT 0")
    conn.execute("INSERT INTO emulators (name, binary_name, binary_path_override, args_template, "
                 "is_retroarch, is_player, enabled) VALUES ('RetroDB Player', 'retrodb-player', ?, 'unused', 0, 1, 1)",
                 (str(binary),))
    conn.execute("CREATE TABLE emulator_setting_choices (id INTEGER PRIMARY KEY, emulator_id INTEGER, "
                 "scope TEXT, scope_id INTEGER, setting TEXT, value TEXT, "
                 "UNIQUE (emulator_id, scope, scope_id, setting))")
    conn.execute("UPDATE system_emulators SET is_default = 0")
    conn.execute("INSERT INTO system_emulators (system_id, emulator_id, retroarch_core, is_default) "
                 "VALUES (1, 3, 'mednafen_psx_hw_libretro.so', 1)")
    conn.commit()
    base_dir = tmp_path / 'base'
    monkeypatch.setattr('config.BASE_DIR', str(base_dir))
    from services import player
    cores = player.core_file('x').parent
    cores.mkdir(parents=True)
    (cores / 'mednafen_psx_hw_libretro.so').write_bytes(b'\x7fELF')
    monkeypatch.setattr('services.player._user_system_dir',
                        lambda: str(tmp_path / 'ra-system'))
    tmpdb['profile'] = player.profile_dir()
    # PASS-59-81: the buildbot's core list, without the network.
    tmpdb['index'] = {'mednafen_psx_hw_libretro.so.zip': ('2026-10-19', '00000000'),
                      'swanstation_libretro.so.zip': ('2026-10-19', '00000000')}
    monkeypatch.setattr('services.player_cores.index', lambda: tmpdb['index'])
    return tmpdb


def _resolve():
    from services.launch_resolver import resolve_launch_context
    return resolve_launch_context(game_id=1)


def _cfg(path):
    from services.player import _read
    return _read(Path(path))


# -----------------------------------------------------------------------------
# INV-8 argv shape
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('platform', ['linux', 'darwin'])
@pytest.mark.parametrize('extras', [False, True])
def test_inv8_argv_shape(playerdb, monkeypatch, platform, extras):
    monkeypatch.setattr('services.player.sys.platform', platform)
    if extras:
        playerdb['conn'].execute("UPDATE system_emulators SET extra_args = '--sys1' WHERE emulator_id = 3")
        playerdb['conn'].execute("UPDATE games SET launch_args_override = '--g1 --g2'")
        playerdb['conn'].commit()
    system_cfg = playerdb['profile'] / 'settings' / 'system' / 'psx.cfg'
    system_cfg.parent.mkdir(parents=True)
    system_cfg.write_text('video_smooth = "false"\n')

    ctx = _resolve()
    profile = playerdb['profile']
    argv = ctx.argv
    assert argv[0] == playerdb['binary']
    assert argv[1:3] == ['--config', str(profile / 'retroarch.cfg')]
    assert argv[3] == '--appendconfig'
    layers = argv[4].split('|')
    assert layers[:2] == [str(system_cfg), str(profile / 'settings' / 'game' / '1.cfg')]
    if platform == 'darwin':
        assert layers[2:] == [str(profile / 'run' / f'{ctx.token}.cfg')]
        assert ctx.quit_port
    else:
        assert len(layers) == 2 and ctx.quit_port is None
    tail = argv[5:]
    assert tail[:-3] == (['--sys1', '--g1', '--g2'] if extras else [])
    assert tail[-3:] == ['-L', str(profile / 'cores' / 'mednafen_psx_hw_libretro.so'),
                         str(playerdb['rom_file'].resolve())]
    for word in [argv[2], *layers, tail[-2], tail[-1]]:
        assert os.path.isabs(word)
    assert ctx.is_player and ctx.on_exit is not None


def test_inv8_system_layer_written_before_each_launch(playerdb):
    # PASS-59-81 §4.6 writes the system cfg before every player launch, so
    # the layer the system cfg once lacked is always there now.
    layers = _resolve().argv[4].split('|')
    assert layers == [str(playerdb['profile'] / 'settings' / 'system' / 'psx.cfg'),
                      str(playerdb['profile'] / 'settings' / 'game' / '1.cfg')]
    assert _cfg(layers[0])['aspect_ratio_index'] == '22'


# -----------------------------------------------------------------------------
# INV-9 base cfg
# -----------------------------------------------------------------------------

def test_inv9_base_keys_reset_other_lines_kept(playerdb):
    base = playerdb['profile'] / 'retroarch.cfg'
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text('config_save_on_exit = "true"\nvideo_driver = "vulkan"\n')
    _resolve()
    cfg = _cfg(base)
    assert cfg['config_save_on_exit'] == 'false'
    assert cfg['video_driver'] == 'vulkan'
    assert cfg['confirm_quit'] == 'false'
    assert cfg['libretro_directory'] == str(playerdb['profile'] / 'cores')


def test_left_stick_works_as_the_d_pad_for_every_player(playerdb):
    """Value 1, not the forced 3: RetroArch drops the mapping when a core asks
    for analog input, so a game that uses the stick keeps it."""
    _resolve()
    cfg = _cfg(playerdb['profile'] / 'retroarch.cfg')
    for port in range(1, 9):
        assert cfg[f'input_player{port}_analog_dpad_mode'] == '1'


# -----------------------------------------------------------------------------
# RetroAchievements: the launching user's sign-in, for this launch only
# -----------------------------------------------------------------------------

_RA_KEYS = {'cheevos_enable': 'true', 'cheevos_username': 'Ants',
            'cheevos_token': 'secret-token', 'cheevos_hardcore_mode_enable': 'false'}


def _run_layer(ctx):
    words = ctx.argv[ctx.argv.index('--appendconfig') + 1].split('|')
    return next((w for w in words if '/run/' in w), None)


def test_signed_in_user_gets_achievements_in_the_run_layer_only(playerdb, monkeypatch):
    monkeypatch.setattr('services.launch_resolver.ra_sign_in.launch_keys', lambda uid: _RA_KEYS)
    ctx = _resolve()
    layer = Path(_run_layer(ctx))
    assert {k: _cfg(layer)[k] for k in _RA_KEYS} == _RA_KEYS
    assert layer.stat().st_mode & 0o077 == 0
    profile = playerdb['profile']
    # On its command line and in every lasting settings file: no token.
    assert 'secret-token' not in ' '.join(ctx.argv)
    for path in profile.rglob('*'):
        if path.is_file() and path != layer:
            assert 'secret-token' not in path.read_text(errors='replace'), path


def test_run_layer_is_deleted_after_the_session(playerdb, monkeypatch):
    monkeypatch.setattr('services.launch_resolver.ra_sign_in.launch_keys', lambda uid: _RA_KEYS)
    ctx = _resolve()
    layer = Path(_run_layer(ctx))
    ctx.on_exit()
    assert not layer.exists()


def test_signed_out_launch_says_nothing_about_achievements(playerdb, monkeypatch):
    monkeypatch.setattr('services.launch_resolver.ra_sign_in.launch_keys', lambda uid: {})
    ctx = _resolve()
    layer = _run_layer(ctx)
    assert layer is None or not any(k.startswith('cheevos_') for k in _cfg(layer))


def test_launch_uses_the_user_who_pressed_play(playerdb, monkeypatch):
    from flask import Flask, g
    from services.launch_resolver import _launching_user_id
    assert _launching_user_id() is None
    with Flask(__name__).test_request_context():
        assert _launching_user_id() is None
        g.user = {'id': 42}
        assert _launching_user_id() == 42


def test_menu_save_cannot_copy_a_sign_in_into_game_settings():
    from services.player import _PROTECTED_KEYS
    assert set(_RA_KEYS) | {'cheevos_password'} <= _PROTECTED_KEYS


def test_base_cfg_recreated_when_deleted(playerdb):
    _resolve()
    base = playerdb['profile'] / 'retroarch.cfg'
    base.unlink()
    _resolve()
    assert _cfg(base)['quit_on_close_content'] == '2'


# -----------------------------------------------------------------------------
# INV-10 a '|' in the profile path
# -----------------------------------------------------------------------------

def test_inv10_pipe_in_profile_refused(playerdb, tmp_path, monkeypatch):
    from services.launcher.base import LaunchResolutionError
    from services import player
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'a|b'))
    player.core_file('x').parent.mkdir(parents=True)
    player.core_file('mednafen_psx_hw_libretro.so').write_bytes(b'\x7fELF')
    with pytest.raises(LaunchResolutionError, match=r"\|"):
        _resolve()
    assert not (player.profile_dir() / 'retroarch.cfg').exists()


# -----------------------------------------------------------------------------
# INV-11 menu saves kept after a session
# -----------------------------------------------------------------------------

def _run_stub(ctx, code):
    """Launch `code` as the player through a real LocalLauncher, wait for
    it, and run active() as the next launch request would."""
    from services.launcher.local import LocalLauncher
    ctx.argv = [sys.executable, '-c', code]
    launcher = LocalLauncher()
    h = launcher.launch(ctx)
    launcher._registry.get(h.token).proc.wait(timeout=10)
    launcher.active()
    return launcher


def test_inv11_override_absorbed_and_deleted(playerdb):
    ctx = _resolve()
    game_cfg = playerdb['profile'] / 'settings' / 'game' / '1.cfg'
    override = playerdb['profile'] / 'config' / 'Beetle PSX HW' / 'crash.cfg'
    code = (f"import os; os.makedirs({str(override.parent)!r}, exist_ok=True); "
            f"open({str(override)!r}, 'w').write("
            "'video_shader_enable = \"true\"\\nconfirm_quit = \"true\"\\n')")
    _run_stub(ctx, code)
    cfg = _cfg(game_cfg)
    assert cfg['video_shader_enable'] == 'true'
    assert 'confirm_quit' not in cfg
    assert not override.exists()

    from services import player
    assert player.is_customised(1)
    before = game_cfg.read_text()
    _run_stub(_resolve(), 'pass')
    assert game_cfg.read_text() == before


def test_inv11_hook_runs_once(playerdb):
    from services.launcher.local import LocalLauncher
    ctx = _resolve()
    calls = []
    ctx.on_exit = lambda: calls.append(1)
    ctx.argv = [sys.executable, '-c', 'pass']
    launcher = LocalLauncher()
    h = launcher.launch(ctx)
    launcher._registry.get(h.token).proc.wait(timeout=10)
    launcher.status(h.token)
    launcher.active()
    launcher.kill(h.token)
    assert calls == [1]


def test_malformed_override_rejected(playerdb):
    ctx = _resolve()
    override = playerdb['profile'] / 'config' / 'Core' / 'crash.cfg'
    code = (f"import os; os.makedirs({str(override.parent)!r}, exist_ok=True); "
            f"open({str(override)!r}, 'w').write('this is not a setting\\n')")
    _run_stub(ctx, code)
    assert not override.exists()
    assert list((playerdb['profile'] / 'rejected').iterdir())
    from services import player
    assert not player.is_customised(1)


# -----------------------------------------------------------------------------
# INV-12 user-set keys survive regeneration; reset removes them
# -----------------------------------------------------------------------------

def test_inv12_user_core_option_survives_until_reset(playerdb):
    from services import player
    game = {'id': 1, 'system_folder': 'psx'}
    core = str(player.core_file('mednafen_psx_hw_libretro.so'))
    rom = playerdb['rom_file'].resolve()
    player.launch_args(game, None, core, rom, 't1',
                       recommended={'opt': {'beetle_psx_hw_renderer': 'hardware'}})
    opt = player._game_file(1, 'opt')
    opt.write_text('beetle_psx_hw_renderer = "software"\n')   # the player's menu
    player.after_session(1, rom, 't1')
    player.launch_args(game, None, core, rom, 't2',
                       recommended={'opt': {'beetle_psx_hw_renderer': 'vulkan'}})
    assert _cfg(opt)['beetle_psx_hw_renderer'] == 'software'
    assert player.is_customised(1)

    player.reset(1)
    player.launch_args(game, None, core, rom, 't3',
                       recommended={'opt': {'beetle_psx_hw_renderer': 'vulkan'}})
    assert _cfg(opt)['beetle_psx_hw_renderer'] == 'vulkan'
    assert not player.is_customised(1)


# -----------------------------------------------------------------------------
# INV-13 the user's own RetroArch is unaffected; INV-16 network key placement
# -----------------------------------------------------------------------------

def _use_m3u(playerdb):
    m3u = playerdb['rom_file'].parent / 'Crash.m3u'
    m3u.write_text('crash.bin\n')
    playerdb['conn'].execute("UPDATE games SET rom_path = ? WHERE id = 1", (str(m3u),))
    playerdb['conn'].commit()


@pytest.mark.parametrize('platform,m3u,expected', [
    ('linux', False, False), ('linux', True, True),
    ('darwin', False, True), ('win32', False, True)])
def test_inv16_network_cmd_only_where_used(playerdb, monkeypatch, platform, m3u, expected):
    """Commands are on, in the run layer only, where RetroDB sends one: QUIT
    on macOS and Windows, DISK_NEXT for a .m3u game (PASS-59-139)."""
    monkeypatch.setattr('services.player.sys.platform', platform)
    if m3u:
        _use_m3u(playerdb)
    base = playerdb['profile'] / 'retroarch.cfg'
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text('network_cmd_enable = "true"\n')   # left by an older launch
    ctx = _resolve()
    assert _cfg(base)['network_cmd_enable'] == 'false'
    run = playerdb['profile'] / 'run' / f'{ctx.token}.cfg'
    assert run.is_file() is expected
    if expected:
        assert _cfg(run) == {'network_cmd_enable': 'true',
                             'network_cmd_port': str(ctx.command_port)}
        assert ctx.argv[4].split('|')[-1] == str(run)
    assert (ctx.command_port is not None) is expected
    assert (ctx.quit_port is not None) is (platform != 'linux')


def test_inv13_retroarch_row_writes_no_profile(playerdb, monkeypatch, tmp_path):
    monkeypatch.setattr('services.player.sys.platform', 'darwin')
    home = tmp_path / 'home'
    monkeypatch.setenv('HOME', str(home))
    playerdb['conn'].execute("UPDATE games SET emulator_override_id = 2")
    playerdb['conn'].commit()
    ctx = _resolve()
    assert '--config' not in ctx.argv
    assert not ctx.is_player
    assert [p.name for p in playerdb['profile'].iterdir()] == ['cores']  # the fixture's
    assert not (home / '.config' / 'retroarch').exists()


# -----------------------------------------------------------------------------
# Play button check and failure modes
# -----------------------------------------------------------------------------

def test_play_check_finds_player_core(playerdb, monkeypatch):
    from services.launch_resolver import launch_checker
    assert launch_checker()(1, None) is True
    from services import player
    player.core_file('mednafen_psx_hw_libretro.so').unlink()
    # PASS-59-81 §4.5: a missing core is offered while it can be downloaded.
    assert launch_checker()(1, None) is True
    monkeypatch.setattr('settings_manager.get_setting',
                        lambda key, default=None: False if key == 'player_core_downloads' else default)
    assert launch_checker()(1, None) is False


def test_missing_core_is_422_material(playerdb):
    from services.launcher.base import LaunchResolutionError
    from services import player
    player.core_file('mednafen_psx_hw_libretro.so').unlink()
    with pytest.raises(LaunchResolutionError, match='Player core not found'):
        _resolve()


def test_unwritable_profile_refused(playerdb, monkeypatch):
    from services.launcher.base import LaunchResolutionError

    def boom(*a, **k):
        raise PermissionError(13, 'Permission denied', 'retroarch.cfg')
    monkeypatch.setattr('services.player._set_keys', boom)
    with pytest.raises(LaunchResolutionError, match='retroarch.cfg'):
        _resolve()


# -----------------------------------------------------------------------------
# INV-17 one player session at a time (route)
# -----------------------------------------------------------------------------

@pytest.fixture
def launch_client(monkeypatch):
    import app as mod
    from tests.test_routes_launch import _make_authed_client
    monkeypatch.setitem(mod.app.config, 'TESTING', True)
    return _make_authed_client(mod, monkeypatch, 'player')


def test_inv17_second_player_session_refused(launch_client, monkeypatch):
    running = MagicMock(token='tok-a', pid=1, game_id=1, emulator_id=7, started_at=1.0)
    launcher = MagicMock()
    launcher.active.return_value = [running]
    monkeypatch.setattr('routes.launch.get_launcher', lambda: launcher)
    monkeypatch.setattr('routes.launch.launches_on_player', lambda gid: True)
    monkeypatch.setattr('routes.launch.query', lambda sql, args=(), one=False: [{'id': 7}])
    resolve = MagicMock()
    monkeypatch.setattr('routes.launch.resolve_launch_context', resolve)
    rv = launch_client.post('/api/game/2/launch', headers={'X-CSRF-Token': 'test-csrf-token'})
    assert rv.status_code == 409
    assert rv.get_json()['existing_token'] == 'tok-a'
    resolve.assert_not_called()
    launcher.launch.assert_not_called()


def test_reset_route_registered():
    import app as mod
    rules = {r.rule for r in mod.app.url_map.iter_rules()}
    assert '/api/games/<int:game_id>/player-settings/reset' in rules


# -----------------------------------------------------------------------------
# Migration 020
# -----------------------------------------------------------------------------

def test_migration_020_adds_player_row():
    import importlib
    import sqlite3
    mig = importlib.import_module('services.migrations.scripts.020_player')
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE emulators (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, "
                 "binary_name TEXT NOT NULL, binary_path_override TEXT, args_template TEXT NOT NULL, "
                 "is_retroarch INTEGER NOT NULL DEFAULT 0, description TEXT, enabled INTEGER NOT NULL DEFAULT 1, "
                 "created_at TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch) "
                 "VALUES ('RetroArch', 'retroarch', 'x', 1)")
    mig.apply(conn)
    mig.apply(conn)
    rows = conn.execute("SELECT name, is_player, is_retroarch FROM emulators ORDER BY id").fetchall()
    assert rows == [('RetroArch', 0, 1), ('RetroDB Player', 1, 0)]

    # Migration 022 (PASS-59-139) renames the placeholder, once.
    mig22 = importlib.import_module('services.migrations.scripts.022_player_name')
    mig22.apply(conn)
    mig22.apply(conn)
    rows = conn.execute("SELECT name, is_player FROM emulators ORDER BY id").fetchall()
    assert rows == [('RetroArch', 0), ('RetroArch (RetroDB)', 1)]


def test_migration_022_keeps_a_name_the_user_chose():
    import importlib
    import sqlite3
    mig22 = importlib.import_module('services.migrations.scripts.022_player_name')
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE emulators (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
                 "is_player INTEGER, description TEXT, updated_at TEXT)")
    conn.execute("INSERT INTO emulators (name, is_player) VALUES ('My Player', 1)")
    mig22.apply(conn)
    assert conn.execute("SELECT name FROM emulators").fetchone() == ('My Player',)


# -----------------------------------------------------------------------------
# PASS-59-81 — which core runs, and what a missing one does
# -----------------------------------------------------------------------------

def _choose_core(playerdb, scope, scope_id, value):
    playerdb['conn'].execute("INSERT INTO emulator_setting_choices (emulator_id, scope, scope_id, "
                             "setting, value) VALUES (3, ?, ?, 'core', ?)", (scope, scope_id, value))
    playerdb['conn'].commit()


def test_81_inv9_game_core_choice_is_the_l_path(playerdb):
    from services import player
    player.core_file('swanstation_libretro.so').write_bytes(b'\x7fELF')
    _choose_core(playerdb, 'game', 1, 'swanstation')
    argv = _resolve().argv
    assert argv[argv.index('-L') + 1].endswith('swanstation_libretro.so')


def test_81_inv9_choice_outside_the_list_is_ignored(playerdb):
    _choose_core(playerdb, 'system', 1, 'mame')
    argv = _resolve().argv
    assert argv[argv.index('-L') + 1].endswith('mednafen_psx_hw_libretro.so')


def test_81_inv2_no_core_built_is_a_resolution_error(playerdb):
    from services.launcher.base import LaunchResolutionError
    playerdb['index'].clear()
    with pytest.raises(LaunchResolutionError, match='No core for Sony PlayStation is built'):
        _resolve()


def test_81_missing_core_names_the_core(playerdb):
    from services import player, player_cores
    player.core_file('mednafen_psx_hw_libretro.so').unlink()
    with pytest.raises(player_cores.CoreMissing) as info:
        _resolve()
    assert (info.value.core, info.value.system_id) == ('mednafen_psx_hw', 1)


def test_81_inv7_launch_never_updates_an_installed_core(playerdb, monkeypatch):
    calls = []
    monkeypatch.setattr('services.player_cores._http_get', lambda *a, **k: calls.append(a))
    monkeypatch.setattr('services.player_cores._http_head', lambda *a, **k: calls.append(a))
    cores = playerdb['profile'] / 'cores'
    (cores / 'installed.json').write_text('{"mednafen_psx_hw": {"crc": "11111111", "date": "2026-01-01"}}')
    playerdb['index']['mednafen_psx_hw_libretro.so.zip'] = ('2026-10-19', '22222222')
    ctx = _resolve()
    assert ctx.is_player
    assert calls == []
    assert (cores / 'mednafen_psx_hw_libretro.so').read_bytes() == b'\x7fELF'


@pytest.mark.parametrize('downloads, expected', [(True, 202), (False, 422)])
def test_81_inv6_missing_core_downloads_or_422(launch_client, monkeypatch, tmp_path,
                                               downloads, expected):
    from services import player_cores
    from services.jobs import player_cores_job
    launcher = MagicMock()
    launcher.active.return_value = []
    monkeypatch.setattr('routes.launch.get_launcher', lambda: launcher)
    monkeypatch.setattr('routes.launch.launches_on_player', lambda gid: False)

    def missing(gid):
        raise player_cores.CoreMissing('snes9x', 4, 'Super Nintendo', tmp_path / 'x')
    monkeypatch.setattr('routes.launch.resolve_launch_context', missing)
    monkeypatch.setattr('routes.launch.get_setting', lambda key, default=None:
                        downloads if key == 'player_core_downloads' else default)
    monkeypatch.setattr('services.player_cores.buildbot_dir', lambda: 'linux/x86_64')
    monkeypatch.setattr('services.player_cores.download_size', lambda core: 917066)
    asked = []
    monkeypatch.setattr(player_cores_job, 'request', lambda items, **k: asked.append(items) or 'job-1')
    rv = launch_client.post('/api/game/1/launch', headers={'X-CSRF-Token': 'test-csrf-token'})
    assert rv.status_code == expected
    launcher.launch.assert_not_called()
    if downloads:
        assert rv.get_json()['installing'] == {'core': 'snes9x', 'system': 'Super Nintendo',
                                               'bytes': 917066, 'job_id': 'job-1'}
        assert asked == [[('snes9x', 4)]]
    else:
        assert asked == []
        assert 'Player core not found' in rv.get_json()['error']
