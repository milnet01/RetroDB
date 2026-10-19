"""Shared fixture for the PASS-59-106 regional-versions tests.

Works on the throwaway schema conftest points RETRODB_DB_PATH at. Each test
gets two fresh systems; everything it creates is removed afterwards.
"""
import json
import os
import sqlite3
from itertools import count
from types import SimpleNamespace

import pytest

_seq = count()


@pytest.fixture
def vdb():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (1, 'admin-stub', 'x', 'admin')")
    n = next(_seq)
    sids = []
    for side in ('a', 'b'):
        folder = f'p59106{side}{n}'
        conn.execute("INSERT INTO systems (name, folder) VALUES (?, ?)", (folder, folder))
        sids.append(conn.execute("SELECT id FROM systems WHERE folder = ?", (folder,)).fetchone()[0])
    conn.commit()

    def game(title, rom=None, sid=None, alt=None, **cols):
        sid = sid or sids[0]
        cols = {'rom_path': f'/roms/p59106/{rom or title + " (USA).zip"}', **cols}
        if alt is not None:
            cols['alternate_titles'] = json.dumps(alt)
        names = ', '.join(cols)
        cur = conn.execute(
            f"INSERT INTO games (system_id, title, {names}) "
            f"VALUES (?, ?, {', '.join('?' * len(cols))})",
            (sid, title, *cols.values()))
        conn.commit()
        return cur.lastrowid

    def group_of(game_id):
        return conn.execute("SELECT version_group_id FROM games WHERE id = ?",
                            (game_id,)).fetchone()[0]

    def orphan_groups():
        return conn.execute(
            "SELECT COUNT(*) FROM version_groups WHERE id NOT IN "
            "(SELECT version_group_id FROM games WHERE version_group_id IS NOT NULL)"
        ).fetchone()[0]

    yield SimpleNamespace(conn=conn, sid=sids[0], sid2=sids[1], game=game,
                          group_of=group_of, orphan_groups=orphan_groups)
    for sid in sids:
        conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
        conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.execute("DELETE FROM version_groups")
    conn.commit()
    conn.close()
