# =============================================================================
# RETRODB - HowLongToBeat (HLTB) API Routes
# =============================================================================
# Lookup, save, clear, and search endpoints for HLTB playtime data.
# =============================================================================

import json

from flask import Blueprint, render_template, request, jsonify

from services.database import query, execute
from services.auth import login_required, admin_required
from services.api_helpers import handle_api_errors

bp = Blueprint('games_hltb', __name__)


def _extract_alt_titles(alternate_titles_json):
    """Decode games.alternate_titles JSON into a flat list of title strings."""
    if not alternate_titles_json:
        return []
    try:
        parsed = json.loads(alternate_titles_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    titles = []
    for entry in parsed:
        if isinstance(entry, dict):
            t = entry.get('title')
            if isinstance(t, str) and t.strip():
                titles.append(t.strip())
    return titles


@bp.route('/api/hltb-lookup/<int:game_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_hltb_lookup(game_id):
    """Look up playtime from HLTB for a game."""
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

    # Pull alternate titles from the game row so HLTB can fall back to
    # regional names (e.g. search for "Action in New York" matches the
    # canonical "S.C.A.T.: Special Cybernetic Attack Team").
    alt_titles = _extract_alt_titles(game.get('alternate_titles'))

    result = lookup_playtime(search_title, game['system_folder'],
                             alternate_titles=alt_titles)

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
        'completionist': result['completionist'],
        'search_term_used': result.get('search_term_used'),
        'matched_via_alternate': result.get('matched_via_alternate', False),
    })


@bp.route('/api/hltb-save/<int:game_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_hltb_save(game_id):
    """Save HLTB playtime data to database."""
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


@bp.route('/api/hltb-clear/<int:game_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_hltb_clear(game_id):
    """Clear HLTB playtime data from database."""
    execute("""
        UPDATE games SET
            playtime_estimate = NULL,
            hltb_match_name = NULL,
            hltb_match_platform = NULL,
            hltb_match_confidence = NULL
        WHERE id = ?
    """, (game_id,))

    return jsonify({'success': True})


@bp.route('/api/hltb/search', methods=['POST'])
@login_required
@handle_api_errors
def api_hltb_search():
    """Generic HLTB search by title (used by game detail, PSN trophies, achievements)."""
    from scraper.hltb_lookup import lookup_playtime, format_playtime

    data = request.get_json() or {}
    search_query = str(data.get('query', '')).strip()
    system_folder = str(data.get('system_folder', '')).strip()
    year = str(data.get('year', '')).strip() or None

    if not search_query:
        return jsonify({'success': False, 'error': 'No search query provided'})

    # Resolve alternate titles: explicit list wins; otherwise look them up
    # from the game row if a game_id was supplied.
    alt_titles = []
    explicit_alts = data.get('alternate_titles')
    if isinstance(explicit_alts, list):
        alt_titles = [str(t).strip() for t in explicit_alts if str(t).strip()]
    elif data.get('game_id'):
        try:
            row = query(
                "SELECT alternate_titles FROM games WHERE id = ?",
                (int(data['game_id']),), one=True,
            )
            if row:
                alt_titles = _extract_alt_titles(row.get('alternate_titles'))
        except (ValueError, TypeError):
            pass

    folder = system_folder or 'ps4'
    result = lookup_playtime(search_query, folder, year=year,
                             alternate_titles=alt_titles or None)

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
            'developer': result.get('profile_dev'),
            'search_term_used': result.get('search_term_used'),
            'matched_via_alternate': result.get('matched_via_alternate', False),
        }
    })


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
    from services.jobs import hltb_bulk_job
    data = request.get_json(silent=True) or {}
    only_missing = bool(data.get('only_missing', True))
    threshold = int(data.get('confidence_threshold', 95))
    result = hltb_bulk_job.start(only_missing=only_missing,
                                 confidence_threshold=threshold)
    return jsonify(result)


@bp.route('/api/hltb/bulk/status', methods=['GET'])
@login_required
@handle_api_errors
def api_hltb_bulk_status():
    """Poll bulk HLTB lookup job status."""
    from services.jobs import hltb_bulk_job
    status = hltb_bulk_job.get_status()
    status['success'] = True
    # Include queue depth so the UI can deep-link to /hltb/review.
    queue_row = query("SELECT COUNT(*) AS c FROM hltb_pending_matches", (), one=True)
    status['pending_review'] = queue_row['c'] if queue_row else 0
    return jsonify(status)


