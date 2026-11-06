# =============================================================================
# RETRODB - Maintenance Blueprint
# =============================================================================
# Thin HTTP surface over the maintenance service layer
# (services/game_cleanup.py, services/media_cleanup.py, services/rom_scanner.py).
# Also exposes image-resize and alt-titles backfill job controls.
# =============================================================================

from flask import Blueprint, request, jsonify
from flask_babel import gettext as _
from scraper.service_limits import SCREENSCRAPER
from services.service_stop_text import stop_sentences
import os
import sys
import time
import signal
import threading
import logging

import config
from services.analytics import invalidate_analytics_cache
from services.game_query import invalidate_filter_cache
from services.api_helpers import error, handle_api_errors, success, job_reply
from services.database import get_db, query
from services.auth import admin_required, login_required
from services.game_cleanup import (
    count_ai_region_mismatches,
    count_label_changes,
    count_release_date_changes,
    fix_labels,
    fix_release_dates,
    fix_ai_region_mismatches,
    clean_missing_roms,
    clear_clz_imports,
    clear_scraped_data,
    preview_scraped_data,
)
from services.media_cleanup import (
    clean_orphaned_files,
    clear_missing_media_refs,
    clear_rawg_covers,
    count_rawg_covers,
    find_missing_media_refs,
    find_orphaned_media,
)
from services.rom_scanner import RomPathNotConfigured

logger = logging.getLogger(__name__)

bp = Blueprint('maintenance', __name__)


# =============================================================================
# MAINTENANCE API ROUTES
# =============================================================================

@bp.route('/api/status')
@admin_required
def api_status():
    """Server status endpoint"""
    return jsonify({
        'status': 'online',
        'version': config.APP_VERSION
    })


@bp.route('/api/scan', methods=['POST'])
@admin_required
@handle_api_errors
def api_scan():
    """Scan ROM library.

    v3.6.5 — RomPathNotConfigured is converted to a 4xx with a remediation
    message so the user sees "ROM path not configured. Go to Settings → Paths
    to set it." instead of a misleading green "scan complete, 0 new games"
    toast (the previous behaviour, caused by an empty config.ROM_PATH).
    """
    try:
        from scraper.scan_roms import scan_roms
        new_games = scan_roms()
    except RomPathNotConfigured as exc:
        return error(str(exc), 400)

    if new_games:
        invalidate_analytics_cache()
    return success(new_games=new_games, message=f'Found {new_games} new games')


@bp.route('/api/clean-missing-roms', methods=['POST'])
@admin_required
@handle_api_errors
def api_clean_missing_roms():
    """Remove games from database whose ROM files no longer exist"""
    removed, removed_games = clean_missing_roms()
    if removed:
        invalidate_analytics_cache()
    return success(
        removed=removed,
        removed_games=removed_games,
        message=f'Removed {removed} games with missing ROM files',
    )


@bp.route('/api/clear-clz-imports', methods=['POST'])
@admin_required
@handle_api_errors
def api_clear_clz_imports():
    """Remove all CLZ Import games from the database"""
    removed, removed_games = clear_clz_imports()
    if removed == 0:
        return success(removed=0, removed_games=[], message='No CLZ Import games found')
    invalidate_analytics_cache()
    return success(
        removed=removed,
        removed_games=removed_games,
        message=f'Removed {removed} CLZ Import games',
    )


