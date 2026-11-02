"""PASS-59-211: AI answers are checked, and the game page says what is a guess.
The examples are the ones the PASS-59-162 review found."""
import json
import sqlite3

import pytest

from scraper import metadata_merger, scrape_ai
from services import field_sources


@pytest.mark.parametrize('value,expected', [
    ('85', '85'), (85, '85'), ('85/100', '85'), ('85%', '85'), ('8.5/10', '85'),
    ('4.2/5', '84'), ('~72', '72'), ('8.5', ''), ('7', ''), (7, ''), ('4.2', ''),
    ('850', ''), ('0', ''), ('great', ''), ('5/0', ''), (None, ''),
])
def test_score_scale(value, expected):
    assert scrape_ai._validate_field('critic_score', value) == expected


@pytest.mark.parametrize('value,expected', [
    ('2.4 million', 2400000), ('2,400,000', 2400000), ('~850k', 850000),
    ('over 1 million', 1000000), (2400000, 2400000),
    ('1-2 million', None), ('3.5-4 million', None), ('1 to 2 million', None),
    ('2.4', None), ('3', None), (12.5, None), ('5 million dollars', None),
    ('$5 million', None),
])
def test_sales_figure(value, expected):
    assert scrape_ai.parse_units_sold(value) == expected


def test_list_answers_are_joined():
    assert scrape_ai._validate_field('developer', ['Sega', 'AM2']) == 'Sega, AM2'
    assert scrape_ai._validate_field('modes', ['Single-Player']) == 'Single-Player'
    assert scrape_ai._validate_field('similar_games', ['Tetris', 'Columns']) == 'Tetris, Columns'


@pytest.mark.parametrize('word', ['None', 'N/A', 'null', 'Unknown'])
def test_placeholder_answers_are_dropped(word):
    assert scrape_ai._validate_field('developer', word) == ''
    assert scrape_ai._validate_field('franchise', word) == ''


@pytest.mark.parametrize('system,given,left', [
    ('Sega Mega Drive', 'Genesis, Mega Drive, SNES', 'SNES'),
    ('Nintendo Entertainment System', 'NES, SNES', 'SNES'),
    ('Sony PlayStation 2', 'PlayStation 2', ''),
    ('Some Unknown System', 'SNES', 'SNES'),
])
def test_own_platform_is_removed(system, given, left):
    assert scrape_ai._drop_own_platform(given, system) == left


def test_prompt_does_not_claim_a_search_it_cannot_do():
    with_tool = scrape_ai._build_prompt('Doom', 'SNES', ['critic_score'])
    without = scrape_ai._build_prompt('Doom', 'SNES', ['critic_score'], can_search=False)
    assert 'no web search' not in with_tool
    assert 'You have no web search here' in without


def test_prompt_allows_the_rating_guess_it_asks_for():
    prompt = scrape_ai._build_prompt('Doom', 'SNES', ['pegi_rating'])
    assert 'Rate based on game content' in prompt
    assert 'Age ratings are the one exception' in prompt


# --- Merging -----------------------------------------------------------------

def _merge(metadata, ai_data):
    result = {'filled_fields': []}
    metadata_merger.apply_ai_to_metadata(metadata, ai_data, 1, result, fill_only=True)
    return result['filled_fields']


def test_count_is_not_written_beside_another_sources_score():
    metadata = {'user_score': 50, 'user_score_count': None}
    filled = _merge(metadata, {'user_score': '60', 'user_score_count': '8'})
    assert metadata == {'user_score': 50, 'user_score_count': None}
    assert filled == []


def test_count_without_a_score_is_not_written():
    metadata = {'critic_score': None, 'critic_score_count': None}
    _merge(metadata, {'critic_score_count': '16'})
    assert metadata['critic_score_count'] is None


def test_score_and_count_are_written_together():
    metadata = {'critic_score': None, 'critic_score_count': None, 'units_sold': None}
    filled = _merge(metadata, {'critic_score': '66', 'critic_score_count': '16', 'units_sold': '5000'})
    assert metadata == {'critic_score': 66, 'critic_score_count': 16, 'units_sold': 5000}
    assert set(filled) == {'critic_score (AI)', 'critic_score_count (AI)', 'units_sold (AI)'}


def test_save_type_is_not_guessed_for_cartridges():
    from scraper.hybrid_scraper import detect_save_type
    assert detect_save_type('snes', 'x') is None
    assert detect_save_type('atari2600', 'x') is None
    assert detect_save_type('psx', 'x') == 'Memory Card'


# --- What the page marks ------------------------------------------------------

def _history(*items):
    return json.dumps([{'fields_filled': list(items)}])


