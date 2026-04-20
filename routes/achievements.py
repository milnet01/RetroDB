# =============================================================================
# RETRODB - Achievements Routes Blueprint
# =============================================================================
# Handles RetroAchievements integration and synchronization.
# =============================================================================

from flask import Blueprint, render_template, redirect, url_for, jsonify, flash, g
import logging
from datetime import datetime, timezone

from services.database import query, execute
from services.auth import login_required
from services.jobs import ra_sync_job, ra_refresh_job

logger = logging.getLogger('scraper')

bp = Blueprint('achievements', __name__)


def system_log(level, message):
    """Convenience function for system category logging"""
    if level == 'info':
        logger.info(message)
    elif level == 'warning':
        logger.warning(message)
    elif level == 'error':
        logger.error(message)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_user_ra_credentials():
    """Get RetroAchievements credentials for current user, or global if not configured

    NOTE: This function is duplicated in routes/trophies.py. If modifying, update both.
    """
    if g.user and g.user_settings:
        try:
            user_username = g.user_settings['ra_username'] or ''
            user_api_key = g.user_settings['ra_api_key'] or ''
            if user_username and user_api_key:
                return user_username, user_api_key
        except (KeyError, TypeError):
            pass
    
    # Fall back to global credentials
    from scraper.retroachievements import get_ra_credentials
    return get_ra_credentials()


@bp.route('/achievements')
@login_required
def achievements():
    """RetroAchievements - redirects to last visited or first system with achievement games"""
    # Get first system as fallback
    first_system = query("""
        SELECT s.id
        FROM systems s
        JOIN games g ON g.system_id = s.id
        WHERE g.ra_game_id IS NOT NULL AND g.ra_game_id != ''
        GROUP BY s.id
        ORDER BY s.name COLLATE NOCASE
        LIMIT 1
    """, one=True)
    
    if not first_system:
        flash('No games with RetroAchievements found in your library', 'info')
        return redirect(url_for('dashboard'))
    
    # Return a minimal page that checks localStorage for last system
    return f'''<!DOCTYPE html>
<html>
<head><title>Redirecting...</title></head>
<body>
<script>
    const lastSystem = localStorage.getItem('retrodb_last_achievement_system');
    if (lastSystem) {{
        window.location.replace('/achievements/system/' + lastSystem);
    }} else {{
        window.location.replace('/achievements/system/{first_system["id"]}');
    }}
</script>
<noscript>
    <meta http-equiv="refresh" content="0;url=/achievements/system/{first_system["id"]}">
</noscript>
</body>
</html>'''


