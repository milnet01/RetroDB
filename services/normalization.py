# =============================================================================
# RETRODB - Normalization Service
# =============================================================================
# One set of names for genre, modes, perspective, dimension and game_structure.
# A word ends as a value in FIELD_SCHEMAS or that field's dropdown, or it is
# dropped: an unknown word stored as it came splits a filter and cannot be
# translated (PASS-59-206). Used by the scraper during ingestion, by the Tidy
# maintenance tool and by the settings UI for bulk fixes.
# Custom rules in the normalization_rules DB table override hardcoded maps when
# their target is one of those values.
# =============================================================================

import html
import logging
import re
from services.database import query, get_db_with_context

logger = logging.getLogger(__name__)

# Strict whitelist of allowed column names for dynamic SQL.
# These are the only values accepted as the 'field' parameter.
_ALLOWED_FIELDS = frozenset(('genre', 'modes'))

# Every field with one set of names, and the dropdown_options category holding
# values a user added to it.
_LABEL_CATEGORIES = {
    'genre': 'genre',
    'modes': 'game_modes',
    'perspective': 'perspective',
    'dimension': 'dimension',
    'game_structure': 'game_structure',
}

# =============================================================================
# HARDCODED NORMALIZATION MAPS
# =============================================================================

GENRE_NORMALIZATION = {
    # Platformer variations
    'platform': 'Platformer',
    'platforms': 'Platformer',
    'action-platformer': 'Action-Platformer',
    'action platformer': 'Action-Platformer',
    # RPG variations
    'rpg': 'RPG',
    'role playing': 'RPG',
    'role-playing': 'RPG',
    'role-playing game': 'RPG',
    'roleplaying': 'RPG',
    'jrpg': 'JRPG',
    'action rpg': 'Action-RPG',
    'action-rpg': 'Action-RPG',
    'tactical rpg': 'Strategy',
    'mmorpg': 'MMORPG',
    # Shooter variations
    'shooter': 'Shooter',
    'fps': 'First-Person-Shooter',
    'first person shooter': 'First-Person-Shooter',
    'first-person shooter': 'First-Person-Shooter',
    'first-person-shooter': 'First-Person-Shooter',
    'third person shooter': 'Shooter',
    'third-person shooter': 'Shooter',
    'tps': 'Shooter',
    "shoot 'em up": 'Shoot-em-up',
    "shoot'em up": 'Shoot-em-up',
    'shoot em up': 'Shoot-em-up',
    'shmup': 'Shoot-em-up',
    'scrolling shooter': 'Shoot-em-up',
    'shoot-em-up': 'Shoot-em-up',
    'light gun': 'Light-Gun',
    'light-gun': 'Light-Gun',
    'gun game': 'Light-Gun',
    # Fighting variations
    "beat 'em up": 'Beat-em-up',
    "beat'em up": 'Beat-em-up',
    'beat em up': 'Beat-em-up',
    'brawler': 'Beat-em-up',
    'beat-em-up': 'Beat-em-up',
    'hack and slash': 'Hack-n-Slash',
    'hack & slash': 'Hack-n-Slash',
    'hack-and-slash': 'Hack-n-Slash',
    'hack-n-slash': 'Hack-n-Slash',
    # Strategy variations
    'rts': 'Real-Time Strategy',
    'real time strategy': 'Real-Time Strategy',
    'real-time strategy': 'Real-Time Strategy',
    'turn based strategy': 'Turn-Based Strategy',
    'turn-based strategy': 'Turn-Based Strategy',
    'turn-based': 'Turn-Based Strategy',
    'tower defense': 'Tower-Defence',
    'tower defence': 'Tower-Defence',
    'tower-defense': 'Tower-Defence',
    'tower-defence': 'Tower-Defence',
    # Sports/Racing
    'sport': 'Sports',
    'driving': 'Driving',
    'kart racing': 'Racing',
    # Adventure variations
    'action-adventure': 'Action-Adventure',
    'action adventure': 'Action-Adventure',
    'point and click': 'Adventure',
    'point-and-click': 'Adventure',
    'point-and-click adventure': 'Adventure',
    'visual novel': 'Visual-Novel',
    'visual-novel': 'Visual-Novel',
    'interactive fiction': 'Adventure',
    'interactive movie': 'Adventure',
    # Puzzle variations
    'puzzles': 'Puzzle',
    # Simulation
    'sim': 'Simulation',
    'simulator': 'Simulation',
    'life simulation': 'Life-Simulation',
    'life sim': 'Life-Simulation',
    'life-simulation': 'Life-Simulation',
    'city builder': 'City-Builder',
    'city-builder': 'City-Builder',
    'flight simulator': 'Flight',
    'flight sim': 'Flight',
    'flight': 'Flight',
    # Horror
    'survival horror': 'Survival-Horror',
    'survival-horror': 'Survival-Horror',
    'horror': 'Horror',
    'psychological horror': 'Psychological-Horror',
    'psychological-horror': 'Psychological-Horror',
    # Other
    'battle royale': 'Battle-Royale',
    'battle-royale': 'Battle-Royale',
    'card game': 'Board-Card',
    'board game': 'Board-Card',
    'board': 'Board-Card',
    'card': 'Board-Card',
    'board-card': 'Board-Card',
    'board games': 'Board-Card',
    'card & board game': 'Board-Card',
    'shougi': 'Board-Card',
    'asiatic board game': 'Board-Card',
    'playing cards': 'Board-Card',
    # IGDB, RAWG and TheGamesDB names
    'role-playing (rpg)': 'RPG',
    'real time strategy (rts)': 'Real-Time Strategy',
    'turn-based strategy (tbs)': 'Turn-Based Strategy',
    'tactical': 'Strategy',
    'moba': 'Strategy',
    'quiz': 'Trivia',
    'music': 'Music-Rhythm',
    'rhythm': 'Music-Rhythm',
    'music and dancing': 'Music-Rhythm',
    'massively multiplayer': 'MMORPG',
    'mmo': 'MMORPG',
    'education': 'Educational',
    'pinball': 'Casual',
    'casino': 'Casual',
    'construction and management simulation': 'Management',
    'build and management': 'Management',
    'life': 'Life-Simulation',
    'vehicle simulation': 'Simulation',
    # ScreenScraper and ES-DE names
    'role playing game': 'RPG',
    'japanese rpg': 'JRPG',
    'dungeon crawler rpg': 'RPG',
    'party-based rpg': 'RPG',
    'shooter scrolling': 'Shoot-em-up',
    'space invaders like': 'Shoot-em-up',
    'fighter scrolling': 'Beat-em-up',
    'lightgun shooter': 'Light-Gun',
    'run and gun': 'Shooter',
    'run & jump': 'Platformer',
    'run & jump scrolling': 'Platformer',
    'thinking': 'Puzzle',
    'racing tpv': 'Racing',
    'racing fpv': 'Racing',
    'motorcycle race tpv': 'Racing',
    'motorcycle race fpv': 'Racing',
    'hunting and fishing': 'Hunting',
    # One sport is still Sports: the list holds no single sports.
    'football (american)': 'Sports',
    'football (soccer)': 'Sports',
    'baseball': 'Sports',
    'basketball': 'Sports',
    'boxing': 'Sports',
    'golf': 'Sports',
    'multisports': 'Sports',
    'tennis': 'Sports',
    'hockey': 'Sports',
    'pool': 'Sports',
    'cycling': 'Sports',
    'bowling': 'Sports',
    'skiing': 'Sports',
    'wrestling': 'Sports',
    'rugby': 'Sports',
    'skateboard': 'Sports',
    'volleyball': 'Sports',
    'darts': 'Sports',
    'extreme': 'Sports',
    'fishing': 'Sports',
}

