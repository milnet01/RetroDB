"""
ROM Tools Blueprint - Phase 4a Extraction
Handles ROM tools pages and API endpoints for archive scanning, CHD conversion,
CHD verification, and duplicate finding.
"""

from flask import Blueprint, render_template, request, jsonify, g
from datetime import datetime
import os
import json
import logging
import threading
import uuid
import subprocess
import shutil
import hashlib
import re
import glob
import tempfile

import config
import settings_manager
from services.atomic_io import atomic_write_json
from services.database import query
from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required, admin_required
from services.security import safe_path
from services.rom_tools_validators import (
    validate_rom_tools_value,
    known_rom_tools_keys,
)

logger = logging.getLogger(__name__)


def _get_rom_path():
    """Get effective ROM path from settings (overrides config.py default)"""
    return settings_manager.get_effective_path('rom_path', config.ROM_PATH)

# Create blueprint
tools_bp = Blueprint('tools', __name__)

# Task storage for ROM tools operations
_rom_tool_tasks = {}
_TASK_RETENTION_SECONDS = 1800  # 30 minutes


def _cleanup_completed_tasks():
    """Remove completed/failed/cancelled tasks older than 30 minutes."""
    now = datetime.now()
    to_remove = []
    for task_id, task in _rom_tool_tasks.items():
        status = task.get('status')
        if status in ('completed', 'failed', 'cancelled'):
            end_time = task.get('end_time')
            if end_time and (now - end_time).total_seconds() > _TASK_RETENTION_SECONDS:
                to_remove.append(task_id)
            elif not end_time:
                # No end_time recorded — stamp it now so it gets cleaned up next cycle
                task['end_time'] = now
    for task_id in to_remove:
        del _rom_tool_tasks[task_id]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def load_rom_tools_config():
    """Load ROM Tools configuration from JSON file"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'rom_tools_config.json')
    defaults = {
        'roms_path': _get_rom_path(),
        'output_path': '',
        'temp_path': os.path.join(tempfile.gettempdir(), 'retrodb_romtools'),
        'archive_types': ['.zip', '.7z', '.rar'],
        'recursive_scan': True,
        'verify_integrity': False,
        'generate_m3u': False,
        'remove_unwanted': False,
        'unwanted_patterns': ['.txt', '.nfo', '.diz', '.url', '.html', '.htm', '.sfv', '.png', '.jpg', '.jpeg', '.gif', '.scr'],
        'excluded_paths': [],
        'chdman_path': 'chdman',
        'chd_verify_after_convert': True,
        'chd_delete_originals': False,
        'chd_skip_existing': True,
        'duplicate_method': 'hash',
        'ignore_region_tags': True,
        'include_archives': False
    }
    
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                saved = json.load(f)
                defaults.update(saved)
    except Exception as e:
        logger.error(f"Error loading ROM tools config: {e}")
    
    return defaults


def save_rom_tools_config(settings):
    """Save ROM Tools configuration to JSON file"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'rom_tools_config.json')
    try:
        atomic_write_json(config_path, settings)
        return True
    except Exception as e:
        logger.error(f"Error saving ROM tools config: {e}")
        return False


def check_rom_tools_availability():
    """Check which external tools are available, with install instructions"""
    from platform_utils import get_tool_install_instructions, PLATFORM_NAME
    instructions = get_tool_install_instructions()
    tools = {
        'unzip': shutil.which('unzip') is not None,
        '7z': shutil.which('7z') is not None,
        'unrar': shutil.which('unrar') is not None or shutil.which('rar') is not None,
        'chdman': shutil.which('chdman') is not None
    }
    return {
        'tools': tools,
        'install_instructions': instructions,
        'platform': PLATFORM_NAME
    }


# =============================================================================
# PAGE ROUTES
# =============================================================================

@tools_bp.route('/tools/')
@login_required
def rom_tools_hub():
    """ROM Tools hub page listing all available tools"""
    tool_status = check_rom_tools_availability()
    return render_template('rom_tools_hub.html', tool_status=tool_status)


@tools_bp.route('/tools/archive-scanner')
@login_required
def archive_scanner():
    """Archive Scanner tool page"""
    return render_template('archive_scanner.html', rom_path=_get_rom_path())


@tools_bp.route('/tools/chd-converter')
@login_required
def chd_converter():
    """CHD Converter tool page"""
    return render_template('chd_converter.html', rom_path=_get_rom_path())


@tools_bp.route('/tools/chd-verify')
@login_required
def chd_verify():
    """CHD Verify tool page"""
    return render_template('chd_verify.html', rom_path=_get_rom_path())


@tools_bp.route('/tools/duplicate-finder')
@login_required
def duplicate_finder():
    """Duplicate Finder tool page"""
    return render_template('duplicate_finder.html', rom_path=_get_rom_path())


@tools_bp.route('/tools/multi-disc-organizer')
@login_required
def multi_disc_organizer():
    """Multi-Disc Organizer tool page"""
    disc_system_folders = [
        'psx', 'ps2', 'ps3', 'saturn', 'segacd', 'dreamcast', 
        '3do', 'pcenginecd', 'pcfx', 'neogeocd', 'gc', 'wii', 'wiiu'
    ]
    systems = query("""
        SELECT id, name, folder FROM systems 
        WHERE folder IN ({})
        ORDER BY name COLLATE NOCASE
    """.format(','.join(['?' for _ in disc_system_folders])), disc_system_folders)
    return render_template('multi_disc_organizer.html', systems=systems, rom_path=_get_rom_path())


