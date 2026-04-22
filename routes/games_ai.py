# =============================================================================
# RETRODB - AI Metadata Fill Route
# =============================================================================
# POST /api/game/<id>/ai-fill — fill missing metadata via AI (Gemini/OpenAI/Claude)
# with smart overwrite rules, rating cross-mapping, controller-default preference,
# and scrape-history audit trail.
# =============================================================================

import json as json_lib
import logging
from datetime import datetime, timezone

from flask import Blueprint

from services.api_helpers import handle_api_errors, success, error
from services.auth import editor_required
from services.database import query, execute
from services.game_metadata_service import cross_map_ratings
from services.game_utils import (
    generate_sort_title, infer_rating_from_content,
    RATING_SYSTEM_KEYS, RATING_SYSTEMS,
)

logger = logging.getLogger(__name__)

bp = Blueprint('games_ai', __name__)


@bp.route('/api/game/<int:game_id>/ai-fill', methods=['POST'])
@editor_required
@handle_api_errors
def api_game_ai_fill(game_id):
    """Fill missing metadata fields using AI scraper with smart overwrite logic."""
    try:
        game = query("""
            SELECT g.*, s.name AS system_name, s.folder AS system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,), one=True)

        if not game:
            return error('Game not found', 404)

        from scraper.scrape_ai import get_game_details as ai_get_details, VALIDATE_FIELDS
        from scraper.hybrid_scraper import should_use_default_controller, get_system_default_controller_name

        ai_fields = [
            'genre', 'description', 'developer', 'publisher', 'release_date',
            'players', 'modes', 'esrb_rating', 'pegi_rating', 'cero_rating',
            'usk_rating', 'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
            'region', 'franchise', 'similar_games', 'controller_support', 'save_type',
            'game_structure', 'perspective', 'dimension', 'campaign',
            'other_platforms', 'edition',
            'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
        ]
        _int_fields = {'critic_score', 'critic_score_count', 'user_score', 'user_score_count', 'players'}
        existing_metadata = {}
        for field in ai_fields:
            existing_metadata[field] = str(game.get(field, '') or '') or ''

        # Always re-fetch similar_games (scraper data unreliable)
        existing_metadata['similar_games'] = ''
        if (existing_metadata.get('other_platforms', '') or '').strip().lower() == 'exclusive':
            existing_metadata['other_platforms'] = ''
        db_default_ctrl = get_system_default_controller_name(game['system_id'])
        if not db_default_ctrl and should_use_default_controller(existing_metadata.get('controller_support', '')):
            existing_metadata['controller_support'] = ''
        elif db_default_ctrl:
            existing_metadata['controller_support'] = db_default_ctrl

        ai_data = ai_get_details(
            game_id, game['title'], game['system_name'],
            game['system_folder'], existing_metadata=existing_metadata
        )

        if not ai_data:
            return error(
                'AI returned no data. Check your API key and provider settings.',
                code=200,
            )

        filled_fields = []
        all_updates = []
        all_values = []
        for field, value in ai_data.items():
            if field not in ai_fields or not value:
                continue
            current = str(game.get(field, '') or '').strip()
            should_apply = False

            if not current:
                should_apply = True
            elif field == 'similar_games':
                should_apply = True
            elif field == 'other_platforms' and current.lower() == 'exclusive':
                should_apply = True
            elif field in VALIDATE_FIELDS and value != current:
                should_apply = True
                logger.info(f"AI fill: correcting {field}: '{current}' → '{value}'")

            if should_apply:
                if field in _int_fields:
                    try:
                        value = int(float(value))
                    except (ValueError, TypeError):
                        continue
                all_updates.append(f"{field} = ?")
                all_values.append(value)
                filled_fields.append(field)

        # Post-fill fixups (merged into the same UPDATE)
        pending = dict(zip(filled_fields, all_values[: len(filled_fields)]))

        title_val = (game.get('title', '') or '').strip()
        if title_val:
            new_sort = generate_sort_title(title_val)
            if new_sort and new_sort != (game.get('sort_title', '') or ''):
                all_updates.append("sort_title = ?")
                all_values.append(new_sort)

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
                all_updates.append(f"{col} = ?")
                all_values.append(mapped[key])
                filled_fields.append(col)
                logger.info(f"AI fill: auto-mapped {RATING_SYSTEMS[key]['name']} '{mapped[key]}'")

        # Content-based rating inference (fallback when still no ratings)
        has_any_rating = any(
            (pending.get(RATING_SYSTEMS[k]['db_column']) or (game.get(RATING_SYSTEMS[k]['db_column'], '') or '').strip())
            not in ('', None, 'RP', 'rp')
            for k in RATING_SYSTEM_KEYS
        )
        if not has_any_rating:
            infer_data = {f: pending.get(f) or (game.get(f, '') or '').strip() for f in ai_fields}
            infer_data['system_folder'] = game.get('system_folder', '')
            inferred = infer_rating_from_content(infer_data)
            if inferred:
                for col, val in inferred.items():
                    all_updates.append(f"{col} = ?")
                    all_values.append(val)
                    filled_fields.append(col)
                logger.info(f"AI fill: inferred ratings from content ({len(inferred)} systems)")

        # Curated DB controller always wins over AI/scraped data
        ctrl = pending.get('controller_support') or (game.get('controller_support', '') or '').strip()
        if db_default_ctrl:
            if ctrl != db_default_ctrl:
                all_updates.append("controller_support = ?")
                all_values.append(db_default_ctrl)
                if 'controller_support' not in filled_fields:
                    filled_fields.append('controller_support')

        franchise_val = pending.get('franchise') or (game.get('franchise', '') or '').strip()
        if franchise_val.lower() == 'standalone':
            all_updates.append("franchise = ?")
            all_values.append(None)
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
                for i, u in enumerate(all_updates):
                    if u == "other_platforms = ?":
                        all_values[i] = sorted_str
                        break
                else:
                    all_updates.append("other_platforms = ?")
                    all_values.append(sorted_str)
                logger.info(f"AI fill: sorted platforms '{other_plats}' → '{sorted_str}'")

        edition = pending.get('edition') or (game.get('edition', '') or '').strip()
        if not edition:
            all_updates.append("edition = ?")
            all_values.append('Standard Edition')
            if 'edition' not in filled_fields:
                filled_fields.append('edition')

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
                existing_history.append(history_entry)
                scrape_history_json = json_lib.dumps(existing_history)
            except Exception as e:
                logger.warning(f"AI fill: failed to build scrape history: {e}")

        if scrape_history_json is not None:
            all_updates.append("scrape_history = ?")
            all_values.append(scrape_history_json)

        if all_updates:
            all_values.append(game_id)
            execute(f"UPDATE games SET {', '.join(all_updates)} WHERE id = ?", tuple(all_values))

            verify = query("SELECT esrb_rating, edition FROM games WHERE id = ?", (game_id,), one=True)
            if verify:
                v_esrb = (verify.get('esrb_rating', '') or '').strip()
                v_edition = (verify.get('edition', '') or '').strip()
                if 'esrb_rating' in filled_fields and not v_esrb:
                    logger.error(f"AI fill: VERIFICATION FAILED — esrb_rating not persisted for game {game_id}")
                if 'edition' in filled_fields and not v_edition:
                    logger.error(f"AI fill: VERIFICATION FAILED — edition not persisted for game {game_id}")

        updated_game = query("""
            SELECT g.*, s.name AS system_name, s.folder AS system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,), one=True)

        return success(
            filled_fields=filled_fields,
            filled_count=len(filled_fields),
            game={
                'id': updated_game['id'],
                'title': updated_game['title'],
                'genre': updated_game['genre'],
                'description': updated_game['description'],
                'developer': updated_game['developer'],
                'publisher': updated_game['publisher'],
                'release_date': updated_game['release_date'],
                'players': updated_game['players'],
                'modes': updated_game['modes'],
                'esrb_rating': updated_game['esrb_rating'],
                'pegi_rating': updated_game['pegi_rating'],
                'cero_rating': updated_game.get('cero_rating'),
                'usk_rating': updated_game.get('usk_rating'),
                'acb_rating': updated_game.get('acb_rating'),
                'fpb_rating': updated_game.get('fpb_rating'),
                'grac_rating': updated_game.get('grac_rating'),
                'classind_rating': updated_game.get('classind_rating'),
                'region': updated_game['region'],
                'franchise': updated_game['franchise'],
                'similar_games': updated_game['similar_games'],
                'controller_support': updated_game['controller_support'],
                'save_type': updated_game['save_type'],
                'game_structure': updated_game['game_structure'],
                'perspective': updated_game['perspective'],
                'dimension': updated_game['dimension'],
                'campaign': updated_game['campaign'],
                'other_platforms': updated_game['other_platforms'],
                'edition': updated_game['edition'],
            },
        )

    except ImportError:
        return error('AI scraper module not available', 500)