# Words that belong in another field. They fill it only when it is empty.
_FIRST_PERSON = ('perspective', 'First-Person')
_THIRD_PERSON = ('perspective', 'Third-Person')
_VERTICAL = ('perspective', 'Vertical-Scroller')
_SIDE_ON = ('perspective', 'Side-Scroller')
_3D = ('dimension', '3D')
GENRE_MOVES = {
    'fpv': _FIRST_PERSON,
    'racing fpv': _FIRST_PERSON,
    'motorcycle race fpv': _FIRST_PERSON,
    'tpv': _THIRD_PERSON,
    'racing tpv': _THIRD_PERSON,
    'motorcycle race tpv': _THIRD_PERSON,
    'third person shooter': _THIRD_PERSON,
    'third-person shooter': _THIRD_PERSON,
    'vertical': _VERTICAL,
    'vertical scrolling': _VERTICAL,
    'vertical scroller': _VERTICAL,
    'vertical-scroller': _VERTICAL,
    'horizontal': _SIDE_ON,
    'horizontal scrolling': _SIDE_ON,
    'side-scrolling': _SIDE_ON,
    'side scroller': _SIDE_ON,
    'side-scroller': _SIDE_ON,
    '2d': ('dimension', '2D'),
    '3d': _3D,
    'realtime 3d': _3D,
    'roguelike': ('game_structure', 'Roguelike'),
    'rogue-like': ('game_structure', 'Roguelike'),
    'roguelite': ('game_structure', 'Roguelike'),
    'metroidvania': ('game_structure', 'Metroidvania'),
    'sandbox': ('game_structure', 'Sandbox'),
    'open world': ('game_structure', 'Open-World'),
    'open-world': ('game_structure', 'Open-World'),
    'labyrinth': ('game_structure', 'Labyrinth'),
    'maze': ('game_structure', 'Labyrinth'),
}