@bp.route('/api/clear-scraped-data/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_clear_scraped_data_preview():
    """Preview how many games would be affected by clear scraped data"""
    system_id = request.args.get('system_id')
    return success(count=preview_scraped_data(system_id=system_id))


@bp.route('/api/clear-scraped-data', methods=['POST'])
@admin_required
@handle_api_errors
def api_clear_scraped_data():
    """Clear scraped metadata from games and reset titles to filename-derived values"""
    data = request.get_json() or {}
    cleared, images_deleted = clear_scraped_data(
        system_id=data.get('system_id'),
        delete_images=data.get('delete_images') is True,  # never a "false" string
    )
    if cleared:
        invalidate_analytics_cache()
    return success(cleared=cleared, images_deleted=images_deleted)


def _scan_orphaned_media():
    """The orphan scan over every game and wishlist row (PASS-59-238)."""
    games = query("SELECT id, boxart, boxart_3d, screenshots, fanart, game_logo, boxart_back, video, manual FROM games")
    wishlist = query("SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM wishlist")
    return find_orphaned_media(games, wishlist)


@bp.route('/api/orphaned-media/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_orphaned_media_preview():
    """Scan for orphaned media files (not linked to any game in database)"""
    orphaned, total_size = _scan_orphaned_media()
    return success(
        files=orphaned,
        total_size_mb=total_size / (1024 * 1024),
    )


@bp.route('/api/orphaned-media/clean', methods=['POST'])
@admin_required
@handle_api_errors
def api_orphaned_media_clean():
    """Delete orphaned media files"""
    orphaned, _ = _scan_orphaned_media()
    # Pass 48.4 — honour the original preview scan-start so a file written by
    # a concurrent scraper during the preview→clean window is skipped. The
    # client echoes back the timestamp it received from /preview; a missing or
    # malformed value falls back to the re-scan's own race guard.
    payload = request.get_json(silent=True) or {}
    try:
        override = float(payload['scan_started_at'])
    except (KeyError, TypeError, ValueError):
        override = None
    deleted, errors, freed_size = clean_orphaned_files(orphaned, scan_started_override=override)
    return success(
        deleted=deleted,
        errors=errors,
        freed_mb=freed_size / (1024 * 1024),
    )


@bp.route('/api/missing-media-refs/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_missing_media_refs_preview():
    """Preview games whose media DB references point to files gone from disk.

    Inverse of orphaned-media (files with no DB row). Read-only — lists the
    affected games/fields plus any directories held back by the Pass 54.1
    mass-missing guard so the UI can warn before the user clears anything.
    """
    games = query(
        "SELECT id, title, boxart, boxart_3d, screenshots, fanart, game_logo, boxart_back, video, manual "
        "FROM games"
    )
    affected, guarded = find_missing_media_refs(games)
    ref_count = sum(len(g['fields']) for g in affected)
    return success(
        games=affected[:200],
        game_count=len(affected),
        ref_count=ref_count,
        guarded=guarded,
    )


@bp.route('/api/missing-media-refs/clear', methods=['POST'])
@admin_required
@handle_api_errors
def api_missing_media_refs_clear():
    """Clear DB media references pointing to files no longer on disk.

    Re-derives the set server-side (never trusts the preview payload) and
    honours the mass-missing guard, so a bulk "everything's missing" state
    can't wipe the whole library's references in one click.
    """
    cleared, game_count, guarded = clear_missing_media_refs()
    if cleared:
        invalidate_analytics_cache()
    return success(
        cleared=cleared,
        game_count=game_count,
        guarded=guarded,
    )


@bp.route('/api/database/optimize', methods=['POST'])
@admin_required
@handle_api_errors
def api_database_optimize():
    """Run VACUUM, ANALYZE, and PRAGMA optimize on the database"""
    db_path = config.DB_PATH
    size_before = os.path.getsize(db_path)
    start_time = time.time()

    conn = get_db()
    try:
        conn.execute("VACUUM")
        conn.execute("ANALYZE")
        conn.execute("PRAGMA optimize")
    finally:
        # VACUUM raises "database is locked" while a job writes; close anyway.
        conn.close()

    duration = time.time() - start_time
    size_after = os.path.getsize(db_path)

    logger.info(f"Database optimized: {size_before / (1024*1024):.2f}MB -> {size_after / (1024*1024):.2f}MB in {duration:.2f}s")

    return success(
        message='Database optimized successfully',
        size_before_mb=round(size_before / (1024 * 1024), 2),
        size_after_mb=round(size_after / (1024 * 1024), 2),
        duration_seconds=round(duration, 2),
    )


# =============================================================================
# IMAGE RESIZE / STANDARDIZATION
# =============================================================================

@bp.route('/api/maintenance/image-resize/start', methods=['POST'])
@admin_required
@handle_api_errors
def api_image_resize_start():
    """Start bulk image standardization job."""
    from services.jobs import image_resize_job
    from services.jobs.image_resize import IMAGE_TYPES

    data = request.get_json(silent=True) or {}
    image_types = data.get('image_types', list(IMAGE_TYPES))
    if not isinstance(image_types, list) or any(t not in IMAGE_TYPES for t in image_types):
        return error(_('Unknown image type'), 400)

    result = image_resize_job.start(image_types=image_types)
    return job_reply(result)


@bp.route('/api/maintenance/image-resize/status', methods=['GET'])
@login_required
@handle_api_errors
def api_image_resize_status():
    """Poll image resize job status."""
    from services.jobs import image_resize_job
    status = image_resize_job.get_status()
    status['success'] = True
    return jsonify(status)


@bp.route('/api/maintenance/image-resize/cancel', methods=['POST'])
@admin_required
@handle_api_errors
def api_image_resize_cancel():
    """Cancel running image resize job."""
    from services.jobs import image_resize_job
    result = image_resize_job.cancel()
    return job_reply(result)


# =============================================================================
# BULK JPEG/PNG → WEBP MIGRATION (FU.3)
# =============================================================================
# Convert legacy .jpg / .png library files to .webp in-place. Walks every
# games.boxart / boxart_3d / fanart / screenshots filename, re-encodes any
# convertible original as a sibling .webp, updates the DB pointer, then
# deletes the original after the new file verifies. Manuals (PDF) and
# existing .webp / .gif entries pass through.

@bp.route('/api/maintenance/convert-to-webp/start', methods=['POST'])
@admin_required
@handle_api_errors
def api_convert_to_webp_start():
    """Start the bulk JPEG/PNG → WebP migration job."""
    from services.jobs import webp_migrate_job
    result = webp_migrate_job.start()
    return job_reply(result)


@bp.route('/api/maintenance/convert-to-webp/status', methods=['GET'])
@login_required
@handle_api_errors
def api_convert_to_webp_status():
    """Poll WebP migration status."""
    from services.jobs import webp_migrate_job
    status = webp_migrate_job.get_status()
    status['success'] = True
    return jsonify(status)


@bp.route('/api/maintenance/convert-to-webp/cancel', methods=['POST'])
@admin_required
@handle_api_errors
def api_convert_to_webp_cancel():
    """Cancel the running WebP migration."""
    from services.jobs import webp_migrate_job
    result = webp_migrate_job.cancel()
    return job_reply(result)


# =============================================================================
# ALTERNATE TITLES BACKFILL JOB
# =============================================================================

@bp.route('/api/maintenance/alt-titles-backfill/start', methods=['POST'])
@admin_required
@handle_api_errors
def api_alt_titles_backfill_start():
    """Start bulk alternate-titles backfill job."""
    from services.jobs import alt_titles_backfill_job
    data = request.get_json(silent=True) or {}
    only_empty = bool(data.get('only_empty', True))
    result = alt_titles_backfill_job.start(only_empty=only_empty)
    return job_reply(result)


@bp.route('/api/maintenance/alt-titles-backfill/status', methods=['GET'])
@login_required
@handle_api_errors
def api_alt_titles_backfill_status():
    """Poll alt-titles backfill job status."""
    from services.jobs import alt_titles_backfill_job
    status = alt_titles_backfill_job.get_status()
    status['success'] = True
    return jsonify(status)


@bp.route('/api/maintenance/alt-titles-backfill/cancel', methods=['POST'])
@admin_required
@handle_api_errors
def api_alt_titles_backfill_cancel():
    """Cancel running alt-titles backfill job."""
    from services.jobs import alt_titles_backfill_job
    result = alt_titles_backfill_job.cancel()
    return job_reply(result)


# =============================================================================
# RAWG PICTURES USED AS BOX ART (PASS-59-203)
# =============================================================================

@bp.route('/api/maintenance/rawg-covers/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_rawg_covers_preview():
    """How many covers the clean-up would clear. Changes nothing."""
    return success(count=count_rawg_covers())


@bp.route('/api/maintenance/rawg-covers/clear', methods=['POST'])
@admin_required
@handle_api_errors
def api_rawg_covers_clear():
    """Clear covers taken from RAWG so a scrape can fill in real ones."""
    cleared = clear_rawg_covers()
    if cleared:
        invalidate_analytics_cache()
    return success(cleared=cleared)


# =============================================================================
# REGIONS THE AI GUESSED AGAINST THE FILE NAME (PASS-59-204)
# =============================================================================

@bp.route('/api/maintenance/file-regions/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_file_regions_preview():
    """How many regions the fix would change. Changes nothing."""
    return success(count=count_ai_region_mismatches())


@bp.route('/api/maintenance/file-regions/fix', methods=['POST'])
@admin_required
@handle_api_errors
def api_file_regions_fix():
    """Replace AI regions that contradict the ROM's file name."""
    fixed = fix_ai_region_mismatches()
    if fixed:
        invalidate_analytics_cache()
        invalidate_filter_cache()
    return success(fixed=fixed)


# =============================================================================
# ONE SET OF NAMES FOR GENRES, PERSPECTIVES AND MODES (PASS-59-206)
# =============================================================================

@bp.route('/api/maintenance/labels/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_labels_preview():
    """How many games the tidy would change. Changes nothing."""
    return success(count=count_label_changes())


@bp.route('/api/maintenance/labels/fix', methods=['POST'])
@admin_required
@handle_api_errors
def api_labels_fix():
    """Give stored genres, perspectives, modes and player counts one set of names."""
    fixed = fix_labels()
    if fixed:
        invalidate_analytics_cache()
        invalidate_filter_cache()
    return success(fixed=fixed)


# =============================================================================
# RELEASE DATES THAT CLAIM A DAY NOBODY PUBLISHED (PASS-59-207)
# =============================================================================

@bp.route('/api/maintenance/release-dates/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_release_dates_preview():
    """How many games the tidy would change. Changes nothing."""
    return success(count=count_release_date_changes())


@bp.route('/api/maintenance/release-dates/fix', methods=['POST'])
@admin_required
@handle_api_errors
def api_release_dates_fix():
    """Cut stored release dates back to what their source knew."""
    fixed = fix_release_dates()
    if fixed:
        invalidate_analytics_cache()
        invalidate_filter_cache()
    return success(fixed=fixed)


# =============================================================================
# SCREENSCRAPER REGION REPAIR JOB (PASS-59-202)
# =============================================================================

@bp.route('/api/maintenance/ss-region-repair/start', methods=['POST'])
@admin_required
@handle_api_errors
def api_ss_region_repair_start():
    """Start swapping ScreenScraper boxes and manuals from the wrong region."""
    from services.jobs import ss_region_repair_job
    result = ss_region_repair_job.start()
    if result['success']:
        return jsonify(result)
    if result['error'] == 'no_account':
        return error(_('Add your ScreenScraper account in Settings first.'), 400)
    return error(_('This fix is already running.'), 409)


@bp.route('/api/maintenance/ss-region-repair/status', methods=['GET'])
@login_required
@handle_api_errors
def api_ss_region_repair_status():
    """Poll the region repair job."""
    from services.jobs import ss_region_repair_job
    status = ss_region_repair_job.get_status()
    status['service_stops'] = stop_sentences([SCREENSCRAPER])
    status['success'] = True
    return jsonify(status)


@bp.route('/api/maintenance/ss-region-repair/cancel', methods=['POST'])
@admin_required
@handle_api_errors
def api_ss_region_repair_cancel():
    """Stop the region repair job after the game it is on."""
    from services.jobs import ss_region_repair_job
    return jsonify(ss_region_repair_job.cancel())


@bp.route('/api/restart', methods=['POST'])
@admin_required
def api_restart():
    """Restart server.

    Drains running jobs first, as the SIGTERM handler behind /api/shutdown
    does: os.execv replaces the process at once, so without the drain a
    restart mid-scrape loses the progress the drain exists to persist.
    Under PyInstaller sys.executable IS the app and sys.argv[0] names it
    again, so the frozen argv drops argv[0] rather than pass it as an arg.
    """
    def restart():
        from services.jobs.base import request_shutdown
        time.sleep(1)
        request_shutdown(timeout=5.0)
        args = sys.argv[1:] if getattr(sys, 'frozen', False) else sys.argv
        os.execv(sys.executable, [sys.executable] + args)

    threading.Thread(target=restart).start()

    return success(message='Server restarting...')


@bp.route('/api/shutdown', methods=['POST'])
@admin_required
@handle_api_errors
def api_shutdown():
    """Gracefully shut the server down.

    Mirrors api_restart's delayed-thread pattern, but sends SIGTERM to trigger
    the graceful-drain handler installed in app.py (drains running jobs, then
    re-raises to exit) instead of re-exec'ing. The ~1 s sleep lets the JSON
    response flush to the browser before the process dies.

    SIGTERM (not sys.exit / os._exit): sys.exit only unwinds this worker thread
    while waitress keeps serving; os._exit skips the job drain the graceful
    handler exists to provide.
    """
    def shutdown():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=shutdown, daemon=True).start()

    return success(message='Server shutting down...')
