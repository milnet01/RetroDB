# =============================================================================
# RETRODB - Official Names Blueprint (PASS-59-159)
# =============================================================================
# ROM Tools > Official Names: start an AI run that proposes each game's
# official name, then accept or reject the proposals. The rules live in
# services/official_names.py and services/jobs/official_names.py; the
# contract is docs/specs/PASS-59-159-official-names.md §4.5.
# =============================================================================

from flask import Blueprint, render_template, request
from flask_babel import gettext as _

from services import official_names
from services.analytics import invalidate_analytics_cache
from services.api_helpers import handle_api_errors, success, error
from services.auth import editor_required
from services.database import query
from services.game_query import invalidate_filter_cache

bp = Blueprint('official_names', __name__)

_MAX_IDS = 5000


def _game_ids():
    data = request.get_json(silent=True) or {}
    ids = data.get('game_ids')
    if not isinstance(ids, list):
        return []
    return [i for i in ids if isinstance(i, int) and not isinstance(i, bool)][:_MAX_IDS]


@bp.route('/tools/official-names')
@editor_required
def official_names_review():
    """Review page: run the AI, then accept or reject its proposed names."""
    systems = query("""
        SELECT s.id, s.name FROM systems s
        WHERE EXISTS (SELECT 1 FROM games g WHERE g.system_id = s.id)
        ORDER BY s.name COLLATE NOCASE
    """)
    return render_template('official_names_review.html', systems=systems)


@bp.route('/api/official-names/proposals')
@editor_required
@handle_api_errors
def api_official_names_proposals():
    system_id = request.args.get('system_id', type=int)
    return success(proposals=official_names.pending(system_id))


@bp.route('/api/official-names/accept', methods=['POST'])
@editor_required
@handle_api_errors
def api_official_names_accept():
    accepted, skipped = official_names.accept(_game_ids())
    invalidate_filter_cache()
    invalidate_analytics_cache()
    return success(accepted=accepted, skipped=skipped)


@bp.route('/api/official-names/reject', methods=['POST'])
@editor_required
@handle_api_errors
def api_official_names_reject():
    return success(rejected=official_names.reject(_game_ids()))


@bp.route('/api/official-names/run', methods=['POST'])
@editor_required
@handle_api_errors
def api_official_names_run():
    from scraper import scrape_ai
    from services.jobs import official_names_job
    if not scrape_ai.active_provider_name():
        return error(_('Set up an AI provider in Settings > Scraping first.'), 400)
    data = request.get_json(silent=True) or {}
    system_id = data.get('system_id')
    if system_id is not None and (not isinstance(system_id, int) or isinstance(system_id, bool)):
        return error(_('Pick a system, or all systems.'), 400)
    result = official_names_job.start(system_id)
    if not result.get('success'):
        return error(_('An official names run is already running.'), 409)
    return success(job_id=result['job_id'])


@bp.route('/api/official-names/status')
@editor_required
@handle_api_errors
def api_official_names_status():
    from services.jobs import official_names_job
    return success(status=official_names_job.get_status())


@bp.route('/api/official-names/cancel', methods=['POST'])
@editor_required
@handle_api_errors
def api_official_names_cancel():
    from services.jobs import official_names_job
    result = official_names_job.cancel()
    if not result.get('success'):
        return error(_('No official names run to cancel.'), 400)
    return success()
