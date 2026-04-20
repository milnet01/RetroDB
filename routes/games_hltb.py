# =============================================================================
# RETRODB - HowLongToBeat (HLTB) API Routes
# =============================================================================
# Lookup, save, clear, and search endpoints for HLTB playtime data.
# =============================================================================

import logging

from flask import Blueprint, request, jsonify

from services.database import query, execute
from services.auth import login_required

logger = logging.getLogger(__name__)

bp = Blueprint('games_hltb', __name__)


@bp.route('/api/hltb-lookup/<int:game_id>', methods=['POST'])
@login_required
def api_hltb_lookup(game_id):
    """Look up playtime from HLTB for a game."""
    try:
        from scraper.hltb_lookup import lookup_playtime, format_playtime

        game = query("""
            SELECT g.*, s.folder AS system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,), one=True)

        if not game:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        data = request.get_json() or {}
        search_title = data.get('search_title', game['title'])
        preview_mode = data.get('preview', False)

        result = lookup_playtime(search_title, game['system_folder'])

        if not result:
            return jsonify({'success': False, 'error': f'No HLTB match found for "{search_title}"'})

        parts = []
        if result['main_story']:
            parts.append(f"Main: {format_playtime(result['main_story'])}")
        if result['main_plus_sides']:
            parts.append(f"Main+Extras: {format_playtime(result['main_plus_sides'])}")
        if result['completionist']:
            parts.append(f"100%: {format_playtime(result['completionist'])}")

        playtime_str = ' | '.join(parts) if parts else None

        if playtime_str and not preview_mode:
            execute("""
                UPDATE games SET playtime_estimate = ? WHERE id = ?
            """, (playtime_str, game_id))

        match_platform = result.get('match_platform', '')
        if isinstance(match_platform, (list, tuple)):
            match_platform = ', '.join(str(p) for p in match_platform) if match_platform else ''

        return jsonify({
            'success': True,
            'playtime': playtime_str,
            'match_name': result['match_name'],
            'match_platform': match_platform,
            'confidence': result['match_confidence'],
            'main_story': result['main_story'],
            'main_plus_sides': result['main_plus_sides'],
            'completionist': result['completionist']
        })

    except Exception as e:
        logger.error(f"HLTB lookup error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/hltb-save/<int:game_id>', methods=['POST'])
@login_required
def api_hltb_save(game_id):
    """Save HLTB playtime data to database."""
    try:
        data = request.get_json() or {}
        playtime = data.get('playtime')
        match_name = data.get('match_name')
        match_platform = data.get('match_platform')
        confidence = data.get('confidence')

        if not playtime:
            return jsonify({'success': False, 'error': 'No playtime provided'}), 400

        if isinstance(match_platform, (list, tuple)):
            match_platform = ', '.join(str(p) for p in match_platform) if match_platform else None

        if confidence is not None:
            if isinstance(confidence, (list, tuple)):
                confidence = float(confidence[0]) if confidence else None
            else:
                confidence = float(confidence)
            if confidence is not None and confidence > 1:
                confidence = confidence / 100.0

        execute("""
            UPDATE games SET
                playtime_estimate = ?,
                hltb_match_name = ?,
                hltb_match_platform = ?,
                hltb_match_confidence = ?
            WHERE id = ?
        """, (playtime, match_name, match_platform, confidence, game_id))

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"HLTB save error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/hltb-clear/<int:game_id>', methods=['POST'])
@login_required
def api_hltb_clear(game_id):
    """Clear HLTB playtime data from database."""
    try:
        execute("""
            UPDATE games SET
                playtime_estimate = NULL,
                hltb_match_name = NULL,
                hltb_match_platform = NULL,
                hltb_match_confidence = NULL
            WHERE id = ?
        """, (game_id,))

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"HLTB clear error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/hltb/search', methods=['POST'])
@login_required
def api_hltb_search():
    """Generic HLTB search by title (used by game detail, PSN trophies, achievements)."""
    try:
        from scraper.hltb_lookup import lookup_playtime, format_playtime

        data = request.get_json() or {}
        search_query = str(data.get('query', '')).strip()
        system_folder = str(data.get('system_folder', '')).strip()
        year = str(data.get('year', '')).strip() or None

        if not search_query:
            return jsonify({'success': False, 'error': 'No search query provided'})

        folder = system_folder or 'ps4'
        result = lookup_playtime(search_query, folder, year=year)

        if not result:
            return jsonify({'success': False, 'error': f'No HLTB match found for "{search_query}"'})

        return jsonify({
            'success': True,
            'result': {
                'hltb_id': result.get('game_id'),
                'main_story': format_playtime(result['main_story']) if result.get('main_story') else None,
                'main_extra': format_playtime(result['main_plus_sides']) if result.get('main_plus_sides') else None,
                'completionist': format_playtime(result['completionist']) if result.get('completionist') else None,
                'match_name': result.get('match_name', ''),
                'match_platform': result.get('match_platform', ''),
                'confidence': result.get('match_confidence', 0),
                'platform_mismatch': result.get('platform_mismatch', False),
                'release_year': result.get('release_world'),
                'developer': result.get('profile_dev')
            }
        })

    except Exception as e:
        logger.error(f"HLTB search error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500
