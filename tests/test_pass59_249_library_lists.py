"""PASS-59-249: Library lists, Select all and bulk edit (audit 2026-11-04 lows)."""
import os
import sqlite3

import pytest


@pytest.fixture
def library(admin_test_client):
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Test 249', 'p249_sys')")
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p249_sys'").fetchone()[0]
    ids = [conn.execute("INSERT INTO games (system_id, title, rom_path, genre) VALUES (?, ?, ?, 'Puzzle')",
                        (sid, title, f'/roms/p249/{title}.zip')).lastrowid
           for title in ('Alpha', 'Beta')]
    conn.commit()
    client, csrf = admin_test_client()
    yield client, csrf, ids, conn
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def _bulk(client, csrf, body):
    return client.post('/api/games/bulk-edit', json=body, headers={'X-CSRF-Token': csrf})


@pytest.mark.parametrize('ids', ['12', [1, 'x'], [True], 5])
def test_bulk_edit_refuses_ids_that_are_not_a_list_of_numbers(library, ids):
    # A string id was walked character by character: "12" edited games 1 and 2.
    client, csrf, _, _ = library
    reply = _bulk(client, csrf, {'game_ids': ids, 'fields': {'publisher': 'X'}})
    assert reply.status_code == 400


def test_bulk_edit_string_id_edits_no_other_game(library):
    client, csrf, (a, b), conn = library
    _bulk(client, csrf, {'game_ids': f'{a}{b}', 'fields': {'publisher': 'Wrong'}})
    rows = conn.execute("SELECT publisher FROM games WHERE id IN (?, ?)", (a, b)).fetchall()
    assert [r[0] for r in rows] == [None, None]


def test_bulk_edit_append_with_a_number_is_refused_not_a_crash(library):
    client, csrf, ids, conn = library
    conn.execute("UPDATE games SET genre = 'Puzzle' WHERE id = ?", (ids[0],))
    conn.commit()
    reply = _bulk(client, csrf, {'game_ids': ids, 'fields': {'genre': 5},
                                 'field_modes': {'genre': 'append'}})
    assert reply.status_code == 400


def test_bulk_edit_credits_nobody_when_the_save_fails(library, monkeypatch):
    # The hand-edit credit was written per game before the transaction, so a
    # failed save still marked the games as edited by a person.
    import routes.games as games_routes
    client, csrf, ids, conn = library

    def _boom(_current):
        raise RuntimeError('save failed')
    monkeypatch.setattr(games_routes, 'cross_map_ratings', _boom)
    reply = _bulk(client, csrf, {'game_ids': ids, 'fields': {'esrb_rating': 'T'}})
    assert reply.status_code == 500
    rows = conn.execute("SELECT scrape_history, esrb_rating FROM games WHERE id IN (?, ?)", ids).fetchall()
    assert rows == [(None, None), (None, None)]


# --- Lists hide BIOS sets and fold regional versions ---------------------------