@tools_bp.route('/tools/settings')
@login_required
def rom_tools_settings():
    """ROM Tools Settings page"""
    settings = load_rom_tools_config()
    tool_status = check_rom_tools_availability()
    return render_template('rom_tools_settings.html', settings=settings, tool_status=tool_status)


# =============================================================================
# ROM TOOLS API - SETTINGS AND STATUS
# =============================================================================

@tools_bp.route('/api/rom-tools/settings', methods=['GET', 'POST'])
@login_required
@handle_api_errors
def api_rom_tools_settings():
    """Get or update ROM Tools settings.

    Pass 40.1 — POST is admin-only and runs every key/value through
    validate_rom_tools_value().  The chdman_path field flows directly into
    subprocess.run() argv[0], so writing it without a per-key allowlist is
    a CWE-78 RCE primitive for any logged-in user.

    GET stays accessible to every logged-in user because the archive
    scanner page reads roms_path / excluded_paths / unwanted_patterns to
    populate its scan UI.
    """
    if request.method == 'GET':
        return jsonify(load_rom_tools_config())

    if not g.user or g.user.get('role') != 'admin':
        return error('Administrator privileges required', 403)

    incoming = request.get_json() or {}
    if not isinstance(incoming, dict):
        return error('Settings payload must be an object', 400)

    valid_keys = known_rom_tools_keys()
    current = load_rom_tools_config()
    for key, value in incoming.items():
        if key not in valid_keys:
            return error(f"Unknown setting key: {key}", 400)
        ok, reason, cleaned = validate_rom_tools_value(key, value)
        if not ok:
            return error(f"Invalid value for '{key}': {reason}", 400)
        current[key] = cleaned

    if save_rom_tools_config(current):
        return success()
    return error('Failed to save settings', 500)


@tools_bp.route('/api/rom-tools/status')
@login_required
def api_rom_tools_status():
    """Check status of external tools"""
    return jsonify(check_rom_tools_availability())


@tools_bp.route('/api/rom-tools/browse-folders', methods=['POST'])
@login_required
@handle_api_errors
def api_rom_tools_browse_folders():
    """Browse folders within the ROMs directory"""
    data = request.get_json() or {}
    base_path = _get_rom_path()
    current_path = data.get('path', base_path)

    # Security: Ensure path is within base_path
    try:
        current_real = os.path.realpath(current_path)
        base_real = os.path.realpath(base_path)

        if not current_real.startswith(base_real):
            current_path = base_path
            current_real = base_real
    except (OSError, ValueError):
        current_path = base_path
        current_real = os.path.realpath(base_path)

    if not os.path.exists(current_path):
        return error(f'Path does not exist: {current_path}', 400)

    parent_path = None
    if current_real != base_real:
        parent = os.path.dirname(current_path)
        if os.path.realpath(parent).startswith(base_real):
            parent_path = parent

    folders = []
    try:
        for item in sorted(os.listdir(current_path)):
            item_path = os.path.join(current_path, item)
            if os.path.isdir(item_path) and not item.startswith('.'):
                try:
                    file_count = len([f for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f))])
                    subfolder_count = len([f for f in os.listdir(item_path) if os.path.isdir(os.path.join(item_path, f))])
                except PermissionError:
                    file_count = 0
                    subfolder_count = 0

                folders.append({
                    'name': item,
                    'path': item_path,
                    'file_count': file_count,
                    'subfolder_count': subfolder_count
                })
    except PermissionError:
        return error('Permission denied', 403)

    return success(
        base_path=base_path,
        current_path=current_path,
        parent_path=parent_path,
        folders=folders,
        is_root=current_real == base_real,
    )


# =============================================================================
# ROM TOOLS API - TASK MANAGEMENT
# =============================================================================

@tools_bp.route('/api/rom-tools/task/<task_id>')
@login_required
def api_rom_tools_task_status(task_id):
    """Get status of a running task"""
    task = _rom_tool_tasks.get(task_id)
    if task:
        return jsonify(task)

    from scraper.rom_tools import get_task
    task_obj = get_task(task_id)
    if task_obj:
        return jsonify(task_obj.to_dict())

    return jsonify({'error': 'Task not found'}), 404


@tools_bp.route('/api/rom-tools/task/<task_id>/cancel', methods=['POST'])
@login_required
def api_rom_tools_task_cancel(task_id):
    """Cancel a running task"""
    task = _rom_tool_tasks.get(task_id)
    if task and task.get('status') == 'running':
        task['status'] = 'cancelled'
        return success()

    from scraper.rom_tools import cancel_task
    if cancel_task(task_id):
        return success()

    return error('Task not found or not running', 404)


@tools_bp.route('/api/rom-tools/task/<task_id>/pause', methods=['POST'])
@login_required
def api_rom_tools_task_pause(task_id):
    """Pause a running task"""
    from scraper.rom_tools import get_task, update_task
    
    task = _rom_tool_tasks.get(task_id)
    if task and task.get('status') == 'running':
        task['status'] = 'paused'
        return success()

    task_obj = get_task(task_id)
    if task_obj and task_obj.status == 'running':
        task_obj.status = 'paused'
        update_task(task_obj)
        return success()

    return error('Task not found or not running', 404)


