# =============================================================================
# RETRODB - Wishlist Scraper
# =============================================================================
# Lightweight metadata scraper for wishlist items. Reuses the existing
# scraper_manager + per-source metadata appliers from the games-side pipeline
# (scraper/hybrid_scraper.py and scraper/metadata_merger.py) but writes into
# the `wishlist` table instead of `games`.
#
# Image files are namespaced with a "w{wishlist_id}" prefix (passed into the
# scraper download helpers as db_game_id) so they never collide with boxart
# for owned games. If an item is later promoted to a real game, the images
# can simply be re-downloaded.
#
# Scrape flow (per item):
#   1. resolve system info (system_id → system.name / system.folder, else
#      use the free-text system_name field as-is so future systems like
#      "Sony PlayStation 6" still work)
#   2. scraper_manager.search_games() across all enabled scrapers
#   3. pick best match, respecting enabled scrapers and score
#   4. fetch detail from primary source, apply_*_to_metadata()
#   5. iterate remaining enabled sources in priority order, re-search with
#      the selected title, and let each apply_* fill gaps in the same dict
#   6. UPDATE the wishlist row with the assembled metadata
# =============================================================================

import logging
import threading
from datetime import datetime, timezone

from services.database import query, execute, get_db

logger = logging.getLogger(__name__)


# Columns the wishlist scraper writes into. Must match services/database_init.py
# wishlist_columns. Kept as a whitelist so the UPDATE statement below can't be
# tricked into writing other columns via dict mutation.
_WRITABLE_METADATA_COLUMNS = (
    'boxart', 'boxart_3d', 'fanart', 'screenshots', 'video', 'manual',
    'description', 'release_date', 'developer', 'publisher', 'genre',
    'franchise', 'modes', 'players',
    'esrb_rating', 'pegi_rating',
    'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
)

# Which scrapers the wishlist scraper will consult. ES-DE and ScreenScraper
# both require local ROM context (gamelist.xml / rom_path) so they can't
# contribute useful metadata to a not-yet-owned wishlist item. AI fill is
# also excluded — it's designed to fill specific fields on an existing game
# row, not to bootstrap a wishlist entry from scratch.
_SUPPORTED_SCRAPERS = ('tgdb', 'igdb', 'rawg')


def _utcnow_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _empty_metadata():
    """Seed metadata dict matching the keys the apply_* functions expect.

    The per-source appliers (see scraper/metadata_merger.py) mutate this dict
    in place, only filling keys where the value is falsy — so initialising
    every key to None lets the first source fill everything and subsequent
    sources fill only the gaps.
    """
    return {
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
    }


def _resolve_system(item):
    """Return (system_name, system_folder) for an item.

    Prefers the linked systems row (when system_id is set), falls back to the
    free-text system_name column so wishlist entries for systems RetroDB
    doesn't yet know about (e.g. an upcoming PlayStation 6 title) still get
    passed to scrapers verbatim. Scrapers that need system_folder will simply
    return no platform-filtered results for unknown systems, which is fine.
    """
    system_id = item.get('system_id')
    if system_id:
        row = query(
            "SELECT name, folder FROM systems WHERE id = ?",
            (system_id,), one=True
        )
        if row:
            return row['name'], row['folder']
    return (item.get('system_name') or ''), ''


def _set_status(item_id, status):
    """Update scrape_status on a wishlist row without touching other fields."""
    execute(
        "UPDATE wishlist SET scrape_status = ? WHERE id = ?",
        (status, item_id)
    )


def _apply_source(source, metadata, fake_db_id, source_id, result):
    """Fetch extended data from `source` for `source_id`, apply it to
    `metadata`. Returns True if the source contributed anything."""
    try:
        if source in ('tgdb', 'thegamesdb'):
            from scraper.hybrid_scraper import fetch_tgdb_extended
            from scraper.metadata_merger import apply_tgdb_to_metadata
            data = fetch_tgdb_extended(source_id)
            if data:
                apply_tgdb_to_metadata(metadata, data, fake_db_id, result)
                return True

        elif source == 'igdb':
            from scraper.hybrid_scraper import fetch_igdb_extended
            from scraper.metadata_merger import apply_igdb_to_metadata
            data = fetch_igdb_extended(source_id)
            if data:
                apply_igdb_to_metadata(metadata, data, fake_db_id, result)
                return True

        elif source == 'rawg':
            from scraper.scrape_rawg import get_game_details as fetch_rawg
            from scraper.metadata_merger import apply_rawg_to_metadata
            data = fetch_rawg(source_id)
            if data:
                apply_rawg_to_metadata(metadata, data, fake_db_id, result)
                return True

    except Exception as e:
        logger.warning(f"Wishlist scrape: {source} fetch/apply failed: {e}")
    return False


