# =============================================================================
# Migration 026 — games.hltb_match_reviewed, and match scores on one scale
# =============================================================================
# PASS-59-209. A person approved this HowLongToBeat match when the new column is
# 1, so "Check Saved Play Times" does not ask about it again.
#
# Scores are 0 to 1, but some old rows hold 72.0 for 72%, and the game page caps
# those at "100% match". Values above 1.5 can only be percentages; the few from
# 1 to 1.5 are capped. Older values are not kept.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    _add_column_if_missing(cursor, 'games', 'hltb_match_reviewed', 'INTEGER NOT NULL DEFAULT 0')
    cursor.execute("""
        UPDATE games SET hltb_match_confidence = CASE
            WHEN hltb_match_confidence > 1.5 THEN hltb_match_confidence / 100.0
            ELSE 1.0 END
        WHERE hltb_match_confidence > 1
    """)
