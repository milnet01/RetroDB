# =============================================================================
# Migration 031 — HowLongToBeat's own game ID and how many players timed it
# =============================================================================
# PASS-59-216. The ID links a saved match to its page. The count shows how far
# to trust a time. A saved match stays empty until it is next looked up.
# =============================================================================

from services.migrations._helpers import _has_column


def apply(conn):
    c = conn.cursor()
    for table, column in (('games', 'hltb_id'), ('games', 'hltb_players'),
                          ('hltb_pending_matches', 'players')):
        if not _has_column(c, table, column):
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER")