@bp.route('/achievements/system/<int:system_id>')
@login_required
def achievements_system(system_id):
    """RetroAchievements page for a specific system - shows games with achievements"""
    system_log('info', f'Loading achievements page for system {system_id}')
    
    # Check if user has RA configured
    ra_username, ra_api_key = get_user_ra_credentials()
    
    # Get system info with user's earned stats from database
    system = query("""
        SELECT s.id, s.name, s.folder, COUNT(g.id) as game_count,
               SUM(g.ra_achievement_count) as total_achievements,
               SUM(g.ra_points) as total_points,
               SUM(COALESCE(gap.earned_achievements, 0)) as earned_achievements,
               SUM(COALESCE(gap.earned_points, 0)) as earned_points,
               MAX(gap.last_synced) as last_synced
        FROM systems s
        JOIN games g ON g.system_id = s.id
        LEFT JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE s.id = ? AND g.ra_game_id IS NOT NULL AND g.ra_game_id != ''
        GROUP BY s.id
    """, (system_id,), one=True)
    
    if not system:
        flash('System not found or has no achievement games', 'warning')
        return redirect(url_for('dashboard'))
    
    # Get games for this system with their stored progress
    games = query("""
        SELECT g.id, g.title, g.boxart, g.system_id, s.name as system_name, s.folder as system_folder,
               g.ra_game_id, g.ra_achievement_count, g.ra_points,
               gap.earned_achievements, gap.earned_points, gap.completion_percentage, gap.last_synced
        FROM games g
        JOIN systems s ON g.system_id = s.id
        LEFT JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE g.system_id = ? AND g.ra_game_id IS NOT NULL AND g.ra_game_id != ''
        ORDER BY g.title COLLATE NOCASE
    """, (system_id,))
    
    # Get all systems for the navigation tabs with user stats
    all_systems = query("""
        SELECT s.id, s.name, COUNT(g.id) as game_count,
               SUM(COALESCE(gap.earned_achievements, 0)) as earned_achievements,
               SUM(g.ra_achievement_count) as total_achievements
        FROM systems s
        JOIN games g ON g.system_id = s.id
        LEFT JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE g.ra_game_id IS NOT NULL AND g.ra_game_id != ''
        GROUP BY s.id
        ORDER BY s.name COLLATE NOCASE
    """)
    
    # Get overall stats across all systems with user's earned totals
    overall_stats = query("""
        SELECT COUNT(g.id) as total_games,
               SUM(g.ra_achievement_count) as total_achievements,
               SUM(g.ra_points) as total_points,
               SUM(COALESCE(gap.earned_achievements, 0)) as earned_achievements,
               SUM(COALESCE(gap.earned_points, 0)) as earned_points
        FROM games g
        LEFT JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE g.ra_game_id IS NOT NULL AND g.ra_game_id != ''
    """, one=True)
    
    return render_template('achievements_system.html',
                         system=system,
                         games=games,
                         all_systems=all_systems,
                         ra_configured=bool(ra_api_key),
                         ra_username=ra_username,
                         overall_stats=overall_stats)

