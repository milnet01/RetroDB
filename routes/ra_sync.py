# =============================================================================
# RETRODB - RetroAchievements Sync Blueprint
# =============================================================================
# Handles RetroAchievements refresh and sync background job management.
# =============================================================================

from flask import Blueprint, jsonify
import logging

from services.analytics import invalidate_analytics_cache
from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required, admin_required
from services.database import query, execute
from services.jobs import ra_sync_job, ra_refresh_job

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


# =============================================================================
# RETROACHIEVEMENTS REFRESH API
# =============================================================================

@bp.route('/api/refresh-retroachievements', methods=['POST'])
@admin_required
@handle_api_errors
def api_refresh_retroachievements():
    """Start background job to refresh RetroAchievements status for all games"""
    # Check if RA Sync is currently running - they share the same API
    sync_status = ra_sync_job.get_status()
    if sync_status.get('running', False) and not sync_status.get('completed', False):
        system_log('info', 'RA Sync is running, queueing global RA Refresh')
        return success(
            queued=True,
            message='RA Sync is running. Global Refresh will start when current operation completes.',
            blocked_by='ra-sync',
            system_id=None,
            system_name='All Systems',
        )

    # Check if RA Refresh is already running
    refresh_status = ra_refresh_job.get_status()
    if refresh_status.get('running', False) and not refresh_status.get('completed', False):
        system_log('info', 'RA Refresh already running, cannot start another')
        return success(
            queued=True,
            message='Another RA Refresh is running. Global Refresh will start when current operation completes.',
            blocked_by='ra-refresh',
            system_id=None,
            system_name='All Systems',
        )

    result = ra_refresh_job.start()
    return jsonify(result)


@bp.route('/api/refresh-retroachievements/status', methods=['GET'])
@login_required
def api_refresh_retroachievements_status():
    """Get status of the RA refresh background job"""
    return jsonify(ra_refresh_job.get_status())


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
        return error('System not found', 404)

    system_folder = system['folder'].lower()

    # Check if system supports RA
    if system_folder not in RA_CONSOLE_MAP:
        return error(f'System {system["name"]} does not support RetroAchievements', 400)

    # Get game count for this system
    game_count = query("SELECT COUNT(*) as cnt FROM games WHERE system_id = ?", (system_id,), one=True)['cnt']

    # Check if RA Sync is currently running - they share the same API
    sync_status = ra_sync_job.get_status()
    if sync_status.get('running', False) and not sync_status.get('completed', False):
        system_log('info', f'RA Sync is running, queueing RA Refresh for {system["name"]}')
        return success(
            queued=True,
            message=f'RA Sync is running. {system["name"]} Refresh will start when current operation completes.',
            blocked_by='ra-sync',
            system_id=system_id,
            system_name=system['name'],
            game_count=game_count,
        )

    # Check if RA Refresh is already running
    refresh_status = ra_refresh_job.get_status()
    if refresh_status.get('running', False) and not refresh_status.get('completed', False):
        system_log('info', f'RA Refresh already running, queueing Refresh for {system["name"]}')
        return success(
            queued=True,
            message=f'Another RA Refresh is running. {system["name"]} will start when current operation completes.',
            blocked_by='ra-refresh',
            system_id=system_id,
            system_name=system['name'],
            game_count=game_count,
        )

    # Start the per-system refresh
    result = ra_refresh_job.start(system_id=system_id, system_name=system['name'])
    result['game_count'] = game_count

    return jsonify(result)


# =============================================================================
# CLEAR RA DATA API
# =============================================================================

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
        UPDATE games SET ra_game_id = NULL, has_retroachievements = 0
        WHERE system_id = ?
    """, (system_id,))

    # Clear progress data
    placeholders = ','.join('?' * len(game_ids))
    execute(f"""
        DELETE FROM game_achievement_progress WHERE game_id IN ({placeholders})
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
    execute("UPDATE games SET ra_game_id = NULL, has_retroachievements = 0 WHERE ra_game_id IS NOT NULL")

    # Clear all progress data
    execute("DELETE FROM game_achievement_progress")

    invalidate_analytics_cache()
    return success(
        message=f'Cleared RA data for {count} games',
        cleared=count,
    )
