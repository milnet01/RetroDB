# PASS-59-209: HowLongToBeat takes the right game on the right platform, and
# minutes count as minutes.

import sqlite3
from unittest.mock import patch

import pytest

import config
from scraper import hltb_lookup
from services import migrations
from services.jobs.hltb_bulk import classify_match
from services.playtime import main_story_hours


def _hit(name, platform='PC', year=2000, game_id=1):
    return {'game_id': game_id, 'game_name': name, 'comp_main': 36000,
            'comp_plus': 0, 'comp_100': 0, 'profile_platform': platform,
            'release_world': year}


class TestMainStoryHours:
    @pytest.mark.parametrize('text,hours', [
        ('Main: 36 mins', 0.6),
        ('Main: 36 mins | Main+Extras: 2 hrs | 100%: 5 hrs', 0.6),
        ('Main: 9 hrs', 9.0),
        ('Main: 7.2 hrs | 100%: 54 mins', 7.2),
        ('Main Story: 25½ Hours', 25.5),
        ('Main: 25h', 25.0),
    ])
    def test_reads_the_unit(self, text, hours):
        assert main_story_hours(text) == pytest.approx(hours)

    @pytest.mark.parametrize('text', [
        None, '', 'Main: -- | Main+Extras: 10 hrs', 'Main+Extras: 10 hrs',
        '100%: 54 mins',
    ])
    def test_no_main_story_time(self, text):
        assert main_story_hours(text) is None


class TestTitleScore:
    @pytest.mark.parametrize('title,name', [
        ('Double Dragon II', 'Double Dragon III'),
        ('Back to the Future Part II', 'Back to the Future Part III'),
        ('Lotus Turbo Challenge', 'Lotus Turbo Challenge 2'),
        ('Final Fantasy VII', 'Final Fantasy VIII'),
        ('Sonic the Hedgehog 2', 'Sonic the Hedgehog 3'),
    ])
    def test_a_sequel_stays_under_the_bar(self, title, name):
        assert hltb_lookup.title_score(title, name) < 0.6

    def test_the_same_number_written_two_ways_is_the_same_game(self):
        assert hltb_lookup.title_score('Alan Wake II', 'Alan Wake 2') == 1.0

    @pytest.mark.parametrize('title,name', [
        ('3D Glooper', '3-D Glooper'),
        ('Road Rash 3D', 'Road Rash 3-D'),
        ('D-2', 'D2'),
    ])
    def test_spacing_inside_a_title_is_not_a_sequel_number(self, title, name):
        assert hltb_lookup.title_score(title, name) > hltb_lookup.SEQUEL_SCORE_CAP

    def test_exact_title(self):
        assert hltb_lookup.title_score('Contra', 'contra') == 1.0

    def test_lookup_does_not_take_the_sequel(self):
        with patch.object(hltb_lookup, '_search_hltb',
                          return_value=[_hit('Double Dragon III', 'Game Boy')]):
            result = hltb_lookup.lookup_playtime('Double Dragon II', 'gb')
        assert classify_match(result, 'Double Dragon II', 95) == 'queue_low_conf'


class TestOnPlatform:
    @pytest.mark.parametrize('wanted,listed,expected', [
        ('Game Boy', 'Game Boy Advance', False),
        ('Game Boy', 'Game Boy Color, PC', False),
        ('PlayStation', 'PlayStation 2', False),
        ('Wii', 'Wii U', False),
        ('Game Boy', 'PC, Game Boy', True),
        ('Atari ST', ', Atari ST, PC', True),
        ('Sega Mega Drive/Genesis', 'Sega Mega Drive/Genesis', True),
    ])
    def test_whole_names(self, wanted, listed, expected):
        assert hltb_lookup.on_platform(wanted, listed) is expected

    def test_lookup_flags_a_longer_name_as_another_platform(self):
        with patch.object(hltb_lookup, '_search_hltb',
                          return_value=[_hit('Spider-Man 2', 'Game Boy Advance')]):
            result = hltb_lookup.lookup_playtime('Spider-Man 2', 'gb')
        assert result['platform_mismatch'] is True

    def test_folder_maps_use_names_the_site_lists(self):
        assert hltb_lookup.SYSTEM_TO_HLTB_PLATFORM['ngpc'] == 'Neo Geo Pocket'
        assert hltb_lookup.SYSTEM_TO_HLTB_PLATFORM['amigacd32'] == 'Amiga CD32'


