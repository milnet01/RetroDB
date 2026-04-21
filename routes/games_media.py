# =============================================================================
# RETRODB - Game Media & Deletion Routes
# =============================================================================
# Delete game record, rename ROM file on disk, remove a single screenshot.
# =============================================================================

import logging
import os

from flask import Blueprint, request, jsonify

import config
from services.analytics import invalidate_analytics_cache
from services.api_helpers import handle_api_errors
from services.auth import login_required
from services.database import query, execute
from services.game_query import invalidate_filter_cache
from services.security import safe_filename

logger = logging.getLogger(__name__)

bp = Blueprint('games_media', __name__)


@bp.route('/api/delete-game/<int:game_id>', methods=['DELETE', 'POST'])
@login_required
@handle_api_errors
def api_delete_game(game_id):
    """Delete a game from the database."""
    game = query("SELECT id, title, rom_path FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return jsonify({'success': False, 'error': 'Game not found'}), 404

    # Unlink any records that reference this game via foreign keys
    execute("UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 WHERE parent_game_id = ?", (game_id,))
    execute("UPDATE psn_games SET linked_game_id = NULL WHERE linked_game_id = ?", (game_id,))

    execute("DELETE FROM games WHERE id = ?", (game_id,))

    invalidate_filter_cache()
    invalidate_analytics_cache()

    logger.info(f"Deleted game from database: {game['title']} (ID: {game_id})")

    return jsonify({
        'success': True,
        'message': f"Game '{game['title']}' deleted from database",
        'game_id': game_id
    })


@bp.route('/api/rename-rom/<int:game_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_rename_rom(game_id):
    """Rename a ROM file on disk and update the database."""
    data = request.get_json()
    new_filename = data.get('new_filename', '').strip()

    if not new_filename:
        return jsonify({'success': False, 'error': 'No filename provided'}), 400

    invalid_chars = '<>:"/\\|?*'
    if any(c in new_filename for c in invalid_chars):
        return jsonify({'success': False, 'error': f'Filename contains invalid characters: {invalid_chars}'}), 400

    if '..' in new_filename:
        return jsonify({'success': False, 'error': 'Filename cannot contain path traversal sequences'}), 400

    game = query("SELECT id, title, rom_path FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return jsonify({'success': False, 'error': 'Game not found'}), 404

    old_path = game['rom_path']

    if not os.path.exists(old_path):
        return jsonify({'success': False, 'error': f'ROM file not found on disk: {old_path}'}), 404

    directory = os.path.dirname(old_path)
    new_path = os.path.join(directory, new_filename)

    if os.path.exists(new_path) and new_path != old_path:
        return jsonify({'success': False, 'error': 'A file with that name already exists'}), 400

    try:
        os.rename(old_path, new_path)
        logger.info(f"Renamed ROM: {old_path} -> {new_path}")
    except OSError as e:
        logger.error(f"Failed to rename ROM file: {e}")
        return jsonify({'success': False, 'error': 'Failed to rename file'}), 500

    execute("UPDATE games SET rom_path = ? WHERE id = ?", (new_path, game_id))

    return jsonify({
        'success': True,
        'new_path': new_path,
        'new_filename': new_filename,
        'message': 'ROM file renamed successfully'
    })


@bp.route('/api/delete-screenshot/<int:game_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_delete_screenshot(game_id):
    """Delete a screenshot from a game."""
    data = request.get_json()
    screenshot_to_delete = data.get('screenshot')

    if not screenshot_to_delete:
        return jsonify({'success': False, 'error': 'No screenshot specified'})

    if not safe_filename(screenshot_to_delete):
        return jsonify({'success': False, 'error': 'Invalid screenshot filename'}), 400

    game = query("SELECT screenshots FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return jsonify({'success': False, 'error': 'Game not found'}), 404

    current = game['screenshots'] or ''
    screenshots = [s.strip() for s in current.split(',') if s.strip()]

    if screenshot_to_delete not in screenshots:
        return jsonify({'success': False, 'error': 'Screenshot not found'})

    screenshots.remove(screenshot_to_delete)
    new_screenshots = ','.join(screenshots)

    execute("UPDATE games SET screenshots = NULLIF(?, '') WHERE id = ?",
            (new_screenshots, game_id))

    screenshot_path = os.path.join(config.IMAGE_PATH, 'screenshots', screenshot_to_delete)
    if os.path.exists(screenshot_path):
        os.remove(screenshot_path)
        logger.info(f"Deleted screenshot file: {screenshot_to_delete}")

    return jsonify({
        'success': True,
        'remaining': len(screenshots),
        'screenshots': screenshots
    })