@tools_bp.route('/api/rom-tools/task/<task_id>/resume', methods=['POST'])
@login_required
def api_rom_tools_task_resume(task_id):
    """Resume a paused task"""
    from scraper.rom_tools import get_task, update_task
    
    task = _rom_tool_tasks.get(task_id)
    if task and task.get('status') == 'paused':
        task['status'] = 'running'
        return success()

    task_obj = get_task(task_id)
    if task_obj and task_obj.status == 'paused':
        task_obj.status = 'running'
        update_task(task_obj)
        return success()

    return error('Task not found or not paused', 404)


# =============================================================================
# ROM TOOLS API - ARCHIVE SCANNER
# =============================================================================

@tools_bp.route('/api/rom-tools/archive-scanner/scan', methods=['POST'])
@login_required
@handle_api_errors
def api_archive_scanner_scan():
    """Start archive scanning for issues"""
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig, create_task, update_task
    
    data = request.get_json() or {}
    path = data.get('path', _get_rom_path())
    if safe_path(path, _get_rom_path()) is None:
        return error('Invalid scan path', 400)
    excluded_paths = data.get('excluded_paths', [])
    types = data.get('types', ['.zip', '.7z', '.rar'])
    modes = data.get('modes', {'corrupted': True, 'multiFile': True, 'unwanted': True})

    settings = load_rom_tools_config()
    unwanted_patterns = settings.get('unwanted_patterns', [])
    logger.info(f"Archive scanner using unwanted patterns: {unwanted_patterns}")

    task = create_task('archive_scan')
    task.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting scan of {path}")
    task.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Unwanted patterns: {unwanted_patterns}")
    update_task(task)
    
    def run_scan():
        rom_config = ROMToolsConfig()
        scanner = ArchiveScanner(rom_config)
        scanner.scan_for_issues(path, task, excluded_paths, types, modes, unwanted_patterns)
    
    thread = threading.Thread(target=run_scan)
    thread.daemon = True
    thread.start()
    
    return success(task_id=task.task_id)
    


@tools_bp.route('/api/rom-tools/archive-scanner/contents', methods=['POST'])
@login_required
@handle_api_errors
def api_archive_scanner_contents():
    """Get contents of an archive file"""
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    
    data = request.get_json() or {}
    path = data.get('path')

    if not path:
        return error('No path provided', 400)

    if safe_path(path, _get_rom_path()) is None:
        return error('Invalid path', 400)

    if not os.path.exists(path):
        return error('File not found', 404)

    rom_config = ROMToolsConfig()
    scanner = ArchiveScanner(rom_config)
    result = scanner.get_archive_contents_detailed(path)

    return jsonify(result)
    


@tools_bp.route('/api/rom-tools/archive-scanner/remove-files', methods=['POST'])
@admin_required
@handle_api_errors
def api_archive_scanner_remove_files():
    """Remove specific files from an archive"""
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    
    data = request.get_json() or {}
    archive_path = data.get('archive_path')
    files = data.get('files', [])

    if not archive_path:
        return error('No archive path provided', 400)

    if safe_path(archive_path, _get_rom_path()) is None:
        return error('Invalid archive path', 400)

    if not files:
        return error('No files to remove', 400)

    logger.info(f"Removing {len(files)} files from archive: {archive_path}")
    
    rom_config = ROMToolsConfig()
    scanner = ArchiveScanner(rom_config)
    result = scanner.remove_files_from_archive(archive_path, files)
    
    return jsonify(result)
    


@tools_bp.route('/api/rom-tools/archive-scanner/clean', methods=['POST'])
@admin_required
@handle_api_errors
def api_archive_scanner_clean():
    """Remove unwanted files from an archive"""
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    
    data = request.get_json() or {}
    path = data.get('path')

    if not path:
        return error('No path provided', 400)

    if safe_path(path, _get_rom_path()) is None:
        return error('Invalid path', 400)

    settings = load_rom_tools_config()
    unwanted_patterns = settings.get('unwanted_patterns', [])

    rom_config = ROMToolsConfig()
    scanner = ArchiveScanner(rom_config)
    result = scanner.clean_archive(path, unwanted_patterns)
    
    return jsonify(result)
    


@tools_bp.route('/api/rom-tools/archive-scanner/create-m3u', methods=['POST'])
@admin_required
@handle_api_errors
def api_archive_scanner_create_m3u():
    """Create M3U playlist for multi-file archive.

    Pass 40.3 — admin-only.  Previously @login_required, which let any
    logged-in user run unzip/7z/unrar on archives anywhere the Flask UID
    could read and shutil.move() the contents into staging_folder
    (request-controlled).  staging_folder is no longer accepted from the
    request body — the scanner uses its own server-side default.
    """
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig

    data = request.get_json() or {}
    path = data.get('path')
    move_to_staging = data.get('move_to_staging', True)

    if not path:
        return error('No path provided', 400)

    if safe_path(path, _get_rom_path()) is None:
        return error('Invalid path', 400)

    rom_config = ROMToolsConfig()
    scanner = ArchiveScanner(rom_config)
    # staging_folder intentionally omitted — scanner falls back to
    # tempfile.gettempdir()/retrodb_m3u_staging.
    result = scanner.create_m3u_playlist(path, move_to_staging=move_to_staging)

    return jsonify(result)



