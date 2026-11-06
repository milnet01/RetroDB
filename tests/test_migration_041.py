"""Migration 041 (PASS-59-260): only the link to the game the PSN import made
for a title counts as set by hand; every other old link is checked again."""
import sqlite3

from tests.test_migration_015 import _load


def test_only_the_psn_import_link_counts_as_set_by_hand():
    conn = sqlite3.connect(':memory:')
    conn.executescript("""
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, rom_path TEXT);
        CREATE TABLE psn_games (npwr_id TEXT, user_id INTEGER, linked_game_id INTEGER);
        INSERT INTO games VALUES (1, 'EA SPORTS FC 25', 'psn_import/ps5/NPWR41872_00'),
                                 (2, 'D', '/roms/psx/D (USA).m3u'),
                                 (3, 'Madden NFL 24', 'psn_import/ps5/NPWR38000_00');
        INSERT INTO psn_games VALUES ('NPWR41872_00', 1, 1),   -- the import's own game
                                     ('NPWR11111_00', 1, 2),   -- the old matcher's guess
                                     ('NPWR39854_00', 1, 3),   -- another title's import
                                     ('NPWR22222_00', 1, NULL);
    """)
    migration = _load('041_psn_hand_links')
    migration.apply(conn)
    migration.apply(conn)                      # runs twice without harm
    rows = conn.execute("SELECT npwr_id, link_set_by_hand FROM psn_games ORDER BY npwr_id").fetchall()
    assert rows == [('NPWR11111_00', 0), ('NPWR22222_00', 0),
                    ('NPWR39854_00', 0), ('NPWR41872_00', 1)]