PERSPECTIVE_NORMALIZATION = {
    'first person': 'First-Person',
    'third person': 'Third-Person',
    'side view': 'Side-Scroller',
    'bird view': 'Isometric',
    'top down': 'Top-Down',
}

GAME_STRUCTURE_NORMALIZATION = {
    'open world': 'Open-World',
    'interactive drama': 'Interactive-Drama',
}

_LABEL_MOVES = {
    'genre': GENRE_MOVES,
    'perspective': {'virtual reality': ('dimension', 'VR')},
}

MODES_NORMALIZATION = {
    'single player': 'Single-Player',
    'singleplayer': 'Single-Player',
    'single-player': 'Single-Player',
    'local multiplayer': 'Local Multiplayer',
    'online multiplayer': 'Online Multiplayer',
    # The list has no plain Co-op. Most of a retro library shares one screen.
    'co-op': 'Local Co-op',
    'coop': 'Local Co-op',
    'co-operative': 'Local Co-op',
    'cooperative': 'Local Co-op',
    'co-op multiplayer': 'Local Co-op',
    'local co-op': 'Local Co-op',
    'local coop': 'Local Co-op',
    'online co-op': 'Online Co-op',
    'online coop': 'Online Co-op',
    'split-screen': 'Split-Screen',
    'split screen': 'Split-Screen',
    'splitscreen': 'Split-Screen',
    'split-screen multiplayer': 'Split-Screen',
    'competitive multiplayer': 'Versus',
    'massively multiplayer online (mmo)': 'MMO',
    'battle royale': 'Online Multiplayer',
    'versus': 'Versus',
    'pvp': 'Versus',
    # A bare 'Multiplayer' (IGDB's generic mode, and what the player-count
    # derivations used to emit) is not in the canonical set, so
    # display_field_value() could not translate it and the modes filter chip
    # could not match it. 'Local Multiplayer' is the token this library
    # already uses for it (Pass 59.29).
    'multiplayer': 'Local Multiplayer',
}


def modes_from_player_count(players):
    """Derive canonical `modes` from a max-player count or range ("1-4").

    Single home for a derivation that had three diverged copies - TGDB wrote
    a lowercase 'Single-player', ES-DE wrote 'Single-Player', and neither
    emitted a canonical multiplayer token. Returns '' when the count is
    unknown so each caller decides what an absent value means (Pass 59.29).
    A range starting above one ("2-4") needs a second player, so it is not
    Single-Player. A bare "2" usually means "up to 2", so it still is.
    """
    from services.game_utils import normalize_players_value
    count = normalize_players_value(players)
    if not count:
        return ''
    if count == 1:
        return 'Single-Player'
    needs_two = re.match(r'\s*([2-9]|\d\d+)\s*-', str(players))
    return 'Local Multiplayer' if needs_two else 'Single-Player, Local Multiplayer'


def multiplayer_for_platform(multiplayer_modes, platform_id):
    """IGDB's multiplayer details for this console. Each entry names its platform;
    one that does not (or an unknown console) is kept."""
    details = [m for m in multiplayer_modes or [] if isinstance(m, dict)]
    if not platform_id:
        return details
    return [m for m in details if m.get('platform') in (None, platform_id)]