@tools_bp.route('/api/rom-tools/archive-scanner/batch-create-m3u', methods=['POST'])
@admin_required
@handle_api_errors
def api_archive_scanner_batch_create_m3u():
    """Create M3U playlists for multiple multi-file archives.

    Pass 40.3 — admin-only; every entry in paths[] is safe_path-validated
    before the scanner touches it; staging_folder is server-side only.
    """
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig

    data = request.get_json() or {}
    paths = data.get('paths', [])
    delete_archives = data.get('delete_archives', False)

    if not paths:
        return error('No paths provided', 400)

    rom_root = _get_rom_path()
    valid_paths = []
    for p in paths:
        if not isinstance(p, str) or safe_path(p, rom_root) is None:
            return error(f'Invalid path: {p}', 400)
        valid_paths.append(p)

    staging_folder = os.path.join(tempfile.gettempdir(), 'retrodb_m3u_staging')

    rom_config = ROMToolsConfig()
    scanner = ArchiveScanner(rom_config)
    result = scanner.batch_create_m3u(valid_paths, delete_archives, staging_folder)

    return jsonify(result)
    


# =============================================================================
# ROM TOOLS API - CHD CONVERTER
# =============================================================================

@tools_bp.route('/api/rom-tools/chd-converter/scan', methods=['POST'])
@login_required
@handle_api_errors
def api_chd_converter_scan():
    """Scan for convertible disc images"""
    data = request.get_json() or {}
    path = data.get('path', _get_rom_path())
    if safe_path(path, _get_rom_path()) is None:
        return error('Invalid scan path', 400)
    settings = load_rom_tools_config()

    extensions = ['.iso', '.cue', '.gdi', '.mds']
    files = []
    
    for ext in extensions:
        pattern = os.path.join(path, '**', f'*{ext}')
        files.extend(glob.glob(pattern, recursive=True))
    
    result = []
    for f in sorted(files):
        chd_path = os.path.splitext(f)[0] + '.chd'
        chd_exists = os.path.exists(chd_path)
        
        if chd_exists and settings.get('chd_skip_existing', True):
            continue
        
        result.append({
            'path': f,
            'name': os.path.basename(f),
            'size': os.path.getsize(f),
            'type': os.path.splitext(f)[1].upper()[1:],
            'chd_exists': chd_exists
        })
    
    return success(files=result)



