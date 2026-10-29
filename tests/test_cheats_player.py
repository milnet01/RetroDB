"""PASS-59-155 INV-1, INV-2, INV-11 — the player loads the game's cheat
switches, keeps what changed in play, and launches whatever goes wrong
with cheats. docs/specs/PASS-59-155-cheats.md §4.5.
"""
import logging

from tests.test_launch_resolver import tmpdb  # noqa: F401  (fixture)
from tests.test_player_launch import playerdb, _resolve, _cfg  # noqa: F401  (fixtures)

CHT = ('cheats = 2\n\ncheat0_desc = "Infinite Lives"\ncheat0_code = "1"\ncheat0_enable = true\n\n'
       'cheat1_desc = "Moon Jump"\ncheat1_code = "2"\ncheat1_enable = false\n')


def _launch_copy(profile):
    from services import player_cores
    return profile / 'cheats' / player_cores.library_name('mednafen_psx_hw') / 'crash.cht'


def _game_cht():
    from services import player
    path = player._game_file(1, 'cht')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CHT)
    return path


# INV-1 ------------------------------------------------------------------------

def test_inv1_launch_puts_the_games_list_where_retroarch_looks(playerdb):  # noqa: F811
    game_cht = _game_cht()
    ctx = _resolve()
    profile = playerdb['profile']
    assert _launch_copy(profile).read_text() == game_cht.read_text()
    base = _cfg(profile / 'retroarch.cfg')
    assert base['apply_cheats_after_load'] == 'true'
    assert base['cheat_database_path'] == str(profile / 'cheats')
    assert ctx.argv[-1] == str(playerdb['rom_file'].resolve())


def test_inv1_no_list_leaves_no_stale_copy(playerdb):  # noqa: F811
    stale = _launch_copy(playerdb['profile'])
    stale.parent.mkdir(parents=True)
    stale.write_text(CHT)
    _resolve()
    assert not stale.exists()


# INV-2 ------------------------------------------------------------------------

def test_inv2_in_game_changes_are_kept(playerdb):  # noqa: F811
    from services import player
    game_cht = _game_cht()
    ctx = _resolve()
    copy = _launch_copy(playerdb['profile'])
    rewritten = CHT.replace('cheat1_enable = false', 'cheat1_enable = "true"')
    copy.write_text(rewritten)          # RetroArch's rewrite on exit
    player.after_session(1, playerdb['rom_file'].resolve(), ctx.token)
    assert game_cht.read_text() == rewritten
    assert not copy.exists()


def test_inv2_no_launch_copy_keeps_the_games_list(playerdb):  # noqa: F811
    from services import player
    game_cht = _game_cht()
    ctx = _resolve()
    _launch_copy(playerdb['profile']).unlink()
    player.after_session(1, playerdb['rom_file'].resolve(), ctx.token)
    assert game_cht.read_text() == CHT


# INV-11 -----------------------------------------------------------------------

def test_inv11_a_cheat_problem_never_stops_a_launch(playerdb, caplog):  # noqa: F811
    from services import player
    _game_cht()
    (playerdb['profile'] / 'cheats').write_text('a file where the folder goes')
    with caplog.at_level(logging.WARNING):
        ctx = _resolve()
        player.after_session(1, playerdb['rom_file'].resolve(), ctx.token)
    assert ctx.argv
    assert 'cheats' in caplog.text


def test_inv11_an_unreadable_list_never_stops_a_launch(playerdb, caplog):  # noqa: F811
    from services import player
    player._game_file(1, 'cht').mkdir(parents=True)    # not a file
    with caplog.at_level(logging.WARNING):
        ctx = _resolve()
    assert ctx.argv
    assert 'cheats' in caplog.text
