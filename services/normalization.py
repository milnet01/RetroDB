# =============================================================================
# RETRODB - Normalization Service
# =============================================================================
# Shared normalization dictionaries and functions for genre/modes consistency.
# Used by the scraper during ingestion and by the settings UI for bulk fixes.
# Custom rules stored in the normalization_rules DB table override hardcoded maps.
# =============================================================================

import logging
import re
from services.database import query, get_db_with_context

logger = logging.getLogger(__name__)

# Strict whitelist of allowed column names for dynamic SQL.
# These are the only values accepted as the 'field' parameter.
_ALLOWED_FIELDS = frozenset(('genre', 'modes'))

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
    'point and click': 'Point and Click',
    'point-and-click': 'Point and Click',
    'point-and-click adventure': 'Point and Click',
    'visual novel': 'Visual-Novel',
    'visual-novel': 'Visual-Novel',
    'interactive fiction': 'Interactive Fiction',
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
    # Scrolling directions (from ScreenScraper compound genres)
    'vertical': 'Vertical-Scroller',
    'vertical scrolling': 'Vertical-Scroller',
    'vertical scroller': 'Vertical-Scroller',
    'horizontal': 'Side-Scroller',
    'horizontal scrolling': 'Side-Scroller',
    'side-scrolling': 'Side-Scroller',
    'side scroller': 'Side-Scroller',
    'side-scroller': 'Side-Scroller',
    # Other
    'roguelike': 'Roguelike',
    'rogue-like': 'Roguelike',
    'roguelite': 'Roguelike',
    'metroidvania': 'Metroidvania',
    'sandbox': 'Sandbox',
    'open world': 'Open World',
    'open-world': 'Open World',
    'battle royale': 'Battle-Royale',
    'battle-royale': 'Battle-Royale',
    'card game': 'Board-Card',
    'board game': 'Board-Card',
    'board': 'Board-Card',
    'card': 'Board-Card',
    'board-card': 'Board-Card',
    'labyrinth': 'Labyrinth',
    'maze': 'Labyrinth',
}

MODES_NORMALIZATION = {
    'single player': 'Single-Player',
    'singleplayer': 'Single-Player',
    'single-player': 'Single-Player',
    'local multiplayer': 'Local Multiplayer',
    'online multiplayer': 'Online Multiplayer',
    'co-op': 'Co-op',
    'coop': 'Co-op',
    'co-operative': 'Co-op',
    'cooperative': 'Co-op',
    'local co-op': 'Local Co-op',
    'local coop': 'Local Co-op',
    'online co-op': 'Online Co-op',
    'online coop': 'Online Co-op',
    'split-screen': 'Split-Screen',
    'split screen': 'Split-Screen',
    'splitscreen': 'Split-Screen',
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
    """
    from services.game_utils import normalize_players_value
    count = normalize_players_value(players)
    if not count:
        return ''
    return 'Single-Player, Local Multiplayer' if count > 1 else 'Single-Player'


# =============================================================================
# COMBINED MAP (HARDCODED + DB RULES)
# =============================================================================

def _validate_field(field):
    """Validate field is in the strict whitelist. Raises ValueError if not."""
    if field not in _ALLOWED_FIELDS:
        raise ValueError(f"Invalid normalization field: {field!r}")


_combined_map_cache = {}
_combined_map_cache_time = {}
_COMBINED_MAP_CACHE_TTL = 300  # 5 minutes


def _get_combined_map(field):
    """Merge hardcoded map with custom DB rules. DB rules override hardcoded.

    Results are cached for 5 minutes to avoid repeated DB reads.
    Call invalidate_normalization_cache() after rule changes.
    """
    import time as _time
    _validate_field(field)

    now = _time.time()
    if field in _combined_map_cache and (now - _combined_map_cache_time.get(field, 0)) < _COMBINED_MAP_CACHE_TTL:
        return _combined_map_cache[field]

    base_map = dict(GENRE_NORMALIZATION if field == 'genre' else MODES_NORMALIZATION)
    try:
        db_rules = query(
            "SELECT from_value, to_value FROM normalization_rules WHERE category = ?",
            (field,)
        )
        for rule in db_rules:
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


# =============================================================================
# NORMALIZE FUNCTIONS (used by scraper and bulk operations)
# =============================================================================

def normalize_genre(genre_str):
    """
    Normalize genre names for consistency across all scrapers.
    Maps variations to canonical dropdown values.
    Handles slash-separated compound genres from ScreenScraper
    (e.g., "Shoot'em Up / Vertical" -> "Shoot 'em Up, Vertical-Scroller").
    """
    if not genre_str:
        return genre_str

    norm_map = _get_combined_map('genre')

    # Split genres by comma, then split each part by "/" for compound genres
    raw_parts = [g.strip() for g in genre_str.split(',')]
    genres = []
    for part in raw_parts:
        if '/' in part:
            genres.extend(sub.strip() for sub in part.split('/'))
        else:
            genres.append(part)

    normalized = []
    seen = set()

    for genre in genres:
        if not genre:
            continue
        genre_lower = genre.lower().strip()
        result = norm_map.get(genre_lower, genre)
        result_lower = result.lower()
        if result_lower not in seen:
            seen.add(result_lower)
            normalized.append(result)

    return ', '.join(normalized)


def normalize_modes(modes_str):
    """
    Normalize game mode names for consistency across all scrapers.
    Maps variations to canonical dropdown_options values.
    """
    if not modes_str:
        return modes_str

    norm_map = _get_combined_map('modes')

    modes = [m.strip() for m in modes_str.split(',')]
    normalized = []
    seen = set()

    for mode in modes:
        if not mode:
            continue
        mode_lower = mode.lower().strip()
        result = norm_map.get(mode_lower, mode)
        result_lower = result.lower()
        if result_lower not in seen:
            seen.add(result_lower)
            normalized.append(result)

    return ', '.join(normalized)


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