class TestYear:
    def test_equal_titles_go_to_the_nearer_year(self):
        results = [_hit('Doom', year=2016, game_id=2), _hit('Doom', year=1993, game_id=1)]
        with patch.object(hltb_lookup, '_search_hltb', return_value=results):
            result = hltb_lookup.lookup_playtime('Doom', 'pc', year='1993')
        assert result['game_id'] == 1
        assert result['year_mismatch'] is False

    def test_a_game_released_years_after_this_one_is_flagged(self):
        with patch.object(hltb_lookup, '_search_hltb',
                          return_value=[_hit('Doom', year=2016)]):
            result = hltb_lookup.lookup_playtime('Doom', 'pc', year='1993')
        assert result['year_mismatch'] is True

    @pytest.mark.parametrize('game_year,result_year', [
        ('1987', 1985),     # a port comes after the original
        ('1987', 1988),     # one year out is a regional release
        (None, 2016),       # the game's year is not known
        ('1987', 0),        # the site's year is not known
    ])
    def test_ports_and_unknown_years_pass(self, game_year, result_year):
        with patch.object(hltb_lookup, '_search_hltb',
                          return_value=[_hit('Doom', year=result_year)]):
            result = hltb_lookup.lookup_playtime('Doom', 'pc', year=game_year)
        assert result['year_mismatch'] is False

    @pytest.mark.parametrize('date,year', [
        ('1987-05-01', '1987'), ('1987', '1987'), ('', None), (None, None),
        ('unknown', None),
    ])
    def test_release_year(self, date, year):
        assert hltb_lookup.release_year(date) == year


class TestClassify:
    def test_another_platform_is_queued_at_a_perfect_score(self):
        result = {'match_confidence': 100, 'platform_mismatch': True}
        assert classify_match(result, 'X', 95) == 'queue_platform'

    def test_another_year_is_queued_at_a_perfect_score(self):
        result = {'match_confidence': 100, 'year_mismatch': True}
        assert classify_match(result, 'X', 95) == 'queue_year'

    def test_a_clean_match_still_applies(self):
        result = {'match_confidence': 100, 'platform_mismatch': False,
                  'year_mismatch': False}
        assert classify_match(result, 'X', 95) == 'auto_apply'


