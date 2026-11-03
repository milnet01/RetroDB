# =============================================================================
# HYBRID SCRAPER
# =============================================================================
# Combines metadata from ES-DE, TheGamesDB, and IGDB to fill all gaps
# =============================================================================

import contextvars
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import IMAGE_PATH, STATIC_PATH
from services.normalization import canonicalize_metadata
from services.release_dates import year_gap_with_own_region
from services.game_utils import generate_sort_title, infer_rating_from_content, RATING_SYSTEM_KEYS, RATING_SYSTEMS
from services.game_metadata_service import cross_map_ratings
from services.media_cleanup import media_dir_is_healthy
from services import apply_progress

logger = logging.getLogger(__name__)

# Source names as the Apply Metadata progress gauge shows them (PASS-59-108).
_PROGRESS_SOURCE_LABELS = {
    'esde': 'ES-DE', 'tgdb': 'TheGamesDB', 'igdb': 'IGDB', 'rawg': 'RAWG',
    'screenscraper': 'ScreenScraper', 'ai': 'AI', 'steam': 'Steam',
}

# Import individual scrapers
from scraper.base_scraper import get_scraper_conn
from scraper.scrape_esde import (
    extract_region_from_filename
)
from scraper.scrape_thegamesdb import (
    fetch_game_details as fetch_tgdb_details,
)
from scraper.scrape_igdb import (
    get_platform_id as get_igdb_platform_id,
    igdb_auth,
    igdb_request
)

# Import metadata merging functions (extracted to reduce file size)
from scraper.metadata_merger import (
    fill_labels,
    apply_tgdb_to_metadata,
    apply_igdb_to_metadata,
    apply_rawg_to_metadata,
    apply_screenscraper_to_metadata,
    apply_steam_to_metadata,
    apply_ai_to_metadata,
    load_scraper_settings,
)
from scraper.metadata_normalizer import (
    normalize_title,
    normalize_esrb_rating,
)
from scraper.match_scorer import MIN_TITLE_SCORE, calculate_title_match_score
from scraper.scraper_manager import DEFAULT_SCRAPER_PRIORITY
from scraper.ss_regions import own_region as game_own_region
from scraper.scrape_rawg import platform_id as rawg_platform_id

# Try to import AI scraper
AI_AVAILABLE = False
try:
    from scraper.scrape_ai import AI_FILLABLE_FIELDS, get_game_details as fetch_ai_metadata
    AI_AVAILABLE = True
    logger.info("AI metadata scraper module loaded successfully")
except ImportError:
    logger.debug("AI metadata scraper module not available")

# =============================================================================
# FALLBACK BEST-MATCH SELECTION
# =============================================================================

def _pick_best_fallback(results, game_title, min_title_score=MIN_TITLE_SCORE):
    """Pick the best-matching result from a fallback scraper search using title scoring.

    Returns the single best result dict, or None if no results or if the best
    match doesn't meet the minimum title score threshold.  This prevents
    wrong-game matches (e.g. "Alan Wake II" when searching "Alan Wake Remastered")
    from polluting a game's screenshots/metadata. A result a source says is for
    another console is never picked.

    Args:
        results: List of search result dicts.
        game_title: The title to match against.
        min_title_score: Minimum title match score to accept.
    """
    if not results:
        return None

    best = None
    best_score = -1
    for r in results:
        if r.get('platform_match') is False:
            continue
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


# =============================================================================
# METADATA FIELD DEFINITIONS
# =============================================================================


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
               release_dates.date, release_dates.y, release_dates.m, release_dates.date_format,
               release_dates.platform, release_dates.release_region,
               involved_companies.company.name, involved_companies.developer, involved_companies.publisher,
               genres.name, age_ratings.category, age_ratings.rating,
               age_ratings.organization.name, age_ratings.rating_category.rating,
               game_modes.name, player_perspectives.name,
               multiplayer_modes.platform, multiplayer_modes.offlinemax, multiplayer_modes.onlinemax,
               multiplayer_modes.campaigncoop, multiplayer_modes.splitscreen,
               multiplayer_modes.offlinecoop, multiplayer_modes.onlinecoop,
               summary, storyline, cover.url, screenshots.url, artworks.url, artworks.artwork_type,
               videos.video_id, alternative_names.name, alternative_names.comment,
               franchise.name, franchises.name, collections.name,
               similar_games.name, similar_games.cover.url,
               game_engines.name, platforms.name,
               game_localizations.name, game_localizations.region.name,
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
            elif game.get('collections'):
                franchise = game['collections'][0].get('name')

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
        return fetch_tgdb_details(game_id) or None

    except Exception as e:
        logger.error(f"TGDB extended fetch error: {e}")
        return None


# =============================================================================
# SAVE TYPE DETECTION
# =============================================================================

def detect_save_type(system_folder, title):
    """The save type every game on a system shares, or None.

    Cartridge systems are not guessed: many of their games save nothing.
    """

    # Systems that use memory cards
    memcard_systems = ['psx', 'ps2', 'gc', 'dreamcast', 'saturn']

    # Systems that use internal storage
    internal_systems = ['ps3', 'xbox', 'xbox360', 'wii', 'wiiu', 'switch', 'psp', 'psvita']

    system = (system_folder or '').lower()  # Pass 48.5 — guard None system_folder

    if system in memcard_systems:
        return "Memory Card"
    elif system in internal_systems:
        return "Internal Storage"
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

