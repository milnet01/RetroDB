"""PASS-59-242: scrapes, AI Fill and the edit paths keep what the user typed."""
import json
import os
import sqlite3

import pytest

from scraper import hybrid_scraper
from services import ai_fill, field_sources, normalization
from tests.test_pass59_205_esde_merge import library, later_source  # noqa: F401  (fixtures)


def _history(*items):
    return json.dumps([{'fields_filled': list(items)}])


def _scrape(force=False):
    return hybrid_scraper.apply_hybrid_metadata(1, 'esde', 'nothing', 'atari2600',
                                                fill_gaps=False, force_overwrite=force)


# --- 1. Tidying names never blanks or rewrites a stored value --------------------

def test_tidying_keeps_a_stored_value_it_has_no_name_for():
    metadata = {'genre': 'Zzz Unknown', 'players': 1, 'modes': 'Local Multiplayer'}
    normalization.canonicalize_metadata(metadata, keep={'genre', 'players', 'modes'})
    assert metadata == {'genre': 'Zzz Unknown', 'players': 1, 'modes': 'Local Multiplayer'}


def test_tidying_still_renames_a_stored_value():
    metadata = {'genre': 'Shmup'}
    normalization.canonicalize_metadata(metadata, keep={'genre'})
    assert metadata['genre'] == 'Shoot-em-up'


def test_a_scrape_keeps_stored_words_and_player_count(library):
    library.add_game(genre='Zzz Unknown', players=1, modes='Local Multiplayer')
    _scrape()
    row = library.row()
    assert (row['genre'], row['players'], row['modes']) == ('Zzz Unknown', 1, 'Local Multiplayer')


# --- 2. An edit made while a scrape runs is not written over ---------------------

def test_an_edit_made_during_a_scrape_stays(library, monkeypatch):
    library.add_game(publisher='Old')
    real = hybrid_scraper._log_date_disagreement

    def edit_meanwhile(metadata, game):
        conn = sqlite3.connect(library.db, timeout=5)
        conn.execute("UPDATE games SET publisher = 'New', developer = 'Typed' WHERE id = 1")
        conn.commit()
        conn.close()
        return real(metadata, game)
    monkeypatch.setattr(hybrid_scraper, '_log_date_disagreement', edit_meanwhile)
    _scrape()
    row = library.row()
    assert (row['publisher'], row['developer']) == ('New', 'Typed')


def test_a_scrape_keeps_its_own_tidy_of_missing_screenshots(library):
    # The scrape clears a missing file's link before it saves. Its own clear
    # is not an edit made meanwhile, so the shots still on disk stay linked.
    for name in ('a.png', 'b.png'):
        path = library.image('screenshots', name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'shot')
    library.add_game(screenshots='a.png,b.png,c.png')
    _scrape()
    assert library.row()['screenshots'] == 'a.png,b.png'


def test_a_full_rescrape_keeps_what_it_found_for_a_cleared_link(library, later_source):
    other = library.image('fanart', 'other.png')
    os.makedirs(os.path.dirname(other), exist_ok=True)
    with open(other, 'wb') as f:
        f.write(b'art')
    library.add_game(fanart='gone.png')
    hybrid_scraper.apply_hybrid_metadata(1, 'none', None, 'atari2600',
                                         fill_gaps=True, force_overwrite=True)
    assert library.row()['fanart'] == 'later_fanart.png'


# --- 3 and 4. AI Fill: an unchanged value is not "replaced"; a hand edit stays ---

def _ai_fill(monkeypatch, reply):
    monkeypatch.setattr('scraper.scrape_ai.get_game_details', lambda *a, **k: dict(reply))
    monkeypatch.setattr('scraper.hybrid_scraper.get_system_default_controller_name',
                        lambda system_id: None)
    ai_fill.fill_game(ai_fill.load_game(1))


def test_ai_fill_does_not_claim_a_value_it_only_wrote_differently(library, monkeypatch):
    library.add_game(players=4, genre='Racing, Action', scrape_history=_history('players (igdb)'))
    _ai_fill(monkeypatch, {'players': '1-4', 'genre': 'Action, Racing'})
    row = library.row()
    assert row['players'] == 4 and row['genre'] == 'Racing, Action'
    credits = field_sources.credits(row['scrape_history'])
    assert credits.get('players') == 'igdb' and 'genre' not in credits
    assert 'replaced' not in (row['scrape_history'] or '')


def test_ai_fill_leaves_a_hand_edited_value(library, monkeypatch):
    """User, 2026-11-04: AI Fill replaces only scraped values."""
    library.add_game(publisher='Typed By Hand', developer='Scraped Dev',
                     scrape_history=_history('publisher (manual)', 'developer (igdb)'))
    _ai_fill(monkeypatch, {'publisher': 'AI Pub', 'developer': 'AI Dev'})
    row = library.row()
    assert row['publisher'] == 'Typed By Hand'
    assert row['developer'] == 'AI Dev'


