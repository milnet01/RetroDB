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

_REPLY_FIELDS = (
    'id', 'title', 'sort_title', 'title_locked', 'genre', 'description', 'developer',
    'publisher', 'release_date', 'release_dates', 'players', 'modes', 'units_sold',
    'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating',
    'grac_rating', 'classind_rating', 'china_rating',
    'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
    'region', 'franchise', 'similar_games', 'controller_support', 'save_type',
    'game_structure', 'perspective', 'dimension', 'campaign', 'other_platforms', 'edition',
)


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

        # Every field the edit modal shows, and every field this fill wrote
        # (PASS-59-249: units_sold, release_dates and the scores were missing).
        shown = {f: updated_game.get(f) for f in _REPLY_FIELDS}
        shown.update({f: updated_game.get(f) for f in filled_fields if f in updated_game})
        return success(filled_fields=filled_fields, filled_count=len(filled_fields), game=shown)

    except ImportError:
        return error(_('AI scraper module not available'), 500)
