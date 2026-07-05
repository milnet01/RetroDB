# =============================================================================
# RETRODB - Game Metadata Service
# =============================================================================
# Shared helpers for game metadata merging:
#   - Rating cross-mapping (manual edit + AI fill).
#   - Game-card dict shaping for /api/games and /api/games/card-data.
#   - Unified metadata-apply orchestrator (apply_metadata_to_game +
#     apply_hybrid_metadata_to_game) used by routes/games.py,
#     routes/bulk_scrape.py, and services/jobs/bulk_scrape.py so all three
#     go through the same source-name normalization + secondary-source build
#     instead of each reaching into scraper_manager or scraper.hybrid_scraper
#     directly.
# =============================================================================

import logging
from datetime import datetime

from services.game_utils import (
    map_rating,
    RATING_SYSTEM_KEYS,
    generate_sort_title,
    normalize_players_value,
)
from services.image_utils import boxart_srcset, boxart_dir_listing

logger = logging.getLogger(__name__)

# 'RP' is "Rating Pending" — not an actual maturity level. Treat it as empty
# so cross-mapping replaces it with a real rating from another system.
_RP_VALUES = frozenset({'RP', 'rp'})

# Field groups used by normalize_game_edit (Pass 42.1).
_GAME_EDIT_RATING_KEYS = (
    'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
    'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
    'china_rating',
)


def cross_map_ratings(ratings):
    """Fill empty rating slots from any available rating via maturity tier.

    Args:
        ratings: dict keyed by system ('esrb', 'pegi', ...) with raw rating
                 values (strings; empty strings or None mean "missing").

    Returns:
        dict: new dict with the same keys; empty slots filled from the first
              mappable source.
    """
    result = {k: (ratings.get(k) or '') for k in RATING_SYSTEM_KEYS}
    for tgt_key in RATING_SYSTEM_KEYS:
        if result[tgt_key] and result[tgt_key] not in _RP_VALUES:
            continue
        for src_key in RATING_SYSTEM_KEYS:
            if src_key == tgt_key:
                continue
            src_val = result[src_key]
            if not src_val or src_val in _RP_VALUES:
                continue
            mapped = map_rating(src_key, src_val, tgt_key)
            if mapped:
                result[tgt_key] = mapped
                break
    return result


def normalize_game_edit(payload):
    """Sanitise a game-edit payload for an UPDATE on the games row.

    Single source of truth for the form-POST (`game_view edit_metadata`)
    and JSON (`api_game_edit`) edit paths — Pass 42.1 collapses the two
    independent normalisations that had drifted (form-POST cross-mapped
    ratings + generated sort_title; JSON did neither).

    Behaviour:
        - Strips whitespace on every string value; the empty string maps to None.
        - `release_date`: accepts `YYYY-MM-DD` or `YYYY/MM/DD`; junk → None.
        - `players`: routed through `normalize_players_value` so the INTEGER
          column stays well-typed (Pass 40.6 invariant).
        - 8-system rating cross-map: fires only on the rating keys that are
          actually present in the payload, so callers that pass a single
          rating field do not get the other seven written underneath them.
        - `sort_title`: auto-generated from `title` when `title` is provided
          and `sort_title` is empty / missing.
        - `similar_games`: comma-separated list re-joined with one space after
          each comma; empties dropped.

    Args:
        payload: dict of edit fields (raw values, possibly with surrounding
                 whitespace, possibly with the empty string for "clear").

    Returns:
        dict: shallow copy of `payload` with the transforms above applied.
              Keys absent from `payload` stay absent in the result.
    """
    out = dict(payload)

    # Whitespace strip + empty-string-to-None on every string field.  This
    # lets callers feed `request.form.get(...).strip()` or `request.json[k]`
    # without per-field handling at the call site.
    for k in list(out.keys()):
        v = out[k]
        if isinstance(v, str):
            v = v.strip()
            out[k] = v if v != '' else None

    # release_date — accept slashes, validate YYYY-MM-DD, junk → None.
    if out.get('release_date'):
        rd = out['release_date']
        if '/' in rd:
            rd = rd.replace('/', '-')
        try:
            datetime.strptime(rd, '%Y-%m-%d')
            out['release_date'] = rd
        except ValueError:
            out['release_date'] = None

    # players — INTEGER column; Pass 40.6 invariant.
    if 'players' in out:
        out['players'] = normalize_players_value(out['players'])

    # similar_games — re-join with single space after comma, drop empties.
    if out.get('similar_games'):
        out['similar_games'] = ', '.join(
            part.strip() for part in out['similar_games'].split(',')
            if part.strip()
        )

    # Rating cross-map.  Only run when at least one rating key is present
    # in the payload, and only assign back the keys the caller actually
    # included (so a JSON caller updating just `esrb_rating` does not have
    # the other seven systems written by side effect).
    rating_keys_present = [k for k in _GAME_EDIT_RATING_KEYS if k in payload]
    if rating_keys_present:
        rating_input = {
            k.replace('_rating', ''): (out.get(k) or '')
            for k in _GAME_EDIT_RATING_KEYS
        }
        mapped = cross_map_ratings(rating_input)
        for k in rating_keys_present:
            short = k.replace('_rating', '')
            mapped_value = mapped.get(short, '')
            out[k] = mapped_value if mapped_value else None

    # sort_title — generate from title if title given and sort_title blank.
    if out.get('title') and not out.get('sort_title'):
        out['sort_title'] = generate_sort_title(out['title'])

    return out


