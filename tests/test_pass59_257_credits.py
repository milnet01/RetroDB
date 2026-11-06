"""PASS-59-257: a scrape credits only what it wrote, the edit form credits only
what a person typed, and AI Fill keeps an edit made while it waits."""
import json
import sqlite3

from scraper import hybrid_scraper
from services import ai_fill, field_sources
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (fixture)
from tests.test_pass59_242_user_edits import _ai_fill, _history, _scrape, page_game  # noqa: F401


def _edit_row(db, sql):
    conn = sqlite3.connect(db, timeout=5)
    conn.execute(sql)
    conn.commit()
    conn.close()


# --- 1. A field the save check drops is not credited to the scrape -----------------

def test_a_scrape_does_not_credit_a_field_it_did_not_write(library, monkeypatch):
    library.add_game()
    real = hybrid_scraper._log_date_disagreement

    def edit_meanwhile(metadata, game):
        _edit_row(library.db, "UPDATE games SET controller_support = 'Typed' WHERE id = 1")
        return real(metadata, game)
    monkeypatch.setattr(hybrid_scraper, '_log_date_disagreement', edit_meanwhile)
    result = _scrape()
    row = library.row()
    assert row['controller_support'] == 'Typed'
    credits = field_sources.credits(row['scrape_history'])
    assert 'controller_support' not in credits
    assert credits.get('region') == 'filename'
    assert not any(f.startswith('controller_support ') for f in result['filled_fields'])


# --- 2. The edit form credits only what the person typed ---------------------------

def test_the_edit_form_leaves_an_empty_player_count_empty(page_game):
    client, csrf, gid, conn = page_game
    page = client.get(f'/game/{gid}').get_data(as_text=True)
    field = page.split('id="edit_players"', 1)[1].split('/>', 1)[0]
    assert 'value=""' in field


def test_a_rating_the_form_converts_is_not_credited_as_typed(page_game):
    client, csrf, gid, conn = page_game
    client.post(f'/game/{gid}', data={'action': 'edit_metadata', 'edit_title': 'Zelda',
                                      'edit_esrb_rating': 'E', 'edit_pegi_rating': '',
                                      'edit_players': '', 'csrf_token': csrf},
                headers={'X-CSRF-Token': csrf})
    pegi, players, history = conn.execute(
        "SELECT pegi_rating, players, scrape_history FROM games WHERE id = ?", (gid,)).fetchone()
    assert pegi and players is None
    credits = field_sources.credits(history)
    assert credits.get('esrb_rating') == 'manual'
    assert 'pegi_rating' not in credits and 'players' not in credits


def test_the_json_edit_credits_only_what_was_typed(page_game):
    client, csrf, gid, conn = page_game
    client.post(f'/api/game/{gid}/edit', json={'esrb_rating': 'E', 'pegi_rating': ''},
                headers={'X-CSRF-Token': csrf})
    history = conn.execute("SELECT scrape_history FROM games WHERE id = ?", (gid,)).fetchone()[0]
    credits = field_sources.credits(history)
    assert credits.get('esrb_rating') == 'manual' and 'pegi_rating' not in credits


# --- 3. AI Fill keeps a hand-set Exclusive ------------------------------------------

def test_ai_fill_keeps_a_hand_set_exclusive(library, monkeypatch):
    library.add_game(other_platforms='Exclusive',
                     scrape_history=_history('other_platforms (manual)'))
    _ai_fill(monkeypatch, {'other_platforms': 'PC, Amiga'})
    assert library.row()['other_platforms'] == 'Exclusive'


def test_ai_fill_still_replaces_a_scraped_exclusive(library, monkeypatch):
    library.add_game(other_platforms='Exclusive',
                     scrape_history=_history('other_platforms (igdb)'))
    _ai_fill(monkeypatch, {'other_platforms': 'PC, Amiga'})
    assert library.row()['other_platforms'] == 'Amiga, PC'


# --- 4. AI Fill keeps an edit made while it waited for the AI ------------------------

def test_ai_fill_keeps_an_edit_made_while_it_waited(library, monkeypatch):
    library.add_game(developer='Scraped Dev', scrape_history=_history('developer (igdb)'))
    typed = json.dumps([{'fields_filled': ['developer (igdb)']},
                        {'fields_filled': ['developer (manual)']}])

    def answer_after_an_edit(*args, **kwargs):
        _edit_row(library.db, f"UPDATE games SET developer = 'Typed', "
                              f"scrape_history = '{typed}' WHERE id = 1")
        return {'developer': 'AI Dev', 'publisher': 'AI Pub'}
    monkeypatch.setattr('scraper.scrape_ai.get_game_details', answer_after_an_edit)
    monkeypatch.setattr('scraper.hybrid_scraper.get_system_default_controller_name',
                        lambda system_id: None)
    ai_fill.fill_game(ai_fill.load_game(1))
    row = library.row()
    assert row['developer'] == 'Typed' and row['publisher'] == 'AI Pub'
    credits = field_sources.credits(row['scrape_history'])
    assert credits.get('developer') == 'manual' and credits.get('publisher') == 'AI'
