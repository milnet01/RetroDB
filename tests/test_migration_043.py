"""Migration 043 (PASS-59-262): games gain not_bonus_disc, 0 for every row."""
import sqlite3

from tests.test_migration_015 import _load


def test_adds_not_bonus_disc_defaulting_to_zero():
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, is_bonus_disc INTEGER)")
    conn.execute("INSERT INTO games (is_bonus_disc) VALUES (0)")
    migration = _load('043_not_bonus_disc')
    migration.apply(conn)
    migration.apply(conn)                      # runs twice without harm
    assert conn.execute("SELECT not_bonus_disc FROM games").fetchall() == [(0,)]
