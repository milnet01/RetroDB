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

from services.database import execute, get_db, get_db_with_context, query
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
    'grac_rating', 'classind_rating', 'china_rating', 'region',
    'franchise', 'similar_games', 'playtime_estimate', 'controller_support',
    'save_type', 'critic_score', 'critic_score_count', 'user_score',
    'user_score_count', 'boxart', 'boxart_3d', 'screenshots', 'fanart',
    'video', 'manual',
)


def clean_missing_roms():
    """Remove games from the DB whose rom_path is not a real, present file.

    Returns (removed_count, removed_games_preview) where the preview is
    capped at the first 50 removals for UI display.

    Pass 32.4: one SELECT to enumerate candidates, filesystem checks in
    Python, then one single-transaction batched UPDATE/DELETE so we never
    leave the DB with orphan parent_game_id references if interrupted.
    """
    games = query("SELECT id, title, rom_path FROM games")

    missing = []
    for game in games:
        rom_path = game['rom_path']
        if not rom_path:
            continue
        if rom_path.startswith(_VIRTUAL_ROM_PREFIXES):
            continue
        if not os.path.exists(rom_path):
            # Guard against a transiently-offline mount (NFS / USB / external
            # drive): if the ROM's own parent directory is also gone, the
            # file's absence is ambiguous and could be an unmounted share —
            # skip it rather than risk mass-deleting an entire library. A
            # genuinely-removed ROM leaves its parent directory intact, so it
            # is still caught. The user can re-scan once the mount is back.
            # Only apply the guard when there IS a parent dir to test — a bare
            # filename (dirname == '') has no mount to check, so fall through
            # and treat its absence as genuinely-missing.
            parent = os.path.dirname(rom_path)
            if parent and not os.path.isdir(parent):
                continue
            missing.append({
                'id': game['id'],
                'title': game['title'],
                'path': rom_path,
            })

    if not missing:
        return 0, []

    missing_ids = [m['id'] for m in missing]

    # Batch the rewrites + deletes into a single transaction. SQLite caps
    # host-parameter lists at ~999 by default; chunk to stay safely below.
    CHUNK = 500
    with get_db_with_context() as conn:
        for start in range(0, len(missing_ids), CHUNK):
            chunk = missing_ids[start:start + CHUNK]
            placeholders = ','.join('?' * len(chunk))
            conn.execute(
                f"UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 "
                f"WHERE parent_game_id IN ({placeholders})",
                chunk,
            )
            conn.execute(
                f"UPDATE psn_games SET linked_game_id = NULL "
                f"WHERE linked_game_id IN ({placeholders})",
                chunk,
            )
            conn.execute(
                f"DELETE FROM games WHERE id IN ({placeholders})",
                chunk,
            )

    for m in missing:
        logger.info(f"Removed missing ROM: {m['title']} ({m['path']})")

    return len(missing), missing[:50]


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

    If `delete_images` is set, also remove every boxart/boxart_3d/screenshot/
    fanart/video/manual file linked from the affected games.

    Returns (cleared_count, images_deleted).
    """
    set_clause = ', '.join(f"{field} = NULL" for field in _SCRAPED_FIELDS)
    set_clause += ", scraped = 0, scrape_history = NULL"

    images_deleted = 0

    # `scraped = 1` mirrors preview_scraped_data() exactly. Without it the
    # preview counted the scraped rows and the action cleared the whole table,
    # so the dialog promised N and did something else entirely — and with
    # delete_images it unlinked hand-uploaded custom art on never-scraped rows
    # and reset their hand-edited titles. Keep the two in lockstep: the preview
    # is the promise this function is measured against.
    if system_id:
        games = query(
            "SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual "
            "FROM games WHERE system_id = ? AND scraped = 1",
            (system_id,),
        )
    else:
        games = query(
            "SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual "
            "FROM games WHERE scraped = 1"
        )

    game_ids_to_reset = [g['id'] for g in games]

    # Null the DB references BEFORE unlinking files. The reverse order (delete
    # files, then UPDATE) leaves dangling boxart/screenshot pointers site-wide
    # if the UPDATE raises (lock, disk-full, interrupt): the files are gone but
    # the columns still name them. Doing the UPDATE first means a later
    # delete_game_images() failure only strands orphan files on disk — harmless
    # and reclaimable by the media-cleanup sweep — never a broken DB reference.
    # `games` already holds the captured paths, so the delete still has them.
    if system_id:
        execute(
            f"UPDATE games SET {set_clause} WHERE system_id = ? AND scraped = 1",
            (system_id,),
        )
    else:
        execute(f"UPDATE games SET {set_clause} WHERE scraped = 1")
    cleared = len(game_ids_to_reset)

    if delete_images:
        images_deleted = delete_game_images(games)

    if game_ids_to_reset:
        # try/finally so a raise inside reset_game_title_from_filename can't
        # leak this fresh connection (get_db() opens a new handle each call).
        conn = get_db()
        try:
            for game_id in game_ids_to_reset:
                reset_game_title_from_filename(game_id, conn)
        finally:
            conn.close()

    logger.info(
        f"Cleared scraped data from {cleared} games"
        + (f", deleted {images_deleted} images" if delete_images else "")
    )

    return cleared, images_deleted
