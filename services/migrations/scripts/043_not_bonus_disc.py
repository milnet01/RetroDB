# =============================================================================
# Migration 043 — remember a person's "not a bonus disc" (PASS-59-262)
# =============================================================================
# Unlinking or unmarking a disc sets is_bonus_disc to 0, which auto-link read
# as "never judged", so the next sweep marked the disc again. not_bonus_disc = 1
# records the person's answer; auto-detect skips it, a manual link or mark
# clears it. A separate column, because every game list hides any
# is_bonus_disc other than 0 or NULL.
# =============================================================================

from services.migrations._helpers import _has_column


def apply(conn):
    c = conn.cursor()
    if not _has_column(c, 'games', 'not_bonus_disc'):
        c.execute("ALTER TABLE games ADD COLUMN not_bonus_disc INTEGER NOT NULL DEFAULT 0")
