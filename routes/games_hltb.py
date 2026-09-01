# =============================================================================
# RETRODB - HowLongToBeat (HLTB) API Routes
# =============================================================================
# Thin HTTP wrappers over services.hltb_service. Lookup / save / clear /
# generic search, plus the bulk-lookup review queue and job orchestration.
# =============================================================================

from flask import Blueprint, jsonify, render_template, request

from services.auth import login_required, admin_required, permission_required
from services.api_helpers import handle_api_errors, success, error
from services.hltb_service import (
    lookup_service, pending_queue, bulk_orchestrator,
    HLTBError,
)

bp = Blueprint('games_hltb', __name__)


# `edit`, not `login_required`: lookup writes playtime_estimate whenever
# `preview` is falsy, and `preview` defaults to False -- so this is a write
# path, not a read one. save/clear likewise: clear() NULLs four curated
# columns. At @login_required the read-only `viewer` role reached all three.
@bp.route('/api/hltb-lookup/<int:game_id>', methods=['POST'])
@permission_required('edit')
@handle_api_errors
def api_hltb_lookup(game_id):
    """Look up playtime from HLTB for a game."""
    data = request.get_json() or {}
    try:
        result = lookup_service.lookup(
            game_id,
            search_title=data.get('search_title'),
            preview=bool(data.get('preview', False)),
        )
    except HLTBError as e:
        return error(e.message, e.status_code)
    return success(**result)


@bp.route('/api/hltb-save/<int:game_id>', methods=['POST'])
@permission_required('edit')
@handle_api_errors
def api_hltb_save(game_id):
    """Save HLTB playtime data to the database."""
    try:
        lookup_service.save_result(game_id, request.get_json() or {})
    except HLTBError as e:
        return error(e.message, e.status_code)
    return success()


@bp.route('/api/hltb-clear/<int:game_id>', methods=['POST'])
@permission_required('edit')
@handle_api_errors
def api_hltb_clear(game_id):
    """Clear HLTB playtime data from the database."""
    lookup_service.clear(game_id)
    return success()


@bp.route('/api/hltb/search', methods=['POST'])
@login_required
@handle_api_errors
def api_hltb_search():
    """Generic HLTB search by title (game detail, PSN trophies, achievements)."""
    data = request.get_json() or {}
    try:
        result = lookup_service.search(
            data.get('query', ''),
            data.get('system_folder', ''),
            year=data.get('year'),
            alternate_titles=data.get('alternate_titles'),
            game_id=data.get('game_id'),
        )
    except HLTBError as e:
        return error(e.message, e.status_code)
    return success(result=result)


# =============================================================================
# BULK HLTB LOOKUP JOB + REVIEW QUEUE
# =============================================================================

@bp.route('/hltb/review')
@login_required
def hltb_review_page():
    """Render the HLTB pending-matches review page."""
    return render_template('hltb_review.html')


@bp.route('/api/hltb/bulk/start', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_bulk_start():
    """Kick off a bulk HLTB lookup across the library."""
    data = request.get_json(silent=True) or {}
    # The job class already returns a canonical {'success': ..., ...} dict;
    # pass through verbatim rather than reshape through success()/error().
    return jsonify(bulk_orchestrator.start(
        only_missing=bool(data.get('only_missing', True)),
        confidence_threshold=int(data.get('confidence_threshold', 95)),
    ))


@bp.route('/api/hltb/bulk/status', methods=['GET'])
@login_required
@handle_api_errors
def api_hltb_bulk_status():
    """Poll bulk HLTB lookup job status."""
    return success(**bulk_orchestrator.status())


@bp.route('/api/hltb/bulk/cancel', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_bulk_cancel():
    """Cancel the running bulk HLTB lookup."""
    return jsonify(bulk_orchestrator.cancel())


@bp.route('/api/hltb/pending', methods=['GET'])
@login_required
@handle_api_errors
def api_hltb_pending_list():
    """Return all queued HLTB matches awaiting review."""
    return success(items=pending_queue.list())


@bp.route('/api/hltb/pending/<int:pending_id>/approve', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_approve(pending_id):
    """Approve a single pending match — write it to the game row."""
    try:
        pending_queue.approve(pending_id)
    except HLTBError as e:
        return error(e.message, e.status_code)
    return success()


@bp.route('/api/hltb/pending/<int:pending_id>/reject', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_reject(pending_id):
    """Reject a single pending match — drop it from the queue."""
    pending_queue.reject(pending_id)
    return success()


@bp.route('/api/hltb/pending/approve-all', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_approve_all():
    """Approve every pending match matching the current filter."""
    data = request.get_json(silent=True) or {}
    applied = pending_queue.approve_all(data.get('filter', 'all'))
    return success(applied=applied)


@bp.route('/api/hltb/pending/reject-all', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_reject_all():
    """Drop every pending match matching the current filter."""
    data = request.get_json(silent=True) or {}
    rejected = pending_queue.reject_all(data.get('filter', 'all'))
    return success(rejected=rejected)
