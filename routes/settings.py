# =============================================================================
# RETRODB - Settings Blueprint
# =============================================================================
# Handles settings page, logging configuration, backups, and dropdown options.
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, g, current_app
import sqlite3
import os
import shutil
import json
import logging
from datetime import datetime, timezone

import config
import settings_manager
import log_manager
from services.api_helpers import handle_api_errors
from services.database import query, execute, get_db, backup_database
from services.auth import login_required, admin_required
from services.security import safe_filename
from services.normalization import get_unique_values, apply_normalization

logger = logging.getLogger(__name__)

bp = Blueprint('settings', __name__)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_rom_path():
    """Get effective ROM path from settings or config"""
    return settings_manager.get_effective_path('rom_path', config.ROM_PATH)


def get_esde_gamelists_path():
    """Get effective ES-DE gamelists path"""
    return settings_manager.get_effective_path('esde_gamelists_path', getattr(config, 'ESDE_GAMELISTS_PATH', ''))


def get_esde_media_path():
    """Get effective ES-DE media path"""
    return settings_manager.get_effective_path('esde_downloaded_media_path', getattr(config, 'ESDE_DOWNLOADED_MEDIA_PATH', ''))


def get_rpcs3_trophy_path():
    """Get effective RPCS3 trophy path"""
    return settings_manager.get_effective_path('rpcs3_trophy_path', getattr(config, 'RPCS3_TROPHY_PATH', ''))


def get_stats():
    """Get library statistics - delegates to app.py's canonical version."""
    import importlib
    app_module = importlib.import_module('app')
    return app_module.get_stats()


def get_api_status():
    """Get API status - delegates to app.py's canonical version."""
    import importlib
    app_module = importlib.import_module('app')
    return app_module.get_api_status()


def format_size(bytes_size):
    """Format bytes to human readable size"""
    if bytes_size is None:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} PB"


# =============================================================================
# SETTINGS PAGE
# =============================================================================

@bp.route('/settings')
@login_required
def settings():
    """Settings page"""
    try:
        # Import SCRAPER_SETTINGS_FILE from scraper blueprint
        from routes.scraper import SCRAPER_SETTINGS_FILE

        stats = get_stats()
        api_status = get_api_status()

        # Get systems for the clear scraped data dropdown
        systems = query("SELECT id, name, folder FROM systems ORDER BY name")

        # Get all users for user management (admin only sees this)
        users = []
        if g.user and g.user['role'] == 'admin':
            users = query("""
                SELECT u.id, u.username, u.display_name, u.role, u.created_at, u.last_login, u.is_active,
                       us.rpcs3_trophy_path, us.ra_username
                FROM users u
                LEFT JOIN user_settings us ON u.id = us.user_id
                ORDER BY u.role, u.username
            """)

        # Load saved scraper settings
        scraper_settings = {
            'priority': ['esde', 'tgdb', 'igdb', 'rawg'],
            'enabled': {
                'esde': config.SCRAPER_ESDE_ENABLED,
                'tgdb': config.SCRAPER_TGDB_ENABLED,
                'igdb': config.SCRAPER_IGDB_ENABLED,
                'rawg': config.SCRAPER_RAWG_ENABLED,
                'ai': False
            },
            'api_keys': {
                'tgdb': getattr(config, 'TGDB_API_KEY', ''),
                'igdb_client_id': getattr(config, 'IGDB_CLIENT_ID', ''),
                'igdb_client_secret': getattr(config, 'IGDB_CLIENT_SECRET', ''),
                'rawg': getattr(config, 'RAWG_API_KEY', ''),
                'ra_username': getattr(config, 'RETROACHIEVEMENTS_USERNAME', ''),
                'ra_apikey': getattr(config, 'RETROACHIEVEMENTS_API_KEY', ''),
                'ai_provider': getattr(config, 'AI_METADATA_PROVIDER', ''),
                'ai_gemini_api_key': getattr(config, 'AI_GEMINI_API_KEY', ''),
                'ai_gemini_model': '',
                'ai_openai_api_key': getattr(config, 'AI_OPENAI_API_KEY', ''),
                'ai_openai_model': '',
                'ai_claude_api_key': getattr(config, 'AI_CLAUDE_API_KEY', ''),
                'ai_claude_model': ''
            }
        }

        # Override with saved settings if available
        if os.path.exists(SCRAPER_SETTINGS_FILE):
            try:
                with open(SCRAPER_SETTINGS_FILE, 'r') as f:
                    saved = json.load(f)
                    if 'priority' in saved:
                        scraper_settings['priority'] = saved['priority']
                    if 'enabled' in saved:
                        scraper_settings['enabled'].update(saved['enabled'])
                    if 'api_keys' in saved:
                        scraper_settings['api_keys'].update(saved['api_keys'])
                    # Load match filtering settings from saved file
                    if 'minimum_match_score' in saved:
                        scraper_settings['minimum_match_score'] = saved['minimum_match_score']
                    if 'match_mode' in saved:
                        scraper_settings['match_mode'] = saved['match_mode']
                    if 'match_criteria' in saved:
                        scraper_settings['match_criteria'] = saved['match_criteria']
            except Exception as e:
                logger.warning(f"Could not load saved scraper settings: {e}")

        # Ensure match filtering settings have defaults
        scraper_settings.setdefault('minimum_match_score', 200)
        scraper_settings.setdefault('match_mode', 'score')
        scraper_settings.setdefault('match_criteria', {'title_quality': 'close', 'platform_required': True})

        # Load user settings (including logging settings)
        user_settings = settings_manager.load_settings()

        return render_template('settings.html',
                             stats=stats,
                             api_status=api_status,
                             scraper_settings=scraper_settings,
                             systems=systems,
                             users=users,
                             settings=user_settings)
    except Exception as e:
        logger.error(f"Settings error: {e}")
        return f"Error loading settings: {e}", 500


