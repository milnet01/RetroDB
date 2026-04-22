# =============================================================================
# RETRODB - Achievement Linking Service
# =============================================================================
# Pure title-matching helpers used to link games to external achievement /
# trophy providers (RetroAchievements, RPCS3 local trophies, PSN, Steam, Xbox).
#
# Originally lived in routes/trophies.py and was imported from routes/games.py
# via a cross-module import. Pulled out so it can be reused by background sync
# jobs without dragging the trophies blueprint into the import graph.
# =============================================================================

import re

# Trademark / copyright glyphs stripped from titles before comparison.
_TRADEMARK_CHARS = ('™', '®', '©')

# Bracket glyphs flattened to empty (keeping the text inside).
_BRACKET_CHARS = ('[', ']', '(', ')')

# Non-word, non-space run: punctuation collapsed to empty.
_NON_WORD = re.compile(r'[^\w\s]')

# Whitespace normalization.
_WHITESPACE = re.compile(r'\s+')


def clean_title_for_matching(title):
    """Normalize a title for fuzzy cross-provider matching.

    Strips trademark symbols, bracket punctuation, colons and separator
    dashes, all remaining non-word punctuation, collapses whitespace, and
    lowercases. Two titles that differ only in typographic noise will
    compare equal after this pass.

    Args:
        title: raw title string (may be None / empty).

    Returns:
        str: normalized matching key. Empty string for falsy input.
    """
    if not title:
        return ''
    cleaned = title
    for ch in _TRADEMARK_CHARS:
        cleaned = cleaned.replace(ch, '')
    for ch in _BRACKET_CHARS:
        cleaned = cleaned.replace(ch, '')
    cleaned = cleaned.replace(':', '').replace(' - ', ' ')
    cleaned = _NON_WORD.sub('', cleaned)
    return _WHITESPACE.sub(' ', cleaned).strip().lower()


def build_rpcs3_trophy_map(rows, trophy_sets=None):
    """Build a {clean_title: {earned, total}} map for PS3 RPCS3 local trophies.

    Args:
        rows: iterable of sqlite3.Row-like game rows. Used only to detect
              whether any row has system_folder == 'ps3' — if none do, returns
              an empty dict and skips the trophy fetch entirely.
        trophy_sets: optional pre-fetched trophy_sets dict (as returned by
                     routes.trophies.get_trophy_data). Left None for auto-load.

    Returns:
        dict: clean_title -> {'earned': int, 'total': int}. Empty dict when no
              PS3 rows or no matchable trophy sets found.
    """
    has_ps3 = any(
        (r['system_folder'] if 'system_folder' in r.keys() else None) == 'ps3'
        for r in rows
    )
    if not has_ps3:
        return {}

    if trophy_sets is None:
        try:
            from routes.trophies import get_trophy_data
            trophy_sets, _ = get_trophy_data()
        except Exception:
            return {}

    trophy_map = {}
    for _, ts in trophy_sets.items():
        clean = clean_title_for_matching(ts.title)
        total = len(ts.base_game_trophies)
        earned = sum(1 for t in ts.base_game_trophies if t.unlocked)
        if total > 0 and clean:
            trophy_map[clean] = {'earned': earned, 'total': total}
    return trophy_map


def lookup_rpcs3_info(game_row, trophy_map):
    """Look up an RPCS3 trophy-progress entry for a PS3 game row.

    Returns None for non-PS3 rows, empty maps, or title misses.
    """
    if not trophy_map:
        return None
    system_folder = game_row['system_folder'] if 'system_folder' in game_row.keys() else None
    if system_folder != 'ps3':
        return None
    return trophy_map.get(clean_title_for_matching(game_row['title']))