def test_ai_rating_is_marked_and_a_scraped_one_is_not():
    game = {'esrb_rating': 'E', 'pegi_rating': 'PEGI 3', 'cero_rating': 'A',
            'scrape_history': _history('esrb_rating (AI)', 'pegi_rating (ScreenScraper)')}
    assert field_sources.ai_marks(game)['ratings'] == {'esrb_rating'}


def test_inferred_ratings_are_marked():
    game = {'usk_rating': 'USK 6',
            'scrape_history': _history('ratings (inferred from content)')}
    assert field_sources.ai_marks(game)['ratings'] == {'usk_rating'}


def test_newest_credit_decides():
    history = json.dumps([{'fields_filled': ['esrb_rating (AI)']},
                          {'fields_filled': ['esrb_rating (IGDB)']}])
    assert field_sources.ai_marks({'esrb_rating': 'E', 'scrape_history': history})['ratings'] == set()


def test_ai_count_is_hidden_beside_another_sources_score():
    game = {'user_score': 50, 'user_score_count': 8,
            'scrape_history': _history('user_score (ScreenScraper)', 'user_score_count (AI)')}
    marks = field_sources.ai_marks(game)
    assert marks['user_score'] is False and marks['user_score_count'] is None


def test_ai_count_stays_with_an_ai_score():
    game = {'critic_score': 66, 'critic_score_count': 16,
            'scrape_history': _history('critic_score (AI)', 'critic_score_count (AI)')}
    marks = field_sources.ai_marks(game)
    assert marks['critic_score'] is True and marks['critic_score_count'] == 16


def test_broken_history_marks_nothing():
    assert field_sources.ai_marks({'esrb_rating': 'E', 'scrape_history': 'not json'})['ratings'] == set()


def test_every_board_has_a_start_year():
    from services.game_utils import RATING_SYSTEMS
    assert all(isinstance(b['started'], int) for b in RATING_SYSTEMS.values())
    assert field_sources.rating_board_starts({'pegi_rating', 'esrb_rating'}) == ['ESRB 1994', 'PEGI 2003']


def test_hand_edit_removes_the_mark():
    history = _history('esrb_rating (AI)')
    changed = field_sources.hand_edit_history(history, {'esrb_rating': 'E'}, {'esrb_rating': 'T'})
    assert field_sources.ai_marks({'esrb_rating': 'T', 'scrape_history': changed})['ratings'] == set()


def test_saving_an_unchanged_form_keeps_the_mark():
    old = {'esrb_rating': 'E', 'pegi_rating': None, 'units_sold': 5000}
    new = {'esrb_rating': 'E', 'pegi_rating': '', 'units_sold': '5000', 'title': 'Other'}
    assert field_sources.hand_edit_history('[]', old, new) is None


# --- Through the app ----------------------------------------------------------

@pytest.fixture
def game(admin_test_client):
    import os
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Sinclair ZX Spectrum', 'ai211_zx')")
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'ai211_zx'").fetchone()[0]
    gid = conn.execute(
        "INSERT INTO games (system_id, title, rom_path, esrb_rating, pegi_rating, critic_score, "
        "critic_score_count, scrape_history) VALUES (?, 'OutRun', '/roms/o.z80', 'E', 'PEGI 3', 66, 16, ?)",
        (sid, _history('esrb_rating (AI)', 'pegi_rating (AI)', 'critic_score (AI)'))).lastrowid
    conn.commit()
    client, csrf = admin_test_client()
    yield client, csrf, gid, conn
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def test_game_page_says_it_is_a_guess_and_when_boards_started(game):
    client, _, gid, _ = game
    html = client.get(f'/game/{gid}').get_data(as_text=True)
    assert 'class="ai-guess-note"' in html
    assert 'based on the game' in html
    assert 'ESRB 1994, PEGI 2003' in html
    assert html.count('AI guess</span>') == 2
    assert 'From the AI, not checked' in html


def test_editing_a_rating_in_the_app_removes_its_mark(game):
    client, csrf, gid, _ = game
    reply = client.post(f'/api/game/{gid}/edit', json={'esrb_rating': 'T', 'pegi_rating': 'PEGI 3'},
                        headers={'X-CSRF-Token': csrf})
    assert reply.status_code == 200
    html = client.get(f'/game/{gid}').get_data(as_text=True)
    assert 'PEGI 2003' in html and 'ESRB 1994' not in html
    assert html.count('AI guess</span>') == 1


def test_bulk_edit_removes_the_mark(game):
    client, csrf, gid, conn = game
    reply = client.post('/api/games/bulk-edit', json={'game_ids': [gid], 'fields': {'esrb_rating': 'T'}},
                        headers={'X-CSRF-Token': csrf})
    assert reply.status_code == 200
    history = conn.execute("SELECT scrape_history FROM games WHERE id = ?", (gid,)).fetchone()[0]
    assert field_sources.credits(history)['esrb_rating'] == 'manual'