def _normalize_ratings(metadata, result, system_folder=None):
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
        inferred = infer_rating_from_content({**metadata, 'system_folder': system_folder})
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


_REGION_ALIASES = {'north america': 'USA'}


def _normalize_region(metadata, result):
    """Reduce `metadata['region']` to a single value, falling back to the
    user's `default_region` setting (default 'USA').

    Two cases handled:
      - Multi-value ('USA, Europe, Japan' or 'USA/Europe'): pick the first
        part that matches a configured region option, else `default_region`.
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

    region_value = _REGION_ALIASES.get(str(metadata.get('region') or '').lower(), metadata.get('region') or '')
    metadata['region'] = region_value
    if region_value:
        parts = [p.strip() for p in re.split(r'[,/]', region_value) if p.strip()]
        if len(parts) > 1:
            matched = next((p for p in parts if p.lower() in region_opts), None)
            metadata['region'] = matched or default_region
        # Single-value path: leave as-is.
    else:
        metadata['region'] = default_region
        result['filled_fields'].append('region (default)')


def _apply_retroachievements_check(db_game_id, title, system_folder):
    """Look up RetroAchievements support for `(title, system_folder)` and
    store the answer on the games row. Returns True when the game is now
    linked (caller should append 'retroachievements' to its filled_fields list).

    RA having no such game clears an old link; RA not answering changes nothing
    (PASS-59-210).

    Pass 38.1 partial extraction — this block was inline at the tail of
    apply_hybrid_metadata; it opens its own connection (independent of
    the caller's transaction) and silently swallows exceptions to keep
    a missing/down RA service from poisoning the rest of the scrape.
    """
    try:
        from scraper.retroachievements import check_retroachievements
        from services.achievement_linking import save_ra_link
        from services.hltb_service import extract_alt_titles
        conn2 = get_scraper_conn()
        try:
            row = conn2.execute("SELECT rom_path, alternate_titles FROM games WHERE id = ?",
                                (db_game_id,)).fetchone()
            ra_info = check_retroachievements(
                title, system_folder, row[0], extract_alt_titles(row[1]))
            if ra_info is None:
                return False
            linked = save_ra_link(conn2, db_game_id, ra_info)
            conn2.commit()
        finally:
            conn2.close()
        if not linked:
            return False
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


def source_game_id(data):
    """The numeric game id a source's fetched data carries, or None.
    ScreenScraper ids may arrive as "gameid:systemid"."""
    raw = (data or {}).get('id')
    if raw in (None, ''):
        return None
    try:
        return int(str(raw).split(':')[0])
    except ValueError:
        return None


_KEPT_MEDIA_FIELDS = ('boxart', 'boxart_3d', 'fanart', 'game_logo', 'manual', 'video', 'screenshots')


def _seed_kept_media(metadata, game, stale_fields):
    """PASS-59-133 — Full Re-scrape with "keep existing media": seed each media
    field whose file is still on disk, so the fill-only media checks skip its
    download. New screenshots still append to the kept list, which holds only
    names whose file is there."""
    for field in _KEPT_MEDIA_FIELDS:
        if game.get(field) and field not in stale_fields:
            metadata[field] = game[field]
    ss_dir = os.path.join(IMAGE_PATH, 'screenshots')
    if metadata.get('screenshots') and media_dir_is_healthy(ss_dir):
        names = (name.strip() for name in metadata['screenshots'].split(','))
        metadata['screenshots'] = ','.join(
            name for name in names if name and os.path.exists(os.path.join(ss_dir, name))) or None


def _save_source_ids(c, db_game_id, sources_data, force_overwrite=False):
    """PASS-59-106 §4.5 — store the IGDB and ScreenScraper game ids this scrape
    used; they are regional-version suggestion signals. A stored id is kept
    (INV-10); only Full Re-scrape replaces it with one a source provides, and
    a record for this exact file replaces ScreenScraper's (PASS-59-217)."""
    igdb_id = source_game_id(sources_data.get('igdb'))
    ss_record = sources_data.get('screenscraper')
    ss_id = source_game_id(ss_record)
    if igdb_id is None and ss_id is None:
        return
    if ss_id is not None and ss_record.get('_matched_file'):
        c.execute("UPDATE games SET screenscraper_id = ? WHERE id = ?", (ss_id, db_game_id))
    if force_overwrite:
        sql = ("UPDATE games SET igdb_id = COALESCE(?, igdb_id), "
               "screenscraper_id = COALESCE(?, screenscraper_id) WHERE id = ?")
    else:
        sql = ("UPDATE games SET igdb_id = COALESCE(igdb_id, ?), "
               "screenscraper_id = COALESCE(screenscraper_id, ?) WHERE id = ?")
    c.execute(sql, (igdb_id, ss_id, db_game_id))


def _log_date_disagreement(metadata, game):
    """Log a date over a year from the regional date for this copy's region.
    Neither is corrected, as neither is proof (PASS-59-162, merge_and_stored 10)."""
    if year_gap_with_own_region(metadata.get('release_date'), metadata.get('release_dates'),
                                game_own_region(game)):
        logger.warning(f"Game {game.get('id')}: release date {metadata['release_date']} "
                       f"disagrees with its regional dates {metadata['release_dates']}")


def _save_game_row(c, metadata, scrape_history_json, db_game_id, mark_scraped=True):
    """Write the assembled metadata back to the games row (fill-only).

    Pops the internal `_boxart_source` tracking key, JSON-encodes
    `alternate_titles`, then issues the COALESCE-guarded UPDATE so an empty
    metadata field preserves the existing DB value (the scraper fill-only
    invariant). `scrape_history` is set unconditionally, and `scraped` unless
    `mark_scraped` is False.
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
    # A locked title (PASS-59-159) is never written, in either mode.
    c.execute("""
        UPDATE games SET
            title = CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END,
            sort_title = CASE WHEN title_locked = 1 THEN sort_title ELSE COALESCE(?, sort_title) END,
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
            china_rating = COALESCE(?, china_rating),
            boxart = COALESCE(?, boxart),
            boxart_3d = COALESCE(?, boxart_3d),
            screenshots = COALESCE(?, screenshots),
            fanart = COALESCE(?, fanart),
            game_logo = COALESCE(?, game_logo),
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
            units_sold = COALESCE(?, units_sold),
            release_dates = COALESCE(?, release_dates),
            alternate_titles = COALESCE(?, alternate_titles),
            scrape_history = ?,
            scraped = COALESCE(?, scraped)
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
        metadata.get('china_rating'),
        metadata['boxart'],
        metadata['boxart_3d'],
        metadata['screenshots'],
        metadata['fanart'],
        metadata.get('game_logo'),
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
        metadata.get('units_sold'),
        metadata.get('release_dates'),
        alt_titles_json,
        scrape_history_json,
        1 if mark_scraped else None,
        db_game_id
    ))