def modes_from_igdb(mode_names, multiplayer_modes, platform_id=None):
    """Canonical modes from IGDB's game_modes names and multiplayer_modes details.

    IGDB's bare "Multiplayer" says nothing of where people play, and its details
    do: an online-only game is not couch multiplayer. With no details, the bare
    name maps to Local Multiplayer as before. With details only for other
    consoles, multiplayer may not be on this one, so the name is dropped.
    """
    details = multiplayer_for_platform(multiplayer_modes, platform_id)
    if multiplayer_modes and not details:
        mode_names = [n for n in mode_names if n.strip().lower() != 'multiplayer']
    found = []
    if any(m.get('offlinemax') for m in details):
        found.append('Local Multiplayer')
    if any(m.get('onlinemax') for m in details):
        found.append('Online Multiplayer')
    if any(m.get('splitscreen') for m in details):
        found.append('Split-Screen')
    if any(m.get('offlinecoop') for m in details):
        found.append('Local Co-op')
    if any(m.get('onlinecoop') for m in details):
        found.append('Online Co-op')

    names = []
    for name in mode_names:
        if name.strip().lower() == 'multiplayer' and found:
            names.extend(found)
        else:
            names.append(name)
    return normalize_modes(', '.join(names))


# =============================================================================
# COMBINED MAP (HARDCODED + DB RULES)
# =============================================================================

def _validate_field(field):
    """Validate field is in the strict whitelist. Raises ValueError if not."""
    if field not in _ALLOWED_FIELDS:
        raise ValueError(f"Invalid normalization field: {field!r}")


_combined_map_cache = {}
_combined_map_cache_time = {}
_canonical_cache = {}
_canonical_cache_time = {}
_COMBINED_MAP_CACHE_TTL = 300  # 5 minutes


def _canonical_values(field):
    """{lowercase: proper form} of a field's values: FIELD_SCHEMAS plus its dropdown."""
    import time as _time
    now = _time.time()
    if field in _canonical_cache and (now - _canonical_cache_time.get(field, 0)) < _COMBINED_MAP_CACHE_TTL:
        return _canonical_cache[field]

    from scraper.scrape_ai import FIELD_SCHEMAS
    values = {v.lower(): v for v in FIELD_SCHEMAS[field]}
    try:
        rows = query("SELECT value FROM dropdown_options WHERE category = ?",
                     (_LABEL_CATEGORIES[field],))
        for row in rows:
            values.setdefault(row['value'].lower(), row['value'])
    except Exception:
        pass  # Table may not exist yet during startup

    _canonical_cache[field] = values
    _canonical_cache_time[field] = now
    return values


def _get_combined_map(field):
    """Merge hardcoded map with custom DB rules. DB rules override hardcoded.

    A rule whose target is not one of the field's values is ignored, so an old
    rule cannot split a genre in two.

    Results are cached for 5 minutes to avoid repeated DB reads.
    Call invalidate_normalization_cache() after rule changes.
    """
    import time as _time

    now = _time.time()
    if field in _combined_map_cache and (now - _combined_map_cache_time.get(field, 0)) < _COMBINED_MAP_CACHE_TTL:
        return _combined_map_cache[field]

    base_map = dict({
        'genre': GENRE_NORMALIZATION,
        'modes': MODES_NORMALIZATION,
        'perspective': PERSPECTIVE_NORMALIZATION,
        'game_structure': GAME_STRUCTURE_NORMALIZATION,
    }.get(field, {}))
    canonical = _canonical_values(field)
    try:
        db_rules = query(
            "SELECT from_value, to_value FROM normalization_rules WHERE category = ?",
            (field,)
        )
        for rule in db_rules:
            targets = [t.strip().lower() for t in rule['to_value'].split(',')]
            if all(t in canonical for t in targets):
                base_map[rule['from_value'].lower()] = rule['to_value']
    except Exception:
        pass  # Table may not exist yet during startup

    _combined_map_cache[field] = base_map
    _combined_map_cache_time[field] = now
    return base_map


def invalidate_normalization_cache():
    """Clear cached normalization maps (call after rule changes)."""
    _combined_map_cache.clear()
    _combined_map_cache_time.clear()
    _canonical_cache.clear()
    _canonical_cache_time.clear()


# =============================================================================
# NORMALIZE FUNCTIONS (used by scraper and bulk operations)
# =============================================================================