def _normalize_source_name(source):
    """scraper_manager tags results with 'thegamesdb'; we use 'tgdb'
    everywhere else. Collapse to canonical form."""
    return 'tgdb' if source == 'thegamesdb' else source


def scrape_wishlist_item(item_id):
    """Scrape metadata for a single wishlist item. Synchronous.

    Returns a dict: {success, status, message, filled_fields, sources_used}.
    The wishlist row's scrape_status column is updated to reflect the outcome.
    """
    item = query("SELECT * FROM wishlist WHERE id = ?", (item_id,), one=True)
    if not item:
        return {'success': False, 'status': 'not_found', 'message': 'Wishlist item not found'}

    _set_status(item_id, 'scraping')

    try:
        from scraper.scraper_manager import scraper_manager
        from scraper.metadata_merger import load_scraper_settings
    except ImportError as e:
        logger.error(f"Wishlist scrape: scraper modules unavailable: {e}")
        _set_status(item_id, 'failed')
        return {'success': False, 'status': 'failed', 'message': 'Scrapers unavailable'}

    title = item['title']
    system_name, system_folder = _resolve_system(item)
    logger.info(f"Wishlist scrape item {item_id}: '{title}' on '{system_name}' (folder='{system_folder}')")

    # 1. Search across enabled scrapers
    try:
        results = scraper_manager.search_games(title, system_name, system_folder, limit=10)
    except Exception as e:
        logger.error(f"Wishlist scrape: search failed: {e}")
        _set_status(item_id, 'failed')
        return {'success': False, 'status': 'failed', 'message': f'Search error: {e}'}

    # Filter to sources the wishlist scraper supports — ES-DE and ScreenScraper
    # require local ROM context that wishlist entries don't have.
    results = [
        r for r in results
        if _normalize_source_name(r.get('source', '')) in _SUPPORTED_SCRAPERS
    ]

    if not results:
        logger.info(f"Wishlist scrape item {item_id}: no matches from supported scrapers")
        _set_status(item_id, 'no_match')
        execute(
            "UPDATE wishlist SET scraped_at = ? WHERE id = ?",
            (_utcnow_iso(), item_id)
        )
        return {'success': False, 'status': 'no_match', 'message': 'No matches found'}

    # Pick the highest-scoring enabled result as primary
    scraper_settings = load_scraper_settings()
    enabled = scraper_settings.get('enabled', {})
    sorted_results = sorted(results, key=lambda r: -r.get('score', 0))

    primary = None
    for r in sorted_results:
        src = _normalize_source_name(r.get('source', ''))
        if enabled.get(src, True):
            primary = r
            break
    if primary is None:
        primary = sorted_results[0]

    primary_source = _normalize_source_name(primary.get('source', ''))
    primary_id = primary.get('id')
    logger.info(f"Wishlist scrape item {item_id}: picked {primary_source} '{primary.get('name')}' (id={primary_id}, score={primary.get('score')})")

    # 2. Fetch + apply primary source
    metadata = _empty_metadata()
    apply_result = {'filled_fields': [], 'missing_fields': [], 'sources_used': []}
    fake_db_id = f"w{item_id}"  # Namespaced for image filename generation

    if _apply_source(primary_source, metadata, fake_db_id, primary_id, apply_result):
        apply_result['sources_used'].append(primary_source)
    else:
        logger.warning(f"Wishlist scrape item {item_id}: primary source {primary_source} returned no data")

    # 3. Gap-fill from remaining supported+enabled sources.
    # For each remaining source, re-search with the primary's canonical title
    # (if we got one) so we match the *same game*, not a same-named one, then
    # apply the first result. apply_* only fills empty keys, so this naturally
    # gap-fills without overwriting.
    canonical_title = metadata.get('title') or title
    used_sources = {primary_source}

    for candidate_source in _SUPPORTED_SCRAPERS:
        if candidate_source in used_sources:
            continue
        if not enabled.get(candidate_source, True):
            continue
        # Skip if every writable field is already populated
        if all(metadata.get(f) for f in _WRITABLE_METADATA_COLUMNS):
            break

        try:
            gap_results = scraper_manager.search_games(
                canonical_title, system_name, system_folder, limit=3
            )
        except Exception as e:
            logger.debug(f"Wishlist scrape: gap-fill search ({candidate_source}) failed: {e}")
            continue

        gap_results = [
            r for r in gap_results
            if _normalize_source_name(r.get('source', '')) == candidate_source
        ]
        if not gap_results:
            continue

        best = max(gap_results, key=lambda r: r.get('score', 0))
        if _apply_source(candidate_source, metadata, fake_db_id, best.get('id'), apply_result):
            apply_result['sources_used'].append(candidate_source)
            used_sources.add(candidate_source)

    # 4. Persist
    update_fields = []
    update_values = []
    for col in _WRITABLE_METADATA_COLUMNS:
        if metadata.get(col) is not None:
            update_fields.append(f"{col} = ?")
            update_values.append(metadata[col])

    update_fields.extend(['source = ?', 'source_id = ?', 'scrape_status = ?', 'scraped_at = ?'])
    update_values.extend([primary_source, str(primary_id) if primary_id is not None else None,
                          'scraped', _utcnow_iso()])
    update_values.append(item_id)

    conn = get_db()
    try:
        conn.execute(
            f"UPDATE wishlist SET {', '.join(update_fields)} WHERE id = ?",
            tuple(update_values)
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        f"Wishlist scrape item {item_id}: done "
        f"(sources: {apply_result['sources_used']}, "
        f"filled {len(apply_result['filled_fields'])} fields)"
    )

    return {
        'success': True,
        'status': 'scraped',
        'sources_used': apply_result['sources_used'],
        'filled_fields': apply_result['filled_fields'],
        'primary_source': primary_source,
        'matched_title': primary.get('name'),
    }


