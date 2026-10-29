# =============================================================================
# RETRODB - AI Metadata Fill Route
# =============================================================================
# POST /api/game/<id>/ai-fill — fill missing metadata via AI (Gemini/OpenAI/Claude).
# The fill rules live in services/ai_fill.py, shared with the bulk run.
# =============================================================================

import logging

from flask import Blueprint
from flask_babel import gettext as _

from services.api_helpers import handle_api_errors, success, error
from services.auth import editor_required

logger = logging.getLogger(__name__)

bp = Blueprint('games_ai', __name__)


@bp.route('/api/game/<int:game_id>/ai-fill', methods=['POST'])
@editor_required
@handle_api_errors
def api_game_ai_fill(game_id):
    """Fill missing metadata fields using AI scraper with smart overwrite logic."""
    try:
        from services.ai_fill import load_game
        game = load_game(game_id)

        if not game:
            return error(_('Game not found'), 404)

        from services.ai_fill import fill_game
        filled_fields = fill_game(game)
        if filled_fields is None:
            return error(
                _('AI returned no data. Check your API key and provider settings.'),
                code=502,
            )

        updated_game = load_game(game_id)

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
                'china_rating': updated_game.get('china_rating'),
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
        return error(_('AI scraper module not available'), 500)