@tools_bp.route('/api/rom-tools/chd-converter/convert', methods=['POST'])
@login_required
@handle_api_errors
def api_chd_converter_convert():
    """Start CHD conversion"""
    data = request.get_json() or {}
    files = data.get('files', [])
    settings = load_rom_tools_config()
    
    chdman_path = settings.get('chdman_path', 'chdman')
    if not shutil.which(chdman_path):
        return error('chdman not found. Please install MAME tools.', 400)
    
    _cleanup_completed_tasks()
    task_id = str(uuid.uuid4())[:8]
    task = {
        'task_id': task_id,
        'task_type': 'chd_convert',
        'status': 'running',
        'progress': 0,
        'total': len(files),
        'current_file': '',
        'percent': 0,
        'results': {
            'converted': 0, 'failed': 0, 'skipped': 0,
            'original_size': 0, 'compressed_size': 0, 'files': []
        },
        'logs': [f"[{datetime.now().strftime('%H:%M:%S')}] Starting conversion of {len(files)} files"]
    }
    _rom_tool_tasks[task_id] = task
    
    rom_root = _get_rom_path()

    def run_conversion():
        for i, file_path in enumerate(files):
            if task['status'] == 'cancelled':
                task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Conversion cancelled")
                break

            # Pass 40.2 — every file_path must resolve under rom_root.
            # api_chd_converter_scan validates the scan root, but the
            # client can hand back arbitrary paths in the convert POST,
            # which would otherwise feed straight into subprocess.run
            # (CHD work) and os.remove (when chd_delete_originals=True).
            if safe_path(file_path, rom_root) is None:
                task['results']['failed'] += 1
                task['logs'].append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Rejected (path outside ROM library): "
                    f"{os.path.basename(file_path)}"
                )
                task['progress'] = i + 1
                continue

            task['progress'] = i + 1
            task['current_file'] = os.path.basename(file_path)
            task['percent'] = round((i + 1) / len(files) * 100, 1) if files else 0

            src_size = os.path.getsize(file_path)
            dst_path = os.path.splitext(file_path)[0] + '.chd'
            tmp_path = dst_path + '.part'

            task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Converting: {os.path.basename(file_path)}")

            # Pass 40.11 — atomic write: chdman → .chd.part, optional verify,
            # then os.replace.  Mirrors CHDConverter._convert_file.  Without
            # this, a SIGKILL mid-conversion left a truncated .chd that
            # chd_skip_existing then treated as good on the next run.
            chd_succeeded = False
            try:
                # Clean up any stale tempfile from a previous failed run.
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

                cmd = [chdman_path, 'createcd', '-i', file_path, '-o', tmp_path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

                if result.returncode != 0 or not os.path.exists(tmp_path):
                    task['results']['failed'] += 1
                    task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Failed")
                else:
                    if settings.get('chd_verify_after_convert', True):
                        verify = subprocess.run(
                            [chdman_path, 'verify', '-i', tmp_path],
                            capture_output=True, text=True, timeout=600,
                        )
                        if verify.returncode != 0:
                            task['results']['failed'] += 1
                            task['logs'].append(
                                f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Verify failed"
                            )
                        else:
                            os.replace(tmp_path, dst_path)
                            chd_succeeded = True
                    else:
                        os.replace(tmp_path, dst_path)
                        chd_succeeded = True

                    if chd_succeeded:
                        dst_size = os.path.getsize(dst_path)
                        task['results']['converted'] += 1
                        task['results']['original_size'] += src_size
                        task['results']['compressed_size'] += dst_size
                        task['results']['files'].append({
                            'source': file_path, 'destination': dst_path,
                            'original_size': src_size, 'compressed_size': dst_size, 'status': 'success'
                        })
                        task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Converted")

                        if settings.get('chd_delete_originals', False):
                            os.remove(file_path)
            except Exception as e:
                task['results']['failed'] += 1
                logger.error(f"CHD conversion error for {file_path}: {e}")
                task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Error processing file")
            finally:
                if not chd_succeeded and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
        
        task['status'] = 'completed' if task['status'] != 'cancelled' else 'cancelled'
        task['end_time'] = datetime.now()
        if task['results']['original_size'] > 0:
            saved = task['results']['original_size'] - task['results']['compressed_size']
            task['results']['space_saved'] = saved
            task['results']['percent_saved'] = round((saved / task['results']['original_size']) * 100, 1)
        task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Conversion completed")
    
    thread = threading.Thread(target=run_conversion)
    thread.daemon = True
    thread.start()

    return success(task_id=task_id)
    


# =============================================================================
# ROM TOOLS API - CHD VERIFY
# =============================================================================

@tools_bp.route('/api/rom-tools/chd-verify/scan', methods=['POST'])
@login_required
@handle_api_errors
def api_chd_verify_scan():
    """Scan for CHD files"""
    data = request.get_json() or {}
    path = data.get('path', _get_rom_path())
    if safe_path(path, _get_rom_path()) is None:
        return error('Invalid scan path', 400)
    settings = load_rom_tools_config()

    recursive = settings.get('recursive_scan', True)
    pattern = os.path.join(path, '**', '*.chd') if recursive else os.path.join(path, '*.chd')
    files = glob.glob(pattern, recursive=recursive)
    
    result = [{'path': f, 'name': os.path.basename(f), 'size': os.path.getsize(f)} for f in sorted(files)]
    return success(files=result)
    


@tools_bp.route('/api/rom-tools/chd-verify/verify', methods=['POST'])
@login_required
@handle_api_errors
def api_chd_verify_verify():
    """Start CHD verification"""
    data = request.get_json() or {}
    files = data.get('files', [])
    settings = load_rom_tools_config()
    
    chdman_path = settings.get('chdman_path', 'chdman')
    if not shutil.which(chdman_path):
        return error('chdman not found', 400)
    
    _cleanup_completed_tasks()
    task_id = str(uuid.uuid4())[:8]
    task = {
        'task_id': task_id,
        'task_type': 'chd_verify',
        'status': 'running',
        'progress': 0,
        'total': len(files),
        'current_file': '',
        'percent': 0,
        'results': {'total': len(files), 'valid': 0, 'invalid': 0, 'total_size': 0, 'files': []},
        'logs': [f"[{datetime.now().strftime('%H:%M:%S')}] Starting verification"]
    }
    _rom_tool_tasks[task_id] = task
    
    rom_root = _get_rom_path()

    def run_verification():
        for i, file_path in enumerate(files):
            if task['status'] == 'cancelled':
                break

            # Pass 40.2 — reject paths outside rom_root before running
            # chdman verify on them.  Mirrors the convert endpoint guard.
            if safe_path(file_path, rom_root) is None:
                task['results']['invalid'] += 1
                task['logs'].append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Rejected (path outside ROM library): "
                    f"{os.path.basename(file_path)}"
                )
                task['progress'] = i + 1
                continue

            task['progress'] = i + 1
            task['current_file'] = os.path.basename(file_path)
            task['percent'] = round((i + 1) / len(files) * 100, 1) if files else 0

            file_size = os.path.getsize(file_path)
            task['results']['total_size'] += file_size
            task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Verifying: {os.path.basename(file_path)}")

            try:
                result = subprocess.run([chdman_path, 'verify', '-i', file_path],
                                      capture_output=True, text=True, timeout=600)
                
                if result.returncode == 0:
                    task['results']['valid'] += 1
                    task['results']['files'].append({
                        'path': file_path, 'name': os.path.basename(file_path),
                        'size': file_size, 'status': 'valid'
                    })
                    task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Valid")
                else:
                    task['results']['invalid'] += 1
                    task['results']['files'].append({
                        'path': file_path, 'name': os.path.basename(file_path),
                        'size': file_size, 'status': 'invalid'
                    })
                    task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Invalid")
            except Exception as e:
                task['results']['invalid'] += 1
                task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Error: {e}")

        task['status'] = 'completed' if task['status'] != 'cancelled' else 'cancelled'
        task['end_time'] = datetime.now()

    thread = threading.Thread(target=run_verification)
    thread.daemon = True
    thread.start()

    return success(task_id=task_id)
    


# =============================================================================
# ROM TOOLS API - DUPLICATE FINDER
# =============================================================================

