# =============================================================================
# RETRODB - AI Fill
# =============================================================================
# Fills one game's empty metadata from the AI, with the smart overwrite
# rules, rating cross-mapping, controller-default preference and the
# scrape-history entry. The game page's AI Fill button and the bulk run on
# ROM Tools > Bulk AI Fill both use fill_game().
# =============================================================================

import json as json_lib
import logging
import os
from datetime import datetime, timezone

from services.analytics import invalidate_analytics_cache
from services.database import query, execute
from services.field_sources import credits as field_credits
from services.game_query import invalidate_filter_cache
from services.game_metadata_service import cross_map_ratings
from services.game_utils import (
    generate_sort_title, infer_rating_from_content,
    normalize_players_value,
    RATING_SYSTEM_KEYS, RATING_SYSTEMS,
)

logger = logging.getLogger(__name__)

_COUNT_OF = {'critic_score_count': 'critic_score', 'user_score_count': 'user_score'}

# The bulk run's on/off switches: switch key -> the columns it covers, in the
# order the page shows them. 'title' is the official name. Every column of
# scrape_ai.AI_FILLABLE_FIELDS is under one switch (tests/test_ai_fill_bulk.py).
FIELD_GROUPS = {
    'title': ['title'],
    'description': ['description'],
    'genre': ['genre'],
    'developer': ['developer'],
    'publisher': ['publisher'],
    'release_date': ['release_date'],
    'release_dates': ['release_dates'],
    'units_sold': ['units_sold'],
    'players': ['players'],
    'modes': ['modes'],
    'region': ['region'],
    'franchise': ['franchise'],
    'similar_games': ['similar_games'],
    'other_platforms': ['other_platforms'],
    'controller_support': ['controller_support'],
    'save_type': ['save_type'],
    'game_structure': ['game_structure'],
    'perspective': ['perspective'],
    'dimension': ['dimension'],
    'campaign': ['campaign'],
    'edition': ['edition'],
    'ratings': [RATING_SYSTEMS[k]['db_column'] for k in RATING_SYSTEM_KEYS],
    'critic_score': ['critic_score', 'critic_score_count'],
    'user_score': ['user_score', 'user_score_count'],
}


def columns_for(groups):
    """The columns under the switch keys `groups`; None (every field) for None."""
    if groups is None:
        return None
    return {col for g in groups for col in FIELD_GROUPS[g]}