def _game(db, title, folder='gb', estimate='Main: 9 hrs', match=None,
          platform='Game Boy', confidence=1.0, reviewed=0, alternate_titles=None):
    system = db.execute("SELECT id FROM systems WHERE folder = ?", (folder,)).fetchone()
    system_id = system['id'] if system else db.execute(
        "INSERT INTO systems (name, folder) VALUES (?, ?)", (folder, folder)).lastrowid
    game_id = db.execute(
        """INSERT INTO games (system_id, title, rom_path, playtime_estimate,
                              hltb_match_name, hltb_match_platform,
                              hltb_match_confidence, hltb_match_reviewed,
                              alternate_titles)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (system_id, title, f'{folder}/{title}.gb', estimate, match or title,
         platform, confidence, reviewed, alternate_titles)).lastrowid
    db.commit()
    return game_id


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(config, 'DB_PATH', path)
    yield conn
    conn.close()


class TestStoredCheck:
    def _reasons(self, db):
        return {r['game_id']: r['reason'] for r in db.execute(
            "SELECT game_id, reason FROM hltb_pending_matches")}

    def test_finds_a_stored_sequel_and_another_platform(self, db):
        from services.hltb_service import pending_queue
        sequel = _game(db, 'Double Dragon II', match='Double Dragon III')
        other = _game(db, 'Spider-Man 2', platform='Game Boy Advance')
        good = _game(db, 'Tetris')
        assert pending_queue.count_stored_suspects() == 2
        assert pending_queue.queue_stored_suspects() == 2
        reasons = self._reasons(db)
        assert reasons[sequel] == 'stored_title'
        assert reasons[other] == 'stored_platform'
        assert good not in reasons
        assert pending_queue.count_stored_suspects() == 0

    def test_a_match_through_an_alternate_title_is_not_suspect(self, db):
        from services.hltb_service import pending_queue
        _game(db, 'Action in New York', match='S.C.A.T.',
              alternate_titles='[{"title": "S.C.A.T."}]')
        assert pending_queue.count_stored_suspects() == 0

    def test_a_row_with_no_time_or_a_person_approved_is_left_alone(self, db):
        from services.hltb_service import pending_queue
        _game(db, 'Spider-Man 2', platform='PC', estimate=None)
        _game(db, 'Spider-Man 3', platform='PC', reviewed=1)
        assert pending_queue.count_stored_suspects() == 0

    def test_approving_keeps_the_time_and_stops_it_being_asked_again(self, db):
        from services.hltb_service import pending_queue
        game_id = _game(db, 'Spider-Man 2', platform='PC')
        pending_queue.queue_stored_suspects()
        pending_queue.approve_all('stored')
        row = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        assert row['playtime_estimate'] == 'Main: 9 hrs'
        assert row['hltb_match_reviewed'] == 1
        assert pending_queue.count_stored_suspects() == 0

    def test_rejecting_a_stored_match_clears_it(self, db):
        from services.hltb_service import pending_queue
        game_id = _game(db, 'Spider-Man 2', platform='PC')
        pending_queue.queue_stored_suspects()
        pending_id = db.execute("SELECT id FROM hltb_pending_matches").fetchone()['id']
        pending_queue.reject(pending_id)
        row = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        assert row['playtime_estimate'] is None
        assert row['hltb_match_name'] is None
        assert self._reasons(db) == {}

    def test_rejecting_a_new_match_leaves_the_stored_one(self, db):
        from services.hltb_service import pending_queue
        game_id = _game(db, 'Tetris')
        db.execute("""INSERT INTO hltb_pending_matches (game_id, match_name, reason)
                      VALUES (?, 'Tetris 2', 'wrong_platform')""", (game_id,))
        db.commit()
        assert pending_queue.reject_all('other_game') == 1
        row = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        assert row['playtime_estimate'] == 'Main: 9 hrs'

    def test_reject_all_clears_stored_rows_only_in_its_filter(self, db):
        from services.hltb_service import pending_queue
        stored = _game(db, 'Spider-Man 2', platform='PC')
        fresh = _game(db, 'Tetris')
        db.execute("""INSERT INTO hltb_pending_matches (game_id, match_name, reason)
                      VALUES (?, 'Tetris 2', 'low_confidence')""", (fresh,))
        db.commit()
        pending_queue.queue_stored_suspects()
        assert pending_queue.reject_all('stored') == 1
        rows = {r['id']: r['playtime_estimate'] for r in db.execute(
            "SELECT id, playtime_estimate FROM games")}
        assert rows[stored] is None
        assert rows[fresh] == 'Main: 9 hrs'
        assert set(self._reasons(db)) == {fresh}


class TestLookupWritesTheMatch:
    def test_a_saved_lookup_records_what_it_matched(self, db):
        from services.hltb_service import lookup_service
        game_id = _game(db, 'Tetris', estimate=None, match='Old', platform='PC')
        with patch.object(hltb_lookup, '_search_hltb',
                          return_value=[_hit('Tetris', 'Game Boy', 1989)]):
            lookup_service.lookup(game_id)
        row = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        assert row['playtime_estimate'] == 'Main: 10 hrs'
        assert row['hltb_match_name'] == 'Tetris'
        assert row['hltb_match_platform'] == 'Game Boy'
        assert row['hltb_match_confidence'] == 1.0


class TestMigration026:
    def test_repairs_the_scale_and_adds_the_column(self):
        import importlib
        import sqlite3
        migration = importlib.import_module(
            'services.migrations.scripts.026_hltb_match_reviewed')
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, hltb_match_confidence REAL)")
        conn.executemany("INSERT INTO games VALUES (?, ?)",
                         [(1, 72.0), (2, 100.0), (3, 1.09), (4, 0.87), (5, None)])
        migration.apply(conn)
        migration.apply(conn)
        values = dict(conn.execute("SELECT id, hltb_match_confidence FROM games"))
        assert values == {1: 0.72, 2: 1.0, 3: 1.0, 4: 0.87, 5: None}
        assert conn.execute("SELECT hltb_match_reviewed FROM games").fetchone()[0] == 0


class TestBulkJob:
    def _run(self, db, monkeypatch, results):
        from services.jobs.hltb_bulk import HLTBBulkLookupJob
        calls = []

        def lookup(title, system_folder=None, year=None, alternate_titles=None):
            calls.append((title, year))
            return results.get(title)

        monkeypatch.setattr(hltb_lookup, 'lookup_playtime', lookup)
        job = HLTBBulkLookupJob()
        job.only_missing = True
        job.confidence_threshold = 95
        job._worker()
        return calls

    def test_asks_with_the_year_and_retries_a_match_with_no_time(self, db, monkeypatch):
        game_id = _game(db, 'Tetris', estimate=None)
        db.execute("UPDATE games SET release_date = '1989-06-14' WHERE id = ?", (game_id,))
        _game(db, 'Contra')  # has a time: skipped
        db.commit()
        assert self._run(db, monkeypatch, {}) == [('Tetris', '1989')]

    def test_a_stop_from_the_site_ends_the_run(self, db, monkeypatch):
        from scraper import service_limits
        _game(db, 'Tetris', estimate=None)
        _game(db, 'Contra', estimate=None)
        real_stopped = service_limits.stopped
        monkeypatch.setattr(service_limits, 'stopped',
                            lambda source: real_stopped(source) or {'until': 0, 'reason': 'x'})
        calls = self._run(db, monkeypatch, {})
        assert len(calls) == 1

    def test_another_platform_waits_in_the_queue(self, db, monkeypatch):
        game_id = _game(db, 'Final Approach', estimate=None, match='Old')
        self._run(db, monkeypatch, {'Final Approach': {
            'match_name': 'Final Approach', 'match_confidence': 100,
            'match_platform': 'PC', 'platform_mismatch': True, 'main_story': 9.0}})
        row = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        assert row['playtime_estimate'] is None
        queued = db.execute("SELECT reason FROM hltb_pending_matches").fetchone()
        assert queued['reason'] == 'wrong_platform'


def test_analytics_counts_minutes_as_minutes(db):
    from services.analytics import _get_playtime_data
    _game(db, 'Short', estimate='Main: 36 mins')
    labels, data, average, count = _get_playtime_data()
    assert count == 1
    assert data[labels.index('< 5h')] == 1
    assert average == 0.6


class TestSearchAlternates:
    """The game page's search tries a game's other titles only for its own
    title: text a person types is searched as typed (walk 2026-11-04)."""

    def _search(self, db, typed):
        from services.hltb_service import lookup_service
        game_id = _game(db, 'Sonic the Hedgehog 3', folder='megadrive',
                        alternate_titles='[{"title": "Sonic 3"}]')
        seen = {}

        def lookup(title, system_folder=None, year=None, alternate_titles=None):
            seen['alts'] = alternate_titles
            return {'game_id': 1, 'match_name': title, 'match_confidence': 100}

        with patch.object(hltb_lookup, 'lookup_playtime', lookup):
            lookup_service.search(typed, 'megadrive', game_id=game_id)
        return seen['alts']

    def test_the_games_own_title_tries_its_other_titles(self, db):
        assert self._search(db, ' sonic the hedgehog 3 ') == ['Sonic 3']

    def test_typed_text_is_searched_as_typed(self, db):
        assert self._search(db, 'zzqx nonexistent game') is None
