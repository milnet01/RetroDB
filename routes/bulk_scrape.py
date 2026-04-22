# =============================================================================
# RETRODB - Bulk Scrape Blueprint
# =============================================================================
# Handles bulk scraping operations and background job management.
# =============================================================================

from flask import Blueprint, request, jsonify
import os
import logging

from services.database import query
from services.jobs import bulk_scrape_job
from services.game_utils import derive_title_from_filename, get_system_type
from services.auth import login_required
from services.api_helpers import handle_api_errors, success, error

logger = logging.getLogger(__name__)

bp = Blueprint('bulk_scrape', __name__)

# =============================================================================
# BULK SCRAPE API (Legacy - single game)
# =============================================================================

@bp.route('/api/bulk-scrape', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape():
    """Bulk scrape a single game - called repeatedly by frontend (LEGACY - kept for compatibility)"""
    data = request.get_json()
    game_id = data.get('game_id')
    system_id = data.get('system_id')

    if not game_id:
        return error('No game ID provided', code=200)

    # Get game info
    game = query("""
        SELECT g.*, s.folder AS system_folder, s.name AS system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)

    if not game:
        return error('Game not found', code=200)

    # Skip if already scraped
    if game['scraped']:
        return jsonify({'success': False, 'skipped': True, 'message': 'Already scraped'})

    # Derive search title from ROM FILENAME, not database title
    is_computer_system = get_system_type(game['system_folder']) == 'computer'
    if game.get('rom_path'):
        search_title = derive_title_from_filename(game['rom_path'], is_computer_system)
        logger.info(f"Derived search title from filename: '{search_title}' (from: {os.path.basename(game['rom_path'])})")
    else:
        import re
        search_title = game['title']
        if is_computer_system:
            search_title = re.sub(r'\s*\[[^\]]*\]', '', search_title).strip()
            search_title = re.sub(r'\s*\([^)]*(?:19\d{2}|20\d{2}|Disk|Side|Part|Ver)[^)]*\)$', '', search_title, flags=re.IGNORECASE).strip()

    # Scrape using hybrid scraper with user's priority order
    from scraper.scraper_manager import scraper_manager, load_scraper_settings

    # Get user's scraper priority
    scraper_settings = load_scraper_settings()
    user_priority = scraper_settings.get('priority', ['screenscraper', 'esde', 'tgdb', 'igdb'])
    enabled_scrapers = scraper_settings.get('enabled', {})

    logger.info(f"Bulk scrape for '{search_title}' using priority: {user_priority}")

    # Search for the game
    results = scraper_manager.search_games(search_title, game['system_name'], game['system_folder'])

    if results:
        from scraper.scraper_manager import get_match_settings, passes_match_filter

        match_settings = get_match_settings()

        source_name_map = {'thegamesdb': 'tgdb', 'screenscraper': 'screenscraper',
                           'esde': 'esde', 'igdb': 'igdb'}

        # Sort by score only — priority boost is already baked into each result's score
        sorted_results = sorted(results, key=lambda r: -r.get('score', 0))

        # Filter out results that don't pass the configured match filter
        sorted_results = [r for r in sorted_results if passes_match_filter(r, match_settings)]

        if not sorted_results:
            return jsonify({'success': False, 'skipped': True, 'message': 'No reliable matches found'})

        # Use the first result from an enabled scraper
        best_match = None
        for result in sorted_results:
            src = result.get('source', result.get('scraper', 'unknown'))
            normalized = source_name_map.get(src, src)
            if enabled_scrapers.get(normalized, True):
                best_match = result
                break

        if not best_match:
            best_match = sorted_results[0]

        source = best_match.get('source', best_match.get('scraper', 'tgdb'))
        source_id = best_match.get('id')

        logger.info(f"Selected {source} match: {best_match.get('name', 'Unknown')} (ID: {source_id})")

        # Build secondary_sources from other top results (best per scraper)
        # so gap-filling can reuse already-matched IDs instead of re-searching
        secondary_sources = []
        seen_sources = {source_name_map.get(source, source)}
        for r in sorted_results:
            r_src = source_name_map.get(r.get('source', ''), r.get('source', ''))
            if r_src not in seen_sources:
                seen_sources.add(r_src)
                secondary_sources.append({'source': r_src, 'id': r.get('id')})

        # Apply metadata via the shared orchestrator — normalizes the raw
        # `source` name ('thegamesdb' -> 'tgdb' etc.) so the hybrid pipeline's
        # primary-source branch fires instead of silently falling through.
        from services.game_metadata_service import apply_hybrid_metadata_to_game
        result = apply_hybrid_metadata_to_game(
            db_game_id=game_id,
            primary_source=source,
            primary_id=source_id,
            system_folder=game['system_folder'],
            fill_gaps=True,
            primary_data=best_match,
            secondary_sources=secondary_sources,
        )

        if result.get('success'):
            return success(
                updated=True,
                message=f"Scraped from {', '.join(result.get('sources_used', []))}",
                filled_fields=len(result.get('filled_fields', [])),
            )
        else:
            return error('Failed to apply metadata', code=200)
    else:
        return error('No matches found', code=200)


# =============================================================================
# BULK SCRAPE JOB API (Backend-driven)
# =============================================================================

@bp.route('/api/bulk-scrape-job/start', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_start():
    """Start a new bulk scrape job that runs in the background"""
    data = request.get_json()
    game_ids = data.get('game_ids', [])
    system_id = data.get('system_id')
    return_url = data.get('return_url')
    scrape_mode = data.get('scrape_mode', 'fill_missing')

    if not game_ids:
        return error('No game IDs provided', code=200)

    result = bulk_scrape_job.start(game_ids, system_id, return_url, scrape_mode)
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/status', methods=['GET'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_status():
    """Get the status of the current bulk scrape job"""
    status = bulk_scrape_job.get_status()
    return success(**status)


@bp.route('/api/bulk-scrape-job/pause', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_pause():
    """Pause the current bulk scrape job"""
    result = bulk_scrape_job.pause()
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/resume', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_resume():
    """Resume the current bulk scrape job"""
    result = bulk_scrape_job.resume()
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/cancel', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_cancel():
    """Cancel the current bulk scrape job"""
    result = bulk_scrape_job.cancel()
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/cancel-queued/<job_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_cancel_queued(job_id):
    """Cancel a specific queued bulk scrape job"""
    result = bulk_scrape_job.cancel_queued(job_id)
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/cancel-all-queued', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_cancel_all_queued():
    """Cancel all queued bulk scrape jobs"""
    result = bulk_scrape_job.cancel_all_queued()
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/promote-queued/<job_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_promote_queued(job_id):
    """Move a queued job up in the queue (run sooner)"""
    result = bulk_scrape_job.promote_queued(job_id)
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/demote-queued/<job_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_demote_queued(job_id):
    """Move a queued job down in the queue (run later)"""
    result = bulk_scrape_job.demote_queued(job_id)
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/swap-running/<job_id>', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_swap_running(job_id):
    """Swap a queued job with the currently running job"""
    result = bulk_scrape_job.swap_with_running(job_id)
    return jsonify(result)


@bp.route('/api/bulk-scrape-job/demote-running', methods=['POST'])
@login_required
@handle_api_errors
def api_bulk_scrape_job_demote_running():
    """Demote the running job to queue position 1 and start the next queued job"""
    result = bulk_scrape_job.demote_running()
    return jsonify(result)