# --- 5. A typed controller beats the system default --------------------------------

def test_a_scrape_keeps_a_typed_controller(library, monkeypatch):
    monkeypatch.setattr(hybrid_scraper, 'get_system_default_controller_name', lambda sid: 'Joystick')
    library.add_game(controller_support='Paddle', scrape_history=_history('controller_support (manual)'))
    _scrape()
    assert library.row()['controller_support'] == 'Paddle'


def test_a_scrape_still_sets_the_default_over_a_scraped_controller(library, monkeypatch):
    monkeypatch.setattr(hybrid_scraper, 'get_system_default_controller_name', lambda sid: 'Joystick')
    library.add_game(controller_support='Gamepad', scrape_history=_history('controller_support (igdb)'))
    _scrape()
    assert library.row()['controller_support'] == 'Joystick'


def test_editing_any_validated_field_by_hand_is_credited():
    old = {'publisher': 'A', 'genre': 'RPG', 'controller_support': 'Joystick'}
    new = {'publisher': 'B', 'genre': 'RPG', 'controller_support': 'Paddle'}
    credits = field_sources.credits(field_sources.hand_edit_history('[]', old, new))
    assert credits == {'publisher': 'manual', 'controller_support': 'manual'}


# --- 9. A rating converted from an AI guess is a guess too --------------------------

def test_a_rating_converted_from_an_ai_guess_is_marked():
    game = {'esrb_rating': 'T', 'pegi_rating': 'PEGI 12',
            'scrape_history': _history('esrb_rating (AI)', 'pegi_rating (cross-map→PEGI)')}
    assert field_sources.ai_marks(game)['ratings'] == {'esrb_rating', 'pegi_rating'}


def test_a_rating_converted_from_an_official_one_is_not():
    game = {'esrb_rating': 'T', 'pegi_rating': 'PEGI 12', 'cero_rating': 'B',
            'scrape_history': _history('esrb_rating (igdb)', 'cero_rating (AI)',
                                       'pegi_rating (cross-map→PEGI)')}
    assert field_sources.ai_marks(game)['ratings'] == {'cero_rating'}


# --- 10. Clear Scraped Data clears every scraped multi-value field ------------------

def test_clear_scraped_data_clears_all_five_label_fields():
    from services.game_cleanup import _SCRAPED_FIELDS
    assert {'genre', 'modes', 'perspective', 'dimension', 'game_structure'} <= set(_SCRAPED_FIELDS)


# --- 6, 7 and 8. The game page's form, Reset and the CLZ import ----------------------

@pytest.fixture
def page_game(admin_test_client):
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT INTO systems (name, folder) VALUES ('P242', 'p242')")
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p242'").fetchone()[0]
    gid = conn.execute(
        "INSERT INTO games (system_id, title, rom_path, publisher, perspective, edition, "
        "alternate_titles, campaign) VALUES (?, 'Zelda', '/roms/p242/Zelda (USA).nes', 'Nintendo', "
        "'Top-Down', 'Gold', '[]', 'Story')", (sid,)).lastrowid
    conn.commit()
    client, csrf = admin_test_client()
    yield client, csrf, gid, conn
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def test_the_edit_form_keeps_fields_it_did_not_send(page_game):
    client, csrf, gid, conn = page_game
    client.post(f'/game/{gid}', data={'action': 'edit_metadata', 'edit_title': 'Zelda',
                                      'edit_publisher': 'Nintendo EAD', 'csrf_token': csrf},
                headers={'X-CSRF-Token': csrf})
    row = conn.execute("SELECT publisher, perspective, edition FROM games WHERE id = ?",
                       (gid,)).fetchone()
    assert row == ('Nintendo EAD', 'Top-Down', 'Gold')


def test_reset_clears_what_it_says(page_game):
    client, csrf, gid, conn = page_game
    client.post(f'/game/{gid}', data={'action': 'reset', 'csrf_token': csrf},
                headers={'X-CSRF-Token': csrf})
    row = conn.execute("SELECT publisher, perspective, edition, alternate_titles, campaign "
                       "FROM games WHERE id = ?", (gid,)).fetchone()
    assert row == (None, None, None, None, None)


def test_clz_keeps_a_year_as_a_year():
    from routes.clz_import import clz_release_date
    assert clz_release_date('2018') == '2018'
    assert clz_release_date('Nov 09, 2018') == '2018-11-09'
    assert clz_release_date('Jan 01, 2018') == '2018'
    assert clz_release_date('') is None