def _fallback_order(primary_source, sources_data, restrict_to_selected,
                    secondary_sources):
    """The fallback scrapers _run_fallbacks will try, in the user's priority
    order: minus the primary, any already-used source and any disabled one.
    With `restrict_to_selected`, only the user-selected secondary_sources
    (plus AI, always allowed for gap-filling); none selected leaves AI."""
    fallback_settings = load_scraper_settings()
    user_priority = fallback_settings.get('priority', DEFAULT_SCRAPER_PRIORITY)
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
    primary_normalized = source_name_map.get(primary_source, primary_source)

    fallback_scrapers = []
    for scraper in user_priority:
        scraper_normalized = source_name_map.get(scraper, scraper)
        if scraper_normalized == primary_normalized:
            continue
        if scraper_normalized in sources_data:
            continue
        if not fallback_enabled.get(scraper_normalized, True):
            continue
        fallback_scrapers.append(scraper_normalized)

    if restrict_to_selected:
        selected_scrapers = {s['source'] for s in secondary_sources or []}
        fallback_scrapers = [s for s in fallback_scrapers
                             if s in selected_scrapers or s == 'ai']
    return fallback_scrapers


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

        fallback_settings = load_scraper_settings()
        fallback_enabled = fallback_settings.get('enabled', {})
        fallback_scrapers = _fallback_order(
            primary_source, sources_data, restrict_to_selected, secondary_sources)

        logger.info(f"Primary source: {primary_source} -> Fallback scrapers in priority order: {fallback_scrapers}")

        # PASS-59-132: every source but AI is searched and fetched at once,
        # one thread per source, so no host gets more requests at a time than
        # the parallel search (Pass 55.1) sends it. The applies below still run
        # one by one in priority order, so field precedence is unchanged. AI is
        # not prefetched: its prompt names the fields still empty at its turn.
        lookup = {
            'title': game_title,
            'game_id': db_game_id,
            'rom_path': game.get('rom_path'),
            'disc_serial': game.get('disc_serial'),
            'system_name': system_name,
            'system_folder': system_folder,
            'secondary_sources': secondary_sources or [],
            'user_ticked': restrict_to_selected,
            'api_keys': fallback_settings.get('api_keys', {}),
        }
        fetchable = [s for s in fallback_scrapers if s in _FALLBACK_FETCHERS]
        # One copied context per task: the progress tracker and step timer
        # are ContextVars, which a pool thread does not inherit. Leaving the
        # pool waits for every fetch, so none overlaps the next game's.
        with ThreadPoolExecutor(max_workers=max(len(fetchable), 1),
                                thread_name_prefix='fallback-fetch') as pool:
            fetches = {s: pool.submit(contextvars.copy_context().run, _fetch_fallback, s, lookup)
                       for s in fetchable}
            apply_progress.plan(len(fallback_scrapers))
            for i, fallback_source in enumerate(fallback_scrapers):
                # Re-check missing fields
                missing = [k for k, v in metadata.items() if not v]
                if not missing:
                    apply_progress.unplan(len(fallback_scrapers) - i)
                    break  # All fields filled

                if fallback_source == 'ai':
                    apply_progress.begin('ai')
                else:
                    apply_progress.begin(
                        'search',
                        source=_PROGRESS_SOURCE_LABELS.get(fallback_source, fallback_source),
                    )
                try:
                    if fallback_source == 'ai':
                        _run_ai_fallback(metadata, result, sources_data, db_game_id,
                                         lookup, fallback_enabled)
                    elif fallback_source in fetches:
                        data = fetches[fallback_source].result()
                        if data:
                            _apply_fallback(fallback_source, data, metadata, result,
                                            sources_data, db_game_id, system_folder,
                                            force_overwrite, own_region=game_own_region(game, data))
                except Exception as fallback_error:
                    logger.warning(f"Fallback scraper {fallback_source} failed: {fallback_error}")
                apply_progress.step_done()