@bp.route('/achievements/<int:game_id>')
@login_required
def achievement_game(game_id):
    """Individual game achievements page"""
    from scraper.retroachievements import get_user_game_progress_custom
    
    # Get game info from database
    game = query("""
        SELECT g.*, s.name as system_name, s.folder as system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)
    
    if not game:
        flash('Game not found', 'error')
        return redirect(url_for('.achievements'))
    
    if not game['ra_game_id']:
        flash('This game does not have RetroAchievements data', 'error')
        return redirect(url_for('game_detail', game_id=game_id))
    
    username, api_key = get_user_ra_credentials()
    
    # Get user's achievement progress using their personal credentials
    progress = None
    if api_key and username:
        progress = get_user_game_progress_custom(game['ra_game_id'], username, api_key)

    # Compute first/last achievement dates
    first_achievement_date = None
    last_achievement_date = None
    if progress and progress.get('achievements'):
        for ach in progress['achievements']:
            date_str = ach.get('date_earned')
            if date_str:
                if first_achievement_date is None or date_str < first_achievement_date:
                    first_achievement_date = date_str
                if last_achievement_date is None or date_str > last_achievement_date:
                    last_achievement_date = date_str

    return render_template('achievement_game.html',
                         game=game,
                         progress=progress,
                         ra_configured=bool(api_key),
                         ra_username=username,
                         first_achievement_date=first_achievement_date,
                         last_achievement_date=last_achievement_date)

@bp.route('/api/achievements/<int:game_id>')
@login_required
def api_get_achievements(game_id):
    """API endpoint to get achievements for a game - loads from local database"""
    # First try to get from local storage
    progress = query("""
        SELECT earned_achievements, total_achievements, earned_points, 
               total_points, completion_percentage, last_synced
        FROM game_achievement_progress WHERE game_id = ?
    """, (game_id,), one=True)
    
    if progress:
        return jsonify({
            'success': True, 
            'data': {
                'unlocked_count': progress['earned_achievements'],
                'total_count': progress['total_achievements'],
                'earned_points': progress['earned_points'],
                'total_points': progress['total_points'],
                'completion_percentage': progress['completion_percentage'],
                'last_synced': progress['last_synced']
            },
            'source': 'local'
        })
    else:
        return jsonify({'success': False, 'error': 'No progress data - click Refresh to sync'})


@bp.route('/api/achievements/sync/<int:game_id>', methods=['POST'])
@login_required
def api_sync_game_achievements(game_id):
    """Sync achievements for a single game from RetroAchievements API and store locally"""
    from scraper.retroachievements import get_user_game_progress_custom
    from datetime import datetime, timezone

    game = query("SELECT ra_game_id FROM games WHERE id = ?", (game_id,), one=True)

    if not game or not game['ra_game_id']:
        return jsonify({'success': False, 'error': 'Game not linked to RetroAchievements'})

    username, api_key = get_user_ra_credentials()
    if not api_key or not username:
        return jsonify({'success': False, 'error': 'RetroAchievements not configured'})
    
    try:
        progress = get_user_game_progress_custom(game['ra_game_id'], username, api_key)
        
        if progress:
            # Store in local database
            now = datetime.now(timezone.utc).isoformat()
            execute("""
                INSERT INTO game_achievement_progress 
                (game_id, ra_game_id, earned_achievements, total_achievements, 
                 earned_points, total_points, completion_percentage, last_synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    earned_achievements = excluded.earned_achievements,
                    total_achievements = excluded.total_achievements,
                    earned_points = excluded.earned_points,
                    total_points = excluded.total_points,
                    completion_percentage = excluded.completion_percentage,
                    last_synced = excluded.last_synced
            """, (
                game_id, 
                game['ra_game_id'],
                progress.get('unlocked_count', 0),
                progress.get('total_count', 0),
                progress.get('earned_points', 0),
                progress.get('total_points', 0),
                progress.get('completion_percentage', 0),
                now
            ))
            
            return jsonify({
                'success': True,
                'data': progress
            })
        else:
            return jsonify({'success': False, 'error': 'Could not fetch achievement data'})
    except Exception as e:
        logger.error(f"Error syncing achievements for game {game_id}: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/achievements/sync-system/<int:system_id>', methods=['POST'])
@login_required
def api_sync_system_achievements(system_id):
    """Start background sync for all achievements in a system"""
    system_log('info', f'Starting achievements sync for system ID {system_id}')
    
    # Get system info first (needed for queue and sync)
    system = query("SELECT id, name FROM systems WHERE id = ?", (system_id,), one=True)
    if not system:
        system_log('error', f'System not found: {system_id}')
        return jsonify({'success': False, 'error': 'System not found'})
    
    # Get all games with RA data in this system
    games = query("""
        SELECT id FROM games 
        WHERE system_id = ? AND ra_game_id IS NOT NULL AND ra_game_id != ''
        AND (is_bonus_disc = 0 OR is_bonus_disc IS NULL)
    """, (system_id,))
    
    if not games:
        system_log('warning', f'No games with RetroAchievements in system: {system["name"]}')
        return jsonify({'success': False, 'error': 'No games with RetroAchievements in this system'})
    
    game_count = len(games)
    
    # Check if RA Sync is already running for THIS SAME system
    sync_status = ra_sync_job.get_status()
    if sync_status.get('running', False) and not sync_status.get('completed', False):
        if sync_status.get('system_id') == system_id:
            system_log('info', f'RA Sync already running for this system: {system["name"]}')
            return jsonify({
                'success': False,
                'error': f'Sync already in progress for {system["name"]}',
                'already_running': True
            })
    
    # Check if RA Refresh is currently running
    refresh_status = ra_refresh_job.get_status()
    if refresh_status.get('running', False):
        system_log('info', f'RA Refresh is running, queueing sync for system ID {system_id}')
        return jsonify({
            'success': True,
            'queued': True,
            'message': 'RA Refresh is running. Sync will start when refresh completes.',
            'refresh_running': True,
            'system_id': system_id,
            'system_name': system['name'],
            'game_count': game_count
        })
    
    # Check if RA Sync is already running for a DIFFERENT system
    if sync_status.get('running', False) and not sync_status.get('completed', False):
        system_log('info', f'RA Sync already running, queueing sync for {system["name"]}')
        return jsonify({
            'success': True,
            'queued': True,
            'message': f'Sync queued. Will start after current sync completes.',
            'sync_running': True,
            'system_id': system_id,
            'system_name': system['name'],
            'game_count': game_count
        })
    
    game_ids = [g['id'] for g in games]
    system_log('info', f'Syncing {len(game_ids)} games for {system["name"]}')
    
    # Start background sync
    result = ra_sync_job.start(system_id, game_ids, system['name'])
    
    return jsonify(result)


@bp.route('/api/achievements/sync-status')
@login_required
def api_achievements_sync_status():
    """Get current RA sync job status"""
    return jsonify(ra_sync_job.get_status())


@bp.route('/api/achievements/sync-cancel', methods=['POST'])
@login_required
def api_achievements_sync_cancel():
    """Cancel the current RA sync job"""
    result = ra_sync_job.cancel()
    return jsonify(result)


@bp.route('/api/achievements/sync-results/<int:system_id>')
@login_required
def api_achievements_sync_results(system_id):
    """Get sync results for a system (loads from database after sync completes)"""
    progress_data = query("""
        SELECT g.id as game_id, gap.earned_achievements, gap.total_achievements,
               gap.earned_points, gap.total_points, gap.completion_percentage, gap.last_synced
        FROM games g
        LEFT JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE g.system_id = ? AND g.ra_game_id IS NOT NULL
    """, (system_id,))
    
    result = {}
    for row in progress_data:
        if row['earned_achievements'] is not None:
            result[str(row['game_id'])] = {
                'unlocked_count': row['earned_achievements'],
                'total_count': row['total_achievements'],
                'earned_points': row['earned_points'],
                'total_points': row['total_points'],
                'completion_percentage': row['completion_percentage'],
                'last_synced': row['last_synced']
            }
    
    return jsonify({
        'success': True,
        'progress': result
    })


@bp.route('/api/achievements/stored/<int:system_id>')
@login_required
def api_get_stored_achievements(system_id):
    """Get all stored achievement progress for a system"""
    progress_data = query("""
        SELECT g.id as game_id, gap.earned_achievements, gap.total_achievements,
               gap.earned_points, gap.total_points, gap.completion_percentage, gap.last_synced
        FROM games g
        LEFT JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE g.system_id = ? AND g.ra_game_id IS NOT NULL
    """, (system_id,))
    
    result = {}
    for row in progress_data:
        if row['earned_achievements'] is not None:  # Has synced data
            result[str(row['game_id'])] = {
                'unlocked_count': row['earned_achievements'],
                'total_count': row['total_achievements'],
                'earned_points': row['earned_points'],
                'total_points': row['total_points'],
                'completion_percentage': row['completion_percentage'],
                'last_synced': row['last_synced']
            }
    
    return jsonify({
        'success': True,
        'progress': result
    })


@bp.route('/api/achievements/refresh/<int:game_id>', methods=['POST'])
@login_required
def api_refresh_achievements(game_id):
    """Refresh achievements from RetroAchievements API"""
    from scraper.retroachievements import check_retroachievements
    
    game = query("""
        SELECT g.title, s.folder as system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)
    
    if not game:
        return jsonify({'success': False, 'error': 'Game not found'})
    
    result = check_retroachievements(game['title'], game['system_folder'])
    
    if result:
        execute("""
            UPDATE games 
            SET ra_game_id = ?, ra_achievement_count = ?, ra_points = ?
            WHERE id = ?
        """, (result['id'], result['achievement_count'], result['points'], game_id))
        
        return jsonify({
            'success': True, 
            'message': f"Found {result['achievement_count']} achievements",
            'data': result
        })
    else:
        return jsonify({'success': False, 'error': 'No RetroAchievements found for this game'})

# =============================================================================
# RETROACHIEVEMENTS API ROUTES
# =============================================================================
# NOTE: RA refresh, cancel, status, and clear-data endpoints are defined in
# routes/ra_sync.py. They were previously duplicated here but have been removed
# to avoid Flask route conflicts (last-registered blueprint wins silently).
# =============================================================================

