# =============================================================================
# HYBRID SCRAPER
# =============================================================================
# Combines metadata from ES-DE, TheGamesDB, and IGDB to fill all gaps
# =============================================================================

import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import IMAGE_PATH, STATIC_PATH
from services.normalization import normalize_genre
from services.game_utils import generate_sort_title, infer_rating_from_content, RATING_SYSTEM_KEYS, RATING_SYSTEMS
from services.game_metadata_service import cross_map_ratings

logger = logging.getLogger(__name__)

# Import individual scrapers
from scraper.base_scraper import get_scraper_conn
from scraper.scrape_esde import (
    extract_region_from_filename
)
from scraper.scrape_thegamesdb import (
    fetch_game_details as fetch_tgdb_details,
)
from scraper.scrape_igdb import (
    igdb_auth,
    igdb_request
)

# Import metadata merging functions (extracted to reduce file size)
from scraper.metadata_merger import (
    apply_tgdb_to_metadata,
    apply_igdb_to_metadata,
    apply_rawg_to_metadata,
    apply_screenscraper_to_metadata,
    apply_ai_to_metadata,
    load_scraper_settings,
)
from scraper.metadata_normalizer import (
    normalize_title,
    normalize_esrb_rating,
)
from scraper.match_scorer import calculate_title_match_score

# Try to import AI scraper
AI_AVAILABLE = False
try:
    from scraper.scrape_ai import get_game_details as fetch_ai_metadata
    AI_AVAILABLE = True
    logger.info("AI metadata scraper module loaded successfully")
except ImportError:
    logger.debug("AI metadata scraper module not available")

# =============================================================================
# FALLBACK BEST-MATCH SELECTION
# =============================================================================

def _pick_best_fallback(results, game_title, min_title_score=80):
    """Pick the best-matching result from a fallback scraper search using title scoring.

    Returns the single best result dict, or None if no results or if the best
    match doesn't meet the minimum title score threshold.  This prevents
    wrong-game matches (e.g. "Alan Wake II" when searching "Alan Wake Remastered")
    from polluting a game's screenshots/metadata.

    Args:
        results: List of search result dicts.
        game_title: The title to match against.
        min_title_score: Minimum title match score to accept (default 80).
    """
    if not results:
        return None

    best = None
    best_score = -1
    for r in results:
        name = r.get('name', r.get('game_title', ''))
        # ScreenScraper raw results use 'noms' list instead of 'name'
        if not name and 'noms' in r:
            noms = r.get('noms', [])
            for region in ['us', 'eu', 'wor', 'ss']:
                for item in noms:
                    if isinstance(item, dict) and item.get('region', '').lower() == region and item.get('text'):
                        name = item['text']
                        break
                if name:
                    break
            if not name and noms and isinstance(noms[0], dict):
                name = noms[0].get('text', '')
        score = calculate_title_match_score(name, game_title)
        if score > best_score:
            best_score = score
            best = r
    if best:
        best_name = best.get('name', best.get('game_title', ''))
        if not best_name and 'noms' in best:
            noms = best.get('noms', [])
            if noms and isinstance(noms[0], dict):
                best_name = noms[0].get('text', '')
        if best_score < min_title_score:
            logger.info(f"  Rejecting fallback match '{best_name}' (title_score={best_score} < {min_title_score})")
            return None
        logger.info(f"  Best fallback match: '{best_name}' (title_score={best_score})")
    return best


def _pick_best_secondary(candidates, target_title, min_title_score=100):
    """Pick the best-matching secondary source entry by title similarity.

    When multiple search results exist for a scraper (e.g. TGDB returned both
    "Rambo III" and "Rambo: First Blood Part II"), pick the one whose name
    best matches the title the user actually selected.

    Returns None if no candidate meets the minimum title score threshold,
    which signals the caller to do a fresh search instead of using a
    poor match (e.g. "Alan Wake II" when searching "Alan Wake Remastered").

    Args:
        candidates: List of dicts with 'source', 'id', 'name' keys.
        target_title: The selected game's title to match against.
        min_title_score: Minimum title match score to accept (default 100).

    Returns:
        Best matching candidate dict, or None if no good match.
    """
    if not candidates:
        return None
    if not target_title:
        return candidates[0]

    best = None
    best_score = -1
    for c in candidates:
        # Use pre-computed title_score if available (set by bulk scrape builder)
        score = c.get('title_score')
        if score is None:
            name = c.get('name', '')
            if not name:
                continue
            score = calculate_title_match_score(name, target_title)
        if score > best_score:
            best_score = score
            best = c

    if best and best_score >= min_title_score:
        logger.info(f"  Best secondary match: '{best.get('name', '')}' (title_score={best_score})")
        return best

    if best and best_score < min_title_score:
        logger.info(f"  Rejecting secondary match '{best.get('name', '')}' (title_score={best_score} < {min_title_score}) — will search fresh")
        return None

    return None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Generic controller values that should be replaced with system default
GENERIC_CONTROLLER_VALUES = [
    'standard controller',
    'gamepad',
    'controller',
    'joypad',
    'built-in controls',
]

