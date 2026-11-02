"""PASS-59-210: RetroAchievements links are for the right game, and a wrong one
goes away. RA game lists here are built by hand; no network call is made."""
import importlib
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from scraper import retroachievements as ra
from services.achievement_linking import (
    NO_RA_MATCH, match_ra_game, ra_link_info, save_ra_link,
)


def _ra(game_id, title, count=10):
    return {'ID': game_id, 'Title': title, 'NumAchievements': count, 'Points': 100}


def _id(title, games, rom='', alternates=None):
    match = match_ra_game(title, rom, games, alternates)
    return match['ID'] if match else None


@pytest.mark.parametrize('title,other', [
    ('X-Men', 'G-Men'),
    ('R-Type', 'Z-Type'),
    ('Mega Man X', 'Mega Man'),
    ('F-Zero X', 'F-Zero'),
    ('Resident Evil: Code Veronica X', 'Resident Evil: Code: Veronica'),
])
def test_one_letter_is_part_of_the_name(title, other):
    assert _id(title, [_ra(1, other)]) is None


def test_final_fantasy_i_still_finds_final_fantasy():
    assert _id('Final Fantasy I', [_ra(1, 'Final Fantasy')]) == 1


@pytest.mark.parametrize('title', [
    '[Subset - Bonus] Pikmin', 'Pikmin [Subset - Bonus]', '~Hack~ Pikmin',
    '~Demo~ Pikmin', '~Prototype~ Pikmin', '~Test Kit~ Pikmin',
])
def test_bonus_sets_and_hacks_are_never_taken(title):
    assert _id('Pikmin', [_ra(1, title)]) is None


def test_a_long_title_does_not_take_its_hack():
    # Six words of seven overlap enough to pass the bar, but a hack is not the game.
    title = 'One Two Three Four Five Six'
    assert _id(title, [_ra(1, f'~Hack~ {title}')]) is None


def test_homebrew_matches_but_retail_comes_first():
    assert _id('Shinobi', [_ra(1, '~Unlicensed~ Shinobi')]) == 1
    assert _id('Shinobi', [_ra(1, '~Homebrew~ Shinobi'), _ra(2, 'Shinobi')]) == 2


def test_either_name_of_a_two_name_title():
    games = [_ra(1, 'Rally Chase | Thrash Rally')]
    assert _id('Thrash Rally', games) == 1
    assert _id('Rally Chase', games) == 1


def test_accents_and_possessives_do_not_matter():
    assert _id('Okami', [_ra(1, 'Ōkami')]) == 1
    assert _id("Kirby's Adventure", [_ra(1, 'Kirby Adventure')]) == 1


def test_numbered_title_finds_its_subtitle():
    assert _id('Gran Turismo 3', [_ra(1, 'Gran Turismo 3: A-Spec')]) == 1


@pytest.mark.parametrize('title,other', [
    ('Metroid', 'Metroid: Zero Mission'),                 # no number
    ('Dynasty Warriors 4', 'Dynasty Warriors 4: Xtreme Legends'),  # add-on
    ('GP-1', 'GP-1: Part II'),                            # another number
    ('The Sims 2: Castaway', 'The Sims 2'),               # the base game
])
def test_a_subtitle_does_not_make_another_game_this_one(title, other):
    assert _id(title, [_ra(1, other)]) is None


def test_two_subtitled_games_are_neither():
    games = [_ra(1, 'Doom 3: One'), _ra(2, 'Doom 3: Two')]
    assert _id('Doom 3', games) is None


def test_rom_name_beats_the_title():
    games = [_ra(1, 'Ratchet & Clank'), _ra(2, 'Ratchet: Deadlocked')]
    assert _id('Ratchet & Clank', games, rom='Ratchet - Deadlocked (USA)') == 2


def test_alternate_title_is_tried():
    assert _id('Bogey Blaster', [_ra(1, 'Air Raiders')], alternates=['Air Raiders']) == 1


