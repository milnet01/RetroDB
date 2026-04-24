# =============================================================================
# RETRODB - Steam Achievements Blueprint
# =============================================================================
# Pages for viewing Steam achievement progress: landing + per-game detail.
#
# Routes:
#   GET  /steam-achievements              - Landing page (all Steam games)
#   GET  /steam-achievements/game/<id>    - Per-game achievement detail
#   POST /api/steam-achievements/sync/<id>- Single game sync
#   GET  /api/steam-achievements/sync-status - Bulk sync status
#   POST /api/steam-achievements/sync-all - Start bulk sync
# =============================================================================

import logging
from datetime import datetime, timezone

from flask import Blueprint, render_template, jsonify, g

from services.database import query, execute
from services.auth import login_required, editor_required

logger = logging.getLogger(__name__)

bp = Blueprint('steam_achievements', __name__)


@bp.route('/steam-achievements')
@login_required
def steam_achievements_landing():
    """Landing page: all games with Steam achievement progress."""
    games = query("""
        SELECT g.id, g.title, g.boxart, g.system_id, s.name as system_name,
               gap.earned_achievements, gap.total_achievements,
               gap.completion_percentage, gap.last_synced
        FROM games g
        JOIN systems s ON g.system_id = s.id
        JOIN game_achievement_progress gap ON g.id = gap.game_id
        WHERE gap.source = 'steam' AND g.steam_app_id IS NOT NULL
        ORDER BY g.title COLLATE NOCASE
    """)

    # Calculate overall stats
    total_games = len(games)
    total_achievements = sum(g['total_achievements'] or 0 for g in games)
    total_earned = sum(g['earned_achievements'] or 0 for g in games)
    avg_completion = round(sum(g['completion_percentage'] or 0 for g in games) / total_games, 1) if total_games > 0 else 0

    stats = {
        'total_games': total_games,
        'total_achievements': total_achievements,
        'total_earned': total_earned,
        'avg_completion': avg_completion,
    }

    return render_template('steam_achievements.html', games=games, stats=stats)


@bp.route('/steam-achievements/game/<int:game_id>')
@login_required
def steam_achievement_game(game_id):
    """Per-game detail: show individual Steam achievements."""
    game = query("""
        SELECT g.*, s.name as system_name, s.folder as system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)

    if not game:
        return "Game not found", 404

    # Get achievement progress summary
    progress = query("""
        SELECT earned_achievements, total_achievements, completion_percentage, last_synced
        FROM game_achievement_progress
        WHERE game_id = ? AND source = 'steam'
    """, (game_id,), one=True)

    # Get individual achievements
    achievements = query("""
        SELECT * FROM steam_achievements
        WHERE game_id = ?
        ORDER BY achieved DESC, unlock_time DESC, name ASC
    """, (game_id,))

    unlocked = [a for a in achievements if a['achieved']]
    locked = [a for a in achievements if not a['achieved']]

    return render_template('steam_achievement_game.html',
                           game=game, progress=progress,
                           unlocked=unlocked, locked=locked,
                           achievements=achievements)


@bp.route('/api/steam-achievements/sync/<int:game_id>', methods=['POST'])
@editor_required
def api_steam_sync_single(game_id):
    """Sync achievements for a single Steam game (Pass 31.4 — per user)."""
    import sqlite3
    import config
    from scraper.scrape_steam import get_player_achievements
    from services.jobs.platform_sync import _upsert_steam_achievements, _get_steam_credentials

    steam_api_key, steam_id = _get_steam_credentials(user_id=g.user['id'])
    if not steam_api_key or not steam_id:
        return jsonify({'success': False, 'error': 'Steam credentials not configured'})

    game = query("SELECT id, title, steam_app_id FROM games WHERE id = ?", (game_id,), one=True)
    if not game or not game['steam_app_id']:
        return jsonify({'success': False, 'error': 'Game not found or not a Steam game'})

    result = get_player_achievements(steam_api_key, steam_id, game['steam_app_id'])
    if result is None:
        return jsonify({'success': True, 'message': 'Game has no achievements', 'earned': 0, 'total': 0})

    try:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("""
            INSERT INTO game_achievement_progress
                (game_id, user_id, earned_achievements, total_achievements,
                 completion_percentage, last_synced, steam_app_id, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'steam')
            ON CONFLICT(game_id, user_id) DO UPDATE SET
                earned_achievements = excluded.earned_achievements,
                total_achievements = excluded.total_achievements,
                completion_percentage = excluded.completion_percentage,
                last_synced = excluded.last_synced,
                steam_app_id = excluded.steam_app_id,
                source = 'steam'
        """, (
            game_id,
            g.user['id'],
            result['earned'],
            result['total'],
            round(result['earned'] / result['total'] * 100, 1) if result['total'] > 0 else 0,
            datetime.now(timezone.utc).isoformat(),
            game['steam_app_id'],
        ))

        _upsert_steam_achievements(c, game_id, game['steam_app_id'], steam_api_key, result, g.user['id'])

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'earned': result['earned'],
            'total': result['total'],
        })
    except Exception as e:
        logger.error(f"Steam achievement sync error for game {game_id}: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/steam-achievements/sync-status')
@login_required
def api_steam_sync_status():
    """Get bulk Steam achievement sync status."""
    from services.jobs import steam_sync_job
    return jsonify(steam_sync_job.get_status())


@bp.route('/api/steam-achievements/sync-all', methods=['POST'])
@editor_required
def api_steam_sync_all():
    """Start bulk Steam achievement sync (Pass 31.4 — per-user credentials)."""
    from services.jobs import steam_sync_job
    result = steam_sync_job.start(user_id=g.user['id'])
    return jsonify(result)
