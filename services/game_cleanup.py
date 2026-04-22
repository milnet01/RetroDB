# =============================================================================
# RETRODB - Game cleanup
# =============================================================================
# Game-centric cleanup operations driven by /api/maintenance/*:
#
#   clean_missing_roms()  — drop games whose ROM files no longer exist on disk
#   clear_clz_imports()   — drop every game with a clz_import/ placeholder path
#   clear_scraped_data()  — null scraped metadata columns + reset titles
# =============================================================================

import logging
import os

from services.database import execute, get_db, query
from services.game_utils import reset_game_title_from_filename
from services.media_cleanup import delete_game_images

logger = logging.getLogger(__name__)


# Virtual rom_path prefixes for games imported from external platforms —
# these have no on-disk ROM, so don't treat them as "missing".
_VIRTUAL_ROM_PREFIXES = ('clz_import/', 'steam_import/', 'xbox_import/', 'psn_import/')


_SCRAPED_FIELDS = (
    'description', 'genre', 'publisher', 'developer', 'release_date',
    'players', 'modes', 'esrb_rating', 'pegi_rating',
    'cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating',
    'grac_rating', 'classind_rating', 'region',
    'franchise', 'similar_games', 'playtime_estimate', 'controller_support',
    'save_type', 'critic_score', 'critic_score_count', 'user_score',
    'user_score_count', 'boxart', 'screenshots', 'fanart', 'video', 'manual',
)


def clean_missing_roms():
    """Remove games from the DB whose rom_path is not a real, present file.

    Returns (removed_count, removed_games_preview) where the preview is
    capped at the first 50 removals for UI display.
    """
    games = query("SELECT id, title, rom_path, system_id FROM games")
    removed = 0
    removed_games = []

    for game in games:
        rom_path = game['rom_path']

        if rom_path and rom_path.startswith(_VIRTUAL_ROM_PREFIXES):
            continue

        if rom_path and not os.path.exists(rom_path):
            execute("UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 WHERE parent_game_id = ?", (game['id'],))
            execute("UPDATE psn_games SET linked_game_id = NULL WHERE linked_game_id = ?", (game['id'],))
            execute("DELETE FROM games WHERE id = ?", (game['id'],))
            removed += 1
            removed_games.append({
                'id': game['id'],
                'title': game['title'],
                'path': rom_path,
            })
            logger.info(f"Removed missing ROM: {game['title']} ({rom_path})")

    return removed, removed_games[:50]


def clear_clz_imports():
    """Delete every game whose rom_path begins with clz_import/.

    Returns (removed_count, removed_games_preview) — preview is the first 50
    titles by alphabetical order.
    """
    count_row = query("SELECT COUNT(*) as count FROM games WHERE rom_path LIKE 'clz_import/%'", one=True)
    count = count_row['count'] if count_row else 0

    if count == 0:
        return 0, []

    clz_games = query(
        "SELECT id, title, rom_path FROM games WHERE rom_path LIKE 'clz_import/%' ORDER BY title LIMIT 50"
    )
    removed_games = [{'id': g['id'], 'title': g['title'], 'path': g['rom_path']} for g in clz_games]

    execute(
        "UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 "
        "WHERE parent_game_id IN (SELECT id FROM games WHERE rom_path LIKE 'clz_import/%')"
    )
    execute(
        "UPDATE psn_games SET linked_game_id = NULL "
        "WHERE linked_game_id IN (SELECT id FROM games WHERE rom_path LIKE 'clz_import/%')"
    )
    execute("DELETE FROM games WHERE rom_path LIKE 'clz_import/%'")
    logger.info(f"Removed {count} CLZ Import games")

    return count, removed_games


def preview_scraped_data(system_id=None):
    """Count the games that would be affected by a clear_scraped_data() call."""
    if system_id:
        row = query(
            "SELECT COUNT(*) as count FROM games WHERE system_id = ? AND scraped = 1",
            (system_id,), one=True,
        )
    else:
        row = query("SELECT COUNT(*) as count FROM games WHERE scraped = 1", one=True)
    return row['count'] if row else 0


def clear_scraped_data(system_id=None, delete_images=False):
    """Null scraped metadata columns and reset titles to their filename forms.

    If `delete_images` is set, also remove every boxart/screenshot/fanart/
    video/manual file linked from the affected games.

    Returns (cleared_count, images_deleted).
    """
    set_clause = ', '.join(f"{field} = NULL" for field in _SCRAPED_FIELDS)
    set_clause += ", scraped = 0, scrape_history = NULL"

    images_deleted = 0

    if system_id:
        games = query(
            "SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM games WHERE system_id = ?",
            (system_id,),
        )
    else:
        games = query("SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM games")

    game_ids_to_reset = [g['id'] for g in games]

    if delete_images:
        images_deleted = delete_game_images(games)

    if system_id:
        execute(f"UPDATE games SET {set_clause} WHERE system_id = ?", (system_id,))
    else:
        execute(f"UPDATE games SET {set_clause}")
    cleared = len(game_ids_to_reset)

    if game_ids_to_reset:
        conn = get_db()
        for game_id in game_ids_to_reset:
            reset_game_title_from_filename(game_id, conn)
        conn.close()

    logger.info(
        f"Cleared scraped data from {cleared} games"
        + (f", deleted {images_deleted} images" if delete_images else "")
    )

    return cleared, images_deleted