def import_source_for_rom_path(rom_path):
    """Classify a ROM path's import provenance.

    Returns 'clz', 'steam', 'xbox', 'psn', or None.
    """
    rp = rom_path or ''
    if rp.startswith('clz_import/'):
        return 'clz'
    if rp.startswith('steam_import/'):
        return 'steam'
    if rp.startswith('xbox_import/'):
        return 'xbox'
    if rp.startswith('psn_import/'):
        return 'psn'
    return None


# Columns pulled into a game-card dict. The row must have been selected with
# these (plus the achievement/psn joins handled in the SQL).
_CARD_COLUMNS = (
    'id', 'title', 'sort_title', 'system_id', 'boxart', 'boxart_3d', 'fanart',
    'genre', 'franchise', 'developer', 'publisher', 'release_date', 'modes',
    'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating', 'acb_rating',
    'fpb_rating', 'grac_rating', 'classind_rating', 'china_rating',
    'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
    'completion_status', 'scraped', 'has_retroachievements', 'is_bonus_disc',
)


def build_game_card(row, rpcs3_info=None, include_source_flag=False):
    """Shape a games JOIN systems row into the card-data dict used by
    /api/games and /api/games/card-data.

    Args:
        row: sqlite3.Row with card columns + system_name, system_folder,
             system_type, bonus_count, earned_achievements, achievement_total,
             achievement_pct, achievement_source, psn_earned, psn_total.
        rpcs3_info: optional dict with 'earned' and 'total' from RPCS3 local
                    trophies (PS3 only).
        include_source_flag: if True, also emit 'is_clz_import' for legacy
                             consumers of /api/games.

    Returns:
        dict: card-compatible dict matching the keys both endpoints used.
    """
    import_source = import_source_for_rom_path(row['rom_path'] if 'rom_path' in row.keys() else None)

    card = {col: row[col] for col in _CARD_COLUMNS}
    card.update({
        'system_name': row['system_name'],
        'system_folder': row['system_folder'],
        'system_type': row['system_type'] or '',
        'bonus_count': row['bonus_count'],
        'import_source': import_source,
        'achievement_earned': row['earned_achievements'],
        'achievement_total': row['achievement_total'],
        'achievement_pct': row['achievement_pct'],
        'achievement_source': row['achievement_source'],
        'psn_earned': row['psn_earned'],
        'psn_total': row['psn_total'],
        'rpcs3_earned': rpcs3_info['earned'] if rpcs3_info else None,
        'rpcs3_total': rpcs3_info['total'] if rpcs3_info else None,
    })

    # Pass FU.2 — emit pre-computed `srcset` strings so the JS card renderer
    # can pick a 160 w / 320 w variant instead of always fetching the full
    # 1080 h original. `boxart_dir_listing` memoizes one `os.scandir` per
    # request on `flask.g`, so a 500-card page does two scans total instead
    # of N × (stat + PIL.Image.open) calls.
    if card.get('boxart'):
        card['boxart_srcset'] = boxart_srcset(
            card['boxart'],
            image_type='boxart',
            existing=boxart_dir_listing('boxart'),
        )
    if card.get('boxart_3d'):
        card['boxart_3d_srcset'] = boxart_srcset(
            card['boxart_3d'],
            image_type='boxart_3d',
            existing=boxart_dir_listing('boxart_3d'),
        )

    if include_source_flag:
        card['is_clz_import'] = import_source == 'clz'
    return card