@tools_bp.route('/api/rom-tools/duplicate-finder/scan', methods=['POST'])
@login_required
@handle_api_errors
def api_duplicate_finder_scan():
    """Start duplicate file scanning"""
    data = request.get_json() or {}
    path = data.get('path', _get_rom_path())
    if safe_path(path, _get_rom_path()) is None:
        return error('Invalid scan path', 400)
    settings = load_rom_tools_config()
    method = data.get('method', settings.get('duplicate_method', 'hash'))
    recursive = data.get('recursive', True)
    ignore_region = data.get('ignore_region', True)
    include_archives = data.get('include_archives', False)

    if not os.path.exists(path):
        return error(f'Path does not exist: {path}', 400)

    _cleanup_completed_tasks()
    task_id = str(uuid.uuid4())[:8]
    task = {
        'task_id': task_id,
        'task_type': 'duplicate_scan',
        'status': 'running',
        'progress': 0,
        'total': 0,
        'current_file': '',
        'current_action': 'Initializing...',
        'percent': 0,
        'results': {'files_scanned': 0, 'duplicate_groups': 0, 'duplicate_files': 0, 'wasted_space': 0, 'groups': []},
        'logs': [f"[{datetime.now().strftime('%H:%M:%S')}] Starting duplicate scan on {path}"],
        'method': method
    }
    _rom_tool_tasks[task_id] = task
    
    rom_logger = logging.getLogger('rom_tools')
    rom_logger.info(f"Duplicate scan started on {path} using method: {method}")
    
    def run_scan():
        rom_extensions = [
            '.iso', '.cue', '.bin', '.chd', '.gdi', '.cso', '.pbp', '.mdf', '.nrg',
            '.nes', '.fds', '.unf', '.sfc', '.smc', '.fig', '.swc', '.n64', '.z64', '.v64',
            '.nds', '.3ds', '.cia', '.gcm', '.gcz', '.wbfs', '.wad', '.wia', '.rvz',
            '.gb', '.gbc', '.gba', '.sgb', '.vb',
            '.md', '.smd', '.gen', '.32x', '.sms', '.gg', '.sg', '.sc',
            '.pbp', '.pkg',
            '.a26', '.a52', '.a78', '.lnx', '.jag', '.j64',
            '.pce', '.sgx', '.cdi', '.ngp', '.ngc', '.ws', '.wsc', '.vec',
            '.adf', '.adz', '.dms', '.ipf', '.d64', '.t64', '.tap', '.crt', '.prg',
            '.tzx', '.z80', '.sna', '.dsk', '.st', '.stx', '.msa',
            '.zip',
        ]
        
        if include_archives:
            rom_extensions.extend(['.7z', '.rar'])
        
        task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Scanning for files...")
        task['current_action'] = 'Scanning directory for files...'
        
        files = []
        extensions_lower = [ext.lower() for ext in rom_extensions]
        
        if recursive:
            for root, dirs, filenames in os.walk(path):
                for filename in filenames:
                    if any(filename.lower().endswith(ext) for ext in extensions_lower):
                        files.append(os.path.join(root, filename))
                task['current_action'] = f'Scanning: {os.path.basename(root)}'
        else:
            for filename in os.listdir(path):
                filepath = os.path.join(path, filename)
                if os.path.isfile(filepath) and any(filename.lower().endswith(ext) for ext in extensions_lower):
                    files.append(filepath)
        
        task['total'] = len(files)
        task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(files)} ROM files")
        
        if len(files) == 0:
            task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] No files found")
            task['status'] = 'completed'
            task['end_time'] = datetime.now()
            return
        
        region_tags = [r'\(USA\)', r'\(Europe\)', r'\(Japan\)', r'\(World\)', r'\(U\)', r'\(E\)', r'\(J\)', 
                      r'\(En\)', r'\(Fr\)', r'\(De\)', r'\(Es\)', r'\(It\)', r'\(Nl\)', r'\(Pt\)', r'\(Sv\)',
                      r'\(Ko\)', r'\(Zh\)', r'\(Tw\)', r'\[!\]', r'\[a\]', r'\[b\]', r'\[h\]', r'\[o\]', r'\[p\]', r'\[t\]']
        
        def normalize_name(name):
            n = name
            if ignore_region:
                for p in region_tags:
                    n = re.sub(p, '', n, flags=re.IGNORECASE)
            n = re.sub(r'\(Rev\s*\d+\)', '', n, flags=re.IGNORECASE)
            n = re.sub(r'\(v\d+\.?\d*\)', '', n, flags=re.IGNORECASE)
            return re.sub(r'\s+', ' ', n).strip().lower()
        
        def hash_file(fp):
            h = hashlib.sha256()
            try:
                with open(fp, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                return h.hexdigest()
            except OSError:
                return None
        
        groups = {}
        for i, f in enumerate(files):
            if task['status'] == 'cancelled':
                break
            
            task['progress'] = i + 1
            task['current_file'] = os.path.basename(f)
            task['percent'] = round((i + 1) / len(files) * 100, 1) if files else 0
            task['results']['files_scanned'] = i + 1
            
            if method == 'hash':
                task['current_action'] = f'Hashing: {os.path.basename(f)}'
            else:
                task['current_action'] = f'Comparing: {os.path.basename(f)}'
            
            try:
                stat_info = os.stat(f)
                info = {
                    'path': f, 
                    'name': os.path.basename(f), 
                    'size': stat_info.st_size, 
                    'modified': datetime.fromtimestamp(stat_info.st_mtime).isoformat()
                }
                
                if method == 'hash':
                    key = hash_file(f)
                    if key is None:
                        continue
                elif method == 'name':
                    key = normalize_name(os.path.splitext(os.path.basename(f))[0])
                else:
                    name_key = normalize_name(os.path.splitext(os.path.basename(f))[0])
                    hash_key = hash_file(f)
                    if hash_key is None:
                        continue
                    key = f"{name_key}|{hash_key}"
                
                if key not in groups:
                    groups[key] = []
                groups[key].append(info)
                
            except Exception as e:
                task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {os.path.basename(f)}: {e}")
        
        task['current_action'] = 'Analyzing duplicate groups...'
        
        dup_groups = []
        for key, gfiles in groups.items():
            if len(gfiles) > 1:
                gfiles.sort(key=lambda x: x['modified'], reverse=True)
                wasted = sum(f['size'] for f in gfiles[1:])
                dup_groups.append({
                    'key': key[:16] if len(key) > 16 else key, 
                    'name': min([f['name'] for f in gfiles], key=len), 
                    'count': len(gfiles), 
                    'wasted': wasted, 
                    'files': gfiles
                })
                task['results']['duplicate_files'] += len(gfiles) - 1
                task['results']['wasted_space'] += wasted
        
        task['results']['groups'] = dup_groups
        task['results']['duplicate_groups'] = len(dup_groups)
        task['status'] = 'completed' if task['status'] != 'cancelled' else 'cancelled'
        task['end_time'] = datetime.now()
        task['current_action'] = 'Scan complete'
        task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Scan complete: {len(dup_groups)} groups found")
    
    thread = threading.Thread(target=run_scan)
    thread.daemon = True
    thread.start()

    return success(task_id=task_id)



@tools_bp.route('/api/rom-tools/duplicate-finder/delete', methods=['POST'])
@admin_required
@handle_api_errors
def api_duplicate_finder_delete():
    """Delete specified duplicate files"""
    data = request.get_json() or {}
    files = data.get('files', [])

    results = {'deleted': 0, 'failed': 0, 'freed_space': 0, 'errors': []}

    for fp in files:
        if safe_path(fp, _get_rom_path()) is None:
            results['failed'] += 1
            results['errors'].append(f'Invalid path: {fp}')
            continue
        try:
            if os.path.exists(fp):
                size = os.path.getsize(fp)
                os.remove(fp)
                results['deleted'] += 1
                results['freed_space'] += size
            else:
                results['failed'] += 1
        except Exception as e:
            results['failed'] += 1
            logger.error(f"Error deleting duplicate file: {e}")
            results['errors'].append('An error occurred during processing')

    return success(results=results)



# =============================================================================
# ROM TOOLS API - SCREENSHOT DEDUPLICATION
# =============================================================================

def _dhash(filepath, hash_size=8):
    """Compute difference hash (dHash) of an image — same algorithm as scraper dedup."""
    try:
        from PIL import Image
        img = Image.open(filepath).convert('L').resize(
            (hash_size + 1, hash_size), Image.LANCZOS
        )
        try:
            pixels = list(img.getdata())
            diff = 0
            for row in range(hash_size):
                for col in range(hash_size):
                    offset = row * (hash_size + 1) + col
                    if pixels[offset] > pixels[offset + 1]:
                        diff |= 1 << (row * hash_size + col)
            return diff
        finally:
            img.close()
    except Exception:
        return None


def _visual_group(file_data, threshold):
    """Group files by visual similarity using average hash Hamming distance"""
    groups = []
    assigned = set()

    for i, fd_i in enumerate(file_data):
        if i in assigned:
            continue
        group = [fd_i]
        assigned.add(i)

        for j in range(i + 1, len(file_data)):
            if j in assigned:
                continue
            dist = bin(fd_i['hash'] ^ file_data[j]['hash']).count('1')
            if dist <= threshold:
                group.append(file_data[j])
                assigned.add(j)

        if len(group) > 1:
            groups.append(group)

    return groups


def _run_screenshot_dedup_scan(task, method, threshold):
    """Background task: scan games for duplicate screenshots"""
    screenshots_dir = os.path.join(config.STATIC_PATH, 'images', 'screenshots')

    games = query("""
        SELECT g.id, g.title, g.screenshots, s.name as system_name
        FROM games g
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE g.screenshots IS NOT NULL AND g.screenshots != ''
        ORDER BY g.title COLLATE NOCASE
    """)

    task['total'] = len(games)
    task['logs'].append(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(games)} games with screenshots")

    task['results'] = {
        'games_scanned': 0,
        'games_with_dupes': 0,
        'total_duplicates': 0,
        'space_reclaimable': 0,
        'groups': []
    }
    results = task['results']

    for i, game in enumerate(games):
        if task['status'] == 'cancelled':
            break

        task['progress'] = i + 1
        task['current_file'] = game['title']
        task['percent'] = round((i + 1) / len(games) * 100, 1)
        results['games_scanned'] = i + 1

        screenshots = [s.strip() for s in game['screenshots'].split(',') if s.strip()]
        if len(screenshots) < 2:
            continue

        # Compute hashes for each screenshot file
        file_data = []
        for ss in screenshots:
            filepath = os.path.join(screenshots_dir, ss)
            if not os.path.exists(filepath):
                continue
            try:
                size = os.path.getsize(filepath)
                if method == 'hash':
                    h = hashlib.md5()
                    with open(filepath, 'rb') as f:
                        for chunk in iter(lambda f=f: f.read(65536), b''):
                            h.update(chunk)
                    file_hash = h.hexdigest()
                else:
                    file_hash = _dhash(filepath)

                if file_hash is not None:
                    file_data.append({
                        'filename': ss,
                        'size': size,
                        'hash': file_hash
                    })
            except Exception:
                continue

        if len(file_data) < 2:
            continue

        # Group duplicates
        if method == 'hash':
            hash_groups = {}
            for fd in file_data:
                h = fd['hash']
                if h not in hash_groups:
                    hash_groups[h] = []
                hash_groups[h].append(fd)
            dup_sets = [g for g in hash_groups.values() if len(g) > 1]
        else:
            dup_sets = _visual_group(file_data, threshold)

        if dup_sets:
            total_dupes = sum(len(s) - 1 for s in dup_sets)
            space = sum(
                sum(f['size'] for f in s[1:])
                for s in dup_sets
            )
            results['games_with_dupes'] += 1
            results['total_duplicates'] += total_dupes
            results['space_reclaimable'] += space
            results['groups'].append({
                'game_id': game['id'],
                'game_title': game['title'],
                'system_name': game['system_name'] or 'Unknown',
                'duplicate_sets': [{'files': s} for s in dup_sets]
            })
            task['logs'].append(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"{game['title']}: {total_dupes} duplicate(s) in {len(dup_sets)} set(s)"
            )

    task['status'] = 'completed' if task['status'] != 'cancelled' else 'cancelled'
    task['end_time'] = datetime.now()
    task['current_file'] = ''
    task['logs'].append(
        f"[{datetime.now().strftime('%H:%M:%S')}] Scan complete: "
        f"{results['games_with_dupes']} games with duplicates, "
        f"{results['total_duplicates']} total duplicates"
    )


@tools_bp.route('/tools/screenshot-dedup')
@login_required
def screenshot_dedup():
    """Screenshot Deduplication tool page"""
    return render_template('screenshot_dedup.html')


@tools_bp.route('/api/rom-tools/screenshot-dedup/scan', methods=['POST'])
@login_required
@handle_api_errors
def api_screenshot_dedup_scan():
    """Start screenshot deduplication scan"""
    data = request.get_json() or {}
    method = data.get('method', 'hash')
    threshold = int(data.get('threshold', 10))

    _cleanup_completed_tasks()
    task_id = str(uuid.uuid4())[:8]
    task = {
        'task_id': task_id,
        'task_type': 'screenshot_dedup',
        'status': 'running',
        'progress': 0,
        'total': 0,
        'current_file': '',
        'percent': 0,
        'results': {
            'games_scanned': 0, 'games_with_dupes': 0,
            'total_duplicates': 0, 'space_reclaimable': 0, 'groups': []
        },
        'logs': [f"[{datetime.now().strftime('%H:%M:%S')}] Starting screenshot dedup scan (method={method})"]
    }
    _rom_tool_tasks[task_id] = task

    thread = threading.Thread(
        target=_run_screenshot_dedup_scan, args=(task, method, threshold)
    )
    thread.daemon = True
    thread.start()

    return success(task_id=task_id)



@tools_bp.route('/api/rom-tools/screenshot-dedup/delete', methods=['POST'])
@admin_required
@handle_api_errors
def api_screenshot_dedup_delete():
    """Delete duplicate screenshots and update database"""
    data = request.get_json() or {}
    deletions = data.get('deletions', [])  # [{game_id, filename}, ...]

    screenshots_dir = os.path.join(config.STATIC_PATH, 'images', 'screenshots')
    results = {'deleted': 0, 'failed': 0, 'freed_space': 0, 'db_updated': 0}

    # Group by game_id
    by_game = {}
    for d in deletions:
        gid = d.get('game_id')
        fn = d.get('filename', '')
        # Validate filename (no path traversal)
        if not fn or os.sep in fn or '/' in fn or '..' in fn:
            results['failed'] += 1
            continue
        if gid not in by_game:
            by_game[gid] = []
        by_game[gid].append(fn)

    from services.database import get_request_db
    db = get_request_db()

    for game_id, filenames in by_game.items():
        game = db.execute(
            "SELECT screenshots FROM games WHERE id = ?", [game_id]
        ).fetchone()
        if not game:
            results['failed'] += len(filenames)
            continue

        current = [s.strip() for s in (game['screenshots'] or '').split(',') if s.strip()]
        new_list = [s for s in current if s not in filenames]

        # Delete files from disk
        for fn in filenames:
            filepath = os.path.join(screenshots_dir, fn)
            try:
                if os.path.exists(filepath):
                    size = os.path.getsize(filepath)
                    os.remove(filepath)
                    results['deleted'] += 1
                    results['freed_space'] += size
                else:
                    results['deleted'] += 1  # File already gone
            except Exception as e:
                results['failed'] += 1
                logger.error(f"Error deleting screenshot {fn}: {e}")

        # Update DB
        db.execute(
            "UPDATE games SET screenshots = ? WHERE id = ?",
            [', '.join(new_list) if new_list else None, game_id]
        )
        results['db_updated'] += 1

    db.commit()
    return success(results=results)

