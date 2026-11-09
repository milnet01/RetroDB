# =============================================================================
# RETRODB - RetroAchievements Sync Blueprint
# =============================================================================
# Handles RetroAchievements refresh and sync background job management.
# =============================================================================

from flask import Blueprint, jsonify, g
from flask_babel import gettext as _
import logging

from services.analytics import invalidate_analytics_cache
from services.api_helpers import handle_api_errors, success, error, job_reply
from services.auth import login_required, admin_required, editor_required
from services.database import query, execute
from services.jobs import ra_sync_job, ra_refresh_job, ra_queue
from services.jobs.base import may_control

logger = logging.getLogger(__name__)

bp = Blueprint('ra_sync', __name__)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def system_log(level, message):
    """Log a system message"""
    if level == 'info':
        logger.info(message)
    elif level == 'warning':
        logger.warning(message)
    elif level == 'error':
        logger.error(message)
    else:
        logger.debug(message)


def queued_reply(kind, system_id, system_name, user_id=None, **extra):
    """Put an RA job in the server's queue and say so (PASS-59-268). The
    reply keeps `queued: true`; `queue_id` and `position` say where it waits."""
    item = ra_queue.add(kind, system_id, system_name, user_id=user_id)
    system_log('info', f'RA {kind} for {system_name} queued at position {item["position"]}')
    return success(
        queued=True,
        queue_id=item['id'],
        position=item['position'],
        system_id=system_id,
        system_name=system_name,
        message=_('%(name)s will start when the current RetroAchievements job '
                  'finishes. Place in line: %(num)s.',
                  name=system_name, num=item['position']),
        **extra,
    )


def _may_cancel(item):
    """A queued refresh is an admin's; a queued sync is its owner's or an admin's."""
    if item['kind'] == 'refresh':
        return g.user['role'] == 'admin'
    return may_control(item['user_id'], g.user)


# =============================================================================
# RETROACHIEVEMENTS REFRESH API
# =============================================================================

@bp.route('/api/refresh-retroachievements', methods=['POST'])
@admin_required
@handle_api_errors
def api_refresh_retroachievements():
    """Start background job to refresh RetroAchievements status for all games"""
    # RA Sync and RA Refresh share one account: while either runs, wait in
    # the server's queue (PASS-59-268).
    if ra_queue.busy():
        return queued_reply('refresh', None, _('All Systems'))

    result = ra_refresh_job.start()
    return job_reply(result)


@bp.route('/api/refresh-retroachievements/status', methods=['GET'])
@login_required
def api_refresh_retroachievements_status():
    """Get status of the RA refresh background job"""
    return jsonify({**ra_refresh_job.get_status(), 'ra_queue': ra_queue.items()})


@bp.route('/api/refresh-retroachievements/cancel', methods=['POST'])
@admin_required
def api_refresh_retroachievements_cancel():
    """Cancel the running RA refresh job"""
    return jsonify(ra_refresh_job.cancel())


@bp.route('/api/refresh-retroachievements/<int:system_id>', methods=['POST'])
@admin_required
@handle_api_errors
def api_refresh_retroachievements_system(system_id):
    """Refresh RetroAchievements status for games in a specific system (background job)"""
    from scraper.retroachievements import RA_CONSOLE_MAP

    # Get the system
    system = query("SELECT * FROM systems WHERE id = ?", (system_id,), one=True)
    if not system:
        return error(_('System not found'), 404)

    system_folder = system['folder'].lower()

    # Check if system supports RA
    if system_folder not in RA_CONSOLE_MAP:
        return error(_('System %(name)s does not support RetroAchievements') % {'name': system["name"]}, 400)

    # Get game count for this system
    game_count = query("SELECT COUNT(*) as cnt FROM games WHERE system_id = ?", (system_id,), one=True)['cnt']

    if ra_queue.busy():
        return queued_reply('refresh', system_id, system['name'], game_count=game_count)

    # Start the per-system refresh
    result = ra_refresh_job.start(system_id=system_id, system_name=system['name'])
    result['game_count'] = game_count

    return job_reply(result)


# =============================================================================
# RETROACHIEVEMENTS QUEUE API (PASS-59-268)
# =============================================================================

@bp.route('/api/ra-queue', methods=['GET'])
@login_required
def api_ra_queue():
    """RA jobs waiting for the running one, in the order they will start."""
    return success(queue=ra_queue.items())


@bp.route('/api/ra-queue/<int:item_id>/cancel', methods=['POST'])
@editor_required
@handle_api_errors
def api_ra_queue_cancel(item_id):
    """Take a waiting RA job out of the queue."""
    item = ra_queue.get(item_id)
    if not item:
        return error(_('That job is no longer waiting'), 404)
    if not _may_cancel(item):
        return error(_('That job belongs to another user'), 403)
    ra_queue.cancel(item_id)
    return success(queue=ra_queue.items())


# =============================================================================
# CLEAR RA DATA API
# =============================================================================

# PASS-59-117 — the progress table holds Steam and Xbox rows too; clearing RA
# data must leave them. A row with no source predates the column: RA's.
_RA_ROWS = "COALESCE(source, 'ra') = 'ra'"


@bp.route('/api/clear-ra-data/<int:system_id>', methods=['POST'])
@admin_required
@handle_api_errors
def api_clear_ra_data_system(system_id):
    """Clear RetroAchievements data for a specific system - useful for re-scanning after algorithm updates"""
    # Get games for this system
    games = query("""
        SELECT id FROM games WHERE system_id = ? AND ra_game_id IS NOT NULL
    """, (system_id,))

    if not games:
        return success(
            message='No games with RA data found for this system',
            cleared=0,
        )

    game_ids = [g['id'] for g in games]

    # Clear ra_game_id from games table
    execute("""
        UPDATE games SET ra_game_id = NULL, ra_title = NULL, ra_achievement_count = NULL,
            ra_points = NULL, has_retroachievements = 0, ra_copy_fits = NULL
        WHERE system_id = ?
    """, (system_id,))

    # Clear progress data
    placeholders = ','.join('?' * len(game_ids))
    execute(f"""
        DELETE FROM game_achievement_progress
        WHERE game_id IN ({placeholders}) AND {_RA_ROWS}
    """, game_ids)

    invalidate_analytics_cache()
    return success(
        message=f'Cleared RA data for {len(games)} games',
        cleared=len(games),
    )


@bp.route('/api/clear-ra-data', methods=['POST'])
@admin_required
@handle_api_errors
def api_clear_ra_data_all():
    """Clear all RetroAchievements data - useful for re-scanning after algorithm updates"""
    # Count before clearing
    count = query("SELECT COUNT(*) as c FROM games WHERE ra_game_id IS NOT NULL", one=True)['c']

    # Clear all ra_game_id values (only touch rows that have RA data)
    execute("UPDATE games SET ra_game_id = NULL, ra_title = NULL, ra_achievement_count = NULL, "
            "ra_points = NULL, has_retroachievements = 0, ra_copy_fits = NULL "
            "WHERE ra_game_id IS NOT NULL")

    # Clear all RA progress data
    execute(f"DELETE FROM game_achievement_progress WHERE {_RA_ROWS}")

    invalidate_analytics_cache()
    return success(
        message=f'Cleared RA data for {count} games',
        cleared=count,
    )