@pytest.mark.parametrize('title,alternate', [
    ('Teen Titans', 'Teen Titans 2'),
    ('Colony Wars', 'Colony Wars: Vengeance'),
])
def test_alternate_for_another_game_is_left_out(title, alternate):
    assert _id(title, [_ra(1, alternate)], alternates=[alternate]) is None


# --- Asking RA ------------------------------------------------------------------

@pytest.fixture
def ra_api(monkeypatch):
    """RA's list request, answered by the test; nothing cached between tests."""
    monkeypatch.setattr(ra, 'get_ra_credentials', lambda: ('user', 'key'))
    monkeypatch.setattr(ra, '_ra_cache_get', lambda _c: None)
    monkeypatch.setattr(ra, '_ra_cache_set', lambda _c, _g: None)
    answer = MagicMock(status_code=200)
    get = MagicMock(return_value=answer)
    monkeypatch.setattr(ra, 'http_get', get)
    return get, answer


def test_list_request_asks_only_for_games_with_achievements(ra_api):
    get, answer = ra_api
    answer.json.return_value = [_ra(1, 'Pikmin')]
    assert ra.fetch_ra_game_list(16) == [_ra(1, 'Pikmin')]
    params = get.call_args.kwargs['params']
    assert params['f'] == 1 and 'h' not in params
    assert get.call_args.kwargs['max_bytes']


@pytest.mark.parametrize('body', [[], {'error': 'nope'}, None])
def test_a_bad_list_is_no_answer(ra_api, body):
    _, answer = ra_api
    answer.json.return_value = body
    assert ra.search_game_by_name('Pikmin', 16) is None


def test_failed_request_is_no_answer_and_a_miss_is_a_miss(ra_api):
    get, answer = ra_api
    answer.status_code = 500
    assert ra.search_game_by_name('Pikmin', 16) is None
    get.return_value = None
    assert ra.search_game_by_name('Pikmin', 16) is None
    get.return_value = answer
    answer.status_code = 200
    answer.json.return_value = [_ra(1, 'Pikmin')]
    assert ra.search_game_by_name('Tetris', 16) == NO_RA_MATCH


# --- Saving ---------------------------------------------------------------------

@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    db.executescript("""
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, rom_path TEXT, alternate_titles TEXT,
            has_retroachievements INTEGER DEFAULT 0, ra_game_id INTEGER, ra_title TEXT,
            ra_achievement_count INTEGER, ra_points INTEGER);
        CREATE TABLE game_achievement_progress (game_id INTEGER, source TEXT);
        INSERT INTO games (id, title, has_retroachievements, ra_game_id, ra_title,
            ra_achievement_count, ra_points) VALUES (1, 'Pikmin 2', 1, 15540, 'Pikmin', 50, 400);
        INSERT INTO game_achievement_progress VALUES (1, 'ra'), (1, NULL), (1, 'steam');
    """)
    yield db
    db.close()


def _row(db):
    return db.execute("SELECT has_retroachievements, ra_game_id, ra_title, ra_achievement_count, "
                      "ra_points FROM games WHERE id = 1").fetchone()


def _sources(db):
    return [r[0] for r in db.execute("SELECT source FROM game_achievement_progress")]


def test_no_match_clears_everything_and_old_progress(conn):
    assert save_ra_link(conn, 1, NO_RA_MATCH) is False
    assert _row(conn) == (0, None, None, None, None)
    assert _sources(conn) == ['steam']


def test_new_link_saves_title_and_points_and_drops_old_progress(conn):
    assert save_ra_link(conn, 1, ra_link_info(_ra(14817, 'Pikmin 2'))) is True
    assert _row(conn) == (1, 14817, 'Pikmin 2', 10, 100)
    assert _sources(conn) == ['steam']