def get_system_default_controller_name(system_id):
    """Get the default controller names for a system (returns comma-separated list if multiple)"""
    if not system_id:
        return None

    conn = None
    try:
        conn = get_scraper_conn()
        c = conn.cursor()

        # Get all default controllers for this system from junction table
        c.execute("""
            SELECT c.name
            FROM controllers c
            JOIN system_controllers sc ON c.id = sc.controller_id
            WHERE sc.system_id = ? AND sc.is_default = 1
            ORDER BY c.name COLLATE NOCASE
        """, (system_id,))

        rows = c.fetchall()

        # If no defaults in junction table, try legacy default_controller_id
        if not rows:
            c.execute("""
                SELECT c.name
                FROM controllers c
                JOIN systems s ON s.default_controller_id = c.id
                WHERE s.id = ?
            """, (system_id,))
            rows = c.fetchall()

        if rows:
            # Return comma-separated list of controller names
            return ', '.join(row['name'] for row in rows)
        return None
    except Exception as e:
        logger.warning(f"Error getting default controllers for system {system_id}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def should_use_default_controller(controller_value):
    """Check if the controller value is generic and should be replaced with system default"""
    if not controller_value:
        return True

    # Check if it's a generic value
    controller_lower = controller_value.lower().strip()
    for generic in GENERIC_CONTROLLER_VALUES:
        if controller_lower == generic or controller_lower.startswith(generic):
            return True

    return False

# normalize_title, normalize_esrb_rating imported from scraper.metadata_normalizer
# normalize_genre, normalize_modes imported from services.normalization


# =============================================================================
# METADATA FIELD DEFINITIONS
# =============================================================================

# Fields that can be filled from each source
# NOTE: For boxart, screenscraper and rawg provide system-specific covers which are preferred
# IGDB provides generic covers so should be last resort for boxart
FIELD_SOURCES = {
    'title': ['esde', 'tgdb', 'igdb'],
    'publisher': ['esde', 'tgdb', 'igdb'],
    'developer': ['esde', 'tgdb', 'igdb'],
    'release_date': ['esde', 'tgdb', 'igdb'],
    'genre': ['esde', 'tgdb', 'igdb'],
    'description': ['esde', 'tgdb', 'igdb'],
    'players': ['esde', 'tgdb', 'igdb'],
    'modes': ['esde', 'tgdb', 'igdb'],
    'esrb_rating': ['igdb', 'tgdb', 'rawg', 'screenscraper'],
    'pegi_rating': ['igdb', 'tgdb', 'screenscraper'],
    'cero_rating': ['igdb', 'screenscraper'],
    'usk_rating': ['igdb', 'screenscraper'],
    'acb_rating': ['igdb', 'screenscraper'],
    'fpb_rating': ['screenscraper'],
    'grac_rating': ['igdb'],
    'classind_rating': ['igdb'],
    'boxart': ['esde', 'screenscraper', 'rawg', 'tgdb', 'igdb'],  # SS and RAWG have system-specific covers; IGDB generic
    'boxart_3d': ['esde', 'screenscraper'],  # 3D boxart from ES-DE or ScreenScraper
    'screenshots': ['esde', 'screenscraper', 'tgdb', 'igdb'],
    'fanart': ['esde', 'screenscraper', 'tgdb', 'igdb'],
    'video': ['esde', 'screenscraper'],
    'manual': ['esde', 'screenscraper'],
    'region': ['esde', 'screenscraper', 'filename'],
    'franchise': ['igdb', 'tgdb'],
    'similar_games': ['igdb'],
    'playtime_estimate': ['igdb'],
    'controller_support': ['igdb'],
    'save_type': ['manual'],  # Derived from common patterns
    'critic_score': ['rawg', 'igdb', 'ai'],  # RAWG has Metacritic, IGDB has aggregated critic scores, AI searches online
    'critic_score_count': ['rawg', 'igdb', 'ai'],
    'user_score': ['rawg', 'igdb', 'screenscraper', 'ai'],  # RAWG user ratings, IGDB user ratings, SS community, AI searches online
    'user_score_count': ['rawg', 'igdb', 'ai'],
}

# =============================================================================
# IGDB EXTENDED FETCH
# =============================================================================

def fetch_igdb_extended(game_id):
    """Fetch extended game information from IGDB including franchise, similar games, ratings, etc."""
    try:
        token = igdb_auth()

        # Note: time_to_beat was deprecated, using external_games for HLTB instead
        body = f"""
        fields name, first_release_date,
               involved_companies.company.name, involved_companies.developer, involved_companies.publisher,
               genres.name, age_ratings.category, age_ratings.rating,
               game_modes.name, player_perspectives.name,
               multiplayer_modes.offlinemax, multiplayer_modes.onlinemax,
               multiplayer_modes.campaigncoop, multiplayer_modes.splitscreen,
               summary, storyline, cover.url, screenshots.url, artworks.url,
               videos.video_id, alternative_names.name,
               franchise.name, franchises.name, collection.name,
               similar_games.name, similar_games.cover.url,
               game_engines.name, platforms.name,
               rating, rating_count, aggregated_rating, aggregated_rating_count;
        where id = {game_id};
        """

        results = igdb_request("games", body, token)

        if results:
            game = results[0]

            # Process franchise
            franchise = None
            if game.get('franchise'):
                franchise = game['franchise'].get('name')
            elif game.get('franchises'):
                franchise = game['franchises'][0].get('name')
            elif game.get('collection'):
                franchise = game['collection'].get('name')

            # Process similar games
            similar = []
            if game.get('similar_games'):
                for sg in game['similar_games'][:5]:
                    similar.append(sg.get('name', ''))

            # Process critic/user scores
            critic_score = game.get('aggregated_rating')  # 0-100 scale
            critic_score_count = game.get('aggregated_rating_count')
            user_score = game.get('rating')  # 0-100 scale
            user_score_count = game.get('rating_count')

            if critic_score:
                logger.info(f"IGDB critic score: {critic_score:.1f} ({critic_score_count} reviews)")
            if user_score:
                logger.info(f"IGDB user score: {user_score:.1f} ({user_score_count} ratings)")

            # Process player perspectives
            perspectives = []
            if game.get('player_perspectives'):
                perspectives = [p.get('name', '') for p in game['player_perspectives'] if p.get('name')]

            game['_extended'] = {
                'franchise': franchise,
                'similar_games': ', '.join(similar) if similar else None,
                'playtime_estimate': None,  # IGDB deprecated time_to_beat
                'critic_score': critic_score,
                'critic_score_count': critic_score_count,
                'user_score': user_score,
                'user_score_count': user_score_count,
                'perspective': ', '.join(perspectives) if perspectives else None,
            }

            logger.info(f"IGDB extended details fetched for game ID: {game_id}")
            return game

        return None

    except Exception as e:
        logger.error(f"IGDB extended fetch error: {e}")
        return None


# =============================================================================
# TGDB EXTENDED FETCH
# =============================================================================

def fetch_tgdb_extended(game_id):
    """Fetch extended game information from TGDB"""
    try:
        details = fetch_tgdb_details(game_id)
        if not details:
            return None

        # TGDB doesn't have franchise/series in basic API, but we can derive from game title
        # Look for common patterns like "Final Fantasy VII" -> "Final Fantasy"
        title = details.get('name', '')
        franchise = extract_franchise_from_title(title)

        details['_extended'] = {
            'franchise': franchise,
        }

        return details

    except Exception as e:
        logger.error(f"TGDB extended fetch error: {e}")
        return None


def extract_franchise_from_title(title):
    """Try to extract franchise/series name from game title"""
    # Common franchise patterns
    franchise_patterns = [
        # Roman numerals
        r'^(.+?)\s+[IVXLCDM]+$',
        r'^(.+?)\s+[IVXLCDM]+\s*[-:].+$',
        # Arabic numerals
        r'^(.+?)\s+\d+$',
        r'^(.+?)\s+\d+\s*[-:].+$',
        # Subtitles
        r'^(.+?):\s+.+$',
        r'^(.+?)\s+-\s+.+$',
    ]

    for pattern in franchise_patterns:
        match = re.match(pattern, title)
        if match:
            franchise = match.group(1).strip()
            # Only return if franchise is substantial
            if len(franchise) > 3:
                return franchise

    return None


# =============================================================================
# SAVE TYPE DETECTION
# =============================================================================

def detect_save_type(system_folder, title):
    """Detect likely save type based on system and game era"""

    # Systems that typically use battery saves
    battery_systems = ['nes', 'snes', 'gb', 'gbc', 'gba', 'genesis', 'megadrive', 'n64']

    # Systems that use memory cards
    memcard_systems = ['psx', 'ps2', 'gc', 'dreamcast', 'saturn']

    # Systems that use internal storage
    internal_systems = ['ps3', 'xbox', 'xbox360', 'wii', 'wiiu', 'switch', 'psp', 'psvita']

    # Cartridge systems without saves (passwords common)
    password_systems = ['atari2600', 'atari5200', 'atari7800', 'colecovision', 'intellivision']

    system = (system_folder or '').lower()  # Pass 48.5 — guard None system_folder

    if system in battery_systems:
        return "Battery Save / SRAM"
    elif system in memcard_systems:
        return "Memory Card"
    elif system in internal_systems:
        return "Internal Storage"
    elif system in password_systems:
        return "Password / None"
    else:
        return None


# =============================================================================
# CONTROLLER SUPPORT DETECTION
# =============================================================================

def detect_controller_support(system_folder, modes):
    """Detect controller support based on system"""

    system = (system_folder or '').lower()  # Pass 48.5 — guard None system_folder

    # Standard controller
    standard = ['nes', 'snes', 'genesis', 'megadrive', 'mastersystem', 'psx', 'ps2', 'ps3',
                'saturn', 'dreamcast', 'xbox', 'xbox360', 'n64', 'gc', 'atari2600', 'neogeo']

    # Motion controls
    motion = ['wii', 'wiiu']

    # Handheld (built-in)
    handheld = ['gb', 'gbc', 'gba', 'nds', 'n3ds', 'psp', 'psvita', 'gamegear', 'atarilynx',
                'ngp', 'ngpc', 'wonderswan', 'wonderswancolor']

    # Touch screen
    touch = ['nds', 'n3ds', 'psvita']

    support = []

    if system in standard:
        support.append("Standard Controller")
    if system in motion:
        support.append("Motion Controls")
    if system in handheld:
        support.append("Built-in Controls")
    if system in touch:
        support.append("Touch Screen")

    # Note: Multiplayer is a game mode, not a controller type - handled in 'modes' field

    return ', '.join(support) if support else None


# =============================================================================
# HYBRID APPLY METADATA
# =============================================================================

def _normalize_ratings(metadata, result):
    """Run the three rating-normalisation steps the save block needs:

    1. Normalize ESRB to its canonical letter (KA → E, etc).
    2. Cross-map empty rating fields from any available rating
       (e.g. ESRB→PEGI, GRAC→ESRB) via `services.game_metadata_service.
       cross_map_ratings`. 'RP' is treated as empty inside that helper.
    3. Content-based inference as a final fallback when no rating
       system has been filled at all (`infer_rating_from_content`).

    Mutates `metadata` in place; appends descriptive entries to
    `result['filled_fields']` for every change. Pass 38.1 partial —
    extracted from the inline NORMALIZE VALUES BEFORE SAVE block.
    """
    # Normalize ESRB (KA → E, etc) before cross-mapping fires.
    if metadata.get('esrb_rating'):
        metadata['esrb_rating'] = normalize_esrb_rating(metadata['esrb_rating'])

    # Cross-map empty rating fields from any available rating.
    _bare = {k: metadata.get(RATING_SYSTEMS[k]['db_column']) for k in RATING_SYSTEM_KEYS}
    _filled = cross_map_ratings(_bare)
    for tgt_key in RATING_SYSTEM_KEYS:
        tgt_col = RATING_SYSTEMS[tgt_key]['db_column']
        new_val = _filled.get(tgt_key)
        if new_val and new_val != (_bare.get(tgt_key) or ''):
            metadata[tgt_col] = new_val
            tgt_name = RATING_SYSTEMS[tgt_key]['name']
            result['filled_fields'].append(f'{tgt_col} (cross-map→{tgt_name})')
            logger.info(f"Auto-mapped rating → {tgt_name} '{new_val}'")

    # Content-based rating inference (final fallback when nothing else fills).
    has_any_rating = any(
        metadata.get(RATING_SYSTEMS[k]['db_column']) not in (None, '', 'RP', 'rp')
        for k in RATING_SYSTEM_KEYS
    )
    if not has_any_rating:
        inferred = infer_rating_from_content(metadata)
        if inferred:
            for col, val in inferred.items():
                metadata[col] = val
            result['filled_fields'].append('ratings (inferred from content)')
            logger.info(
                f"Inferred ratings from content: tier mapped to {len(inferred)} systems"
            )


def _build_scrape_history_json(c, db_game_id, primary_source, metadata,
                                result, force_overwrite):
    """Read the existing `games.scrape_history` JSON for `db_game_id`,
    append a new entry summarising this scrape, and return the
    serialised JSON ready for the save UPDATE.

    Pass 38.1 partial — extracted from the inline "CREATE SCRAPE HISTORY"
    block inside `apply_hybrid_metadata`. The helper takes the caller's
    cursor (no separate connection) so this stays inside the outer
    transaction's lifetime; the saved row carries the same scrape_history
    snapshot regardless of where the helper lives.

    `existing_history` is robust against malformed JSON (rolled back to
    `[]`) so a one-time DB corruption doesn't abort the scrape — the
    entry just becomes the first of a fresh history list.
    """
    import json
    from datetime import datetime

    # `scrape_history` is part of the baseline games schema (migration 001),
    # so it is always present on any DB that reached this code path.
    c.execute("SELECT scrape_history FROM games WHERE id = ? LIMIT 1", (db_game_id,))
    row = c.fetchone()
    existing_history = []
    if row and row[0]:
        try:
            existing_history = json.loads(row[0])
        except (ValueError, TypeError):
            existing_history = []

    history_entry = {
        'timestamp': datetime.now().isoformat(),
        'primary_source': primary_source,
        'sources_used': result['sources_used'],
        'fields_filled': result['filled_fields'],
        'fields_missing': [k for k, v in metadata.items() if not v],
        'scrape_mode': 'full_rescrape' if force_overwrite else 'fill_missing',
    }
    existing_history.append(history_entry)
    return json.dumps(existing_history)


def _normalize_region(metadata, result):
    """Reduce `metadata['region']` to a single value, falling back to the
    user's `default_region` setting (default 'USA').

    Two cases handled:
      - Multi-value ('USA, Europe, Japan'): pick the first part that
        matches a configured region option, else `default_region`.
      - Empty: use `default_region` and record `'region (default)'` in
        `result['filled_fields']`.
      - Single-value: leave untouched.

    Pass 38.1 partial — extracted from the inline normalize block in
    `apply_hybrid_metadata`. The original loaded settings twice (once
    per branch); here it's loaded once. `settings_manager.load_settings`
    is cached internally, so the perf delta is nil; the visible win is
    one try/except instead of two.
    """
    try:
        from settings_manager import load_settings as _load_settings
        _stg = _load_settings()
        region_opts = [
            r.lower()
            for r in _stg.get('region_options', ['USA', 'Europe', 'Japan', 'World'])
        ]
        default_region = _stg.get('default_region', 'USA')
    except Exception:
        region_opts = ['usa', 'europe', 'japan', 'world']
        default_region = 'USA'

    region_value = metadata.get('region') or ''
    if region_value:
        if ',' in region_value:
            parts = [p.strip() for p in region_value.split(',') if p.strip()]
            matched = next((p for p in parts if p.lower() in region_opts), None)
            metadata['region'] = matched or default_region
        # Single-value path: leave as-is.
    else:
        metadata['region'] = default_region
        result['filled_fields'].append('region (default)')


def _apply_retroachievements_check(db_game_id, title, system_folder):
    """Look up RetroAchievements support for `(title, system_folder)` and
    update the games row if found. Returns True when RA data was written
    (caller should append 'retroachievements' to its filled_fields list).

    Pass 38.1 partial extraction — this block was inline at the tail of
    apply_hybrid_metadata; it opens its own connection (independent of
    the caller's transaction) and silently swallows exceptions to keep
    a missing/down RA service from poisoning the rest of the scrape.
    """
    try:
        from scraper.retroachievements import check_retroachievements
        ra_info = check_retroachievements(title, system_folder)
        if not (ra_info and ra_info.get('has_achievements')):
            return False
        conn2 = get_scraper_conn()
        try:
            c2 = conn2.cursor()
            c2.execute("""
                UPDATE games SET
                    has_retroachievements = 1,
                    ra_game_id = ?,
                    ra_achievement_count = ?,
                    ra_points = ?
                WHERE id = ?
            """, (
                ra_info.get('id'),
                ra_info.get('achievement_count', 0),
                ra_info.get('points', 0),
                db_game_id,
            ))
            conn2.commit()
        finally:
            conn2.close()
        logger.info(
            f"Found RetroAchievements for game {db_game_id}: "
            f"ID={ra_info.get('id')}, "
            f"{ra_info.get('achievement_count')} achievements, "
            f"{ra_info.get('points')} points"
        )
        return True
    except Exception as e:
        logger.debug(f"RetroAchievements check skipped: {e}")
        return False


def _normalize_players_and_sort_title(metadata):
    """Final pre-save normalization for two derived fields.

    - players: scraper/AI sources hand back ranges ("1-2", "1-4") or prose
      ("2 players"); the DB column is INTEGER, so reduce to the max integer
      present (the documented contract — see CLAUDE.md "Schema / data
      shapes"). A value with no digits is cleared to None.
    - sort_title: regenerated from the (possibly newly-filled) title via
      generate_sort_title so library sorting stays correct.

    Pass 38.1 partial extraction — was inline in the NORMALIZE VALUES block
    of apply_hybrid_metadata.
    """
    if metadata.get('players'):
        nums = re.findall(r'\d+', str(metadata['players']))
        if nums:
            metadata['players'] = max(int(n) for n in nums)
        else:
            metadata['players'] = None

    if metadata.get('title'):
        metadata['sort_title'] = generate_sort_title(metadata['title'])


def _save_game_row(c, metadata, scrape_history_json, db_game_id):
    """Write the assembled metadata back to the games row (fill-only).

    Pops the internal `_boxart_source` tracking key, JSON-encodes
    `alternate_titles`, then issues the COALESCE-guarded UPDATE so an empty
    metadata field preserves the existing DB value (the scraper fill-only
    invariant). `scrape_history` and `scraped` are set unconditionally.
    Uses the caller's cursor — the caller owns the transaction / commit.

    Pass 38.1 partial extraction — was the SAVE TO DATABASE block inline in
    apply_hybrid_metadata.
    """
    # Remove internal tracking field before saving
    metadata.pop('_boxart_source', None)

    # Encode alternate_titles list → JSON for storage
    alt_titles_json = None
    if metadata.get('alternate_titles'):
        try:
            alt_titles_json = json.dumps(metadata['alternate_titles'])
        except (TypeError, ValueError) as _e:
            logger.warning(f"Failed to JSON-encode alternate_titles: {_e}")
            alt_titles_json = None

    # Fill-only writes across the full metadata dict. Do NOT wrap this in a
    # try/except fallback — a failure here means the metadata dict and the
    # UPDATE bindings have diverged (new field in merger, no column), and
    # the scraper must fail loudly so the drift is caught in review.
    c.execute("""
        UPDATE games SET
            title = COALESCE(?, title),
            sort_title = COALESCE(?, sort_title),
            publisher = COALESCE(?, publisher),
            developer = COALESCE(?, developer),
            release_date = COALESCE(?, release_date),
            genre = COALESCE(?, genre),
            description = COALESCE(?, description),
            players = COALESCE(?, players),
            modes = COALESCE(?, modes),
            esrb_rating = COALESCE(?, esrb_rating),
            pegi_rating = COALESCE(?, pegi_rating),
            cero_rating = COALESCE(?, cero_rating),
            usk_rating = COALESCE(?, usk_rating),
            acb_rating = COALESCE(?, acb_rating),
            fpb_rating = COALESCE(?, fpb_rating),
            grac_rating = COALESCE(?, grac_rating),
            classind_rating = COALESCE(?, classind_rating),
            boxart = COALESCE(?, boxart),
            boxart_3d = COALESCE(?, boxart_3d),
            screenshots = COALESCE(?, screenshots),
            fanart = COALESCE(?, fanart),
            video = COALESCE(?, video),
            manual = COALESCE(?, manual),
            region = COALESCE(?, region),
            franchise = COALESCE(?, franchise),
            similar_games = COALESCE(?, similar_games),
            playtime_estimate = COALESCE(?, playtime_estimate),
            controller_support = COALESCE(?, controller_support),
            save_type = COALESCE(?, save_type),
            game_structure = COALESCE(?, game_structure),
            perspective = COALESCE(?, perspective),
            dimension = COALESCE(?, dimension),
            edition = COALESCE(?, edition),
            campaign = COALESCE(?, campaign),
            other_platforms = COALESCE(?, other_platforms),
            critic_score = COALESCE(?, critic_score),
            critic_score_count = COALESCE(?, critic_score_count),
            user_score = COALESCE(?, user_score),
            user_score_count = COALESCE(?, user_score_count),
            alternate_titles = COALESCE(?, alternate_titles),
            scrape_history = ?,
            scraped = 1
        WHERE id = ?
    """, (
        metadata['title'],
        metadata.get('sort_title'),
        metadata['publisher'],
        metadata['developer'],
        metadata['release_date'],
        metadata['genre'],
        metadata['description'],
        metadata['players'],
        metadata['modes'],
        metadata['esrb_rating'],
        metadata['pegi_rating'],
        metadata.get('cero_rating'),
        metadata.get('usk_rating'),
        metadata.get('acb_rating'),
        metadata.get('fpb_rating'),
        metadata.get('grac_rating'),
        metadata.get('classind_rating'),
        metadata['boxart'],
        metadata['boxart_3d'],
        metadata['screenshots'],
        metadata['fanart'],
        metadata['video'],
        metadata['manual'],
        metadata['region'],
        metadata['franchise'],
        metadata['similar_games'],
        metadata['playtime_estimate'],
        metadata['controller_support'],
        metadata['save_type'],
        metadata.get('game_structure'),
        metadata.get('perspective'),
        metadata.get('dimension'),
        metadata.get('edition'),
        metadata.get('campaign'),
        metadata.get('other_platforms'),
        metadata.get('critic_score'),
        metadata.get('critic_score_count'),
        metadata.get('user_score'),
        metadata.get('user_score_count'),
        alt_titles_json,
        scrape_history_json,
        db_game_id
    ))


def _run_fallbacks(metadata, result, sources_data, game, db_game_id,
                   primary_source, system_folder, secondary_sources,
                   restrict_to_selected, force_overwrite, c):
    """Fill still-empty metadata fields from secondary scrapers.

    Iterates the user's configured scraper priority (minus the primary and
    any disabled / already-used source), searching each for the game and
    applying its data fill-only into `metadata`. Honours
    `restrict_to_selected` (limit fallbacks to the user-selected
    secondary_sources, plus AI). Mutates `metadata`, `result`, and
    `sources_data` in place; uses the caller's cursor `c` for the
    system-name lookup. Each per-source attempt is isolated in try/except
    so one provider failing doesn't abort the rest.

    Pass 38.1 partial extraction — was the FILL GAPS FROM SECONDARY
    SOURCES block (under `if fill_gaps:`) inline in apply_hybrid_metadata.
    """
    missing = [k for k, v in metadata.items() if not v]

    # Get game title for searching other scrapers
    # Prefer the metadata title from the primary source (user's selection)
    # since it's the canonical title they chose. This ensures fallback
    # scrapers match the correct game (e.g. "Rambo: First Blood Part II"
    # instead of "Rambo III" when ROM filename is just "Rambo").
    # Fall back to ROM filename only when no metadata title is available.
    selected_title = metadata.get('title') or ''

    if selected_title:
        game_title = selected_title
        logger.info(f"Using selected game title for fallback search: '{game_title}'")
    else:
        rom_path = game.get('rom_path', '')
        if rom_path:
            # Derive proper title from ROM filename
            filename = os.path.basename(rom_path)
            filename_no_ext = os.path.splitext(filename)[0]

            # Clean up filename for searching
            # Remove region tags
            search_title = re.sub(r'\s*\((?:USA|Europe|Japan|World|En|Fr|De|Es|It|U|E|J|W)\)', '', filename_no_ext, flags=re.IGNORECASE)
            # Remove disc indicators
            search_title = re.sub(r'\s*\(Disc\s*\d+(?:\s*of\s*\d+)?\)', '', search_title, flags=re.IGNORECASE)
            # Remove version tags
            search_title = re.sub(r'\s*\(Rev\s*\d*[A-Z]?\)', '', search_title, flags=re.IGNORECASE)
            search_title = re.sub(r'\s*\(v\d+\.?\d*\)', '', search_title, flags=re.IGNORECASE)
            # Convert ' - ' back to ': ' for proper title matching
            search_title = re.sub(r' - (?=[A-Z])', ': ', search_title)
            search_title = search_title.strip()

            game_title = search_title if search_title else game.get('title', '')
            logger.info(f"Using ROM filename-derived title for fallback search: '{game_title}' (from: {filename})")
        else:
            game_title = game.get('title', '')

    # Get system info for searching
    c.execute("SELECT s.name, s.folder FROM systems s JOIN games g ON g.system_id = s.id WHERE g.id = ?", (db_game_id,))
    sys_info = c.fetchone()
    system_name = sys_info[0] if sys_info else ''

    if missing and game_title:
        logger.info(f"Missing fields: {missing}")
        logger.info(f"Searching other scrapers for: '{game_title}' on {system_name}")

        # Get user's scraper priority from settings
        fallback_settings = load_scraper_settings()
        user_priority = fallback_settings.get('priority', ['screenscraper', 'esde', 'tgdb', 'igdb'])
        fallback_api_keys = fallback_settings.get('api_keys', {})
        fallback_enabled = fallback_settings.get('enabled', {})

        # Map internal names to priority list names
        source_name_map = {
            'screenscraper': 'screenscraper',
            'esde': 'esde',
            'tgdb': 'tgdb',
            'thegamesdb': 'tgdb',
            'igdb': 'igdb',
            'rawg': 'rawg'
        }

        # Get the normalized primary source name
        primary_normalized = source_name_map.get(primary_source, primary_source)

        # Build fallback list: user priority order, excluding primary and disabled scrapers
        fallback_scrapers = []
        for scraper in user_priority:
            scraper_normalized = source_name_map.get(scraper, scraper)
            # Skip if it's the primary source
            if scraper_normalized == primary_normalized:
                continue
            # Skip if already used
            if scraper_normalized in sources_data:
                continue
            # Skip if disabled
            if not fallback_enabled.get(scraper_normalized, True):
                continue
            fallback_scrapers.append(scraper_normalized)

        # When user explicitly selected secondary sources, restrict fallbacks
        # to only those scrapers (plus AI which is always allowed for gap-filling)
        if restrict_to_selected and secondary_sources:
            selected_scrapers = {s['source'] for s in secondary_sources}
            fallback_scrapers = [s for s in fallback_scrapers
                                 if s in selected_scrapers or s == 'ai']

        logger.info(f"Primary source: {primary_source} -> Fallback scrapers in priority order: {fallback_scrapers}")

        for fallback_source in fallback_scrapers:
            # Re-check missing fields
            missing = [k for k, v in metadata.items() if not v]
            if not missing:
                break  # All fields filled

            # Skip if scraper is disabled
            if not fallback_enabled.get(fallback_source, True):
                logger.info(f"Fallback scraper {fallback_source} is disabled, skipping")
                continue

            try:
                if fallback_source == 'esde':
                    # Try ES-DE fallback
                    logger.info(f"Trying ES-DE fallback for: '{game_title}'")
                    from scraper.scrape_esde import search_esde_games, fetch_esde_game_details, apply_esde_metadata as esde_apply
                    esde_results = search_esde_games(game_title, system_folder, limit=5)
                    esde_match = _pick_best_fallback(esde_results, game_title) if esde_results else None
                    if esde_match:
                        esde_path = esde_match.get('id')  # ES-DE uses 'id' which contains the path
                        if esde_path:
                            logger.info(f"Found ES-DE match: {esde_match.get('name')} (Path: {esde_path})")

                            esde_data = fetch_esde_game_details(esde_path, system_folder)
                            if esde_data:
                                sources_data['esde'] = esde_data
                                # Apply ES-DE metadata - pass force_overwrite for consistent behavior
                                esde_apply(db_game_id, esde_data, system_folder,
                                          existing_boxart=metadata.get('boxart'),
                                          existing_screenshots=metadata.get('screenshots'),
                                          force_overwrite=force_overwrite)
                                if 'ES-DE' not in result['sources_used']:
                                    result['sources_used'].append('ES-DE')
                            else:
                                logger.info("ES-DE fallback: failed to fetch game details")
                        else:
                            logger.info("ES-DE fallback: no path found in result")
                    else:
                        logger.info(f"ES-DE fallback: no results found for '{game_title}'")

                elif fallback_source == 'tgdb':
                    logger.info(f"Trying TGDB fallback for: '{game_title}'")
                    tgdb_id = None

                    # First check if we have it in secondary_sources
                    # Pick the best title match (not just the first result)
                    if secondary_sources:
                        tgdb_candidates = [s for s in secondary_sources if s['source'] == 'tgdb']
                        tgdb_info = _pick_best_secondary(tgdb_candidates, game_title)
                        if tgdb_info:
                            tgdb_id = tgdb_info['id']

                    # If not, search for it (fetch multiple and pick best match)
                    if not tgdb_id:
                        from scraper.scrape_thegamesdb import search_games as search_tgdb
                        tgdb_results = search_tgdb(game_title, system_name, limit=5)
                        tgdb_match = _pick_best_fallback(tgdb_results, game_title)
                        if tgdb_match:
                            tgdb_id = tgdb_match.get('id')
                            logger.info(f"Found TGDB match: {tgdb_match.get('name')} (ID: {tgdb_id})")
                        else:
                            logger.info(f"TGDB fallback: no results found for '{game_title}'")

                    if tgdb_id:
                        tgdb_data = fetch_tgdb_extended(tgdb_id)
                        if tgdb_data:
                            sources_data['tgdb'] = tgdb_data
                            apply_tgdb_to_metadata(metadata, tgdb_data, db_game_id, result, fill_only=True)
                            if 'TheGamesDB' not in result['sources_used']:
                                result['sources_used'].append('TheGamesDB')

                elif fallback_source == 'igdb':
                    logger.info(f"Trying IGDB fallback for: '{game_title}'")
                    igdb_id = None

                    # First check if we have it in secondary_sources
                    # Pick the best title match (not just the first result)
                    if secondary_sources:
                        igdb_candidates = [s for s in secondary_sources if s['source'] == 'igdb']
                        igdb_info = _pick_best_secondary(igdb_candidates, game_title)
                        if igdb_info:
                            igdb_id = igdb_info['id']

                    # If not, search for it (fetch multiple and pick best match)
                    if not igdb_id:
                        from scraper.scrape_igdb import search_games as search_igdb
                        igdb_results = search_igdb(game_title, system_name, limit=5)
                        igdb_match = _pick_best_fallback(igdb_results, game_title)
                        if igdb_match:
                            igdb_id = igdb_match.get('id')
                            logger.info(f"Found IGDB match: {igdb_match.get('name')} (ID: {igdb_id})")
                        else:
                            logger.info(f"IGDB fallback: no results found for '{game_title}'")

                    if igdb_id:
                        igdb_data = fetch_igdb_extended(igdb_id)
                        if igdb_data:
                            sources_data['igdb'] = igdb_data
                            apply_igdb_to_metadata(metadata, igdb_data, db_game_id, result, fill_only=True)
                            if 'IGDB' not in result['sources_used']:
                                result['sources_used'].append('IGDB')

                elif fallback_source == 'screenscraper':
                    ss_username = fallback_api_keys.get('screenscraper_username', '')
                    ss_password = fallback_api_keys.get('screenscraper_password', '')
                    ss_devid = fallback_api_keys.get('screenscraper_devid', '')
                    ss_devpassword = fallback_api_keys.get('screenscraper_devpassword', '')

                    if not ss_username or not ss_password:
                        logger.info("ScreenScraper fallback skipped: missing credentials")
                    else:
                        logger.info(f"Trying ScreenScraper fallback for: '{game_title}'")
                        from scraper.scrape_screenscraper import search_game, get_system_id
                        ss_data = None

                        # First check if we have a cached result from the initial search
                        # Pick the best title match (not just the first result)
                        if secondary_sources:
                            ss_candidates = [s for s in secondary_sources if s['source'] == 'screenscraper']
                            ss_info = _pick_best_secondary(ss_candidates, game_title)
                            if ss_info and ss_info.get('id'):
                                from scraper.scraper_manager import get_cached_screenscraper_result
                                ss_id_parts = str(ss_info['id']).split(':')
                                ss_cached = get_cached_screenscraper_result(
                                    ss_id_parts[0],
                                    ss_id_parts[1] if len(ss_id_parts) > 1 else None
                                )
                                if ss_cached:
                                    ss_data = ss_cached
                                    logger.info(f"Using cached ScreenScraper result from initial search (ID: {ss_info['id']})")

                        # If no cached result, search for it
                        if not ss_data:
                            ss_system_id = get_system_id(system_folder)
                            if not ss_system_id:
                                logger.warning(f"ScreenScraper fallback: no system ID found for {system_folder}")
                            else:
                                ss_results = search_game(
                                    game_title, system_folder,
                                    ss_username, ss_password,
                                    ss_devid, ss_devpassword
                                )
                                if ss_results:
                                    ss_data = _pick_best_fallback(ss_results, game_title) if len(ss_results) > 1 else ss_results[0]
                                else:
                                    logger.info(f"ScreenScraper fallback: no results found for '{game_title}'")

                        if ss_data:
                            logger.info(f"Found ScreenScraper match: {ss_data.get('nom', 'Unknown')} (ID: {ss_data.get('id')})")
                            sources_data['screenscraper'] = ss_data
                            apply_screenscraper_to_metadata(metadata, ss_data, db_game_id, result, fill_only=True)
                            if 'ScreenScraper' not in result['sources_used']:
                                result['sources_used'].append('ScreenScraper')

                elif fallback_source == 'rawg':
                    rawg_api_key = fallback_api_keys.get('rawg_api_key', '') or fallback_api_keys.get('rawg', '')
                    if not rawg_api_key:
                        logger.info("RAWG fallback skipped: missing API key")
                    else:
                        logger.info(f"Trying RAWG fallback for: '{game_title}'")
                        from scraper.scrape_rawg import search_games as search_rawg, get_game_details as fetch_rawg
                        rawg_id = None

                        # First check if we have it in secondary_sources
                        # Pick the best title match (not just the first result)
                        if secondary_sources:
                            rawg_candidates = [s for s in secondary_sources if s['source'] == 'rawg']
                            rawg_info = _pick_best_secondary(rawg_candidates, game_title)
                            if rawg_info:
                                rawg_id = rawg_info['id']

                        rawg_match = None
                        if not rawg_id:
                            rawg_results = search_rawg(game_title, system_folder, limit=5)
                            rawg_match = _pick_best_fallback(rawg_results, game_title)
                            if rawg_match:
                                rawg_id = rawg_match.get('id')

                        if rawg_id:
                            logger.info(f"Found RAWG match: {rawg_match.get('name') if rawg_match else 'from secondary'} (ID: {rawg_id})")
                            rawg_details = fetch_rawg(rawg_id)
                            if rawg_details:
                                sources_data['rawg'] = rawg_details
                                apply_rawg_to_metadata(metadata, rawg_details, db_game_id, result, fill_only=True)
                                result['sources_used'].append('RAWG')
                        else:
                            logger.info(f"RAWG fallback: no results found for '{game_title}'")

                elif fallback_source == 'ai':
                    if not AI_AVAILABLE:
                        logger.info("AI fallback skipped: module not available")
                    elif not fallback_enabled.get('ai', False):
                        logger.info("AI fallback skipped: disabled in settings")
                    else:
                        logger.info(f"Trying AI fallback for: '{game_title}'")
                        # Build existing metadata snapshot for AI to know what's missing
                        ai_existing = {k: v for k, v in metadata.items() if v}
                        # Pass 26.3 — wrap AI call in the circuit breaker so
                        # repeated provider failures skip the call entirely
                        # for the recovery window instead of hitting the API
                        # on every gap-fill attempt.
                        from scraper.scraper_manager import _ai_breaker
                        ai_data = _ai_breaker(fetch_ai_metadata)(
                            db_game_id, game_title, system_name,
                            system_folder, existing_metadata=ai_existing
                        )
                        if ai_data:
                            sources_data['ai'] = ai_data
                            apply_ai_to_metadata(metadata, ai_data, db_game_id, result, fill_only=True)
                            if 'AI' not in result['sources_used']:
                                result['sources_used'].append('AI')
                        else:
                            logger.info(f"AI fallback: no results for '{game_title}'")

            except Exception as fallback_error:
                logger.warning(f"Fallback scraper {fallback_source} failed: {fallback_error}")


def apply_hybrid_metadata(db_game_id, primary_source, primary_id, system_folder,
                          secondary_sources=None, fill_gaps=True, force_overwrite=False,
                          primary_data=None, restrict_to_selected=False):
    """
    Apply metadata from primary source, then fill gaps from secondary sources.

    Args:
        db_game_id: Database ID of the game
        primary_source: 'esde', 'tgdb', or 'igdb'
        primary_id: ID/path for the primary source
        system_folder: System folder name for ES-DE lookups
        secondary_sources: List of dicts with 'source' and 'id' for fallback
        fill_gaps: If True, automatically search other scrapers for missing data
        force_overwrite: If True, overwrite existing data (for full re-scrape)
        primary_data: Optional dict with the selected result's data (avoids re-fetching)
        restrict_to_selected: If True, only use scrapers present in secondary_sources
            (no fresh searches for unselected scrapers)

    Returns:
        dict with 'success', 'filled_fields', 'missing_fields'
    """
    conn = get_scraper_conn()
    c = conn.cursor()

    result = {
        'success': False,
        'filled_fields': [],
        'missing_fields': [],
        'sources_used': []
    }

    try:
        # Get current game data
        c.execute("SELECT * FROM games WHERE id = ?", (db_game_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            result['success'] = False
            return result
        game = dict(row)

        # Initialize metadata dict
        metadata = {
            'title': None,
            'publisher': None,
            'developer': None,
            'release_date': None,
            'genre': None,
            'description': None,
            'players': None,
            'modes': None,
            'esrb_rating': None,
            'pegi_rating': None,
            'cero_rating': None,
            'usk_rating': None,
            'acb_rating': None,
            'fpb_rating': None,
            'grac_rating': None,
            'classind_rating': None,
            'boxart': None,
            'boxart_3d': None,
            'screenshots': None,
            'fanart': None,
            'video': None,
            'manual': None,
            'region': None,
            'franchise': None,
            'similar_games': None,
            'playtime_estimate': None,
            'controller_support': None,
            'save_type': None,
            'game_structure': None,
            'perspective': None,
            'dimension': None,
            'edition': None,
            'campaign': None,
            'other_platforms': None,
            'critic_score': None,
            'critic_score_count': None,
            'user_score': None,
            'user_score_count': None,
            'alternate_titles': None,
        }

        # Pre-populate metadata from existing database values (for cumulative scraping)
        # This ensures subsequent scrapes only fill gaps, not replace existing data
        # UNLESS force_overwrite is True (full re-scrape mode)
        if not force_overwrite:
            import json as _json_prepop
            for field in metadata:
                existing_value = game.get(field)
                if existing_value:
                    # alternate_titles is stored as JSON in DB — decode to list
                    # so per-source mergers can append into it.
                    if field == 'alternate_titles':
                        try:
                            parsed = _json_prepop.loads(existing_value)
                            metadata[field] = parsed if isinstance(parsed, list) else None
                        except (ValueError, TypeError):
                            metadata[field] = None
                    else:
                        metadata[field] = existing_value
                    # Don't add to filled_fields since these are pre-existing

            # Validate media files exist on disk — clear stale DB references
            # so scrapers can re-download missing files
            _media_dirs = {
                'boxart': os.path.join(IMAGE_PATH, 'boxart'),
                'boxart_3d': os.path.join(IMAGE_PATH, 'boxart_3d'),
                'fanart': os.path.join(IMAGE_PATH, 'fanart'),
                'manual': os.path.join(IMAGE_PATH, 'manuals'),
            }
            # Pass 40.15 — capture the (field, stale_filename) we observed at
            # stat time so the UPDATE only NULLs the cell when it still holds
            # that exact value.  Otherwise a concurrent upload between stat
            # and UPDATE gets its new reference wiped and the file orphaned.
            stale_media = []  # list of (field, stale_filename)
            for field, directory in _media_dirs.items():
                value = metadata.get(field)
                if value:
                    if not os.path.exists(os.path.join(directory, value)):
                        logger.warning(f"Media file missing from disk, clearing: {field}={value}")
                        metadata[field] = None
                        stale_media.append((field, value))

            # Video lives in STATIC_PATH/videos/
            video_value = metadata.get('video')
            if video_value:
                if not os.path.exists(os.path.join(STATIC_PATH, 'videos', video_value)):
                    logger.warning(f"Media file missing from disk, clearing: video={video_value}")
                    metadata['video'] = None
                    stale_media.append(('video', video_value))

            # Screenshots: filter out individual missing files
            screenshots_value = metadata.get('screenshots')
            if screenshots_value:
                ss_dir = os.path.join(IMAGE_PATH, 'screenshots')
                ss_list = [s.strip() for s in screenshots_value.split(',') if s.strip()]
                valid_ss = [s for s in ss_list if os.path.exists(os.path.join(ss_dir, s))]
                if len(valid_ss) < len(ss_list):
                    missing = [s for s in ss_list if s not in valid_ss]
                    logger.warning(f"Screenshot files missing from disk, removing: {missing}")
                    metadata['screenshots'] = ', '.join(valid_ss) if valid_ss else None
                    stale_media.append(('screenshots', screenshots_value))

            # Clear stale references from DB so COALESCE doesn't restore them.
            # Pass 40.15 — the conditional `AND <field> = ?` WHERE protects
            # against a concurrent upload that may have replaced the value
            # between our os.path.exists check and this write.  Without it
            # the new reference gets NULL'd and the just-uploaded file becomes
            # an orphan that the next media-cleanup sweep will delete.
            if stale_media:
                for field, stale_filename in stale_media:
                    c.execute(
                        f"UPDATE games SET {field} = NULL "
                        f"WHERE id = ? AND {field} = ?",
                        (db_game_id, stale_filename),
                    )
                conn.commit()
                logger.info(
                    f"Cleared {len(stale_media)} stale media reference(s) from DB: "
                    f"{[f for f, _ in stale_media]}"
                )
        else:
            logger.info(f"Force overwrite mode - starting with empty metadata for game {db_game_id}")
            # Pass 48.1 — even in force mode, validate the DB's existing media
            # against disk and NULL any reference whose file is gone. Force mode
            # starts from empty metadata, so the apply COALESCE would otherwise
            # restore a stale reference to a deleted file whenever no source
            # supplies replacement media. Mirrors the fill-path stale-clear above
            # but reads from the DB row (`game`) since metadata is empty here.
            _media_dirs = {
                'boxart': os.path.join(IMAGE_PATH, 'boxart'),
                'boxart_3d': os.path.join(IMAGE_PATH, 'boxart_3d'),
                'fanart': os.path.join(IMAGE_PATH, 'fanart'),
                'manual': os.path.join(IMAGE_PATH, 'manuals'),
            }
            _force_stale = []  # list of (field, stale_filename)
            for field, directory in _media_dirs.items():
                value = game.get(field)
                if value and not os.path.exists(os.path.join(directory, value)):
                    _force_stale.append((field, value))
            video_value = game.get('video')
            if video_value and not os.path.exists(os.path.join(STATIC_PATH, 'videos', video_value)):
                _force_stale.append(('video', video_value))
            # Screenshots: clear the column only when EVERY referenced file is
            # gone (single-value clears can't express a partial prune here).
            ss_value = game.get('screenshots')
            if ss_value:
                ss_dir = os.path.join(IMAGE_PATH, 'screenshots')
                ss_list = [s.strip() for s in ss_value.split(',') if s.strip()]
                if ss_list and not any(os.path.exists(os.path.join(ss_dir, s)) for s in ss_list):
                    _force_stale.append(('screenshots', ss_value))
            if _force_stale:
                for field, stale_filename in _force_stale:
                    c.execute(
                        f"UPDATE games SET {field} = NULL WHERE id = ? AND {field} = ?",
                        (db_game_id, stale_filename),
                    )
                conn.commit()
                logger.info(
                    f"Force mode: cleared {len(_force_stale)} stale media reference(s): "
                    f"{[f for f, _ in _force_stale]}"
                )

        sources_data = {}

        # =============================================
        # FETCH DATA FROM PRIMARY SOURCE
        # =============================================

        logger.info(f"Fetching from primary source: {primary_source}")

        if primary_source == 'esde':
            # Pass 41.4.B (ES-DE branch) — guard the ES-DE primary dispatch
            # with the same per-source try/except contract used for tgdb/igdb/
            # rawg/screenscraper below. A malformed gamelist.xml row or a
            # transient filesystem error during media copy must not abort the
            # hybrid apply; on failure, fall through to the gap-fill phase.
            esde_details = None
            try:
                # For ES-DE, we need to fetch the game details from gamelist.xml first
                from scraper.scrape_esde import fetch_esde_game_details, apply_esde_metadata as apply_esde

                # If primary_data was provided (from search results), use it directly
                # This fixes the bug where selecting an ES-DE result would fetch the wrong game
                if primary_data and primary_data.get('source') == 'esde':
                    logger.info(f"Using provided ES-DE data for: {primary_data.get('name', 'Unknown')}")
                    esde_details = {
                        'name': primary_data.get('name', ''),
                        'description': primary_data.get('description', ''),
                        'developer': primary_data.get('developer', ''),
                        'publisher': primary_data.get('publisher', ''),
                        'genre': primary_data.get('genre', ''),
                        'release_date': primary_data.get('release_date', ''),
                        'players': primary_data.get('players', ''),
                        'esde_data': primary_data.get('esde_data', {})
                    }
                else:
                    logger.info(f"Fetching ES-DE details for path: {primary_id}, folder: {system_folder}")
                    esde_details = fetch_esde_game_details(primary_id, system_folder)
            except Exception as e:
                logger.warning(f"Primary ES-DE fetch failed for {primary_id}: {e}; "
                               "falling through to gap-fill")
                esde_details = None
            # `esde_details is None` already gates the apply block below; with
            # the fetch inside try/except, an exception drops us into that
            # else-branch (logged) without aborting the rest of the function.

            if esde_details:
                logger.info(f"ES-DE details found: {esde_details.get('name', 'Unknown')}")

                # Apply ES-DE data to metadata
                # As the primary (user-selected) source, always set title
                # (matching IGDB/RAWG behavior). Other fields fill only if empty.
                if esde_details.get('name'):
                    metadata['title'] = normalize_title(esde_details['name'])
                    result['filled_fields'].append('title (ES-DE)')
                if esde_details.get('description') and not metadata['description']:
                    metadata['description'] = esde_details['description']
                    result['filled_fields'].append('description (ES-DE)')
                if esde_details.get('developer') and not metadata['developer']:
                    metadata['developer'] = esde_details['developer']
                    result['filled_fields'].append('developer (ES-DE)')
                if esde_details.get('publisher') and not metadata['publisher']:
                    metadata['publisher'] = esde_details['publisher']
                    result['filled_fields'].append('publisher (ES-DE)')
                if esde_details.get('genre') and not metadata['genre']:
                    metadata['genre'] = normalize_genre(esde_details['genre'])
                    result['filled_fields'].append('genre (ES-DE)')
                if esde_details.get('release_date') and not metadata['release_date']:
                    metadata['release_date'] = esde_details['release_date']
                    result['filled_fields'].append('release_date (ES-DE)')
                if esde_details.get('players') and not metadata['players']:
                    metadata['players'] = esde_details['players']
                    result['filled_fields'].append('players (ES-DE)')

                # Now apply ES-DE media (boxart, screenshots, etc.) - pass existing metadata
                # Pass force_overwrite to ensure media is replaced in full rescrape mode
                apply_esde(db_game_id, esde_details.get('esde_data', {}), system_folder,
                          existing_boxart=metadata.get('boxart'),
                          existing_screenshots=metadata.get('screenshots'),
                          force_overwrite=force_overwrite)

                # Refresh game data from DB
                c.execute("SELECT * FROM games WHERE id = ?", (db_game_id,))
                game = dict(c.fetchone())

                # Update metadata with any media that was copied (verify files exist)
                _media_dir_map = {
                    'boxart': os.path.join(IMAGE_PATH, 'boxart'),
                    'boxart_3d': os.path.join(IMAGE_PATH, 'boxart_3d'),
                    'fanart': os.path.join(IMAGE_PATH, 'fanart'),
                    'manual': os.path.join(IMAGE_PATH, 'manuals'),
                    'video': os.path.join(STATIC_PATH, 'videos'),
                    'screenshots': os.path.join(IMAGE_PATH, 'screenshots'),
                }
                # Pass 41.4.A — screenshots are appended (not replaced) by
                # apply_esde_metadata, so the DB value after the apply is the
                # union of pre-existing + newly-scraped. The earlier
                # `if not metadata.get(field)` guard treated a pre-populated
                # metadata['screenshots'] as "no need to sync", silently
                # dropping the appended scrape on the final UPDATE. Sync
                # screenshots unconditionally, file-existence filtered.
                if game.get('screenshots'):
                    ss_list = [s.strip() for s in game['screenshots'].split(',') if s.strip()]
                    valid = [s for s in ss_list if os.path.exists(
                        os.path.join(_media_dir_map['screenshots'], s)
                    )]
                    if valid:
                        metadata['screenshots'] = ', '.join(valid)
                        if 'screenshots (ES-DE)' not in result['filled_fields']:
                            result['filled_fields'].append('screenshots (ES-DE)')
                for field in ['boxart', 'boxart_3d', 'fanart', 'video', 'manual']:
                    if game.get(field) and not metadata.get(field):
                        if not os.path.exists(os.path.join(_media_dir_map[field], game[field])):
                            continue
                        metadata[field] = game[field]
                        if field == 'boxart':
                            metadata['_boxart_source'] = 'esde'
                        if f'{field} (ES-DE)' not in result['filled_fields']:
                            result['filled_fields'].append(f'{field} (ES-DE)')

                result['sources_used'].append('ES-DE')
            else:
                logger.warning(f"No ES-DE details found for path: {primary_id}")

        # Pass 41.4.B — wrap each primary-source dispatch in try/except so a
        # malformed response from one provider doesn't abort the whole hybrid
        # apply. Log the failure and fall through to the gap-fill phase, which
        # may successfully populate the same fields from a fallback source.
        elif primary_source == 'tgdb':
            try:
                tgdb_data = fetch_tgdb_extended(primary_id)
                if tgdb_data:
                    sources_data['tgdb'] = tgdb_data
                    apply_tgdb_to_metadata(metadata, tgdb_data, db_game_id, result)
                    result['sources_used'].append('TheGamesDB')
            except Exception as e:
                logger.warning(f"Primary TGDB fetch/apply failed for {primary_id}: {e}; "
                               "falling through to gap-fill")

        elif primary_source == 'igdb':
            try:
                igdb_data = fetch_igdb_extended(primary_id)
                if igdb_data:
                    sources_data['igdb'] = igdb_data
                    apply_igdb_to_metadata(metadata, igdb_data, db_game_id, result)
                    result['sources_used'].append('IGDB')
            except Exception as e:
                logger.warning(f"Primary IGDB fetch/apply failed for {primary_id}: {e}; "
                               "falling through to gap-fill")

        elif primary_source == 'rawg':
            try:
                from scraper.scrape_rawg import get_game_details as fetch_rawg
                rawg_data = fetch_rawg(primary_id)
                if rawg_data:
                    sources_data['rawg'] = rawg_data
                    apply_rawg_to_metadata(metadata, rawg_data, db_game_id, result)
                    result['sources_used'].append('RAWG')
            except Exception as e:
                logger.warning(f"Primary RAWG fetch/apply failed for {primary_id}: {e}; "
                               "falling through to gap-fill")

        elif primary_source == 'screenscraper':
            try:
                from scraper.scraper_manager import get_cached_screenscraper_result
                settings = load_scraper_settings()
                api_keys = settings.get('api_keys', {})
                ss_username = api_keys.get('screenscraper_username', '')
                ss_password = api_keys.get('screenscraper_password', '')

                if ss_username and ss_password:
                    # Parse gameid:systemid format
                    ss_game_id = primary_id
                    ss_system_id = None
                    if ':' in str(primary_id):
                        parts = str(primary_id).split(':')
                        ss_game_id = parts[0]
                        ss_system_id = parts[1] if len(parts) > 1 else None

                    # Try to get cached search result first (ScreenScraper API doesn't support fetch by ID)
                    ss_data = get_cached_screenscraper_result(ss_game_id, ss_system_id)

                    if ss_data:
                        logger.info(f"Using cached ScreenScraper data for game {ss_game_id}")
                        sources_data['screenscraper'] = ss_data
                        apply_screenscraper_to_metadata(metadata, ss_data, db_game_id, result)
                        result['sources_used'].append('ScreenScraper')
                    else:
                        # Cache expired or not found - try ROM-based lookup as fallback
                        logger.warning(f"ScreenScraper cache miss for {ss_game_id}:{ss_system_id}, trying ROM-based lookup")
                        from scraper.scrape_screenscraper import get_game_info
                        rom_path = game.get('rom_path', '')
                        if rom_path and ss_system_id:
                            ss_devid = api_keys.get('screenscraper_devid', '')
                            ss_devpassword = api_keys.get('screenscraper_devpassword', '')
                            ss_data = get_game_info(rom_path, system_folder, ss_username, ss_password, ss_devid, ss_devpassword)
                            if ss_data and 'error' not in ss_data:
                                sources_data['screenscraper'] = ss_data
                                apply_screenscraper_to_metadata(metadata, ss_data, db_game_id, result)
                                result['sources_used'].append('ScreenScraper')
            except Exception as e:
                logger.warning(f"Primary ScreenScraper fetch/apply failed for {primary_id}: {e}; "
                               "falling through to gap-fill")

        # =============================================
        # FILL GAPS FROM SECONDARY SOURCES
        # =============================================

        if fill_gaps:
            _run_fallbacks(
                metadata, result, sources_data, game, db_game_id,
                primary_source, system_folder, secondary_sources,
                restrict_to_selected, force_overwrite, c,
            )

        # =============================================
        # DETECT ADDITIONAL METADATA
        # =============================================

        # Region from filename if not set
        if not metadata['region']:
            rom_path = game.get('rom_path', '')
            filename = os.path.basename(rom_path)
            metadata['region'] = extract_region_from_filename(filename)
            if metadata['region']:
                result['filled_fields'].append('region (filename)')

        # Pass 38.1 — region normalize extracted to _normalize_region.
        _normalize_region(metadata, result)


        # Save type detection
        if not metadata['save_type']:
            metadata['save_type'] = detect_save_type(system_folder, metadata.get('title', ''))
            if metadata['save_type']:
                result['filled_fields'].append('save_type (detected)')

        # Controller support detection
        if not metadata['controller_support']:
            metadata['controller_support'] = detect_controller_support(
                system_folder, metadata.get('modes', '')
            )
            if metadata['controller_support']:
                result['filled_fields'].append('controller_support (detected)')

        # Always prefer curated DB default controller over scraped/AI values
        c.execute("SELECT system_id FROM games WHERE id = ?", (db_game_id,))
        sys_row = c.fetchone()
        if sys_row:
            system_id = sys_row[0]
            default_controller = get_system_default_controller_name(system_id)
            if default_controller:
                old_value = metadata['controller_support']
                metadata['controller_support'] = default_controller
                if old_value and old_value != default_controller:
                    result['filled_fields'].append(f'controller_support (system default: {default_controller})')
                elif not old_value:
                    result['filled_fields'].append('controller_support (system default)')
                logger.info(f"Using system default controller: {default_controller} (was: {old_value})")
            elif should_use_default_controller(metadata['controller_support']):
                # No DB default exists — only clear generic values
                pass

        # Pass 38.1 — scrape-history build extracted to _build_scrape_history_json.
        scrape_history_json = _build_scrape_history_json(
            c, db_game_id, primary_source, metadata, result, force_overwrite
        )

        # =============================================
        # NORMALIZE VALUES BEFORE SAVE
        # =============================================

        # Pass 38.1 — rating normalize/cross-map/infer extracted to _normalize_ratings.
        _normalize_ratings(metadata, result)

        # Pass 38.1 — players range→max + sort_title regen extracted to
        # _normalize_players_and_sort_title.
        _normalize_players_and_sort_title(metadata)

        # =============================================
        # SAVE TO DATABASE
        # =============================================

        # Pass 38.1 — SAVE TO DATABASE block extracted to _save_game_row.
        _save_game_row(c, metadata, scrape_history_json, db_game_id)

        conn.commit()

        # Pass 38.1 — RA-check extracted to _apply_retroachievements_check.
        title_to_check = metadata['title'] or game.get('title', '')
        if _apply_retroachievements_check(db_game_id, title_to_check, system_folder):
            result['filled_fields'].append('retroachievements')

        # Calculate final missing fields
        result['missing_fields'] = [k for k, v in metadata.items() if not v]
        result['success'] = True

        logger.info(f"Hybrid metadata applied to game {db_game_id}")
        logger.info(f"Sources used: {result['sources_used']}")
        logger.info(f"Filled: {len(result['filled_fields'])}, Missing: {len(result['missing_fields'])}")

        return result

    except Exception as e:
        logger.error(f"Error applying hybrid metadata: {e}")
        conn.rollback()
        result['success'] = False
        return result
    finally:
        conn.close()