def _fetch_fallback(source, lookup):
    """Search `source` for the game and fetch its detail record, or None.
    Runs on a pool thread; touches no shared state."""
    with apply_progress.timed(f"fetch {_PROGRESS_SOURCE_LABELS.get(source, source)}"):
        try:
            return _FALLBACK_FETCHERS[source](lookup)
        except Exception as fallback_error:
            logger.warning(f"Fallback scraper {source} failed: {fallback_error}")
            return None


def _secondary_for(source, lookup):
    """The search result to use for `source`: the one the user ticked, as
    is, else the best title match among the bulk job's results."""
    candidates = [s for s in lookup['secondary_sources'] if s['source'] == source]
    if lookup.get('user_ticked') and candidates:
        return candidates[0]
    return _pick_best_secondary(candidates, lookup['title'])


def _fallback_id(source, label, lookup, search):
    """The id to fetch from `source`: the chosen search result
    (_secondary_for), else the best match of a fresh `search()`."""
    title = lookup['title']
    picked = _secondary_for(source, lookup)
    if picked and picked['id']:
        return picked['id']
    match = _pick_best_fallback(search(), title)
    if match:
        logger.info(f"Found {label} match: {match.get('name')} (ID: {match.get('id')})")
        return match.get('id')
    logger.info(f"{label} fallback: no results found for '{title}'")
    return None


def _fetch_esde(lookup):
    from scraper.scrape_esde import search_esde_games, fetch_esde_game_details
    title, folder = lookup['title'], lookup['system_folder']
    logger.info(f"Trying ES-DE fallback for: '{title}'")
    # The row for this ROM file comes first: a title match can pick another
    # release of the same name. A result the user ticked still wins.
    rom_file = os.path.basename((lookup.get('rom_path') or '').rstrip('/'))
    if rom_file and not lookup.get('user_ticked'):
        own_row = fetch_esde_game_details(f'./{rom_file}', folder)
        if own_row:
            return own_row
    # ES-DE's id is the game's path in gamelist.xml.
    esde_path = _fallback_id('esde', 'ES-DE', lookup,
                             lambda: search_esde_games(title, folder, limit=5))
    if not esde_path:
        return None
    esde_data = fetch_esde_game_details(esde_path, folder)
    if not esde_data:
        logger.info("ES-DE fallback: failed to fetch game details")
    return esde_data


def _fetch_tgdb(lookup):
    from scraper.scrape_thegamesdb import search_games as search_tgdb
    title = lookup['title']
    logger.info(f"Trying TGDB fallback for: '{title}'")
    tgdb_id = _fallback_id('tgdb', 'TGDB', lookup,
                           lambda: search_tgdb(title, lookup['system_name'], limit=5))
    return fetch_tgdb_extended(tgdb_id) if tgdb_id else None


def _fetch_igdb(lookup):
    from scraper.scrape_igdb import search_games as search_igdb
    title = lookup['title']
    logger.info(f"Trying IGDB fallback for: '{title}'")
    igdb_id = _fallback_id('igdb', 'IGDB', lookup,
                           lambda: search_igdb(title, lookup['system_name'], limit=5))
    return fetch_igdb_extended(igdb_id) if igdb_id else None


def _fetch_rawg(lookup):
    keys = lookup['api_keys']
    if not (keys.get('rawg_api_key', '') or keys.get('rawg', '')):
        logger.info("RAWG fallback skipped: missing API key")
        return None
    from scraper.scrape_rawg import search_games as search_rawg, get_game_details as fetch_rawg
    title = lookup['title']
    logger.info(f"Trying RAWG fallback for: '{title}'")
    rawg_id = _fallback_id('rawg', 'RAWG', lookup,
                           lambda: search_rawg(title, lookup['system_folder'], limit=5))
    return fetch_rawg(rawg_id) if rawg_id else None


def _ss_record_by_id(ss_id, keys):
    """ScreenScraper's whole record for "gameid:systemid": the one kept from the
    search when it is still cached, else asked for by id, so a pick is never
    swapped for another game. None when the service has no such record."""
    from scraper.scraper_manager import get_cached_screenscraper_result
    from scraper.scrape_screenscraper import get_game_by_id
    game_id, _, system_id = str(ss_id).partition(':')
    system_id = system_id or None
    cached = get_cached_screenscraper_result(game_id, system_id)
    if cached:
        logger.info(f"Using cached ScreenScraper result (ID: {ss_id})")
        return cached
    logger.info(f"ScreenScraper cache miss for {ss_id}: fetching by id")
    return get_game_by_id(
        game_id, keys.get('screenscraper_username', ''), keys.get('screenscraper_password', ''),
        keys.get('screenscraper_devid', ''), keys.get('screenscraper_devpassword', ''),
        system_id=system_id)


