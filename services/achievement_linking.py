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
import unicodedata

# Trademark / copyright glyphs stripped from titles before comparison.
_TRADEMARK_CHARS = ('™', '®', '©')

# Bracket glyphs flattened to empty (keeping the text inside).
_BRACKET_CHARS = ('[', ']', '(', ')')

# Non-word, non-space run: punctuation collapsed to empty.
_NON_WORD = re.compile(r'[^\w\s]')

# ASCII-only punctuation class used by normalize_title_for_dedup (after
# NFKD + diacritic strip, only [a-z0-9\s] should survive).
_NON_ASCII_ALNUM = re.compile(r'[^a-z0-9\s]')

# Whitespace normalization.
_WHITESPACE = re.compile(r'\s+')

# RA matching — parenthesised / bracketed region+version suffixes.
_RA_BRACKETED_SUFFIX = re.compile(r'\s*[\(\[].*?[\)\]]\s*')

# RA matching — separator punctuation flattened to space (colon, hyphen,
# en/em dash, forward slash, ampersand).
_RA_SEPARATORS = re.compile(r"[:\-–—/&]")

# RA matching — all apostrophe variants folded to ASCII '.
_RA_APOSTROPHES = re.compile(r"['’‘ʼʻ`´′ʹ]")

# RA matching — possessive "'s" trailing a word.
_RA_POSSESSIVE = re.compile(r"'s\b")

# RA matching — any remaining non-word-non-space-non-apostrophe.
_RA_NON_WORD = re.compile(r"[^\w\s']")

_RA_STOPWORDS = frozenset({'the', 'a', 'an', 'of', 'and', 'in', 'on', 'at', 'to', 'for'})

# RA matching — a roman-numeral sequel word (ii..xxxix, plus "v"). Bare "i"
# and "x" are left alone: they are usually a pronoun or a letter ("Mega Man X").
_RA_ROMAN = re.compile(r'^(?=[ivx]{2,}$|v$)x{0,3}(ix|iv|v?i{0,3})$')
_ROMAN_VALUES = {'i': 1, 'v': 5, 'x': 10}


def canonical_ra_word(word):
    """Fold a number word to arabic digits ("II" / "02" -> "2"); others unchanged.

    PASS-59-110: sequel numbers are part of a title's identity, so "Doom II"
    and "Doom 2" must compare equal and "Doom" must not.
    """
    if word.isdigit():
        return str(int(word))
    if _RA_ROMAN.match(word):
        values = [_ROMAN_VALUES[c] for c in word]
        return str(sum(-v if nxt > v else v
                       for v, nxt in zip(values, values[1:] + [0])))
    return word


def ra_sequel_numbers(words):
    """The number words in a significant-word set (see canonical_ra_word)."""
    return {w for w in words if w.isdigit()}


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


# =============================================================================
# PLATFORM-IMPORT DEDUPLICATION
# =============================================================================
# Distinct from clean_title_for_matching: this flavor runs NFKD + diacritic
# strip so ASCII-equivalent titles collide (e.g. "Pokémon" / "Pokemon").
# Used by /api/steam/import, /api/xbox/import, /api/psn/import to detect an
# existing library entry when the platform's own ID (steam_app_id etc.) isn't
# present or hasn't matched.


def normalize_title_for_dedup(title):
    """Normalize a title for duplicate-detection across platform imports.

    Strips diacritical marks via NFKD, lowercases, drops anything that isn't
    ASCII alphanumeric or whitespace, and collapses whitespace.

    This is the Steam / Xbox / PSN import path's fuzzy key. It's stricter
    than `clean_title_for_matching` (which preserves unicode letters) because
    imported titles frequently differ from scraped titles only by region-
    specific glyphs.

    Args:
        title: raw title string (may be None / empty).

    Returns:
        str: normalized dedup key. Empty string for falsy input.
    """
    if not title:
        return ''
    nfkd = unicodedata.normalize('NFKD', title)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    stripped = stripped.lower()
    stripped = _NON_ASCII_ALNUM.sub('', stripped)
    return _WHITESPACE.sub(' ', stripped).strip()


# =============================================================================
# RETROACHIEVEMENTS MATCHING
# =============================================================================
# RA's public game lists come back with provider-specific quirks (region
# suffixes in parens, "'s" possessives that the file-name forms drop, etc.).
# The normalization regime below is deliberately separate from
# `clean_title_for_matching`: it preserves apostrophes until the possessive-
# strip pass, and folds a broader set of dash variants. The three helpers
# here were previously defined inline inside RARefreshJob._run_refresh.


def normalize_for_ra_match(title):
    """Normalize a title for RetroAchievements list-matching.

    Applied symmetrically to both the local game title (or ROM filename) and
    each candidate RA title before comparison. Returns a lowercase string
    with punctuation collapsed and possessive "'s" trimmed.
    """
    if not title:
        return ''
    t = title.lower()
    t = _RA_BRACKETED_SUFFIX.sub('', t)
    t = _RA_SEPARATORS.sub(' ', t)
    t = _RA_APOSTROPHES.sub("'", t)
    t = _RA_POSSESSIVE.sub('', t)
    t = _RA_NON_WORD.sub('', t)
    return _WHITESPACE.sub(' ', t).strip()


def ra_significant_words(title):
    """Extract the stopword-filtered word set used by RA Jaccard matching.

    Number words are folded to arabic and kept even when one character
    long; dropping them made "Donkey Kong Country 2" equal "Donkey Kong
    Country" (PASS-59-110).
    """
    words = (canonical_ra_word(w) for w in normalize_for_ra_match(title).split())
    return {w for w in words
            if w not in _RA_STOPWORDS and (len(w) > 1 or w.isdigit())}


def match_ra_game(game_title, rom_name, ra_games, jaccard_threshold=0.85):
    """Find the best RA-game candidate for a local game.

    Three-pass strategy, matching the pre-extraction inline logic in
    RARefreshJob._run_refresh:
      1. Exact match on normalized game title or ROM-basename.
      2. Exact word-set equality after stopword strip.
      3. Jaccard similarity > threshold with one set a subset of the other.

    Args:
        game_title: the DB game title.
        rom_name: ROM-file basename without extension (may be '').
        ra_games: iterable of RA game dicts as returned by
                  retroachievements.GetGameList; each dict should expose
                  'Title' and 'NumAchievements' keys.
        jaccard_threshold: minimum overlap ratio for the fuzzy fallback.

    Returns:
        dict or None: the winning RA game dict, or None when no candidate
        meets any of the three criteria. RA games with zero achievements are
        always skipped.
    """
    game_title_norm = normalize_for_ra_match(game_title)
    game_words = ra_significant_words(game_title)
    rom_norm = normalize_for_ra_match(rom_name) if rom_name else ''

    best_match = None
    best_score = 0.0

    for ra_game in ra_games:
        if ra_game.get('NumAchievements', 0) == 0:
            continue

        ra_title = ra_game.get('Title', '')
        ra_norm = normalize_for_ra_match(ra_title)
        ra_words = ra_significant_words(ra_title)

        if ra_norm and (ra_norm == game_title_norm or ra_norm == rom_norm):
            return ra_game

        if game_words and ra_words:
            if game_words == ra_words:
                return ra_game
            if ra_sequel_numbers(game_words) != ra_sequel_numbers(ra_words):
                continue
            if game_words.issubset(ra_words) or ra_words.issubset(game_words):
                intersection = len(game_words & ra_words)
                union = len(game_words | ra_words)
                score = intersection / union if union else 0
                if score > jaccard_threshold and score > best_score:
                    best_score = score
                    best_match = ra_game

    return best_match