# =============================================================================
# METADATA APPLY ORCHESTRATOR
# =============================================================================
# Raw search-result `source` field values (what the per-scraper search
# routines tag their results with) vs. the short-form names
# hybrid_scraper.apply_hybrid_metadata dispatches on. Normalizing here means
# bulk callers that previously passed 'thegamesdb' straight through (bypassing
# the manager's source_map step) now actually hit the primary-source branch
# in the hybrid pipeline instead of silently falling through to fallback.
_SOURCE_NAME_MAP = {
    'thegamesdb': 'tgdb',
    'tgdb': 'tgdb',
    'igdb': 'igdb',
    'esde': 'esde',
    'rawg': 'rawg',
    'screenscraper': 'screenscraper',
    'ai': 'ai',
}


def _normalize_source(source):
    """Normalize a raw search-result `source` value to hybrid_scraper's short form."""
    return _SOURCE_NAME_MAP.get(source, source)


def apply_metadata_to_game(db_game_id, game_data, source, system_folder=None):
    """Apply metadata from a single (non-hybrid) source to a game.

    Dispatches to the per-source `apply_*` functions in `scraper/`. Used by the
    manual "Apply from this source" flow in `routes/games.py` when the user
    picked a single scraper and no gap-fill is needed.

    RAWG and ScreenScraper have no standalone apply function — their metadata
    is only reachable through the hybrid path, so those sources return False
    here; callers should use `apply_hybrid_metadata_to_game` instead.

    Args:
        db_game_id: Database game ID.
        game_data: Fetched game-details dict from the chosen source.
        source: Raw source name ('thegamesdb', 'igdb', 'esde', 'rawg',
                'screenscraper') — accepts either raw or short form.
        system_folder: System folder (required for ES-DE apply).

    Returns:
        bool: True on success, False otherwise (including for unroutable
              RAWG / ScreenScraper single-source applies).
    """
    logger.info(f"Applying metadata from {source} to game {db_game_id}")
    normalized = _normalize_source(source)
    try:
        if normalized == 'tgdb':
            from scraper.scrape_thegamesdb import apply_metadata_to_game as apply_tgdb
            return apply_tgdb(db_game_id, game_data)
        if normalized == 'igdb':
            from scraper.scrape_igdb import apply_metadata_to_game as apply_igdb
            return apply_igdb(db_game_id, game_data)
        if normalized == 'esde':
            from scraper.scrape_esde import apply_esde_metadata
            return apply_esde_metadata(db_game_id, game_data, system_folder)
        if normalized in ('rawg', 'screenscraper'):
            logger.info(f"{source} has no single-source apply — caller should use apply_hybrid_metadata_to_game")
            return False
        logger.error(f"Unknown source: {source}")
        return False
    except Exception as e:
        logger.error(f"Error applying metadata from {source}: {e}")
        return False