def test_same_link_keeps_progress(conn):
    save_ra_link(conn, 1, ra_link_info(_ra(15540, 'Pikmin')))
    assert sorted(map(str, _sources(conn))) == ['None', 'ra', 'steam']


# --- A scrape --------------------------------------------------------------------

@pytest.fixture
def scrape(conn, monkeypatch):
    from scraper import hybrid_scraper
    keep_open = MagicMock(wraps=conn)
    keep_open.close = lambda: None
    monkeypatch.setattr(hybrid_scraper, 'get_scraper_conn', lambda: keep_open)

    def _run(answer):
        with patch('scraper.retroachievements.check_retroachievements',
                   return_value=answer) as check:
            result = hybrid_scraper._apply_retroachievements_check(1, 'Pikmin 2', 'gc')
        return result, check
    return _run


def test_scrape_miss_clears_a_wrong_link(scrape, conn):
    assert scrape(NO_RA_MATCH)[0] is False
    assert _row(conn)[1] is None


def test_scrape_failure_keeps_the_link(scrape, conn):
    assert scrape(None)[0] is False
    assert _row(conn)[1] == 15540


def test_scrape_passes_rom_name_and_alternates(scrape, conn):
    conn.execute("""UPDATE games SET rom_path = '/gc/Pikmin 2 (USA).iso',
                    alternate_titles = '[{"title": "Pikmin Two"}]'""")
    result, check = scrape(ra_link_info(_ra(14817, 'Pikmin 2')))
    assert result is True
    check.assert_called_once_with('Pikmin 2', 'gc', 'Pikmin 2 (USA)', ['Pikmin Two'])


# --- The refresh job ---------------------------------------------------------------

def _run_refresh(tmp_path, monkeypatch, game_list):
    from services.jobs import ra_refresh as mod
    db_path = tmp_path / 'r.db'
    db = sqlite3.connect(db_path)
    db.executescript("""
        CREATE TABLE systems (id INTEGER PRIMARY KEY, folder TEXT, name TEXT);
        INSERT INTO systems VALUES (1, 'gc', 'GameCube');
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, rom_path TEXT, system_id INTEGER,
            alternate_titles TEXT, has_retroachievements INTEGER, ra_game_id INTEGER, ra_title TEXT,
            ra_achievement_count INTEGER, ra_points INTEGER);
        INSERT INTO games VALUES (1, 'Pikmin 2', 'gc/Pikmin 2.iso', 1, NULL, 1, 15540, NULL, 50, NULL);
        INSERT INTO games VALUES (2, 'Tetris', 'gc/Tetris.iso', 1, NULL, 1, 15540, NULL, 50, NULL);
        CREATE TABLE game_achievement_progress (game_id INTEGER, source TEXT);
    """)
    db.commit()

    def _conn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(mod, '_get_conn', _conn)
    monkeypatch.setattr(mod, '_commit_with_retry', lambda c: c.commit())
    monkeypatch.setattr(mod, '_get_ra_credentials', lambda *a: ('user', 'key'))
    monkeypatch.setattr(mod, 'persist_job_start', lambda *a, **k: None)
    monkeypatch.setattr(mod, 'persist_job_progress', lambda *a, **k: None)
    monkeypatch.setattr(mod, 'persist_job_complete', lambda *a, **k: None)
    monkeypatch.setattr(mod, 'release_singleton_fd', lambda *a: None)
    monkeypatch.setattr(mod.shutdown_requested, 'wait', lambda *a: False)
    monkeypatch.setattr('scraper.retroachievements.fetch_ra_game_list', lambda _c: game_list)
    job = mod.RARefreshJob()
    job.running = True
    job._run_refresh()
    rows = db.execute("SELECT id, has_retroachievements, ra_game_id, ra_title, ra_achievement_count, "
                      "ra_points FROM games ORDER BY id").fetchall()
    db.close()
    return job, rows