@bp.route('/api/hltb/bulk/cancel', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_bulk_cancel():
    """Cancel the running bulk HLTB lookup."""
    from services.jobs import hltb_bulk_job
    result = hltb_bulk_job.cancel()
    return jsonify(result)


@bp.route('/api/hltb/pending', methods=['GET'])
@login_required
@handle_api_errors
def api_hltb_pending_list():
    """Return all queued HLTB matches awaiting review."""
    rows = query("""
        SELECT p.id, p.game_id, p.hltb_id, p.match_name, p.match_platform,
               p.confidence, p.playtime, p.main_story, p.main_plus_sides,
               p.completionist, p.search_term_used, p.matched_via_alternate,
               p.reason, p.created_at,
               g.title AS game_title, s.name AS system_name
        FROM hltb_pending_matches p
        JOIN games g ON p.game_id = g.id
        JOIN systems s ON g.system_id = s.id
        ORDER BY p.reason, g.title
    """)
    items = []
    for r in rows or []:
        d = dict(r)
        d['matched_via_alternate'] = bool(d.get('matched_via_alternate'))
        items.append(d)
    return jsonify({'success': True, 'items': items})


def _apply_pending_match(pending_row):
    """Write the pending match to the games row and delete it from the queue."""
    confidence_frac = None
    if pending_row.get('confidence') is not None:
        try:
            c = float(pending_row['confidence'])
            confidence_frac = c / 100.0 if c > 1 else c
        except (ValueError, TypeError):
            confidence_frac = None
    execute("""
        UPDATE games SET
            playtime_estimate = ?,
            hltb_match_name = ?,
            hltb_match_platform = ?,
            hltb_match_confidence = ?
        WHERE id = ?
    """, (pending_row.get('playtime'), pending_row.get('match_name'),
          pending_row.get('match_platform'), confidence_frac,
          pending_row['game_id']))
    execute("DELETE FROM hltb_pending_matches WHERE id = ?", (pending_row['id'],))


@bp.route('/api/hltb/pending/<int:pending_id>/approve', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_approve(pending_id):
    """Approve a single pending match — write it to the game row."""
    row = query("SELECT * FROM hltb_pending_matches WHERE id = ?", (pending_id,), one=True)
    if not row:
        return jsonify({'success': False, 'error': 'Pending match not found'}), 404
    _apply_pending_match(dict(row))
    return jsonify({'success': True})


@bp.route('/api/hltb/pending/<int:pending_id>/reject', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_reject(pending_id):
    """Reject a single pending match — drop it from the queue."""
    execute("DELETE FROM hltb_pending_matches WHERE id = ?", (pending_id,))
    return jsonify({'success': True})


def _resolve_filter_clause(filter_value):
    """Map the UI filter to a (where_clause, params) pair."""
    if filter_value == 'alt_title':
        return ("WHERE reason = 'alt_title'", ())
    if filter_value == 'low_confidence':
        return ("WHERE reason = 'low_confidence'", ())
    return ("", ())


@bp.route('/api/hltb/pending/approve-all', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_approve_all():
    """Approve every pending match matching the current filter."""
    data = request.get_json(silent=True) or {}
    where, params = _resolve_filter_clause(data.get('filter', 'all'))
    rows = query(f"SELECT * FROM hltb_pending_matches {where}", params)
    applied = 0
    for r in rows or []:
        _apply_pending_match(dict(r))
        applied += 1
    return jsonify({'success': True, 'applied': applied})


@bp.route('/api/hltb/pending/reject-all', methods=['POST'])
@admin_required
@handle_api_errors
def api_hltb_pending_reject_all():
    """Drop every pending match matching the current filter."""
    data = request.get_json(silent=True) or {}
    where, params = _resolve_filter_clause(data.get('filter', 'all'))
    count_row = query(f"SELECT COUNT(*) AS c FROM hltb_pending_matches {where}",
                      params, one=True)
    count = count_row['c'] if count_row else 0
    execute(f"DELETE FROM hltb_pending_matches {where}", params)
    return jsonify({'success': True, 'rejected': count})