def scrape_wishlist_item_async(item_id):
    """Kick off a wishlist scrape in a background thread.

    The thread closes over its own DB connection (get_db) so it doesn't touch
    the Flask request-scoped connection. Used by the 'Add & scrape' flow and
    the per-item Re-scrape button so the HTTP response doesn't block on the
    scraper calls (which can take several seconds).
    """
    # Mark the item as queued up for scrape immediately so the UI badge
    # flips before the worker thread even starts.
    try:
        _set_status(item_id, 'scraping')
    except Exception as e:
        logger.warning(f"Wishlist scrape: could not mark item {item_id} as scraping: {e}")

    def _run():
        try:
            scrape_wishlist_item(item_id)
        except Exception as e:
            logger.error(f"Wishlist scrape item {item_id} crashed: {e}", exc_info=True)
            try:
                _set_status(item_id, 'failed')
            except Exception:
                pass

    thread = threading.Thread(target=_run, name=f"wishlist-scrape-{item_id}", daemon=True)
    thread.start()
    return thread


def scrape_unscraped_items(owner_id=None):
    """Scrape every wishlist item that hasn't been scraped yet (or failed).

    Runs synchronously in the calling thread, so callers should dispatch it
    via scrape_unscraped_items_async below. Returns the count scraped.

    Args:
        owner_id: when set, only scrape items owned by that user (Pass 27.1
            per-user scoping). None means scrape every user's items — used
            by admin "scrape all" calls.
    """
    if owner_id is None:
        items = query("""
            SELECT id FROM wishlist
            WHERE scrape_status IS NULL
               OR scrape_status IN ('unscraped', 'failed', 'no_match')
            ORDER BY added_at DESC
        """)
    else:
        items = query("""
            SELECT id FROM wishlist
            WHERE (scrape_status IS NULL
                   OR scrape_status IN ('unscraped', 'failed', 'no_match'))
              AND owner_id = ?
            ORDER BY added_at DESC
        """, (owner_id,))
    count = 0
    for row in items:
        try:
            scrape_wishlist_item(row['id'])
            count += 1
        except Exception as e:
            logger.error(f"Wishlist bulk scrape: item {row['id']} failed: {e}")
    return count


def scrape_unscraped_items_async(owner_id=None):
    """Background-thread wrapper for scrape_unscraped_items()."""
    thread = threading.Thread(
        target=scrape_unscraped_items, args=(owner_id,),
        name="wishlist-scrape-all", daemon=True,
    )
    thread.start()
    return thread