def _add(conn, title, **cols):
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p249_sys'").fetchone()[0]
    cols = {'system_id': sid, 'title': title, 'rom_path': f'/roms/p249/{title}.zip', **cols}
    gid = conn.execute(f"INSERT INTO games ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       tuple(cols.values())).lastrowid
    conn.commit()
    return gid


def test_console_page_counts_and_letters_leave_out_bios(library):
    client, _, _, conn = library
    _add(conn, 'Zbios', arcade_category='BIOS', scraped=0)
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p249_sys'").fetchone()[0]
    html = client.get(f'/system/{sid}').get_data(as_text=True)
    assert 'window.AVAILABLE_LETTERS = ["A", "B"]' in html
    assert '2 games in your collection' in html


def test_library_page_counts_leave_out_bios(library):
    client, _, _, conn = library

    def total():
        html = client.get('/games').get_data(as_text=True)
        return html.split('window.TOTAL_GAMES = ')[1].split(';')[0]
    before = total()
    _add(conn, 'Zbios', arcade_category='BIOS')
    assert total() == before


def test_similar_games_leave_out_own_versions_and_keep_null_bonus_rows(library):
    client, _, (a, b), conn = library
    conn.execute("UPDATE games SET franchise = 'Saga', version_group_id = 900249 WHERE id = ?", (a,))
    conn.execute("UPDATE games SET franchise = 'Saga', is_bonus_disc = NULL WHERE id = ?", (b,))
    conn.commit()
    own_jp = _add(conn, 'Alpha JP', franchise='Saga', version_group_id=900249)
    bios = _add(conn, 'Saga BIOS', franchise='Saga', arcade_category='BIOS')
    found = {g['id'] for g in client.get(f'/api/games/{a}/similar').get_json()['games']}
    assert own_jp not in found and bios not in found
    assert b in found


def test_filter_popup_leaves_out_bonus_bios_and_extra_versions(library):
    client, _, (a, b), conn = library
    conn.execute("UPDATE games SET publisher = 'Pub249', version_group_id = 900250 WHERE id = ?", (a,))
    conn.commit()
    _add(conn, 'Alpha JP', publisher='Pub249', version_group_id=900250)
    _add(conn, 'Alpha Bonus', publisher='Pub249', is_bonus_disc=1)
    _add(conn, 'Pub BIOS', publisher='Pub249', arcade_category='BIOS')
    reply = client.get('/api/filter-games?type=publisher&value=Pub249').get_json()
    titles = sorted(row['title'] for row in reply['games'])
    assert len(titles) == 1 and titles[0].startswith('Alpha')


# --- Select all and the card refresh ---------------------------------------------

def test_select_all_says_when_the_list_was_cut(library, monkeypatch):
    import config
    client, _, _, conn = library
    monkeypatch.setattr(config, 'MAX_LIST_ROWS', 1)  # Select all's cap: 20 rows
    for n in range(19):
        _add(conn, f'Extra {n:02d}')
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p249_sys'").fetchone()[0]
    reply = client.get(f'/api/games/ids?system={sid}').get_json()
    assert len(reply['ids']) == 20
    assert reply['total'] == 21 and reply['truncated'] is True


def test_card_refresh_sees_new_achievement_progress(library):
    client, _, (a, _), conn = library
    etag = client.get(f'/api/games/card-data?ids={a}').headers['ETag']
    conn.execute("INSERT INTO game_achievement_progress (game_id, user_id, earned_achievements, "
                 "total_achievements) VALUES (?, 1, 3, 10)", (a,))
    conn.commit()
    try:
        again = client.get(f'/api/games/card-data?ids={a}', headers={'If-None-Match': etag})
        assert again.status_code == 200
    finally:
        conn.execute("DELETE FROM game_achievement_progress WHERE game_id = ?", (a,))
        conn.commit()


def test_card_refresh_still_answers_304_when_nothing_changed(library):
    client, _, (a, _), _ = library
    etag = client.get(f'/api/games/card-data?ids={a}').headers['ETag']
    assert client.get(f'/api/games/card-data?ids={a}', headers={'If-None-Match': etag}).status_code == 304


def test_full_card_query_needs_a_user():
    # Without a user the progress joins took every user's rows (one card per user).
    from services.game_query import _build_games_query
    with pytest.raises(ValueError):
        _build_games_query({})
    _build_games_query({}, count_only=True)
    _build_games_query({}, ids_only=True)


# --- A page that fails shows the error page, not the error's text ------------------

@pytest.mark.parametrize('module,url', [
    ('routes.games', '/games'),
    ('routes.games', '/game/1'),
    ('routes.systems', '/systems'),
    ('routes.systems', '/system/1'),
    ('routes.settings', '/settings'),
])
def test_page_error_does_not_echo_the_exception(module, url, admin_test_client, monkeypatch):
    import importlib
    mod = importlib.import_module(module)

    def _boom(*_a, **_k):
        raise RuntimeError('<script>leak</script>')
    monkeypatch.setattr(mod, 'query', _boom)
    client, _ = admin_test_client()
    reply = client.get(url)
    assert reply.status_code == 500
    assert '<script>leak' not in reply.get_data(as_text=True)
