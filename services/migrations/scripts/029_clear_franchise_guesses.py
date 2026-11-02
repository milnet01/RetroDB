# =============================================================================
# Migration 029 — clear the franchises guessed from titles
# =============================================================================
# PASS-59-212. TheGamesDB's was cut from the title and RAWG's was the letters a
# game's title shared with its neighbours, giving "Alien" for Alien 8 and "Need"
# for Need For Speed. A filled field stops a real answer arriving, so these go
# and the next scrape refills them.
#
# A person's edit leaves no credit, so a guess credited to one of them counts
# only while it is still the start of the title. Repeated names ScreenScraper
# joined ("Centipede, Centipede") are kept once.
# =============================================================================

import json

from services.migrations._helpers import _table_exists

_GUESS_CREDITS = {'franchise (TGDB)', 'franchise (RAWG)'}


def _newest_credit(history):
    try:
        entries = json.loads(history or '[]')
    except (ValueError, TypeError):
        return None
    for entry in reversed(entries if isinstance(entries, list) else []):
        filled = entry.get('fields_filled') if isinstance(entry, dict) else None
        for item in filled if isinstance(filled, list) else []:
            if isinstance(item, str) and item.startswith('franchise ('):
                return item
    return None


def _without_repeats(franchise):
    names = {}
    for name in franchise.split(','):
        names.setdefault(name.strip().casefold(), name.strip())
    return ', '.join(names.values())


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    rows = cursor.execute("SELECT id, title, franchise, scrape_history FROM games "
                          "WHERE franchise IS NOT NULL AND franchise != ''").fetchall()
    for game_id, title, franchise, history in rows:
        if (_newest_credit(history) in _GUESS_CREDITS
                and (title or '').casefold().startswith(franchise.casefold())):
            cursor.execute("UPDATE games SET franchise = NULL WHERE id = ?", (game_id,))
        elif ',' in franchise and _without_repeats(franchise) != franchise:
            cursor.execute("UPDATE games SET franchise = ? WHERE id = ?",
                           (_without_repeats(franchise), game_id))