def load_game(game_id):
    """The game row with its system's name and folder, or None."""
    return query("""
        SELECT g.*, s.name AS system_name, s.folder AS system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)


def _same_value(field, new, old):
    """Do the AI's answer and the stored value say the same thing once both
    are in stored form? `1-4` players is 4, and a list is a set (PASS-59-242)."""
    if field == 'players':
        return normalize_players_value(new) == normalize_players_value(old)
    def words(text):
        return {w.strip().casefold() for w in str(text).split(',') if w.strip()}
    return words(new) == words(old)


def fill_game(game, fields=None):
    """Ask the AI about one game (a load_game() row) and save what it fills.

    `fields` is the set of columns it may fill (see columns_for); None fills
    every field. Returns the list of fields filled, or None when the AI gave
    no data.
    """
    game_id = game['id']
    from scraper.scrape_ai import (
        AI_FILLABLE_FIELDS, VALIDATE_FIELDS, get_game_details as ai_get_details,
    )
    from scraper.hybrid_scraper import should_use_default_controller, get_system_default_controller_name

    ai_fields = AI_FILLABLE_FIELDS
    _int_fields = {'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
                   'units_sold', 'players'}
    existing_metadata = {}
    for field in ai_fields:
        existing_metadata[field] = str(game.get(field, '') or '') or ''

    # Always re-fetch similar_games (scraper data unreliable)
    existing_metadata['similar_games'] = ''
    # User, 2026-11-04: what a person typed is never corrected by the AI.
    hand_edited = {f for f, src in field_credits(game.get('scrape_history')).items()
                   if src == 'manual'}
    if ((existing_metadata.get('other_platforms', '') or '').strip().lower() == 'exclusive'
            and 'other_platforms' not in hand_edited):
        existing_metadata['other_platforms'] = ''
    db_default_ctrl = get_system_default_controller_name(game['system_id'])
    if not db_default_ctrl and should_use_default_controller(existing_metadata.get('controller_support', '')):
        existing_metadata['controller_support'] = ''
    elif db_default_ctrl:
        existing_metadata['controller_support'] = db_default_ctrl

    # The file name decides the region, so the AI is not asked (PASS-59-204).
    from scraper.scrape_esde import extract_region_from_filename
    file_region = extract_region_from_filename(os.path.basename(game.get('rom_path') or ''))
    if file_region:
        existing_metadata['region'] = existing_metadata.get('region') or file_region

    ai_data = ai_get_details(
        game_id, game['title'], game['system_name'],
        game['system_folder'], existing_metadata=existing_metadata,
        only_fields=fields,
    )

    if not ai_data:
        return None

    filled_fields = []
    replaced = {}
    # column -> value. One key per column, so a later fixup overrides an
    # earlier assignment instead of appending a duplicate `col = ?`.
    sets = {}
    for field, value in ai_data.items():
        if field not in ai_fields or not value or (field == 'region' and file_region):
            continue
        current = str(game.get(field, '') or '').strip()
        # A count belongs to its score, so it is written only with an AI score.
        if field in _COUNT_OF and (current or game.get(_COUNT_OF[field]) or not ai_data.get(_COUNT_OF[field])):
            continue
        should_apply = False

        if not current:
            should_apply = True
        elif field == 'similar_games':
            should_apply = True
        elif (field == 'other_platforms' and current.lower() == 'exclusive'
              and field not in hand_edited):
            should_apply = True
        elif (field in VALIDATE_FIELDS and field not in hand_edited
              and not _same_value(field, value, current)):
            should_apply = True
            replaced[field] = current[:200]
            logger.info(f"AI fill: correcting {field}: '{current}' → '{value}'")

        if should_apply:
            if field == 'players':
                # AI is prompted to return players as a range ("1-4"), which
                # int(float()) below would reject — dropping the field. Route
                # it through the canonical normalizer (range → max int) like
                # the form/JSON/bulk edit paths do.
                value = normalize_players_value(value)
                if value is None:
                    continue
            elif field in _int_fields:
                try:
                    value = int(float(value))
                except (ValueError, TypeError):
                    continue
                # Pass 45.3: AI returning 0 for an int field is "unknown",
                # not a legitimate score/count of zero — skip so curated
                # or previously-scraped non-zero values survive (matches
                # the scraper-fill-only invariant in CLAUDE.md).
                if value == 0:
                    continue
            sets[field] = value
            filled_fields.append(field)

    if file_region and not game.get('region'):
        sets['region'] = file_region

    # Post-fill fixups (merged into the same UPDATE)
    pending = dict(sets)

    # The AI's official name replaces the title; the old one is kept as
    # an alternate title. A locked title is never asked about
    # (scrape_ai._official_title_context), so it is never replaced.
    title_val = (game.get('title', '') or '').strip()
    official = ai_data.get('official_title')
    if official and official != title_val and not game.get('title_locked'):
        from scraper.metadata_normalizer import alt_title_entry, merge_alt_titles
        if title_val and title_val.lower() != official.lower():
            alts = merge_alt_titles(
                game.get('alternate_titles'),
                [alt_title_entry(title_val, region=ai_data.get('old_title_region'),
                                 source='ai')],
                primary_title=official)
            alts = [a for a in alts if a['title'].lower() != official.lower()]
            sets['alternate_titles'] = json_lib.dumps(alts) if alts else None
        logger.info(f"AI fill: official title '{title_val}' → '{official}'")
        sets['title'] = official
        filled_fields.append('title')
        title_val = official
    if title_val:
        new_sort = generate_sort_title(title_val)
        if new_sort and new_sort != (game.get('sort_title', '') or ''):
            sets['sort_title'] = new_sort

    # Cross-map empty rating fields from any available rating. The helper
    # treats 'RP' (Rating Pending) as empty so it gets replaced.
    effective = {
        k: pending.get(RATING_SYSTEMS[k]['db_column'])
           or (game.get(RATING_SYSTEMS[k]['db_column'], '') or '').strip()
        for k in RATING_SYSTEM_KEYS
    }
    mapped = cross_map_ratings(effective)
    for key in RATING_SYSTEM_KEYS:
        if mapped[key] and mapped[key] != effective[key]:
            col = RATING_SYSTEMS[key]['db_column']
            sets[col] = mapped[key]
            filled_fields.append(col)
            logger.info(f"AI fill: auto-mapped {RATING_SYSTEMS[key]['name']} '{mapped[key]}'")

    # Content-based rating inference (fallback when still no ratings)
    has_any_rating = any(
        (pending.get(RATING_SYSTEMS[k]['db_column']) or (game.get(RATING_SYSTEMS[k]['db_column'], '') or '').strip())
        not in ('', None, 'RP', 'rp')
        for k in RATING_SYSTEM_KEYS
    )
    if not has_any_rating:
        infer_data = {f: pending.get(f) or str(game.get(f, '') or '').strip() for f in ai_fields}
        infer_data['system_folder'] = game.get('system_folder', '')
        inferred = infer_rating_from_content(infer_data)
        if inferred:
            for col, val in inferred.items():
                sets[col] = val
                filled_fields.append(col)
            logger.info(f"AI fill: inferred ratings from content ({len(inferred)} systems)")

    # Curated DB controller wins over AI/scraped data, not over a typed one.
    ctrl = pending.get('controller_support') or (game.get('controller_support', '') or '').strip()
    if db_default_ctrl and 'controller_support' not in hand_edited:
        if ctrl != db_default_ctrl:
            sets['controller_support'] = db_default_ctrl
            if 'controller_support' not in filled_fields:
                filled_fields.append('controller_support')

    franchise_val = pending.get('franchise') or (game.get('franchise', '') or '').strip()
    if franchise_val.lower() == 'standalone':
        sets['franchise'] = None
        if 'franchise' in filled_fields:
            filled_fields.remove('franchise')

    other_plats = pending.get('other_platforms') or (game.get('other_platforms', '') or '').strip()
    if other_plats and other_plats.lower() != 'exclusive':
        parts = [p.strip() for p in other_plats.split(',') if p.strip()]
        seen = set()
        unique = []
        for p in parts:
            if p.lower() not in seen:
                seen.add(p.lower())
                unique.append(p)
        sorted_str = ', '.join(sorted(unique))
        if sorted_str != other_plats:
            sets['other_platforms'] = sorted_str
            logger.info(f"AI fill: sorted platforms '{other_plats}' → '{sorted_str}'")

    # The fixups above can touch any column; keep only the chosen ones.
    if fields is not None:
        allowed = set(fields)
        if 'title' in fields:
            allowed |= {'sort_title', 'alternate_titles'}
        sets = {col: val for col, val in sets.items() if col in allowed}
        filled_fields = [f for f in filled_fields if f in allowed]

    # A field changed while the AI answered keeps its new value, and the
    # history keeps what was added meanwhile (PASS-59-257).
    now = load_game(game_id) or game
    for col in [col for col in sets if str(now.get(col) or '') != str(game.get(col) or '')]:
        del sets[col]
        replaced.pop(col, None)
        if col in filled_fields:
            filled_fields.remove(col)
    game = {**game, 'scrape_history': now.get('scrape_history')}

    scrape_history_json = None
    if filled_fields:
        try:
            existing_history = []
            hist_raw = game.get('scrape_history')
            if hist_raw:
                try:
                    existing_history = json_lib.loads(hist_raw)
                except (ValueError, TypeError):
                    existing_history = []
            trackable = [
                'genre', 'description', 'developer', 'publisher', 'release_date',
                'players', 'modes', 'esrb_rating', 'pegi_rating', 'region',
                'franchise', 'similar_games', 'controller_support', 'save_type',
                'game_structure', 'perspective', 'dimension', 'campaign',
                'other_platforms', 'edition',
            ]
            still_missing = []
            for f in trackable:
                val = pending.get(f) or str(game.get(f, '') or '').strip()
                if not val:
                    still_missing.append(f)
            history_entry = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'primary_source': 'AI Fill',
                'sources_used': ['AI'],
                'fields_filled': [f'{f} (AI)' for f in filled_fields],
                'fields_missing': still_missing,
                'scrape_mode': 'ai_fill'
            }
            if replaced:
                history_entry['replaced'] = replaced
            existing_history.append(history_entry)
            scrape_history_json = json_lib.dumps(existing_history)
        except Exception as e:
            logger.warning(f"AI fill: failed to build scrape history: {e}")

    if scrape_history_json is not None:
        sets['scrape_history'] = scrape_history_json

    if sets:
        # The lock was read before the AI call; a title locked meanwhile
        # keeps its name, sort title and alternates (PASS-59-159 §4.3).
        locked_form = {
            'title': 'CASE WHEN title_locked = 1 THEN title ELSE COALESCE(?, title) END',
            'sort_title': 'CASE WHEN title_locked = 1 THEN sort_title '
                          'ELSE COALESCE(?, sort_title) END',
            'alternate_titles': 'CASE WHEN title_locked = 1 THEN alternate_titles ELSE ? END',
        }
        assignments = ', '.join(f'{col} = {locked_form.get(col, "?")}' for col in sets)
        execute(f"UPDATE games SET {assignments} WHERE id = ?", (*sets.values(), game_id))
        # AI fill writes genre/developer/publisher/franchise/modes/ratings,
        # all of which feed the Library filter dropdowns — same cache
        # discipline as the edit paths in routes/games.py.
        invalidate_filter_cache()
        invalidate_analytics_cache()
        if 'title' in sets:
            invalidate_filter_cache()

        verify = query("SELECT esrb_rating, edition FROM games WHERE id = ?", (game_id,), one=True)
        if verify:
            v_esrb = (verify.get('esrb_rating', '') or '').strip()
            v_edition = (verify.get('edition', '') or '').strip()
            if 'esrb_rating' in filled_fields and not v_esrb:
                logger.error(f"AI fill: VERIFICATION FAILED — esrb_rating not persisted for game {game_id}")
            if 'edition' in filled_fields and not v_edition:
                logger.error(f"AI fill: VERIFICATION FAILED — edition not persisted for game {game_id}")

    return filled_fields