# ScreenScraper found no PS3 game by serial in a trial, 2026-11-02 (PASS-59-217).
_SS_SERIAL_FOLDERS = ('psx', 'ps2')


def _ss_record_by_file(lookup, keys):
    """ScreenScraper's record for this exact file, or None."""
    from scraper.scrape_screenscraper import identify_by_file
    folder, rom_path = lookup['system_folder'], lookup.get('rom_path')
    if not rom_path:
        return None
    serial = None
    if folder in _SS_SERIAL_FOLDERS:
        serial = lookup.get('disc_serial')
        if serial is None:
            from services.standalone_settings import disc_ids
            serial = disc_ids({'id': lookup['game_id'], 'rom_path': rom_path,
                               'system_folder': folder})[0]
    try:
        return identify_by_file(rom_path, folder, serial or None,
                                keys.get('screenscraper_username', ''),
                                keys.get('screenscraper_password', ''),
                                keys.get('screenscraper_devid', ''),
                                keys.get('screenscraper_devpassword', ''))
    except Exception as e:
        logger.warning(f"ScreenScraper file lookup failed for game {lookup['game_id']}: {e}")
        return None


def _fetch_screenscraper(lookup):
    keys = lookup['api_keys']
    ss_username = keys.get('screenscraper_username', '')
    ss_password = keys.get('screenscraper_password', '')
    if not ss_username or not ss_password:
        logger.info("ScreenScraper fallback skipped: missing credentials")
        return None
    from scraper.scrape_screenscraper import search_game, get_system_id
    game_title, folder = lookup['title'], lookup['system_folder']
    logger.info(f"Trying ScreenScraper fallback for: '{game_title}'")

    if not lookup.get('user_ticked'):
        by_file = _ss_record_by_file(lookup, keys)
        if by_file:
            return by_file

    # A result already chosen from a search is fetched as that game.
    ss_info = _secondary_for('screenscraper', lookup)
    if ss_info and ss_info.get('id'):
        ss_record = _ss_record_by_id(ss_info['id'], keys)
        if ss_record:
            return ss_record

    if not get_system_id(folder):
        logger.warning(f"ScreenScraper fallback: no system ID found for {folder}")
        return None
    ss_results = search_game(
        game_title, folder,
        ss_username, ss_password,
        keys.get('screenscraper_devid', ''), keys.get('screenscraper_devpassword', '')
    )
    if not ss_results:
        logger.info(f"ScreenScraper fallback: no results found for '{game_title}'")
        return None
    # Score unconditionally: a single result used to be accepted with no
    # score at all, bypassing the 80-point floor scrapers.md §6 exists to
    # enforce — and ScreenScraper also supplies video and manual, which are
    # fill-only and so survive a re-scrape (Pass 59.21).
    return _pick_best_fallback(ss_results, game_title)


_FALLBACK_FETCHERS = {
    'esde': _fetch_esde,
    'tgdb': _fetch_tgdb,
    'igdb': _fetch_igdb,
    'screenscraper': _fetch_screenscraper,
    'rawg': _fetch_rawg,
}


def esde_rating_score(rating):
    """ES-DE's `rating`, 0 to 1 in half-star steps, on the 0 to 100 of user_score.
    0 is how ES-DE writes no rating."""
    try:
        score = float(rating) * 100
    except (TypeError, ValueError):
        return None
    return score if 0 < score <= 100 else None


def _use_esde_rating(metadata, result):
    """An ES-DE rating fills user_score only when no online source gave one, and
    before the AI is asked: ES-DE does not record who set it, and it may be the
    owner's own, but it is a real rating and the AI's is a guess."""
    rating = metadata.pop('_esde_rating', None)
    if rating and not metadata['user_score']:
        metadata['user_score'] = rating
        result['filled_fields'].append('user_score (ES-DE)')


def _merge_esde(metadata, details, result, db_game_id, system_folder,
                force_overwrite, fill_only):
    """Merge one ES-DE row into `metadata`, as primary or as a fallback.

    Text fills only what is empty. The title follows the other sources: a
    primary always sets it, a fallback only fills it. Media comes from
    copy_esde_media, which leaves a field that already has a value alone and
    names only what it copied now, so an old value in the row can never stand
    in for ES-DE's (PASS-59-205).
    """
    def fill(field, value):
        if value and not metadata[field]:
            metadata[field] = value
            result['filled_fields'].append(f'{field} (ES-DE)')

    name = details.get('name')
    if name and (not fill_only or not metadata['title']):
        metadata['title'] = normalize_title(name)
        result['filled_fields'].append('title (ES-DE)')
    fill('description', details.get('description'))
    fill('developer', details.get('developer'))
    fill('publisher', details.get('publisher'))
    if not metadata['genre']:
        fill_labels(metadata, result, 'genre', details.get('genre') or '', 'ES-DE')
    fill('release_date', details.get('release_date'))
    metadata['_esde_rating'] = esde_rating_score(details.get('rating'))

    from services.game_utils import normalize_players_value
    from services.normalization import modes_from_player_count
    players = normalize_players_value(details.get('players'))
    if players and not metadata['players']:
        fill('players', players)
        if not metadata['modes']:
            metadata['modes'] = modes_from_player_count(details.get('players'))

    from scraper.scrape_esde import copy_esde_media
    copied = copy_esde_media(db_game_id, details, system_folder,
                             existing=metadata, force_overwrite=force_overwrite)
    for field in ('boxart', 'boxart_3d', 'fanart', 'game_logo', 'video', 'manual'):
        fill(field, copied.get(field))
    if copied.get('boxart'):
        metadata['_boxart_source'] = 'esde'
    if copied.get('screenshots'):
        listed = [s.strip() for s in (metadata['screenshots'] or '').split(',') if s.strip()]
        metadata['screenshots'] = ','.join(listed + copied['screenshots'])
        result['filled_fields'].append(f"screenshots +{len(copied['screenshots'])} (ES-DE)")


