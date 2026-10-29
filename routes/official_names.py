# =============================================================================
# RETRODB - Official Names Blueprint (PASS-59-159)
# =============================================================================
# ROM Tools > Bulk AI Fill. Its Official Names card starts an AI run that
# proposes each game's official name, then accepts or rejects the proposals.
# The rules live in services/official_names.py and
# services/jobs/official_names.py; the contract is
# docs/specs/PASS-59-159-official-names.md §4.5. The page's other card starts
# a bulk AI Fill (routes at the end of this file).
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
    return render_template('official_names_review.html', systems=systems,
                           fill_switches=_fill_switches())


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


# Bulk AI Fill: the game page's AI Fill run on every game of a system, or of
# all systems, written straight to the games (services/jobs/ai_fill_bulk.py).

def _fill_switches():
    """(key, label) for each of the run's on/off switches, in page order."""
    from services.ai_fill import FIELD_GROUPS
    labels = {
        'title': _('Official name'),
        'description': _('Game Description'),
        'genre': _('Genre'),
        'developer': _('Developer'),
        'publisher': _('Publisher'),
        'release_date': _('Release Date'),
        'release_dates': _('Release dates'),
        'units_sold': _('Copies sold'),
        'players': _('Players'),
        'modes': _('Play Modes'),
        'region': _('Region'),
        'franchise': _('Franchise / Series'),
        'similar_games': _('Similar Games'),
        'other_platforms': _('Platform Availability'),
        'controller_support': _('Controller Support'),
        'save_type': _('Save Type'),
        'game_structure': _('Game Structure'),
        'perspective': _('Perspective'),
        'dimension': _('Dimension'),
        'campaign': _('Campaign'),
        'edition': _('Edition'),
        'ratings': _('Age Ratings'),
        'critic_score': _('Critic Score'),
        'user_score': _('User Score'),
    }
    return [(key, labels[key]) for key in FIELD_GROUPS]


def _groups_arg(value):
    """Switch keys from a list or a comma-separated string, None for every
    field, or False when a key is unknown."""
    from services.ai_fill import FIELD_GROUPS
    if value is None:
        return None
    if isinstance(value, str):
        value = [v for v in value.split(',') if v]
    if not isinstance(value, list) or not all(v in FIELD_GROUPS for v in value):
        return False
    return [key for key in FIELD_GROUPS if key in value]


def _system_id_arg(value):
    """A system id, None for all systems, or False when it is neither."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return False


@bp.route('/api/ai-fill-bulk/count')
@editor_required
@handle_api_errors
def api_ai_fill_bulk_count():
    from services.jobs.ai_fill_bulk import count_games_to_fill
    groups = _groups_arg(request.args.get('fields'))
    if groups is False:
        return error(_('Unknown field.'), 400)
    return success(count=count_games_to_fill(
        request.args.get('system_id', type=int), groups,
        request.args.get('include_done') == '1'))


@bp.route('/api/ai-fill-bulk/run', methods=['POST'])
@editor_required
@handle_api_errors
def api_ai_fill_bulk_run():
    from scraper import scrape_ai
    from services.jobs import ai_fill_bulk_job
    if not scrape_ai.active_provider_name():
        return error(_('Set up an AI provider in Settings > Scraping first.'), 400)
    data = request.get_json(silent=True) or {}
    system_id = _system_id_arg(data.get('system_id'))
    if system_id is False:
        return error(_('Pick a system, or all systems.'), 400)
    fields = data.get('fields')
    groups = _groups_arg(fields) if fields is None or isinstance(fields, list) else False
    if groups is False:
        return error(_('Unknown field.'), 400)
    if groups == []:
        return error(_('Turn on at least one field.'), 400)
    result = ai_fill_bulk_job.start(system_id, groups, data.get('include_done') is True)
    if not result.get('success'):
        return error(_('An AI fill run is already running.'), 409)
    return success(job_id=result['job_id'])


@bp.route('/api/ai-fill-bulk/status')
@editor_required
@handle_api_errors
def api_ai_fill_bulk_status():
    from services.jobs import ai_fill_bulk_job
    # Flat, like the other jobs' status replies: the toast reads it as is.
    return success(**ai_fill_bulk_job.get_status())


@bp.route('/api/ai-fill-bulk/cancel', methods=['POST'])
@editor_required
@handle_api_errors
def api_ai_fill_bulk_cancel():
    from services.jobs import ai_fill_bulk_job
    result = ai_fill_bulk_job.cancel()
    if not result.get('success'):
        return error(_('No AI fill run to cancel.'), 400)
    return success()