def apply_hybrid_metadata_to_game(db_game_id, primary_source, primary_id, system_folder,
                                  all_results=None, explicit_secondary=None,
                                  secondary_sources=None, fill_gaps=True,
                                  force_overwrite=False, primary_data=None):
    """Apply primary-source metadata, then fill gaps from secondary scrapers.

    Unified entry point shared by every apply path:
      - Manual edit (routes/games.py) passes `all_results` + optional
        `explicit_secondary`; this function finds `primary_data` by ID match
        and auto-builds `secondary_sources` from the remaining results.
      - Single-game bulk (routes/bulk_scrape.py) and background bulk
        (services/jobs/bulk_scrape.py) pass pre-curated `primary_data` +
        `secondary_sources` directly.

    Args:
        db_game_id: Database game ID.
        primary_source: Raw or short-form source name for the primary scraper.
        primary_id: ID of the chosen primary-source result.
        system_folder: System folder (required for ES-DE and ScreenScraper).
        all_results: Optional list of all search results (manual path).
        explicit_secondary: Optional list of user-picked secondary selections
            [{'source', 'id', 'name'}, ...]. Forces `restrict_to_selected=True`
            in the underlying hybrid apply so unselected scrapers are skipped.
        secondary_sources: Optional pre-built secondary list (bulk paths). If
            None and `all_results` is provided, auto-derived from the other
            search results.
        fill_gaps: If True, search remaining scrapers for any field the
            primary left empty.
        force_overwrite: If True, overwrite existing fields (full-rescrape).
        primary_data: Optional pre-fetched primary-source result dict; saves
            a re-fetch round-trip.

    Returns:
        dict: {'success', 'filled_fields', 'missing_fields', 'sources_used'}
              as produced by scraper.hybrid_scraper.apply_hybrid_metadata. On
              unexpected failure, falls back to `apply_metadata_to_game` on
              freshly-fetched primary data and returns {'success': <bool>}.
    """
    from scraper.hybrid_scraper import apply_hybrid_metadata as hybrid_apply

    primary = _normalize_source(primary_source)

    # Manual path: derive primary_data + secondary_sources from all_results.
    if all_results is not None and secondary_sources is None:
        if primary_data is None:
            for r in all_results:
                if r.get('id') == primary_id and _normalize_source(r.get('source')) == primary:
                    primary_data = r
                    logger.info(f"Found selected result data for {primary}: {r.get('name', 'Unknown')}")
                    break

        if explicit_secondary:
            secondary_sources = []
            for sel in explicit_secondary:
                src = _normalize_source(sel.get('source'))
                if src != primary:
                    secondary_sources.append({
                        'source': src,
                        'id': sel.get('id'),
                        'name': sel.get('name', ''),
                    })
            logger.info(
                f"Using {len(secondary_sources)} explicit secondary selection(s): "
                f"{[s['source'] + ':' + s.get('name', '') for s in secondary_sources]}"
            )
        else:
            secondary_sources = []
            for r in all_results:
                src = _normalize_source(r.get('source'))
                if src != primary:
                    secondary_sources.append({
                        'source': src,
                        'id': r.get('id'),
                        'name': r.get('name', ''),
                    })

    try:
        return hybrid_apply(
            db_game_id=db_game_id,
            primary_source=primary,
            primary_id=primary_id,
            system_folder=system_folder,
            secondary_sources=secondary_sources or [],
            fill_gaps=fill_gaps,
            force_overwrite=force_overwrite,
            primary_data=primary_data,
            restrict_to_selected=bool(explicit_secondary),
        )
    except Exception as e:
        logger.error(f"Error in hybrid metadata apply: {e}")
        from scraper.scraper_manager import scraper_manager
        game_data = scraper_manager.fetch_game_details(primary_id, primary_source, system_folder)
        if game_data:
            return {'success': apply_metadata_to_game(db_game_id, game_data, primary_source, system_folder)}
        return {'success': False}
