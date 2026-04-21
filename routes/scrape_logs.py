# =============================================================================
# RETRODB - Log Viewer Blueprint
# =============================================================================
# Universal log viewer for all log categories: scraping, rom_tools,
# rom_reports, image_resize, and system.
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, send_file
import os
import logging

import log_manager
from services.api_helpers import handle_api_errors
from services.auth import login_required, permission_required
from services.security import safe_filename

logger = logging.getLogger(__name__)

VALID_PREFIXES = ('scraping_', 'rom_tools_', 'rom_reports_', 'image_resize_', 'system_')

logs_bp = Blueprint('logs', __name__)


# =============================================================================
# PAGE ROUTES
# =============================================================================

@logs_bp.route('/logs')
@login_required
@permission_required('system_functions')
def log_viewer():
    """Universal log viewer page"""
    return render_template('logs.html')


@logs_bp.route('/scrape-logs')
@login_required
@permission_required('system_functions')
def scrape_logs_redirect():
    """Backward-compat redirect from old URL"""
    return redirect(url_for('logs.log_viewer'), code=301)


# =============================================================================
# LOG VIEWER API
# =============================================================================

@logs_bp.route('/api/logs/files')
@login_required
@permission_required('system_functions')
def api_log_files():
    """List available log files with optional category filter.

    Query params:
        category (str, optional): Filter by category (scraping, rom_tools, etc.)

    Returns category counts and the list of matching files.
    """
    try:
        all_files = log_manager.get_log_files()
        category_filter = request.args.get('category', '').strip()

        # Build category counts from all files
        category_counts = {}
        for f in all_files:
            cat = f['category']
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Filter if requested
        if category_filter:
            files = [f for f in all_files if f['category'] == category_filter]
        else:
            files = all_files

        return jsonify({
            'success': True,
            'files': files,
            'categories': sorted(category_counts.keys()),
            'category_counts': category_counts,
            'total': len(all_files)
        })
    except Exception as e:
        logger.error(f"Error listing log files: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@logs_bp.route('/api/logs/content/<filename>')
@login_required
@permission_required('system_functions')
def api_log_content(filename):
    """Get full content of a log file.

    Accepts any valid category prefix, not just scraping_.
    Returns category field so JS knows the log type.
    """
    if not any(filename.startswith(p) for p in VALID_PREFIXES):
        return jsonify({'success': False, 'error': 'Invalid log file'}), 403

    content = log_manager.get_full_log_content(filename)
    if content is None:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)
    size = len(content.encode('utf-8'))

    # Extract category from filename
    parts = filename.rsplit('_', 1)
    category = parts[0] if len(parts) > 1 else 'unknown'

    return jsonify({
        'success': True,
        'content': content,
        'size': size,
        'line_count': line_count,
        'category': category
    })


# =============================================================================
# LOG FILE MANAGEMENT (moved from settings.py)
# =============================================================================

@logs_bp.route('/api/logs/download/<filename>')
@login_required
@permission_required('system_functions')
@handle_api_errors
def api_download_log(filename):
    """Download a log file"""
    if not safe_filename(filename):
        return jsonify({'success': False, 'error': 'Invalid filename'}), 400

    if not any(filename.startswith(p) for p in VALID_PREFIXES):
        return jsonify({'success': False, 'error': 'Invalid log file'}), 403

    filepath = os.path.join(log_manager.LOGS_DIR, filename)

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': 'Log file not found'}), 404

    return send_file(
        filepath,
        mimetype='text/plain',
        as_attachment=True,
        download_name=filename
    )


@logs_bp.route('/api/logs/delete/<filename>', methods=['DELETE'])
@login_required
@permission_required('system_functions')
def api_delete_log(filename):
    """Delete a log file"""
    try:
        if not safe_filename(filename):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        if not any(filename.startswith(p) for p in VALID_PREFIXES):
            return jsonify({'success': False, 'error': 'Invalid log file'}), 403

        filepath = os.path.join(log_manager.LOGS_DIR, filename)

        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': 'Log file not found'})

        os.remove(filepath)
        return jsonify({'success': True, 'message': f'Deleted {filename}'})
    except Exception as e:
        logger.error(f"Error deleting log file: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@logs_bp.route('/api/logs/clear-old', methods=['POST'])
@login_required
@permission_required('system_functions')
def api_clear_old_logs():
    """Clear log files older than 5 days"""
    try:
        removed = log_manager.clear_old_logs(days=5)
        return jsonify({'success': True, 'removed': removed})
    except Exception as e:
        logger.error(f"Error clearing old logs: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


# =============================================================================
# BACKWARD-COMPAT ALIASES (used by settings page)
# =============================================================================

@logs_bp.route('/api/logs/list')
@login_required
@permission_required('system_functions')
def api_list_logs_compat():
    """Backward-compat alias for settings page — same as /api/logs/files"""
    return api_log_files()


@logs_bp.route('/api/logs/view/<filename>')
@login_required
@permission_required('system_functions')
def api_view_log_compat(filename):
    """Backward-compat alias for settings page — returns content as array of lines"""
    try:
        if not safe_filename(filename):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        lines = request.args.get('lines', 100, type=int)
        content = log_manager.get_log_content(filename, lines=lines)

        if content is None:
            return jsonify({'success': False, 'error': 'Log file not found'})

        return jsonify({'success': True, 'content': content})
    except Exception as e:
        logger.error(f"Error viewing log file: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


# =============================================================================
# LEGACY API REDIRECT
# =============================================================================

@logs_bp.route('/api/scrape-logs/files')
@login_required
@permission_required('system_functions')
def api_scrape_log_files_legacy():
    """Legacy endpoint — redirects to new API"""
    return api_log_files()


@logs_bp.route('/api/scrape-logs/content/<filename>')
@login_required
@permission_required('system_functions')
def api_scrape_log_content_legacy(filename):
    """Legacy endpoint — redirects to new API"""
    return api_log_content(filename)
