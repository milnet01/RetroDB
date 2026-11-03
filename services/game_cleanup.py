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
from services.normalization import canonicalize_metadata
from services.release_dates import source_date
from services import upscale_queue

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
    'user_score_count', 'units_sold', 'release_dates', 'boxart', 'boxart_3d', 'screenshots', 'fanart',
    'game_logo', 'video', 'manual',
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
    A locked title (PASS-59-159) keeps its value: reset_game_title_from_filename
    skips it.

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
            "SELECT id, boxart, boxart_3d, screenshots, fanart, game_logo, video, manual "
            "FROM games WHERE system_id = ? AND scraped = 1",
            (system_id,),
        )
    else:
        games = query(
            "SELECT id, boxart, boxart_3d, screenshots, fanart, game_logo, video, manual "
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
    upscale_queue.forget_cleared()

    if delete_images:
        images_deleted = delete_game_images(games)

    if game_ids_to_reset:
        # try/finally so a raise inside reset_game_title_from_filename can't
        # leak this fresh connection (get_db() opens a new handle each call).
        conn = get_db()
        try:
            for game_id in game_ids_to_reset:
                reset_game_title_from_filename(game_id, conn)
            # A caller-supplied connection is never committed by the reset
            # itself; without this the close() rolled every title back.
            conn.commit()
        finally:
            conn.close()

    logger.info(
        f"Cleared scraped data from {cleared} games"
        + (f", deleted {images_deleted} images" if delete_images else "")
    )

    return cleared, images_deleted


_LABEL_COLUMNS = ('genre', 'modes', 'perspective', 'dimension', 'game_structure', 'players')


def _filled_by(history, field):
    """The source the newest scrape to record `field` credits, or None."""
    from services.field_sources import credits
    return credits(history).get(field)


def _label_changes():
    """(id, stored columns, new columns) for rows whose names or counts would change.

    RAWG used to send a default of 1 player. It no longer does, and because a
    filled field is never refilled, those old ones block a real count.
    """
    columns = ', '.join(_LABEL_COLUMNS)
    found = []
    for row in query(f"SELECT id, scrape_history, {columns} FROM games"):
        stored = {c: row[c] for c in _LABEL_COLUMNS}
        wanted = dict(stored)
        if wanted['players'] == 1 and _filled_by(row['scrape_history'], 'players') == 'RAWG':
            wanted['players'] = None
        canonicalize_metadata(wanted)
        wanted = {c: (v if v != '' else None) for c, v in wanted.items()}
        if wanted != {c: (v if v != '' else None) for c, v in stored.items()}:
            found.append((row['id'], stored, wanted))
    return found


def count_label_changes():
    """How many games hold names or player counts the tidy would change."""
    return len(_label_changes())


def fix_labels():
    """Give stored rows the canonical names (PASS-59-206). Returns the count."""
    set_clause = ', '.join(f'{c} = ?' for c in _LABEL_COLUMNS)
    # `IS` skips a row changed since the search, and matches an empty value.
    same_clause = ' AND '.join(f'{c} IS ?' for c in _LABEL_COLUMNS)
    fixed = 0
    with get_db_with_context() as conn:
        for game_id, stored, wanted in _label_changes():
            fixed += conn.execute(
                f"UPDATE games SET {set_clause} WHERE id = ? AND {same_clause}",
                (*wanted.values(), game_id, *stored.values()),
            ).rowcount
    logger.info(f"Tidied names or player counts on {fixed} game(s)")
    return fixed


def _tidied_date(stored, source):
    """What a stored `release_date` from `source` really knows (PASS-59-207).

    A date no scrape credits may have been typed by hand, so it stays. 1 January
    1970 stays empty either way: no game came out then.
    """
    if stored == '1970-01-01':
        return None
    if source is None:
        return stored
    if source == 'IGDB':
        # IGDB's year-only dates were stored as the last day of the year.
        return stored[:4] if stored.endswith('-12-31') else stored
    return source_date(stored, padded_months=source == 'ES-DE') or stored


def _release_date_changes():
    """(id, stored date, new date) for rows whose date claims more than is known."""
    found = []
    for row in query("SELECT id, release_date, scrape_history FROM games "
                     "WHERE release_date IS NOT NULL AND release_date != ''"):
        wanted = _tidied_date(row['release_date'], _filled_by(row['scrape_history'], 'release_date'))
        if wanted != row['release_date']:
            found.append((row['id'], row['release_date'], wanted))
    return found


def count_release_date_changes():
    """How many games hold a date the tidy would change."""
    return len(_release_date_changes())


def fix_release_dates():
    """Cut stored release dates back to what their source knew. Returns the count."""
    fixed = 0
    with get_db_with_context() as conn:
        for game_id, stored, wanted in _release_date_changes():
            # `release_date = ?` skips a row changed since the search.
            fixed += conn.execute(
                "UPDATE games SET release_date = ? WHERE id = ? AND release_date = ?",
                (wanted, game_id, stored),
            ).rowcount
    logger.info(f"Tidied the release date on {fixed} game(s)")
    return fixed


def _ai_region_mismatches():
    """(id, stored region, file's region) where the AI's region contradicts the file.

    A stored value that is one of a two-region file's regions agrees with it.
    """
    from scraper.scrape_esde import extract_region_from_filename

    rows = query("""SELECT id, rom_path, region FROM games
                    WHERE scrape_history LIKE '%"region (AI)"%'""")
    found = []
    for row in rows:
        tag = extract_region_from_filename(os.path.basename(row['rom_path'] or ''))
        if tag and row['region'] not in (tag, *tag.split('/')):
            found.append((row['id'], row['region'], tag.split('/')[0]))
    return found


def count_ai_region_mismatches():
    """How many games hold an AI region their file name contradicts."""
    return len(_ai_region_mismatches())


def fix_ai_region_mismatches():
    """Give those games their file name's region (PASS-59-204). Returns the count."""
    fixed = 0
    with get_db_with_context() as conn:
        for game_id, stored, tag in _ai_region_mismatches():
            # `IS` keeps a region changed since the search, and matches an empty one.
            fixed += conn.execute(
                "UPDATE games SET region = ? WHERE id = ? AND region IS ?",
                (tag, game_id, stored),
            ).rowcount
    logger.info(f"Set {fixed} region(s) from file names, replacing the AI's guess")
    return fixed
