# =============================================================================
# RETRODB - Xbox Achievements Blueprint
# =============================================================================
# Pages for viewing Xbox achievement progress: landing + per-game detail.
#
# Routes:
#   GET  /xbox-achievements              - Landing page (all Xbox games)
#   GET  /xbox-achievements/game/<id>    - Per-game achievement detail
#   POST /api/xbox-achievements/sync/<id>- Single game sync
#   GET  /api/xbox-achievements/sync-status - Bulk sync status
#   POST /api/xbox-achievements/sync-all - Start bulk sync
# =============================================================================

import logging

from flask import Blueprint, render_template, jsonify, g
from services.database import query, get_db
from services.auth import login_required, editor_required

logger = logging.getLogger(__name__)

bp = Blueprint('xbox_achievements', __name__)


@bp.route('/xbox-achievements')
@login_required
def xbox_achievements_landing():
    """Landing page: all games with Xbox achievement progress (Pass 31.2 — per user)."""
    user_id = g.user['id']
    games = query("""
        SELECT g.id, g.title, g.boxart, g.system_id, s.name as system_name,
               gap.earned_achievements, gap.total_achievements,
               gap.completion_percentage, gap.last_synced
        FROM games g
        JOIN systems s ON g.system_id = s.id
        JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE gap.source = 'xbox' AND g.xbox_title_id IS NOT NULL
          AND gap.user_id = ?
        ORDER BY g.title COLLATE NOCASE
    """, (user_id,))

    # Calculate overall stats + gamerscore
    total_games = len(games)
    total_achievements = sum(g['total_achievements'] or 0 for g in games)
    total_earned = sum(g['earned_achievements'] or 0 for g in games)
    avg_completion = round(sum(g['completion_percentage'] or 0 for g in games) / total_games, 1) if total_games > 0 else 0

    # Get gamerscore totals from individual achievements (scoped).
    gs_row = query("""
        SELECT COALESCE(SUM(CASE WHEN achieved = 1 THEN gamerscore ELSE 0 END), 0) as earned_gs,
               COALESCE(SUM(gamerscore), 0) as total_gs
        FROM xbox_achievements
        WHERE user_id = ?
    """, (user_id,), one=True)

    stats = {
        'total_games': total_games,
        'total_achievements': total_achievements,
        'total_earned': total_earned,
        'avg_completion': avg_completion,
        'earned_gamerscore': gs_row['earned_gs'] if gs_row else 0,
        'total_gamerscore': gs_row['total_gs'] if gs_row else 0,
    }

    return render_template('xbox_achievements.html', games=games, stats=stats)


@bp.route('/xbox-achievements/game/<int:game_id>')
@login_required
def xbox_achievement_game(game_id):
    """Per-game detail: show individual Xbox achievements."""
    game = query("""
        SELECT g.*, s.name as system_name, s.folder as system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)

    if not game:
        return "Game not found", 404

    # Get achievement progress summary (Pass 31.2 — per user).
    user_id = g.user['id']
    progress = query("""
        SELECT earned_achievements, total_achievements, completion_percentage, last_synced
        FROM game_achievement_progress
        WHERE game_id = ? AND source = 'xbox' AND user_id = ?
    """, (game_id, user_id), one=True)

    # Get individual achievements
    achievements = query("""
        SELECT * FROM xbox_achievements
        WHERE game_id = ? AND user_id = ?
        ORDER BY achieved DESC, unlock_time DESC, name ASC
    """, (game_id, user_id))

    unlocked = [a for a in achievements if a['achieved']]
    locked = [a for a in achievements if not a['achieved']]

    # Gamerscore totals for this game
    earned_gs = sum(a['gamerscore'] for a in unlocked)
    total_gs = sum(a['gamerscore'] for a in achievements)

    return render_template('xbox_achievement_game.html',
                           game=game, progress=progress,
                           unlocked=unlocked, locked=locked,
                           achievements=achievements,
                           earned_gs=earned_gs, total_gs=total_gs)


@bp.route('/api/xbox-achievements/sync/<int:game_id>', methods=['POST'])
@editor_required
def api_xbox_sync_single(game_id):
    """Sync achievements for a single Xbox game (Pass 31.2 — per user)."""
    from scraper.scrape_xbox import get_authenticated_session, get_achievements
    from routes.scraper import get_saved_api_keys
    from services.jobs.platform_sync import _upsert_xbox_achievements, _upsert_xbox_progress

    api_keys = get_saved_api_keys()
    client_id = api_keys.get('xbox_client_id', '')
    client_secret = api_keys.get('xbox_client_secret', '')

    if not client_id or not client_secret:
        return jsonify({'success': False, 'error': 'Xbox credentials not configured'})

    user_id = g.user['id']
    session = get_authenticated_session(client_id, client_secret, user_id)
    if not session:
        return jsonify({'success': False, 'error': 'Xbox authentication failed — please re-connect your account'})

    game = query("SELECT id, title, xbox_title_id FROM games WHERE id = ?", (game_id,), one=True)
    if not game or not game['xbox_title_id']:
        return jsonify({'success': False, 'error': 'Game not found or not an Xbox game'})

    result = get_achievements(session['auth_header'], session['xuid'], game['xbox_title_id'])
    if result is None:
        return jsonify({'success': True, 'message': 'Game has no achievements', 'earned': 0, 'total': 0})

    conn = None
    try:
        conn = get_db()
        c = conn.cursor()

        _upsert_xbox_progress(c, game_id, user_id, game['xbox_title_id'], result)
        _upsert_xbox_achievements(c, game_id, result.get('achievements', []), user_id)

        conn.commit()

        return jsonify({
            'success': True,
            'earned': result['earned'],
            'total': result['total'],
        })
    except Exception as e:
        logger.error(f"Xbox achievement sync error for game {game_id}: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})
    finally:
        if conn:
            conn.close()


@bp.route('/api/xbox-achievements/sync-status')
@login_required
def api_xbox_sync_status():
    """Get bulk Xbox achievement sync status."""
    from services.jobs import xbox_sync_job
    return jsonify(xbox_sync_job.get_status())


@bp.route('/api/xbox-achievements/sync-all', methods=['POST'])
@editor_required
def api_xbox_sync_all():
    """Start bulk Xbox achievement sync (Pass 27.3 — per current user)."""
    from services.jobs import xbox_sync_job
    result = xbox_sync_job.start(user_id=g.user['id'])
    return jsonify(result)
