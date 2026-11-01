"""PASS-59-204: the ROM's file name decides its region, ahead of the AI's guess.

Examples are real rows: `Fatal Run (USA).zip` was stored as Europe, with
`region (AI)` in its history. No test here reaches an AI.
"""
import json
import sqlite3

import pytest

import config
from scraper import hybrid_scraper
from scraper.scrape_esde import extract_region_from_filename
from services import ai_fill, game_cleanup, migrations

AI_GUESS = 'Japan'


def _history(*fields):
    return json.dumps([{'fields_filled': list(fields), 'scrape_mode': 'fill_missing'}])


@pytest.fixture
def library(tmp_path, monkeypatch):
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Atari 2600', 'atari2600')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, 'DB_PATH', path)
    monkeypatch.setattr('scraper.base_scraper.DB_PATH', path)
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path / 'images'))

    def add(game_id, rom, region=None, history=None):
        c = sqlite3.connect(path)
        c.execute("INSERT INTO games (id, system_id, title, rom_path, region, scrape_history) "
                  "VALUES (?, 1, ?, ?, ?, ?)",
                  (game_id, f'Game {game_id}', f'/roms/atari2600/{rom}', region, history))
        c.commit()
        c.close()

    def region(game_id):
        c = sqlite3.connect(path)
        found = c.execute("SELECT region FROM games WHERE id = ?", (game_id,)).fetchone()[0]
        c.close()
        return found

    return add, region


@pytest.fixture
def ai_turn(monkeypatch):
    """Stands in for the fallbacks: the AI answers for whatever is still empty."""
    asked = []

    def fake_fallbacks(metadata, result, *args, **kwargs):
        asked.append(not metadata['region'])
        if not metadata['region']:
            metadata['region'] = AI_GUESS
            result['filled_fields'].append('region (AI)')

    monkeypatch.setattr(hybrid_scraper, '_run_fallbacks', fake_fallbacks)
    monkeypatch.setattr(hybrid_scraper, 'load_scraper_settings',
                        lambda: {'region_options': ['USA', 'Europe', 'Japan', 'World']},
                        raising=False)
    return asked


def _scrape(game_id, force=False):
    result = hybrid_scraper.apply_hybrid_metadata(
        game_id, 'none', None, 'atari2600', fill_gaps=True, force_overwrite=force,
    )
    assert result.get('success', True) is not False, result
    return result


def test_file_name_beats_the_ai_and_the_ai_is_not_asked(library, ai_turn):
    add, region = library
    add(1, 'Fatal Run (USA).zip')

    result = _scrape(1)

    assert region(1) == 'USA'
    assert ai_turn == [False]
    assert 'region (filename)' in result['filled_fields']


def test_the_ai_still_answers_when_the_file_name_has_no_tag(library, ai_turn):
    add, region = library
    add(1, 'Fatal Run.zip')

    _scrape(1)

    assert region(1) == AI_GUESS
    assert ai_turn == [True]


def test_a_stored_region_stays_on_a_normal_scrape(library, ai_turn):
    add, region = library
    add(1, 'Fatal Run (USA).zip', region='Europe')

    _scrape(1)

    assert region(1) == 'Europe'


@pytest.mark.parametrize('stored, expected', [('Europe', 'Europe'), (None, 'USA')])
def test_full_rescrape_keeps_a_stored_region_and_never_asks_the_ai(library, ai_turn, stored, expected):
    add, region = library
    add(1, 'Fatal Run (USA).zip', region=stored)

    _scrape(1, force=True)

    assert region(1) == expected
    assert ai_turn == [False]


def test_a_language_tag_is_not_a_region():
    assert extract_region_from_filename('Game (En).zip') is None


def _ai_fill(monkeypatch, game, reply):
    monkeypatch.setattr('scraper.scrape_ai.get_game_details', lambda *a, **k: dict(reply))
    monkeypatch.setattr('scraper.hybrid_scraper.get_system_default_controller_name',
                        lambda system_id: None)
    return ai_fill.fill_game(game)


def test_ai_fill_cannot_write_region_over_a_tagged_file(library, monkeypatch):
    add, region = library
    add(1, 'Fatal Run (USA).zip')

    _ai_fill(monkeypatch, ai_fill.load_game(1),
             {'region': AI_GUESS, 'franchise': 'Fatal Run'})

    assert region(1) == 'USA'


def test_ai_fill_still_fills_region_for_an_untagged_file(library, monkeypatch):
    add, region = library
    add(1, 'Fatal Run.zip')

    _ai_fill(monkeypatch, ai_fill.load_game(1), {'region': AI_GUESS})

    assert region(1) == AI_GUESS


@pytest.fixture
def mixed(library):
    add, region = library
    ai = _history('region (AI)')
    add(1, 'Fatal Run (USA).zip', 'Europe', ai)             # fixed
    add(2, 'Dragon Defender (USA).zip', 'USA', ai)          # already right
    add(3, 'No Tag.zip', 'Japan', ai)                       # no tag to go by
    add(4, 'Sky Alien (USA).zip', 'Europe', _history('region (ES-DE)'))  # not the AI's
    add(5, 'Tuby Bird (USA).zip', 'Europe', None)           # no history
    add(6, 'Both (USA, Europe).zip', 'Europe', ai)          # one of the file's two
    add(7, 'Other (Japan).zip', 'North America', ai)        # fixed
    add(8, 'Same (USA, Europe).zip', 'USA/Europe', ai)      # already the file's own value
    return region


def test_count_is_only_the_ai_rows_that_disagree(mixed):
    assert game_cleanup.count_ai_region_mismatches() == 2


def test_fix_changes_only_those_rows(mixed):
    assert game_cleanup.fix_ai_region_mismatches() == 2

    assert [mixed(i) for i in range(1, 9)] == [
        'USA', 'USA', 'Japan', 'Europe', 'Europe', 'Europe', 'Japan', 'USA/Europe',
    ]
    assert game_cleanup.count_ai_region_mismatches() == 0


def test_routes_report_the_count_then_fix(mixed, admin_test_client):
    client, csrf = admin_test_client()

    assert client.get('/api/maintenance/file-regions/preview').get_json()['count'] == 2

    reply = client.post('/api/maintenance/file-regions/fix', json={},
                        headers={'X-CSRF-Token': csrf})
    assert reply.get_json()['fixed'] == 2
    assert mixed(1) == 'USA'
