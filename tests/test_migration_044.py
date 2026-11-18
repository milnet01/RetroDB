"""Migration 044 (PASS-59-202): games gain ss_region_checked, 0 for every row."""
import sqlite3

from tests.test_migration_015 import _load


def test_adds_ss_region_checked_defaulting_to_zero():
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO games DEFAULT VALUES")
    migration = _load('044_ss_region_checked')
    migration.apply(conn)
    migration.apply(conn)                      # runs twice without harm
    assert conn.execute("SELECT ss_region_checked FROM games").fetchall() == [(0,)]
