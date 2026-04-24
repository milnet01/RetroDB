# =============================================================================
# RETRODB - Maintenance Blueprint
# =============================================================================
# Thin HTTP surface over the maintenance service layer
# (services/game_cleanup.py, services/media_cleanup.py, services/rom_scanner.py).
# Also exposes image-resize and alt-titles backfill job controls.
# =============================================================================

from flask import Blueprint, request, jsonify
import os
import sys
import time
import threading
import logging

import config
from services.analytics import invalidate_analytics_cache
from services.api_helpers import handle_api_errors, success
from services.database import get_db, query
from services.auth import admin_required, login_required
from services.game_cleanup import (
    clean_missing_roms,
    clear_clz_imports,
    clear_scraped_data,
    preview_scraped_data,
)
from services.media_cleanup import clean_orphaned_files, find_orphaned_media
from services.rom_scanner import run_inline_scan

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
    """Scan ROM library"""
    try:
        from scraper.scan_roms import scan_roms
        new_games = scan_roms()
    except ImportError:
        new_games = run_inline_scan()

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
        delete_images=data.get('delete_images', False),
    )
    if cleared:
        invalidate_analytics_cache()
    return success(cleared=cleared, images_deleted=images_deleted)


@bp.route('/api/orphaned-media/preview', methods=['GET'])
@admin_required
@handle_api_errors
def api_orphaned_media_preview():
    """Scan for orphaned media files (not linked to any game in database)"""
    games = query("SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM games")
    orphaned, total_size = find_orphaned_media(games)
    return success(
        files=orphaned,
        total_size_mb=total_size / (1024 * 1024),
    )


@bp.route('/api/orphaned-media/clean', methods=['POST'])
@admin_required
@handle_api_errors
def api_orphaned_media_clean():
    """Delete orphaned media files"""
    games = query("SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM games")
    orphaned, _ = find_orphaned_media(games)
    deleted, errors, freed_size = clean_orphaned_files(orphaned)
    return success(
        deleted=deleted,
        errors=errors,
        freed_mb=freed_size / (1024 * 1024),
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
    conn.execute("VACUUM")
    conn.execute("ANALYZE")
    conn.execute("PRAGMA optimize")
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

    data = request.get_json(silent=True) or {}
    image_types = data.get('image_types', ['boxart', 'screenshots', 'boxart_3d', 'controllers'])

    result = image_resize_job.start(image_types=image_types)
    return jsonify(result)


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
    return jsonify(result)


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
    return jsonify(result)


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
    return jsonify(result)


@bp.route('/api/restart', methods=['POST'])
@admin_required
def api_restart():
    """Restart server"""
    def restart():
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=restart).start()

    return success(message='Server restarting...')
