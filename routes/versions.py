# =============================================================================
# RETRODB - Regional Versions Blueprint (PASS-59-106)
# =============================================================================
# Links games as versions of one game, unlinks them, records "not versions",
# and serves the suggestion review page (ROM Tools > Regional Versions). The
# rules live in services/version_groups.py; the contract is
# docs/specs/PASS-59-106-regional-versions.md §4.5.
# =============================================================================

from flask import Blueprint, render_template, request
from flask_babel import gettext as _

from services.auth import editor_required
from services.database import query
from services.api_helpers import handle_api_errors, success, error
from services import version_groups

bp = Blueprint('versions', __name__)


def _link_error(exc):
    messages = {
        'too_few': (_('Pick at least two games.'), 400),
        'not_found': (_('One of those games no longer exists.'), 404),
        'systems': (_('Versions must all be on the same system.'), 400),
        'bonus': (_('A bonus disc cannot be a version of a game.'), 400),
    }
    message, code = messages.get(exc.reason, (_('Those games cannot be linked.'), 400))
    return error(message, code)


def _game_ids():
    data = request.get_json(silent=True) or {}
    ids = data.get('game_ids')
    return ids if isinstance(ids, list) else []


@bp.route('/tools/versions')
@editor_required
def versions_review():
    """Review page: suggested version groups to link or reject."""
    systems = query("""
        SELECT s.id, s.name FROM systems s
        WHERE EXISTS (SELECT 1 FROM games g WHERE g.system_id = s.id)
        ORDER BY s.name COLLATE NOCASE
    """)
    return render_template('versions_review.html', systems=systems)


@bp.route('/api/versions/suggestions')
@editor_required
@handle_api_errors
def api_version_suggestions():
    system_id = request.args.get('system_id', type=int)
    return success(suggestions=version_groups.suggest_groups(system_id))


@bp.route('/api/versions/for-game/<int:game_id>')
@editor_required
@handle_api_errors
def api_versions_for_game(game_id):
    return success(versions=version_groups.members(game_id))


@bp.route('/api/versions/link', methods=['POST'])
@editor_required
@handle_api_errors
def api_versions_link():
    try:
        group_id = version_groups.link(_game_ids())
    except version_groups.VersionLinkError as exc:
        return _link_error(exc)
    return success(version_group_id=group_id)


@bp.route('/api/versions/unlink/<int:game_id>', methods=['POST'])
@editor_required
@handle_api_errors
def api_versions_unlink(game_id):
    if not version_groups.unlink(game_id):
        return error(_('That game is not linked to other versions.'), 404)
    return success()


@bp.route('/api/versions/ai-summary/<int:game_id>', methods=['POST'])
@editor_required
@handle_api_errors
def api_versions_ai_summary(game_id):
    """PASS-59-107: write the AI summary of how this game's versions differ."""
    from scraper import scrape_ai
    if not scrape_ai.active_provider_name():
        return error(_('Set up an AI provider in Settings > Scraping first.'), 400)
    try:
        summary = version_groups.generate_ai_summary(game_id)
    except version_groups.VersionLinkError:
        return error(_('That game is not linked to other versions.'), 404)
    if summary is None:
        return error(_('The AI did not give a usable answer. Try again later.'), 502)
    return success(summary=summary)


@bp.route('/api/versions/reject', methods=['POST'])
@editor_required
@handle_api_errors
def api_versions_reject():
    try:
        version_groups.reject(_game_ids())
    except version_groups.VersionLinkError as exc:
        return _link_error(exc)
    return success()