def _apply_fallback(source, data, metadata, result, sources_data, db_game_id,
                    system_folder, force_overwrite, own_region=None):
    """Apply one fetched fallback record, fill-only, on the caller's thread."""
    sources_data[source] = data
    if source == 'esde':
        _merge_esde(metadata, data, result, db_game_id, system_folder,
                    force_overwrite, fill_only=True)
        label = 'ES-DE'
    elif source == 'tgdb':
        apply_tgdb_to_metadata(metadata, data, db_game_id, result, fill_only=True)
        label = 'TheGamesDB'
    elif source == 'igdb':
        apply_igdb_to_metadata(metadata, data, db_game_id, result, fill_only=True,
                               platform_id=get_igdb_platform_id(system_folder), own_region=own_region)
        label = 'IGDB'
    elif source == 'screenscraper':
        logger.info(f"Found ScreenScraper match: {data.get('nom', 'Unknown')} (ID: {data.get('id')})")
        apply_screenscraper_to_metadata(metadata, data, db_game_id, result, fill_only=True,
                                        own_region=own_region)
        label = 'ScreenScraper'
    else:
        apply_rawg_to_metadata(metadata, data, db_game_id, result, fill_only=True,
                               platform_id=rawg_platform_id(system_folder))
        label = 'RAWG'
    if label not in result['sources_used']:
        result['sources_used'].append(label)


def _run_ai_fallback(metadata, result, sources_data, db_game_id, lookup,
                     fallback_enabled):
    """Gap-fill from AI with the fields still empty at its turn."""
    game_title = lookup['title']
    if not AI_AVAILABLE:
        logger.info("AI fallback skipped: module not available")
        return
    if not fallback_enabled.get('ai', False):
        logger.info("AI fallback skipped: disabled in settings")
        return
    logger.info(f"Trying AI fallback for: '{game_title}'")
    _use_esde_rating(metadata, result)
    # Build existing metadata snapshot for AI to know what's missing
    ai_existing = {k: v for k, v in metadata.items() if v}
    # Pass 26.3 — wrap AI call in the circuit breaker so
    # repeated provider failures skip the call entirely
    # for the recovery window instead of hitting the API
    # on every gap-fill attempt.
    from scraper.scraper_manager import _ai_breaker
    ai_data = _ai_breaker(fetch_ai_metadata)(
        db_game_id, game_title, lookup['system_name'],
        lookup['system_folder'], existing_metadata=ai_existing,
        # Filled fields are not asked about: a gap-fill ignores those answers.
        only_fields=[f for f in AI_FILLABLE_FIELDS if not ai_existing.get(f)] + ['title'],
    )
    if ai_data:
        sources_data['ai'] = ai_data
        apply_ai_to_metadata(metadata, ai_data, db_game_id, result, fill_only=True)
        if 'AI' not in result['sources_used']:
            result['sources_used'].append('AI')
    else:
        logger.info(f"AI fallback: no results for '{game_title}'")