def split_labels(field, text):
    """(canonical text, {other field: value}) for a field's raw text.

    Splits on commas and on the "/" and "|" that compound names use, so
    "Shoot'em Up / Vertical" gives ('Shoot-em-up', {'perspective': 'Vertical-Scroller'}).
    A word that reaches no canonical value is dropped.
    """
    norm_map = _get_combined_map(field)
    canonical = _canonical_values(field)
    moves = _LABEL_MOVES.get(field, {})

    kept = []
    moved = {}
    for word in re.split(r'[,/|]', text or ''):
        key = word.strip().lower()
        if not key:
            continue
        if key in moves:
            target, value = moves[key]
            moved.setdefault(target, value)
        for part in norm_map.get(key, key).split(','):
            value = canonical.get(part.strip().lower())
            if value and value not in kept:
                kept.append(value)
    return ', '.join(kept), moved


def normalize_genre(genre_str):
    """Genre text as canonical values only."""
    return split_labels('genre', genre_str)[0] if genre_str else genre_str


def normalize_modes(modes_str):
    """Modes text as canonical values only."""
    return split_labels('modes', modes_str)[0] if modes_str else modes_str


_MULTIPLAYER_MODES = frozenset((
    'Asynchronous Multiplayer', 'Cross-Platform Play', 'LAN-System Link', 'Local Co-op',
    'Local Multiplayer', 'MMO', 'Online Co-op', 'Online Multiplayer', 'Split-Screen', 'Versus',
))


def _reconcile_players_and_modes(metadata):
    """Stop a game saying "1 player" and "Local Multiplayer" together.

    The higher claim wins, since "1" and "Single-Player" are what a source says
    when it knows no better. Two is the least a multiplayer mode means.
    """
    players = metadata.get('players')
    modes = metadata.get('modes')
    if not isinstance(players, int) or not modes:
        return
    words = {m.strip() for m in modes.split(',')}
    if players == 1 and words & _MULTIPLAYER_MODES:
        metadata['players'] = 2
    elif players > 1 and words == {'Single-Player'}:
        metadata['modes'] = 'Single-Player, Local Multiplayer'


_HEADING_MARK = re.compile(r'^#{1,6}\s*', re.MULTILINE)
_BULLET_MARK = re.compile(r'^\*\s+', re.MULTILINE)
_FOOTNOTE_MARK = re.compile(r'(?<=\w)\[(?:[a-z]|\d{1,3})\]')


def clean_description(text):
    """A description as readable text: web codes such as `&quot;`, Windows line
    endings, heading and bullet marks, and footnote marks such as `[a]` go
    (PASS-59-213)."""
    text = html.unescape(str(text)).replace('\r\n', '\n').replace('\r', '\n')
    text = _BULLET_MARK.sub('', _HEADING_MARK.sub('', text))
    lines = (line.rstrip() for line in _FOOTNOTE_MARK.sub('', text).split('\n'))
    return '\n'.join(lines).strip()


# One company under several spellings, as the sources write them. Only names
# that are plainly one company: Atari, Inc. and Atari Games really are two.
COMPANY_ALIASES = {
    'sega': 'SEGA',
    'ubi soft': 'Ubisoft',
    'ubisoft entertainment': 'Ubisoft',
    'ubi soft entertainment software': 'Ubisoft',
    'acclaim': 'Acclaim Entertainment',
    'ocean software': 'Ocean',
    'ocean software ltd.': 'Ocean',
}


def canonical_companies(value):
    """A publisher or developer list with one spelling per company, each once."""
    names = (name.strip() for name in str(value).split(','))
    return ', '.join(dict.fromkeys(
        COMPANY_ALIASES.get(name.casefold(), name) for name in names if name))


def canonicalize_metadata(metadata):
    """The conversion after the merge, whatever filled each field (PASS-59-206).

    Words belonging in another field fill it only when it is empty. A field left
    with no words holds '', which the save's COALESCE writes over the old text.
    """
    if metadata.get('description'):
        metadata['description'] = clean_description(metadata['description']) or None
    for field in ('publisher', 'developer'):
        if metadata.get(field):
            metadata[field] = canonical_companies(metadata[field])
    for field in _LABEL_CATEGORIES:
        text = metadata.get(field)
        if not text:
            continue
        value, moved = split_labels(field, str(text))
        metadata[field] = value
        for target, moved_value in moved.items():
            if not metadata.get(target):
                metadata[target] = moved_value
    _reconcile_players_and_modes(metadata)