def test_refresh_links_saves_points_and_clears_misses(tmp_path, monkeypatch):
    job, rows = _run_refresh(tmp_path, monkeypatch, [_ra(14817, 'Pikmin 2')])
    assert rows[0] == (1, 1, 14817, 'Pikmin 2', 10, 100)
    assert rows[1] == (2, 0, None, None, None, None)
    assert job.get_status()['success'] == 1 and job.get_status()['skipped'] == 1


def test_refresh_changes_nothing_when_the_list_fails(tmp_path, monkeypatch):
    job, rows = _run_refresh(tmp_path, monkeypatch, None)
    assert [r[2] for r in rows] == [15540, 15540]
    assert job.get_status()['failed'] == 2


# --- The upgrade --------------------------------------------------------------------

def _migrate(db):
    importlib.import_module('services.migrations.scripts.027_games_ra_title').apply(db)


@pytest.fixture
def old_db():
    db = sqlite3.connect(':memory:')
    db.executescript("""
        CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER, title TEXT,
            has_retroachievements INTEGER, ra_game_id INTEGER,
            ra_achievement_count INTEGER, ra_points INTEGER);
        CREATE TABLE game_achievement_progress (game_id INTEGER, source TEXT);
        CREATE TABLE job_queue (id INTEGER PRIMARY KEY, job_type TEXT, status TEXT, progress TEXT,
            params TEXT, created_at TEXT, updated_at TEXT);
    """)
    yield db
    db.close()


def test_upgrade_clears_sequels_sharing_a_link(old_db):
    old_db.executescript("""
        INSERT INTO games VALUES
            (1, 64, 'Resident Evil', 1, 3358, 114, 500),
            (2, 64, 'Resident Evil 2', 1, 3358, 114, 500),
            (3, 64, 'Resident Evil 4', 1, 3358, 114, 500),
            (4, 131, 'Tomb Raider II', 1, 11341, 40, 300),
            (5, 131, 'Tomb Raider II Starring Lara Croft', 1, 11341, 40, 300),
            (6, 131, 'Gran Turismo 2 (Arcade Mode)', 1, 11278, 40, 300),
            (7, 131, 'Gran Turismo 2 (Simulation Mode)', 1, 11278, 40, 300),
            (8, 2, 'Commando Raid', 0, NULL, 34, NULL);
        INSERT INTO game_achievement_progress VALUES (2, 'ra'), (2, 'steam'), (4, 'ra');
    """)
    _migrate(old_db)
    rows = dict(old_db.execute("SELECT id, ra_game_id FROM games").fetchall())
    assert [rows[i] for i in (1, 2, 3)] == [None, None, None]
    assert [rows[i] for i in (4, 5, 6, 7)] == [11341, 11341, 11278, 11278]
    assert old_db.execute("SELECT COUNT(*) FROM games WHERE ra_title IS NOT NULL").fetchone()[0] == 0
    # Cleared rows lose their counts and flag; linked rows keep theirs.
    assert old_db.execute("SELECT has_retroachievements, ra_achievement_count, ra_points "
                          "FROM games WHERE id = 2").fetchone() == (0, None, None)
    assert old_db.execute("SELECT ra_achievement_count FROM games WHERE id = 8").fetchone()[0] is None
    assert old_db.execute("SELECT ra_achievement_count FROM games WHERE id = 4").fetchone()[0] == 40
    assert old_db.execute("SELECT game_id, source FROM game_achievement_progress "
                          "ORDER BY game_id, source").fetchall() == [(2, 'steam'), (4, 'ra')]
    assert old_db.execute("SELECT job_type, status FROM job_queue").fetchall() == [('ra_refresh', 'queued')]


def test_upgrade_of_a_library_with_no_links_queues_nothing(old_db):
    old_db.execute("INSERT INTO games VALUES (1, 1, 'Tetris', 0, NULL, NULL, NULL)")
    _migrate(old_db)
    assert old_db.execute("SELECT COUNT(*) FROM job_queue").fetchone()[0] == 0
