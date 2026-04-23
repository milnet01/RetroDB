# =============================================================================
# Migration 002 — normalize legacy genre values to canonical hyphenated forms
# =============================================================================
# Pre-versioned-migrations code shipped a `_migrate_genre_canonical` helper
# that ran on every startup. Once user_version reaches 2 this runs once and
# is then skipped forever.
# =============================================================================

import logging

logger = logging.getLogger(__name__)

GENRE_REPLACEMENTS = [
    ('FPS', 'First-Person-Shooter'),
    ("Shoot 'em Up", 'Shoot-em-up'),
    ("Shoot'em Up", 'Shoot-em-up'),
    ("Beat 'em Up", 'Beat-em-up'),
    ("Beat'em Up", 'Beat-em-up'),
    ('Hack and Slash', 'Hack-n-Slash'),
    ('Third-Person Shooter', 'Shooter'),
    ('Light Gun', 'Light-Gun'),
    ('Tower Defense', 'Tower-Defence'),
    ('Battle Royale', 'Battle-Royale'),
    ('Board Game', 'Board-Card'),
    ('Card Game', 'Board-Card'),
    ('Visual Novel', 'Visual-Novel'),
    ('Life Simulation', 'Life-Simulation'),
    ('City Builder', 'City-Builder'),
    ('Survival Horror', 'Survival-Horror'),
    ('Psychological Horror', 'Psychological-Horror'),
    ('Flight Simulator', 'Flight'),
    ('Kart Racing', 'Racing'),
    ('Tactical RPG', 'Strategy'),
]


def apply(conn):
    cursor = conn.cursor()
    # `games` is part of the baseline migration so it always exists by the
    # time we run, but the explicit existence check keeps this safe to invoke
    # on a hypothetical empty schema for diagnostics.
    games_exists = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='games'"
    ).fetchone() is not None
    if not games_exists:
        return
    for old_val, new_val in GENRE_REPLACEMENTS:
        cursor.execute(
            "UPDATE games SET genre = REPLACE(genre, ?, ?) WHERE genre LIKE ?",
            (old_val, new_val, f'%{old_val}%'),
        )
    logger.info("Genre canonical migration completed")