# =============================================================================
# PREVIEW & APPLY (used by Settings UI)
# =============================================================================

def get_unique_values(field):
    """
    Query all games, split comma-separated field values, count occurrences
    per unique value, look up each in combined map, return analysis list.

    Returns:
        list of dicts: [{value, count, suggested, needs_change}, ...]
    """
    _validate_field(field)

    norm_map = _get_combined_map(field)

    # field is validated against _ALLOWED_FIELDS whitelist above — safe for SQL interpolation
    rows = query(f"SELECT id, {field} FROM games WHERE {field} IS NOT NULL AND {field} != ''")

    # Count occurrences of each unique value
    value_counts = {}
    for row in rows:
        raw = row[field]
        parts = [v.strip() for v in raw.split(',')]
        for part in parts:
            if not part:
                continue
            # Preserve original casing for display
            key = part.lower()
            if key not in value_counts:
                value_counts[key] = {'display': part, 'count': 0}
            value_counts[key]['count'] += 1

    # Build result with suggestions
    results = []
    for key, info in sorted(value_counts.items(), key=lambda x: x[1]['display'].lower()):
        # Check for compound values containing / or | separators
        if re.search(r'[/|]', info['display']):
            sub_parts = re.split(r'\s*[/|]\s*', info['display'])
            normalized_subs = []
            for sub in sub_parts:
                if sub:
                    canonical = norm_map.get(sub.lower().strip(), sub.strip())
                    normalized_subs.append(canonical)
            suggested = ', '.join(normalized_subs)
            needs_change = True  # Always suggest splitting compound values
        else:
            suggested = norm_map.get(key, info['display'])
            needs_change = suggested.lower() != info['display'].lower()
        results.append({
            'value': info['display'],
            'count': info['count'],
            'suggested': suggested,
            'needs_change': needs_change
        })

    return results


def apply_normalization(field, mappings):
    """
    Apply normalization mappings to existing game data and save as custom rules.

    Args:
        field: 'genre' or 'modes'
        mappings: list of {old: str, new: str}

    Returns:
        dict with games_updated and rules_saved counts
    """
    _validate_field(field)

    games_updated = 0
    rules_saved = 0

    with get_db_with_context() as conn:
        cursor = conn.cursor()

        for mapping in mappings:
            old_val = mapping.get('old', '').strip()
            new_val = mapping.get('new', '').strip()
            if not old_val or not new_val or old_val.lower() == new_val.lower():
                continue

            # field is validated against _ALLOWED_FIELDS whitelist — safe for SQL interpolation
            rows = cursor.execute(
                f"SELECT id, {field} FROM games WHERE {field} LIKE ? COLLATE NOCASE",
                (f'%{old_val}%',)
            ).fetchall()

            for row in rows:
                game_id = row[0]
                current = row[1] or ''
                parts = [v.strip() for v in current.split(',')]

                updated_parts = []
                changed = False
                seen = set()
                for part in parts:
                    if not part:
                        continue
                    if part.lower() == old_val.lower():
                        # new_val may be comma-separated (e.g., "Action, Labyrinth")
                        new_parts = [v.strip() for v in new_val.split(',')]
                        for np in new_parts:
                            if np and np.lower() not in seen:
                                seen.add(np.lower())
                                updated_parts.append(np)
                        changed = True
                    else:
                        if part.lower() not in seen:
                            seen.add(part.lower())
                            updated_parts.append(part)

                if changed:
                    new_field_value = ', '.join(updated_parts)
                    cursor.execute(
                        f"UPDATE games SET {field} = ? WHERE id = ?",
                        (new_field_value, game_id)
                    )
                    games_updated += 1

            # Save as custom rule (upsert)
            cursor.execute("""
                INSERT INTO normalization_rules (category, from_value, to_value)
                VALUES (?, ?, ?)
                ON CONFLICT(category, from_value) DO UPDATE SET to_value = excluded.to_value
            """, (field, old_val.lower(), new_val))
            rules_saved += 1

        conn.commit()

    # Invalidate cached maps since rules changed
    invalidate_normalization_cache()
    logger.info(f"Normalization applied for {field}: {games_updated} games updated, {rules_saved} rules saved")
    return {'games_updated': games_updated, 'rules_saved': rules_saved}