def apply_hybrid_metadata(db_game_id, primary_source, primary_id, system_folder,
                          secondary_sources=None, fill_gaps=True, force_overwrite=False,
                          primary_data=None, restrict_to_selected=False,
                          keep_media=False, automatic_pick=False, mark_scraped=True):
    """
    Apply metadata from primary source, then fill gaps from secondary sources.

    Args:
        db_game_id: Database ID of the game
        primary_source: 'esde', 'tgdb', 'igdb', 'rawg', 'screenscraper', or
            'steam', which takes its store reply as primary_data
        mark_scraped: If False, leave `games.scraped` as it is, so a game filled
            from one source still counts as waiting for a scrape
        primary_id: ID/path for the primary source
        system_folder: System folder name for ES-DE lookups
        secondary_sources: List of dicts with 'source' and 'id' for fallback
        fill_gaps: If True, automatically search other scrapers for missing data
        force_overwrite: If True, overwrite existing data (for full re-scrape)
        keep_media: With force_overwrite, keep media whose file is on disk
            instead of downloading it again (PASS-59-133)
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
            'china_rating': None,
            'boxart': None,
            'boxart_3d': None,
            'screenshots': None,
            'fanart': None,
            'game_logo': None,
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
            'units_sold': None,
            'release_dates': None,
            'alternate_titles': None,
        }

        # The file name says which copy this is, so it comes before every source
        # and the AI is never asked (PASS-59-204). A stored region stays: it may
        # be the user's choice, and Full Re-scrape, which starts empty, keeps it too.
        file_region = extract_region_from_filename(os.path.basename(game.get('rom_path') or ''))
        if file_region:
            metadata['region'] = game.get('region') or file_region
            if not game.get('region'):
                result['filled_fields'].append('region (filename)')

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
                'game_logo': os.path.join(IMAGE_PATH, 'game_logos'),
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
                        # Pass 54.1 — skip the clear when the whole media dir is
                        # gone/empty (unmounted drive / bulk deletion); erasing
                        # the ref then would lose the record of every game's art.
                        if not media_dir_is_healthy(directory):
                            logger.warning(f"Media dir {directory} missing/empty — "
                                           f"preserving DB ref {field}={value} (mass-missing guard)")
                            continue
                        logger.warning(f"Media file missing from disk, clearing: {field}={value}")
                        metadata[field] = None
                        stale_media.append((field, value))

            # Video lives in STATIC_PATH/videos/
            video_value = metadata.get('video')
            if video_value:
                _video_dir = os.path.join(STATIC_PATH, 'videos')
                if not os.path.exists(os.path.join(_video_dir, video_value)):
                    if not media_dir_is_healthy(_video_dir):
                        logger.warning(f"Media dir {_video_dir} missing/empty — "
                                       f"preserving DB ref video={video_value} (mass-missing guard)")
                    else:
                        logger.warning(f"Media file missing from disk, clearing: video={video_value}")
                        metadata['video'] = None
                        stale_media.append(('video', video_value))

            # Screenshots: filter out individual missing files
            screenshots_value = metadata.get('screenshots')
            if screenshots_value:
                ss_dir = os.path.join(IMAGE_PATH, 'screenshots')
                ss_list = [s.strip() for s in screenshots_value.split(',') if s.strip()]
                valid_ss = [s for s in ss_list if os.path.exists(os.path.join(ss_dir, s))]
                if len(valid_ss) < len(ss_list) and not media_dir_is_healthy(ss_dir):
                    # Whole screenshots dir gone/empty — don't prune every ref.
                    logger.warning(f"Media dir {ss_dir} missing/empty — preserving "
                                   f"{len(ss_list)} screenshot ref(s) (mass-missing guard)")
                elif len(valid_ss) < len(ss_list):
                    missing = [s for s in ss_list if s not in valid_ss]
                    logger.warning(f"Screenshot files missing from disk, removing: {missing}")
                    metadata['screenshots'] = ','.join(valid_ss) if valid_ss else None
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
                'game_logo': os.path.join(IMAGE_PATH, 'game_logos'),
                'manual': os.path.join(IMAGE_PATH, 'manuals'),
            }
            _force_stale = []  # list of (field, stale_filename)
            # Pass 54.1 — same mass-missing guard as the fill-path above: only
            # treat a missing file as a clearable stale ref when its media dir
            # is still present and populated (a gone/empty dir means an
            # unmounted drive or bulk deletion, not a genuine per-file removal).
            for field, directory in _media_dirs.items():
                value = game.get(field)
                if (value and not os.path.exists(os.path.join(directory, value))
                        and media_dir_is_healthy(directory)):
                    _force_stale.append((field, value))
            video_value = game.get('video')
            _video_dir = os.path.join(STATIC_PATH, 'videos')
            if (video_value and not os.path.exists(os.path.join(_video_dir, video_value))
                    and media_dir_is_healthy(_video_dir)):
                _force_stale.append(('video', video_value))
            # Screenshots: clear the column only when EVERY referenced file is
            # gone (single-value clears can't express a partial prune here).
            ss_value = game.get('screenshots')
            if ss_value:
                ss_dir = os.path.join(IMAGE_PATH, 'screenshots')
                ss_list = [s.strip() for s in ss_value.split(',') if s.strip()]
                if (ss_list and media_dir_is_healthy(ss_dir)
                        and not any(os.path.exists(os.path.join(ss_dir, s)) for s in ss_list)):
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
            if keep_media:
                _seed_kept_media(metadata, game, {f for f, _ in _force_stale})
        # ES-DE replaces media only when this is set.
        media_force = force_overwrite and not keep_media

        sources_data = {}

        # =============================================
        # FETCH DATA FROM PRIMARY SOURCE
        # =============================================

        logger.info(f"Fetching from primary source: {primary_source}")
        # Primary fetch, database save, RetroAchievements check, and the
        # fallbacks expected now so the primary's downloads don't read as most
        # of the job. Each media download adds its own steps when reached.
        expected_fallbacks = len(_fallback_order(
            primary_source, {}, restrict_to_selected, secondary_sources)) if fill_gaps else 0
        apply_progress.plan(3 + expected_fallbacks)
        apply_progress.begin(
            'fetch', source=_PROGRESS_SOURCE_LABELS.get(primary_source, primary_source))

        if primary_source == 'esde':
            # Pass 41.4.B (ES-DE branch) — guard the ES-DE primary dispatch
            # with the same per-source try/except contract used for tgdb/igdb/
            # rawg/screenscraper below. A malformed gamelist.xml row or a
            # transient filesystem error during media copy must not abort the
            # hybrid apply; on failure, fall through to the gap-fill phase.
            esde_details = None
            try:
                # For ES-DE, we need to fetch the game details from gamelist.xml first
                from scraper.scrape_esde import fetch_esde_game_details

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

                _merge_esde(metadata, esde_details, result, db_game_id, system_folder,
                            media_force, fill_only=False)

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
                    apply_igdb_to_metadata(metadata, igdb_data, db_game_id, result,
                                           platform_id=get_igdb_platform_id(system_folder),
                                           own_region=game_own_region(game))
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
                    apply_rawg_to_metadata(metadata, rawg_data, db_game_id, result,
                                           platform_id=rawg_platform_id(system_folder))
                    result['sources_used'].append('RAWG')
            except Exception as e:
                logger.warning(f"Primary RAWG fetch/apply failed for {primary_id}: {e}; "
                               "falling through to gap-fill")

        elif primary_source == 'screenscraper':
            try:
                api_keys = load_scraper_settings().get('api_keys', {})
                if api_keys.get('screenscraper_username') and api_keys.get('screenscraper_password'):
                    # A person's pick stands. A bulk scrape's came from a title search.
                    ss_data = None
                    if automatic_pick:
                        ss_data = _ss_record_by_file(
                            {'game_id': db_game_id, 'rom_path': game.get('rom_path'),
                             'disc_serial': game.get('disc_serial'),
                             'system_folder': system_folder}, api_keys)
                    ss_data = ss_data or _ss_record_by_id(primary_id, api_keys)
                    if ss_data:
                        sources_data['screenscraper'] = ss_data
                        apply_screenscraper_to_metadata(metadata, ss_data, db_game_id, result,
                                                        own_region=game_own_region(game, ss_data))
                        result['sources_used'].append('ScreenScraper')
                    else:
                        logger.warning(f"ScreenScraper has no record for {primary_id}")
            except Exception as e:
                logger.warning(f"Primary ScreenScraper fetch/apply failed for {primary_id}: {e}; "
                               "falling through to gap-fill")

        elif primary_source == 'steam':
            try:
                apply_steam_to_metadata(metadata, primary_data, primary_id, db_game_id, result)
                result['sources_used'].append('Steam')
            except Exception as e:
                logger.warning(f"Steam store apply failed for {primary_id}: {e}; "
                               "falling through to gap-fill")

        apply_progress.step_done()

        # =============================================
        # FILL GAPS FROM SECONDARY SOURCES
        # =============================================

        if fill_gaps:
            # _run_fallbacks plans the steps it will actually take.
            apply_progress.unplan(expected_fallbacks)
            _run_fallbacks(
                metadata, result, sources_data, game, db_game_id,
                primary_source, system_folder, secondary_sources,
                restrict_to_selected, media_force, c,
            )
        _use_esde_rating(metadata, result)

        # =============================================
        # DETECT ADDITIONAL METADATA
        # =============================================

        # Full Re-scrape starts `metadata` empty, so region and save_type fell
        # through to a default ('USA') and a folder guess, and COALESCE then
        # overwrote curated values. These are DERIVED, not source-supplied, and
        # CLAUDE.md scopes the force-mode exception to "any field a source
        # actually provides" — so seed them from the existing row when no
        # source filled them. A source-supplied value still wins, because
        # sources run before this block (Pass 59.22). Ratings and controller too:
        # cross-mapping, inference and the folder guess then have nothing to
        # write over (PASS-59-214).
        if force_overwrite:
            rating_columns = [RATING_SYSTEMS[k]['db_column'] for k in RATING_SYSTEM_KEYS]
            for field in ('region', 'save_type', 'controller_support', *rating_columns):
                if not metadata[field]:
                    metadata[field] = game.get(field) or None

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

        # =============================================
        # NORMALIZE VALUES BEFORE SAVE
        # =============================================

        # Pass 38.1 — rating normalize/cross-map/infer extracted to _normalize_ratings.
        _normalize_ratings(metadata, result, system_folder)

        # Pass 38.1 — players range→max + sort_title regen extracted to
        # _normalize_players_and_sort_title.
        _normalize_players_and_sort_title(metadata)

        # One set of names, whichever source or older scrape filled each field.
        canonicalize_metadata(metadata)

        _log_date_disagreement(metadata, game)

        # After the steps above, so what they filled is credited (PASS-59-214).
        scrape_history_json = _build_scrape_history_json(
            c, db_game_id, primary_source, metadata, result, force_overwrite
        )

        # =============================================
        # SAVE TO DATABASE
        # =============================================

        # Pass 38.1 — SAVE TO DATABASE block extracted to _save_game_row.
        apply_progress.begin('save')
        _save_game_row(c, metadata, scrape_history_json, db_game_id, mark_scraped)
        _save_source_ids(c, db_game_id, sources_data, force_overwrite)

        conn.commit()
        apply_progress.step_done()

        # Pass 38.1 — RA-check extracted to _apply_retroachievements_check.
        apply_progress.begin('achievements')
        title_to_check = metadata['title'] or game.get('title', '')
        if _apply_retroachievements_check(db_game_id, title_to_check, system_folder):
            result['filled_fields'].append('retroachievements')
        apply_progress.step_done()

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
