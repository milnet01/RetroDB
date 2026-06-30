# =============================================================================
# RETRODB - Game Media & Deletion Routes
# =============================================================================
# Delete game record, rename ROM file on disk, remove a single screenshot.
# =============================================================================

import logging
import os

from flask import Blueprint, request
from flask_babel import gettext as _

import config
from services.analytics import invalidate_analytics_cache
from services.api_helpers import handle_api_errors, success, error
from services.auth import editor_required
from services.database import query, execute
from services.game_query import invalidate_filter_cache
from services.security import safe_filename

logger = logging.getLogger(__name__)

bp = Blueprint('games_media', __name__)


@bp.route('/api/delete-game/<int:game_id>', methods=['DELETE', 'POST'])
@editor_required
@handle_api_errors
def api_delete_game(game_id):
    """Delete a game from the database."""
    game = query("SELECT id, title, rom_path FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    # Unlink any records that reference this game via foreign keys
    execute("UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 WHERE parent_game_id = ?", (game_id,))
    execute("UPDATE psn_games SET linked_game_id = NULL WHERE linked_game_id = ?", (game_id,))

    execute("DELETE FROM games WHERE id = ?", (game_id,))

    invalidate_filter_cache()
    invalidate_analytics_cache()

    # Pass 34.7: structured so grep and external log shippers can parse
    # mutation history consistently. user_id may be None in legacy paths
    # but editor_required guarantees g.user for this route today.
    from flask import g as _flask_g
    user_id = getattr(_flask_g, 'user', None) and _flask_g.user.get('id')
    logger.info(
        "game_delete game_id=%s title=%r user_id=%s",
        game_id, game['title'], user_id,
    )

    return success(
        message=f"Game '{game['title']}' deleted from database",
        game_id=game_id,
    )


@bp.route('/api/rename-rom/<int:game_id>', methods=['POST'])
@editor_required
@handle_api_errors
def api_rename_rom(game_id):
    """Rename a ROM file on disk and update the database."""
    data = request.get_json(silent=True) or {}
    new_filename = data.get('new_filename', '').strip()

    if not new_filename:
        return error(_('No filename provided'), 400)

    # Pass 32.5: the previous guard only rejected invalid chars + `..` in
    # the user-supplied filename. safe_filename already covers both (plus
    # path separators), and safe_filename failure is the single canonical
    # reject path.
    if safe_filename(new_filename) is None:
        return error(_('Invalid filename'), 400)

    game = query("SELECT id, title, rom_path FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    old_path = game['rom_path']

    if not os.path.exists(old_path):
        return error(_('ROM file not found on disk: %(path)s') % {'path': old_path}, 404)

    directory = os.path.dirname(old_path)
    new_path = os.path.join(directory, new_filename)

    # Pass 32.5: jail the derived destination inside the configured ROM
    # root. DB rom_path values are trusted by default, but a legacy import
    # (or a pre-Pass-32.1 admin setting) could leave a row whose rom_path
    # points outside ROM_PATH — without this check, rename-rom would then
    # become an arbitrary rename primitive anywhere on disk.
    rom_root = getattr(config, 'ROM_PATH', '') or ''
    if rom_root:
        try:
            canonical_root = os.path.realpath(rom_root)
            canonical_new = os.path.realpath(os.path.dirname(new_path))
            if os.path.commonpath([canonical_root, canonical_new]) != canonical_root:
                return error(_('Destination is outside the configured ROM root'), 400)
        except (ValueError, OSError):
            return error(_('Could not validate destination path'), 400)

    if os.path.exists(new_path) and new_path != old_path:
        return error(_('A file with that name already exists'), 400)

    try:
        os.rename(old_path, new_path)
        logger.info(f"Renamed ROM: {old_path} -> {new_path}")
    except OSError as e:
        logger.error(f"Failed to rename ROM file: {e}")
        return error(_('Failed to rename file'), 500)

    execute("UPDATE games SET rom_path = ? WHERE id = ?", (new_path, game_id))

    return success(
        new_path=new_path,
        new_filename=new_filename,
        message='ROM file renamed successfully',
    )


@bp.route('/api/delete-screenshot/<int:game_id>', methods=['POST'])
@editor_required
@handle_api_errors
def api_delete_screenshot(game_id):
    """Delete a screenshot from a game."""
    data = request.get_json(silent=True) or {}
    screenshot_to_delete = data.get('screenshot')

    if not screenshot_to_delete:
        return error(_('No screenshot specified'), code=200)

    if not safe_filename(screenshot_to_delete):
        return error(_('Invalid screenshot filename'), 400)

    game = query("SELECT screenshots FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    current = game['screenshots'] or ''
    screenshots = [s.strip() for s in current.split(',') if s.strip()]

    if screenshot_to_delete not in screenshots:
        return error(_('Screenshot not found'), code=200)

    screenshots.remove(screenshot_to_delete)
    new_screenshots = ','.join(screenshots)

    execute("UPDATE games SET screenshots = NULLIF(?, '') WHERE id = ?",
            (new_screenshots, game_id))

    screenshot_path = os.path.join(config.IMAGE_PATH, 'screenshots', screenshot_to_delete)
    if os.path.exists(screenshot_path):
        os.remove(screenshot_path)
        logger.info(f"Deleted screenshot file: {screenshot_to_delete}")

    return success(
        remaining=len(screenshots),
        screenshots=screenshots,
    )
