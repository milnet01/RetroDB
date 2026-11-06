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

import hashlib
import re
import unicodedata
from functools import lru_cache

from services import rom_identity
from services.game_utils import ARCADE_SET_FOLDERS

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

# "i" counts as nothing, so "Final Fantasy I" still finds "Final Fantasy".
_RA_STOPWORDS = frozenset({'the', 'a', 'an', 'of', 'and', 'in', 'on', 'at', 'to', 'for', 'i'})

# RA matching — a roman-numeral sequel word (ii..xxxix, plus "v"). Bare "i"
# and "x" are left alone: they are usually a pronoun or a letter ("Mega Man X").
_RA_ROMAN = re.compile(r'^(?=[ivx]{2,}$|v$)x{0,3}(ix|iv|v?i{0,3})$')
_ROMAN_VALUES = {'i': 1, 'v': 5, 'x': 10}


def canonical_ra_word(word):
    """Fold a number word to arabic digits ("II" / "02" -> "2"); others unchanged.

    PASS-59-110: sequel numbers are part of a title's identity, so "Doom II"
    and "Doom 2" must compare equal and "Doom" must not.
    """
    if word.isdecimal():  # isdigit() also takes "²", which int() refuses
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

    A title with no ASCII letter or digit (a Japanese-only title) keeps its
    own letters, case-folded, so two such titles do not share the empty key.

    Args:
        title: raw title string (may be None / empty).

    Returns:
        str: normalized dedup key. Empty string for falsy or blank input.
    """
    if not title:
        return ''
    nfkd = unicodedata.normalize('NFKD', title)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    stripped = stripped.lower()
    stripped = _WHITESPACE.sub(' ', _NON_ASCII_ALNUM.sub('', stripped)).strip()
    return stripped or _WHITESPACE.sub(' ', unicodedata.normalize('NFKC', title).casefold()).strip()


# =============================================================================
# RETROACHIEVEMENTS MATCHING
# =============================================================================
# RA's public game lists come back with provider-specific quirks (region
# suffixes in parens, "'s" possessives that the file-name forms drop, etc.).
# The normalization regime below is deliberately separate from
# `clean_title_for_matching`: it preserves apostrophes until the possessive-
# strip pass, and folds a broader set of dash variants. The three helpers
# here were previously defined inline inside RARefreshJob._run_refresh.


# PASS-59-210. A bonus set and a hack, demo or prototype are not the retail game,
# whatever their title says, so a title match never takes one. Homebrew and
# unlicensed games are real games RA merely marks, so they match without the mark.
_RA_NEVER_MATCH = ('[subset', '~hack~', '~prototype~', '~demo~', '~test kit~')
_RA_NAME_MARK = re.compile(r'~(?:homebrew|unlicensed)~', re.IGNORECASE)

# Subtitles that name an add-on to the numbered game, not the game itself.
_RA_EXPANSION = re.compile(r'xtreme legends|empires|expansion', re.IGNORECASE)

# Where a title's subtitle starts.
_SUBTITLE_MARK = re.compile(r':|\s-\s')

# What a game's RA link holds when RA answered and has no such game. A failed
# request is None instead: it says nothing about the game (PASS-59-117).
NO_RA_MATCH = {'id': None, 'title': None, 'achievement_count': None,
               'points': None, 'has_achievements': False}


@lru_cache(maxsize=65536)
def normalize_for_ra_match(title):
    """Normalize a title for RetroAchievements list-matching.

    Applied symmetrically to both the local game title (or ROM filename) and
    each candidate RA title before comparison. Returns a lowercase string
    with punctuation collapsed, accents folded ("Okami" for RA's "\u014ckami")
    and possessive "'s" trimmed.
    """
    if not title:
        return ''
    t = title
    for ch in _TRADEMARK_CHARS:
        t = t.replace(ch, '')
    t = ''.join(c for c in unicodedata.normalize('NFKD', t)
                if not unicodedata.combining(c)).lower()
    t = _RA_BRACKETED_SUFFIX.sub('', t)
    t = _RA_SEPARATORS.sub(' ', t)
    t = _RA_APOSTROPHES.sub("'", t)
    t = _RA_POSSESSIVE.sub('', t)
    t = _RA_NON_WORD.sub('', t)
    return _WHITESPACE.sub(' ', t).strip()


@lru_cache(maxsize=65536)
def ra_significant_words(title):
    """Extract the stopword-filtered word set used by RA Jaccard matching.

    Number words are folded to arabic. One-letter words are kept: dropping
    them made "Donkey Kong Country 2" equal "Donkey Kong Country" (PASS-59-110)
    and "X-Men" equal "G-Men" (PASS-59-210).
    """
    words = (canonical_ra_word(w) for w in normalize_for_ra_match(title).split())
    return frozenset(w for w in words if w not in _RA_STOPWORDS)


def _ra_identity_words(words):
    """The words a match must agree on: a number or a lone letter ("Mega Man X")."""
    return {w for w in words if w.isdigit() or len(w) == 1}


@lru_cache(maxsize=65536)
def _ra_entry_names(ra_title):
    """The names an RA list title goes by: "Rally Chase | Thrash Rally" has two.
    Empty for a title a match must never take."""
    lowered = ra_title.lower()
    if any(mark in lowered for mark in _RA_NEVER_MATCH):
        return ()
    return tuple(_RA_NAME_MARK.sub('', part).strip() for part in ra_title.split('|'))


def _ra_candidates(ra_games):
    """Every (RA game, name) that may match, retail games ahead of marked ones,
    so a retail game wins over a homebrew of the same name."""
    plain, marked = [], []
    for ra_game in ra_games:
        if not ra_game.get('NumAchievements'):
            continue
        ra_title = ra_game.get('Title') or ''
        names = _ra_entry_names(ra_title)
        target = marked if _RA_NAME_MARK.search(ra_title) else plain
        target.extend((ra_game, name) for name in names)
    return plain + marked


def _ra_same_name(name, candidates):
    """The RA game with this exact name, else the one with the same words."""
    norm = normalize_for_ra_match(name)
    words = ra_significant_words(name)
    if not norm:
        return None
    same_words = None
    for ra_game, ra_name in candidates:
        if normalize_for_ra_match(ra_name) == norm:
            return ra_game
        if same_words is None and words and ra_significant_words(ra_name) == words:
            same_words = ra_game
    return same_words


def _ra_head(title):
    """A title's words before its subtitle; empty if it has no subtitle."""
    parts = _SUBTITLE_MARK.split(title, maxsplit=1)
    return ra_significant_words(parts[0]) if len(parts) > 1 else frozenset()


def _ra_same_but_subtitle(title, candidates):
    """The one RA game that is `title` plus a subtitle.

    Only for a numbered title: "Gran Turismo 3" is "Gran Turismo 3: A-Spec",
    but "Metroid" is not "Metroid: Zero Mission". Never an expansion: "Dynasty
    Warriors 4" is not "Dynasty Warriors 4: Xtreme Legends". Nor another number:
    "GP-1" is not "GP-1: Part II". Two such games: neither. The reverse is not
    safe: "The Sims 2: Castaway" is not "The Sims 2".
    """
    words = ra_significant_words(title)
    if not any(w.isdigit() for w in words):
        return None
    identity = _ra_identity_words(words)
    hits = {}
    for ra_game, ra_name in candidates:
        if (_ra_head(ra_name) == words and not _RA_EXPANSION.search(ra_name)
                and _ra_identity_words(ra_significant_words(ra_name)) == identity):
            hits[ra_game.get('ID')] = ra_game
    return next(iter(hits.values())) if len(hits) == 1 else None


def _ra_usable_alternates(game_title, alternate_titles):
    """Alternate titles that can only be this game. Those lists hold other games
    too, so one with other numbers ("Teen Titans 2" for "Teen Titans") or with
    all the title's words and more ("Colony Wars: Vengeance") is left out."""
    words = ra_significant_words(game_title)
    numbers = ra_sequel_numbers(words)
    usable = []
    for alt in alternate_titles or ():
        alt_words = ra_significant_words(alt)
        if ra_sequel_numbers(alt_words) == numbers and not words < alt_words:
            usable.append(alt)
    return usable


def match_ra_game(game_title, rom_name, ra_games, alternate_titles=None,
                  jaccard_threshold=0.85):
    """Find the best RA-game candidate for a local game. Scrapes and the refresh
    both use it, so a link cannot come and go with whichever ran last.

    In order, stopping at the first hit:
      1. The same name or words as the ROM file's name (it says what the file
         is), the game title, or a usable alternate title.
      2. The game title, apart from a subtitle (`_ra_same_but_subtitle`).
      3. The game title's words all in the RA title, or the reverse, with more
         than `jaccard_threshold` overlap and the same numbers and lone letters.

    Args:
        game_title: the DB game title.
        rom_name: ROM-file basename without extension (may be '').
        ra_games: RA game dicts as returned by GetGameList; each should expose
                  'Title' and 'NumAchievements'.
        alternate_titles: other names the game goes by.
        jaccard_threshold: minimum overlap ratio for step 3.

    Returns:
        dict or None: the winning RA game dict.
    """
    candidates = _ra_candidates(ra_games)
    alternates = _ra_usable_alternates(game_title, alternate_titles)
    for name in (rom_name, game_title, *alternates):
        hit = _ra_same_name(name, candidates)
        if hit:
            return hit

    hit = _ra_same_but_subtitle(game_title or '', candidates)
    if hit:
        return hit

    game_words = ra_significant_words(game_title)
    if not game_words:
        return None
    identity = _ra_identity_words(game_words)
    best_match = None
    best_score = 0.0
    for ra_game, ra_name in candidates:
        ra_words = ra_significant_words(ra_name)
        if not ra_words or _ra_identity_words(ra_words) != identity:
            continue
        if game_words <= ra_words or ra_words <= game_words:
            score = len(game_words & ra_words) / len(game_words | ra_words)
            if score > jaccard_threshold and score > best_score:
                best_score = score
                best_match = ra_game
    return best_match


def ra_rom_name(rom_path):
    """A ROM path's file name without its extension; a Windows path's too."""
    return rom_path.replace('\\', '/').split('/')[-1].rsplit('.', 1)[0] if rom_path else ''


# Systems RetroAchievements identifies by a whole file's MD5 with no special
# rule, from docs.retroachievements.org/developer-docs/game-identification.html.
# On any other system a plain MD5 would call a good copy wrong (PASS-59-217).
PLAIN_MD5_FOLDERS = frozenset({
    'atari2600', 'atarijaguar', 'wonderswan', 'wonderswancolor', 'colecovision',
    'channelf', 'vectrex', 'odyssey2', 'videopac', 'intellivision', 'gb', 'gbc', 'gba',
    'pokemini', 'virtualboy', 'sega32x', 'gamegear', 'mastersystem', 'mark3', 'megadrive',
    'genesis', 'sg-1000', 'sg1000', 'ngp', 'ngpc', 'supervision', 'megaduck',
})


def match_ra_game_for_file(game_title, rom_path, system_folder, ra_games, alternate_titles=None):
    """(RA game or None, whether this copy can earn its achievements).

    On a plain-hash system the file's hash names the game, over any title
    match. An arcade set is matched by its file name alone (`_arcade_match`). The second value is 1 for a listed hash, 0 for a title match with an
    unlisted one, and None when RetroDB cannot tell.
    """
    if (system_folder or '').lower() in ARCADE_SET_FOLDERS:
        return _arcade_match(rom_path, ra_games)
    title_match = match_ra_game(game_title, ra_rom_name(rom_path), ra_games, alternate_titles)
    if (system_folder or '').lower() not in PLAIN_MD5_FOLDERS or not rom_path:
        return title_match, None
    if not any(game.get('Hashes') for game in ra_games):
        return title_match, None
    md5 = rom_identity.file_md5(rom_path)
    if not md5:
        return title_match, None
    for game in ra_games:
        if md5 in (str(h).lower() for h in game.get('Hashes') or ()):
            return game, 1
    return title_match, (0 if title_match else None)


def _arcade_match(rom_path, ra_games):
    """RA knows an arcade set by the MD5 of its file name without the
    extension, case and all. A title never links one: arcade titles are short
    and many, so a title match took the wrong game."""
    name = ra_rom_name(rom_path)
    if not name:
        return None, None
    md5 = hashlib.md5(name.encode('utf-8'), usedforsecurity=False).hexdigest()
    for game in ra_games:
        if md5 in (str(h).lower() for h in game.get('Hashes') or ()):
            return game, 1
    return None, None


def ra_link_info(ra_game):
    """An RA list entry as the link details the rest of RetroDB reads."""
    count = ra_game.get('NumAchievements', 0)
    return {
        'id': ra_game.get('ID'),
        'title': ra_game.get('Title'),
        'console_name': ra_game.get('ConsoleName'),
        'achievement_count': count,
        'points': ra_game.get('Points', 0),
        'has_achievements': count > 0,
        'url': f"https://retroachievements.org/game/{ra_game.get('ID')}",
    }


def save_ra_link(conn, game_id, ra_info):
    """Store a game's RA link, the only place that sets one; the caller commits.
    (The Clear RA Data routes in routes/ra_sync.py empty these columns in bulk.)

    `ra_info` is `ra_link_info`'s result, or NO_RA_MATCH to clear the link. Never
    call this after a failed request. Progress saved under another link was for
    another game, so it goes; a sync rebuilds it from RA. Returns True if linked.
    """
    old = conn.execute("SELECT ra_game_id FROM games WHERE id = ?", (game_id,)).fetchone()
    new_id = ra_info['id'] if ra_info['has_achievements'] else None
    linked = new_id is not None
    conn.execute("""
        UPDATE games SET
            has_retroachievements = ?,
            ra_game_id = ?,
            ra_title = ?,
            ra_achievement_count = ?,
            ra_points = ?,
            ra_copy_fits = ?
        WHERE id = ?
    """, (1 if linked else 0, new_id,
          ra_info.get('title') if linked else None,
          ra_info['achievement_count'] if linked else None,
          ra_info['points'] if linked else None,
          ra_info.get('copy_fits') if linked else None,
          game_id))
    if old and old[0] is not None and str(old[0]) != str(new_id):
        conn.execute(
            "DELETE FROM game_achievement_progress "
            "WHERE game_id = ? AND COALESCE(source, 'ra') = 'ra'", (game_id,))
    return linked
