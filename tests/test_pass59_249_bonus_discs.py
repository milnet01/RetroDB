"""PASS-59-249: a bonus disc link can never form a loop."""
import os
import sqlite3

import pytest


@pytest.fixture
def discs(admin_test_client):
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Test 249 F', 'p249f_sys')")
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'p249f_sys'").fetchone()[0]

    def add(title, **cols):
        cols = {'system_id': sid, 'title': title, 'rom_path': f'/roms/p249f/{title}.iso', **cols}
        gid = conn.execute(f"INSERT INTO games ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           tuple(cols.values())).lastrowid
        conn.commit()
        return gid
    client, csrf = admin_test_client()
    yield client, csrf, add, conn, sid
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def _link(client, csrf, bonus, parent):
    return client.post('/api/bonus-discs/link', json={'bonus_id': bonus, 'parent_id': parent},
                       headers={'X-CSRF-Token': csrf})


def test_a_disc_cannot_be_its_own_parent(discs):
    client, csrf, add, _, _ = discs
    game = add('Saga')
    assert _link(client, csrf, game, game).status_code == 400


def test_the_parent_cannot_be_a_bonus_disc(discs):
    client, csrf, add, _, _ = discs
    main = add('Saga')
    extra = add('Saga Bonus', is_bonus_disc=1)
    extra_parent = add('Saga Extras')
    _link(client, csrf, extra, main)
    assert _link(client, csrf, extra_parent, extra).status_code == 400


def test_a_game_with_bonus_discs_cannot_become_one(discs):
    client, csrf, add, conn, _ = discs
    main = add('Saga')
    other = add('Saga Two')
    extra = add('Saga Bonus Disc')
    assert _link(client, csrf, extra, main).status_code == 200
    assert _link(client, csrf, main, other).status_code == 400
    assert conn.execute("SELECT is_bonus_disc FROM games WHERE id = ?", (main,)).fetchone()[0] in (0, None)


def test_auto_link_never_picks_a_disc_it_marks_in_the_same_sweep(discs):
    # Discs were marked one at a time, so a parent picked early could be
    # marked a bonus disc later in the same sweep.
    client, csrf, add, conn, sid = discs
    first = add('Saga (Bonus Disc)')            # its base title is "Saga"
    second = add('Saga (Bonus Disc) Making Of')  # a title LIKE 'Saga%' — and itself a bonus disc
    reply = client.post(f'/api/bonus-discs/auto-link?system_id={sid}', headers={'X-CSRF-Token': csrf})
    assert reply.status_code == 200, reply.get_json()
    rows = dict(conn.execute("SELECT id, parent_game_id FROM games WHERE system_id = ?", (sid,)).fetchall())
    bonus = {r[0] for r in conn.execute("SELECT id FROM games WHERE system_id = ? AND is_bonus_disc = 1", (sid,))}
    assert not any(parent in bonus for parent in rows.values() if parent)


# PASS-59-262: a person's "not a bonus disc" outlasts the next auto-link.

def _auto_link(client, csrf, sid):
    reply = client.post(f'/api/bonus-discs/auto-link?system_id={sid}', headers={'X-CSRF-Token': csrf})
    assert reply.status_code == 200, reply.get_json()


def _is_bonus(conn, gid):
    return conn.execute("SELECT is_bonus_disc FROM games WHERE id = ?", (gid,)).fetchone()[0] == 1


def test_auto_link_leaves_alone_a_disc_the_user_unlinked(discs):
    client, csrf, add, conn, sid = discs
    add('Quest')
    disc = add('Quest (Bonus Disc)')
    _auto_link(client, csrf, sid)
    assert _is_bonus(conn, disc)
    assert client.post(f'/api/bonus-discs/unlink/{disc}', headers={'X-CSRF-Token': csrf}).status_code == 200
    _auto_link(client, csrf, sid)
    assert not _is_bonus(conn, disc)


def test_auto_link_leaves_alone_a_disc_the_user_unmarked(discs):
    client, csrf, add, conn, sid = discs
    disc = add('Quest (Bonus Disc)', is_bonus_disc=1)
    reply = client.post('/api/bonus-discs/mark', json={'game_id': disc, 'is_bonus': False},
                        headers={'X-CSRF-Token': csrf})
    assert reply.status_code == 200
    _auto_link(client, csrf, sid)
    assert not _is_bonus(conn, disc)


def test_a_manual_link_or_mark_clears_the_users_no(discs):
    client, csrf, add, conn, sid = discs
    main = add('Quest')
    disc = add('Quest (Bonus Disc)')
    other = add('Quest (Making Of Disc)', is_bonus_disc=1)
    for gid in (disc, other):
        client.post('/api/bonus-discs/mark', json={'game_id': gid, 'is_bonus': False},
                    headers={'X-CSRF-Token': csrf})
    assert _link(client, csrf, disc, main).status_code == 200
    client.post('/api/bonus-discs/mark', json={'game_id': other, 'is_bonus': True},
                headers={'X-CSRF-Token': csrf})
    flags = conn.execute("SELECT not_bonus_disc FROM games WHERE id IN (?, ?)", (disc, other)).fetchall()
    assert [f[0] for f in flags] == [0, 0]