# =============================================================================
# DROPDOWN OPTIONS API
# =============================================================================

@bp.route('/api/dropdown-options/<category>')
@login_required
@handle_api_errors
def api_get_dropdown_options(category):
    """Get dropdown options for a category"""
    options = query("""
        SELECT id, value, sort_order
        FROM dropdown_options
        WHERE category = ?
        ORDER BY value COLLATE NOCASE
    """, (category,))
    return jsonify({'success': True, 'options': [dict(o) for o in options]})


@bp.route('/api/dropdown-options/<category>', methods=['POST'])
@admin_required
@handle_api_errors
def api_add_dropdown_option(category):
    """Add a new dropdown option"""
    try:
        data = request.get_json()
        value = data.get('value', '').strip()

        if not value:
            return jsonify({'success': False, 'error': 'Value is required'}), 400

        # Use a single connection for the read+write to avoid "database is locked"
        # when a background job holds a write lock between two separate connections
        conn = get_db()
        try:
            result = conn.execute(
                "SELECT MAX(sort_order) as max_order FROM dropdown_options WHERE category = ?",
                (category,)
            ).fetchone()
            sort_order = (result['max_order'] or 0) + 1

            conn.execute(
                "INSERT INTO dropdown_options (category, value, sort_order) VALUES (?, ?, ?)",
                (category, value, sort_order)
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({'success': True, 'message': f'Added "{value}" to {category}'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Option already exists'}), 400


@bp.route('/api/dropdown-options/<int:option_id>', methods=['DELETE'])
@admin_required
@handle_api_errors
def api_delete_dropdown_option(option_id):
    """Delete a dropdown option"""
    execute("DELETE FROM dropdown_options WHERE id = ?", (option_id,))
    return jsonify({'success': True})


# =============================================================================
# BACKUP / RESTORE API
# =============================================================================

def _prune_old_backups(backup_dir, keep):
    """Delete oldest `roms_backup_*.db` files past `keep`. `pre_restore_*`
    backups are intentionally never pruned — they are safety nets a user
    explicitly relies on to recover a bad restore."""
    if keep <= 0:
        return
    candidates = []
    for filename in os.listdir(backup_dir):
        if filename.startswith('roms_backup_') and filename.endswith('.db'):
            path = os.path.join(backup_dir, filename)
            try:
                candidates.append((os.path.getmtime(path), path))
            except OSError:
                continue
    candidates.sort()
    for _, path in candidates[:-keep]:
        try:
            os.remove(path)
            logger.info(f"Pruned old backup: {os.path.basename(path)}")
        except OSError as e:
            logger.warning(f"Could not prune backup {path}: {e}")


@bp.route('/api/backup', methods=['POST'])
@admin_required
def api_backup():
    """Create a database backup"""
    try:
        # Create backups directory
        backup_dir = os.path.join(os.path.dirname(config.DB_PATH), 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"roms_backup_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)

        # SQLite online backup API — safe under WAL with concurrent writers,
        # post-write integrity check raises if the snapshot is corrupt.
        backup_database(config.DB_PATH, backup_path)

        # Get backup size
        backup_size = format_size(os.path.getsize(backup_path))

        _prune_old_backups(backup_dir, getattr(config, 'MAX_BACKUPS', 30))

        logger.info(f"Created backup: {backup_filename}")
        return jsonify({
            'success': True,
            'message': f'Backup created: {backup_filename}',
            'filename': backup_filename,
            'size': backup_size
        })
    except Exception as e:
        logger.error(f"Backup error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/backups', methods=['GET'])
@admin_required
def api_list_backups():
    """List available backups"""
    try:
        backup_dir = os.path.join(os.path.dirname(config.DB_PATH), 'backups')
        if not os.path.exists(backup_dir):
            return jsonify({'success': True, 'backups': []})

        backups = []
        for filename in sorted(os.listdir(backup_dir), reverse=True):
            if filename.endswith('.db'):
                path = os.path.join(backup_dir, filename)
                backups.append({
                    'filename': filename,
                    'size': format_size(os.path.getsize(path)),
                    'date': datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                })

        return jsonify({'success': True, 'backups': backups})
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/restore/<filename>', methods=['POST'])
@admin_required
def api_restore(filename):
    """Restore database from backup"""
    try:
        if not safe_filename(filename):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400

        backup_dir = os.path.join(os.path.dirname(config.DB_PATH), 'backups')
        backup_path = os.path.join(backup_dir, filename)

        if not os.path.exists(backup_path):
            return jsonify({'success': False, 'error': 'Backup file not found'})

        # Create a backup of current db before restoring (online backup API
        # → consistent snapshot of the live, possibly-being-written DB).
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pre_restore_backup = os.path.join(backup_dir, f"pre_restore_{timestamp}.db")
        backup_database(config.DB_PATH, pre_restore_backup)

        # Restore
        shutil.copy2(backup_path, config.DB_PATH)

        logger.info(f"Restored database from: {filename}")
        return jsonify({
            'success': True,
            'message': f'Database restored from {filename}',
            'restart_required': True
        })
    except Exception as e:
        logger.error(f"Restore error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


# =============================================================================
# SETTINGS API
# =============================================================================

@bp.route('/api/settings/paths', methods=['GET'])
@admin_required
def api_get_paths():
    """Get current path settings"""
    user_settings = settings_manager.load_settings()
    return jsonify({
        'success': True,
        'paths': {
            'rom_path': get_rom_path(),
            'esde_gamelists': get_esde_gamelists_path(),
            'esde_media': get_esde_media_path(),
            'rpcs3_trophy': get_rpcs3_trophy_path()
        },
        'user_overrides': {
            'rom_path': user_settings.get('rom_path', ''),
            'esde_gamelists_path': user_settings.get('esde_gamelists_path', ''),
            'esde_downloaded_media_path': user_settings.get('esde_downloaded_media_path', ''),
            'rpcs3_trophy_path': user_settings.get('rpcs3_trophy_path', '')
        }
    })


@bp.route('/api/settings/paths', methods=['POST'])
@admin_required
def api_update_paths():
    """Update path settings using settings_manager"""
    try:
        data = request.get_json()
        current_settings = settings_manager.load_settings()
        changed_keys = []

        # Update paths
        if 'rom_path' in data:
            current_settings['rom_path'] = data['rom_path']
            changed_keys.append('rom_path')
        if 'esde_gamelists' in data:
            current_settings['esde_gamelists_path'] = data['esde_gamelists']
            changed_keys.append('esde_gamelists_path')
        if 'esde_media' in data:
            current_settings['esde_downloaded_media_path'] = data['esde_media']
            changed_keys.append('esde_downloaded_media_path')
        if 'rpcs3_trophy' in data:
            current_settings['rpcs3_trophy_path'] = data['rpcs3_trophy']
            changed_keys.append('rpcs3_trophy_path')

        # Save settings
        if settings_manager.save_settings(current_settings):
            # Update app config
            current_app.config['ROM_PATH'] = get_rom_path()
            current_app.config['RPCS3_TROPHY_PATH'] = get_rpcs3_trophy_path()

            restart_needed = settings_manager.requires_restart(changed_keys)

            return jsonify({
                'success': True,
                'message': 'Settings saved to settings.json',
                'restart_required': restart_needed
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save settings'})

    except Exception as e:
        logger.error(f"Settings update error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/settings', methods=['GET'])
@admin_required
def api_get_all_settings():
    """Get all user settings"""
    try:
        user_settings = settings_manager.load_settings()
        return jsonify({
            'success': True,
            'settings': user_settings,
            'defaults': settings_manager.DEFAULT_SETTINGS
        })
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/settings', methods=['POST'])
@admin_required
def api_update_all_settings():
    """Update multiple settings at once"""
    try:
        data = request.get_json()
        current_settings = settings_manager.load_settings()
        changed_keys = []

        for key, value in data.items():
            if key in settings_manager.DEFAULT_SETTINGS:
                if current_settings.get(key) != value:
                    changed_keys.append(key)
                current_settings[key] = value

        if settings_manager.save_settings(current_settings):
            restart_needed = settings_manager.requires_restart(changed_keys)
            return jsonify({
                'success': True,
                'message': 'Settings saved',
                'restart_required': restart_needed,
                'changed': changed_keys
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save settings'})
    except Exception as e:
        logger.error(f"Settings update error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/settings/reset', methods=['POST'])
@admin_required
def api_reset_settings():
    """Reset all settings to defaults"""
    try:
        if settings_manager.reset_to_defaults():
            return jsonify({
                'success': True,
                'message': 'Settings reset to defaults',
                'restart_required': True
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to reset settings'})
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


# =============================================================================
# LOGGING API
# =============================================================================

@bp.route('/api/settings/logging', methods=['POST'])
@admin_required
def api_save_logging_settings():
    """Save logging settings"""
    try:
        data = request.get_json()

        # Get current settings
        settings = settings_manager.load_settings()

        # Update logging section
        settings['logging'] = data

        # Save settings
        if settings_manager.save_settings(settings):
            # Reinitialize logging with new settings
            log_manager.setup_all_logging()
            return jsonify({'success': True, 'message': 'Logging settings saved'})
        else:
            return jsonify({'success': False, 'error': 'Failed to save settings'})
    except Exception as e:
        logger.error(f"Error saving logging settings: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


# =============================================================================
# NORMALIZATION API
# =============================================================================

@bp.route('/api/normalize/preview/<field>')
@admin_required
@handle_api_errors
def api_normalize_preview(field):
    """Preview normalization suggestions for a field (genre or modes)"""
    if field not in ('genre', 'modes'):
        return jsonify({'success': False, 'error': 'Invalid field. Must be "genre" or "modes"'}), 400

    values = get_unique_values(field)

    # Get canonical options from dropdown_options table
    category = 'genre' if field == 'genre' else 'game_modes'
    canonical = query(
        "SELECT value FROM dropdown_options WHERE category = ? ORDER BY value COLLATE NOCASE",
        (category,)
    )
    canonical_options = [row['value'] for row in canonical]

    return jsonify({
        'success': True,
        'values': values,
        'canonical_options': canonical_options
    })


@bp.route('/api/normalize/apply', methods=['POST'])
@admin_required
@handle_api_errors
def api_normalize_apply():
    """Apply normalization mappings to game data and save custom rules"""
    data = request.get_json() or {}
    field = data.get('field')
    mappings = data.get('mappings', [])

    if field not in ('genre', 'modes'):
        return jsonify({'success': False, 'error': 'Invalid field. Must be "genre" or "modes"'}), 400

    if not mappings:
        return jsonify({'success': False, 'error': 'No mappings provided'}), 400

    result = apply_normalization(field, mappings)

    return jsonify({
        'success': True,
        'games_updated': result['games_updated'],
        'rules_saved': result['rules_saved']
    })
