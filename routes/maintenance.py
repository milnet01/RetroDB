# =============================================================================
# RETRODB - Maintenance Blueprint
# =============================================================================
# Handles ROM scanning, cleaning, bulk updates, and orphaned media management.
# =============================================================================

from flask import Blueprint, request, jsonify
import os
import sys
import time
import threading
import logging
from datetime import datetime, timezone

import config
from services.database import get_db, get_db_with_context, query, execute
from services.game_utils import find_image_file, reset_game_title_from_filename
from services.auth import admin_required, login_required
from services.security import safe_path

logger = logging.getLogger(__name__)

bp = Blueprint('maintenance', __name__)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def clean_title(filename):
    """Clean a filename to get a proper title"""
    name = os.path.splitext(filename)[0]
    tags = ['(USA)', '(Europe)', '(Japan)', '(World)', '(En)', '(Fr)', '(De)', '(Es)', '(It)',
            '(U)', '(E)', '(J)', '(W)', '[!]', '(Rev', '(v', '[b', '[h', '[a', '[o', '[p', '[t', '[f',
            '(Demo)', '(Proto)', '(Beta)', '(Sample)', '(Unl)', '(Hack)', '(PD)', '(Pirate)']
    for tag in tags:
        if tag in name:
            name = name.split(tag)[0]
    name = name.replace('_', ' ').replace('  ', ' ').strip()
    return name


def parse_systeminfo(system_path):
    """Parse ES-DE systeminfo.txt for supported extensions"""
    info_file = os.path.join(system_path, 'systeminfo.txt')
    extensions = set()

    if not os.path.exists(info_file):
        return extensions

    current_key = None

    with open(info_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()

            if not line:
                current_key = None
                continue

            if line.endswith(':'):
                current_key = line[:-1].strip().lower()
                continue

            if current_key == 'supported file extensions':
                for ext in line.split():
                    if ext.startswith('.'):
                        extensions.add(ext.lower())

    return extensions


def run_inline_scan():
    """Inline ROM scanning when scraper module not available"""
    new_games = 0

    with get_db_with_context() as conn:
        c = conn.cursor()

        rom_path = config.ROM_PATH

        # Load system name mappings
        for folder in sorted(os.listdir(rom_path)):
            system_path = os.path.join(rom_path, folder)

            if not os.path.isdir(system_path):
                continue

            # Get system name
            system_name = config.SYSTEM_NAME_MAP.get(folder, folder.replace('_', ' ').title())

            # Check for system logo (with multiple extensions)
            logo_dir = os.path.join(config.STATIC_PATH, 'images', 'systems')
            logo_filename, logo_path = find_image_file(logo_dir, folder)
            system_logo = logo_filename

            # Insert/update system
            c.execute("INSERT OR IGNORE INTO systems (name, folder, logo) VALUES (?, ?, ?)",
                      (system_name, folder, system_logo))
            c.execute("SELECT id FROM systems WHERE folder = ?", (folder,))
            row = c.fetchone()
            if not row:
                logger.warning(f"System not found for folder: {folder}")
                continue
            system_id = row[0]
            c.execute("UPDATE systems SET name = ?, logo = ? WHERE folder = ?",
                      (system_name, system_logo, folder))

            # Parse extensions from systeminfo.txt
            extensions = parse_systeminfo(system_path)

            if not extensions:
                continue

            # Scan ROMs
            for file in os.listdir(system_path):
                file_path = os.path.join(system_path, file)

                if not os.path.isfile(file_path):
                    continue

                ext = os.path.splitext(file)[1].lower()
                if ext not in extensions:
                    continue

                # Check if already exists
                c.execute("SELECT id FROM games WHERE rom_path = ?", (file_path,))
                if c.fetchone():
                    continue

                # Clean title
                title = clean_title(file)

                # Insert game
                c.execute("""
                    INSERT INTO games (system_id, title, rom_path, scraped, created_at)
                    VALUES (?, ?, ?, 0, ?)
                """, (system_id, title, file_path, datetime.now(timezone.utc).isoformat()))

                new_games += 1

    logger.info(f"ROM scan complete. Found {new_games} new games.")
    return new_games


def delete_game_images(games):
    """Delete image/media files for a list of games"""
    deleted = 0

    for game in games:
        boxart = game['boxart'] if game['boxart'] else None
        boxart_3d = game['boxart_3d'] if 'boxart_3d' in game.keys() and game['boxart_3d'] else None
        fanart = game['fanart'] if game['fanart'] else None
        screenshots = game['screenshots'] if game['screenshots'] else None
        video = game['video'] if 'video' in game.keys() and game['video'] else None
        manual = game['manual'] if 'manual' in game.keys() and game['manual'] else None

        # Delete boxart
        if boxart:
            if not boxart.startswith('/') and not boxart.startswith('images/'):
                boxart_path = os.path.join(config.IMAGE_PATH, 'boxart', boxart)
            else:
                boxart_path = os.path.join(config.STATIC_PATH, boxart.lstrip('/'))

            # Validate path is within static directory
            boxart_path = safe_path(boxart_path, config.STATIC_PATH)
            if not boxart_path:
                continue

            if os.path.exists(boxart_path):
                try:
                    os.remove(boxart_path)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete boxart {boxart_path}: {e}")

        # Delete boxart_3d
        if boxart_3d:
            if not boxart_3d.startswith('/') and not boxart_3d.startswith('images/'):
                boxart_3d_path = os.path.join(config.IMAGE_PATH, 'boxart_3d', boxart_3d)
            else:
                boxart_3d_path = os.path.join(config.STATIC_PATH, boxart_3d.lstrip('/'))

            # Validate path is within static directory
            boxart_3d_path = safe_path(boxart_3d_path, config.STATIC_PATH)
            if not boxart_3d_path:
                continue

            if os.path.exists(boxart_3d_path):
                try:
                    os.remove(boxart_3d_path)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete boxart_3d {boxart_3d_path}: {e}")

        # Delete fanart
        if fanart:
            if not fanart.startswith('/') and not fanart.startswith('images/'):
                fanart_path = os.path.join(config.IMAGE_PATH, 'fanart', fanart)
            else:
                fanart_path = os.path.join(config.STATIC_PATH, fanart.lstrip('/'))

            # Validate path is within static directory
            fanart_path = safe_path(fanart_path, config.STATIC_PATH)
            if not fanart_path:
                continue

            if os.path.exists(fanart_path):
                try:
                    os.remove(fanart_path)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete fanart {fanart_path}: {e}")

        # Delete screenshots
        if screenshots:
            for screenshot in screenshots.split(','):
                screenshot = screenshot.strip()
                if screenshot:
                    if not screenshot.startswith('/') and not screenshot.startswith('images/'):
                        ss_path = os.path.join(config.IMAGE_PATH, 'screenshots', screenshot)
                    else:
                        ss_path = os.path.join(config.STATIC_PATH, screenshot.lstrip('/'))

                    # Validate path is within static directory
                    ss_path = safe_path(ss_path, config.STATIC_PATH)
                    if not ss_path:
                        continue

                    if os.path.exists(ss_path):
                        try:
                            os.remove(ss_path)
                            deleted += 1
                        except Exception as e:
                            logger.warning(f"Could not delete screenshot {ss_path}: {e}")

        # Delete video
        if video:
            if not video.startswith('/') and not video.startswith('videos/'):
                video_path = os.path.join(config.STATIC_PATH, 'videos', video)
            else:
                video_path = os.path.join(config.STATIC_PATH, video.lstrip('/'))

            # Validate path is within static directory
            video_path = safe_path(video_path, config.STATIC_PATH)
            if not video_path:
                continue

            if os.path.exists(video_path):
                try:
                    os.remove(video_path)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete video {video_path}: {e}")

        # Delete manual
        if manual:
            if not manual.startswith('/') and not manual.startswith('images/'):
                manual_path = os.path.join(config.IMAGE_PATH, 'manuals', manual)
            else:
                manual_path = os.path.join(config.STATIC_PATH, manual.lstrip('/'))

            # Validate path is within static directory
            manual_path = safe_path(manual_path, config.STATIC_PATH)
            if not manual_path:
                continue

            if os.path.exists(manual_path):
                try:
                    os.remove(manual_path)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete manual {manual_path}: {e}")

    return deleted


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
def api_scan():
    """Scan ROM library"""
    try:
        from scraper.scan_roms import scan_roms
        new_games = scan_roms()
        return jsonify({
            'success': True,
            'new_games': new_games,
            'message': f'Found {new_games} new games'
        })
    except ImportError:
        # Fallback - run inline scan
        try:
            new_games = run_inline_scan()
            return jsonify({
                'success': True,
                'new_games': new_games,
                'message': f'Found {new_games} new games'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': 'An internal error occurred'
            }), 500
    except Exception as e:
        logger.error(f"Scan error: {e}")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@bp.route('/api/clean-missing-roms', methods=['POST'])
@admin_required
def api_clean_missing_roms():
    """Remove games from database whose ROM files no longer exist"""
    try:
        games = query("SELECT id, title, rom_path, system_id FROM games")
        removed = 0
        removed_games = []

        # Virtual path prefixes for imported games (no actual ROM files on disk)
        virtual_prefixes = ('clz_import/', 'steam_import/', 'xbox_import/', 'psn_import/')

        for game in games:
            rom_path = game['rom_path']

            # Skip imported games (placeholder paths, no actual ROM files)
            if rom_path and rom_path.startswith(virtual_prefixes):
                continue

            if rom_path and not os.path.exists(rom_path):
                # Clear foreign key references before deleting
                execute("UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 WHERE parent_game_id = ?", (game['id'],))
                execute("UPDATE psn_games SET linked_game_id = NULL WHERE linked_game_id = ?", (game['id'],))
                execute("DELETE FROM games WHERE id = ?", (game['id'],))
                removed += 1
                removed_games.append({
                    'id': game['id'],
                    'title': game['title'],
                    'path': rom_path
                })
                logger.info(f"Removed missing ROM: {game['title']} ({rom_path})")

        return jsonify({
            'success': True,
            'removed': removed,
            'removed_games': removed_games[:50],
            'message': f'Removed {removed} games with missing ROM files'
        })
    except Exception as e:
        logger.error(f"Clean missing ROMs error: {e}")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@bp.route('/api/clear-clz-imports', methods=['POST'])
@admin_required
def api_clear_clz_imports():
    """Remove all CLZ Import games from the database"""
    try:
        # Count first
        count_row = query("SELECT COUNT(*) as count FROM games WHERE rom_path LIKE 'clz_import/%'", one=True)
        count = count_row['count'] if count_row else 0

        if count == 0:
            return jsonify({
                'success': True,
                'removed': 0,
                'removed_games': [],
                'message': 'No CLZ Import games found'
            })

        # Get titles for the response (limit to 50)
        clz_games = query("SELECT id, title, rom_path FROM games WHERE rom_path LIKE 'clz_import/%' ORDER BY title LIMIT 50")
        removed_games = [{'id': g['id'], 'title': g['title'], 'path': g['rom_path']} for g in clz_games]

        # Clear foreign key references before deleting
        execute("UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 WHERE parent_game_id IN (SELECT id FROM games WHERE rom_path LIKE 'clz_import/%')")
        execute("UPDATE psn_games SET linked_game_id = NULL WHERE linked_game_id IN (SELECT id FROM games WHERE rom_path LIKE 'clz_import/%')")
        # Delete all CLZ imports
        execute("DELETE FROM games WHERE rom_path LIKE 'clz_import/%'")
        logger.info(f"Removed {count} CLZ Import games")

        return jsonify({
            'success': True,
            'removed': count,
            'removed_games': removed_games,
            'message': f'Removed {count} CLZ Import games'
        })
    except Exception as e:
        logger.error(f"Clear CLZ imports error: {e}")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@bp.route('/api/clear-scraped-data/preview', methods=['GET'])
@admin_required
def api_clear_scraped_data_preview():
    """Preview how many games would be affected by clear scraped data"""
    try:
        system_id = request.args.get('system_id')

        if system_id:
            result = query("SELECT COUNT(*) as count FROM games WHERE system_id = ? AND scraped = 1",
                          (system_id,), one=True)
        else:
            result = query("SELECT COUNT(*) as count FROM games WHERE scraped = 1", one=True)

        count = result['count'] if result else 0

        return jsonify({
            'success': True,
            'count': count
        })
    except Exception as e:
        logger.error(f"Clear scraped data preview error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/clear-scraped-data', methods=['POST'])
@admin_required
def api_clear_scraped_data():
    """Clear scraped metadata from games and reset titles to filename-derived values"""
    try:
        data = request.get_json() or {}
        system_id = data.get('system_id')
        delete_images = data.get('delete_images', False)

        clear_fields = [
            'description', 'genre', 'publisher', 'developer', 'release_date',
            'players', 'modes', 'esrb_rating', 'pegi_rating',
            'cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating',
            'grac_rating', 'classind_rating', 'region',
            'franchise', 'similar_games', 'playtime_estimate', 'controller_support',
            'save_type', 'critic_score', 'critic_score_count', 'user_score',
            'user_score_count', 'boxart', 'screenshots', 'fanart', 'video', 'manual'
        ]

        set_clause = ', '.join([f"{field} = NULL" for field in clear_fields])
        set_clause += ", scraped = 0, scrape_history = NULL"

        images_deleted = 0
        game_ids_to_reset = []

        if system_id:
            games = query("SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM games WHERE system_id = ?",
                         (system_id,))
            game_ids_to_reset = [g['id'] for g in games]

            if delete_images:
                images_deleted = delete_game_images(games)

            execute(f"UPDATE games SET {set_clause} WHERE system_id = ?", (system_id,))
            cleared = len(game_ids_to_reset)
        else:
            games = query("SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM games")
            game_ids_to_reset = [g['id'] for g in games]

            if delete_images:
                images_deleted = delete_game_images(games)

            execute(f"UPDATE games SET {set_clause}")
            cleared = len(game_ids_to_reset)

        if game_ids_to_reset:
            conn = get_db()
            for game_id in game_ids_to_reset:
                reset_game_title_from_filename(game_id, conn)
            conn.close()

        logger.info(f"Cleared scraped data from {cleared} games" +
                   (f", deleted {images_deleted} images" if delete_images else ""))

        return jsonify({
            'success': True,
            'cleared': cleared,
            'images_deleted': images_deleted if delete_images else 0
        })
    except Exception as e:
        logger.error(f"Clear scraped data error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/orphaned-media/preview', methods=['GET'])
@admin_required
def api_orphaned_media_preview():
    """Scan for orphaned media files (not linked to any game in database)"""
    try:
        game_ids = set()
        games = query("SELECT id, boxart, boxart_3d, screenshots, fanart, video, manual FROM games")

        referenced_files = set()
        for game in games:
            game_ids.add(game['id'])
            if game['boxart']:
                referenced_files.add(game['boxart'])
            if game['boxart_3d']:
                referenced_files.add(game['boxart_3d'])
            if game['fanart']:
                referenced_files.add(game['fanart'])
            if game['video']:
                referenced_files.add(game['video'])
            if game['manual']:
                referenced_files.add(game['manual'])
            if game['screenshots']:
                for ss in game['screenshots'].split(','):
                    ss = ss.strip()
                    if ss:
                        referenced_files.add(ss)

        orphaned = []
        total_size = 0

        media_dirs = [
            (os.path.join(config.IMAGE_PATH, 'boxart'), 'boxart'),
            (os.path.join(config.IMAGE_PATH, 'boxart_3d'), 'boxart_3d'),
            (os.path.join(config.IMAGE_PATH, 'screenshots'), 'screenshots'),
            (os.path.join(config.IMAGE_PATH, 'fanart'), 'fanart'),
            (os.path.join(config.STATIC_PATH, 'videos'), 'video'),
            (os.path.join(config.STATIC_PATH, 'manuals'), 'manual'),
        ]

        for dir_path, media_type in media_dirs:
            if not os.path.exists(dir_path):
                continue

            for filename in os.listdir(dir_path):
                filepath = os.path.join(dir_path, filename)
                if not os.path.isfile(filepath):
                    continue

                is_orphaned = True

                try:
                    file_prefix = filename.split('_')[0]
                    if file_prefix.isdigit():
                        game_id = int(file_prefix)
                        if game_id in game_ids:
                            is_orphaned = False
                except (ValueError, IndexError):
                    pass

                if is_orphaned:
                    rel_path = os.path.relpath(filepath, config.STATIC_PATH if 'static' in dir_path else os.path.dirname(config.IMAGE_PATH))
                    if filename in referenced_files or rel_path in referenced_files:
                        is_orphaned = False
                    for ref in referenced_files:
                        if filename in ref:
                            is_orphaned = False
                            break

                if is_orphaned:
                    size = os.path.getsize(filepath)
                    total_size += size
                    orphaned.append({
                        'path': filepath,
                        'filename': filename,
                        'type': media_type,
                        'size': size
                    })

        return jsonify({
            'success': True,
            'files': orphaned,
            'total_size_mb': total_size / (1024 * 1024)
        })
    except Exception as e:
        logger.error(f"Orphaned media preview error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/orphaned-media/clean', methods=['POST'])
@admin_required
def api_orphaned_media_clean():
    """Delete orphaned media files"""
    try:
        preview_response = api_orphaned_media_preview()
        preview_data = preview_response.get_json()

        if not preview_data.get('success'):
            return jsonify({'success': False, 'error': 'Failed to scan for orphaned files'})

        files = preview_data.get('files', [])

        deleted = 0
        errors = 0
        freed_size = 0

        for file_info in files:
            filepath = file_info['path']
            try:
                if os.path.exists(filepath):
                    freed_size += os.path.getsize(filepath)
                    os.remove(filepath)
                    deleted += 1
                    logger.info(f"Deleted orphaned file: {filepath}")
            except Exception as e:
                errors += 1
                logger.warning(f"Failed to delete orphaned file {filepath}: {e}")

        return jsonify({
            'success': True,
            'deleted': deleted,
            'errors': errors,
            'freed_mb': freed_size / (1024 * 1024)
        })
    except Exception as e:
        logger.error(f"Orphaned media clean error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/database/optimize', methods=['POST'])
@admin_required
def api_database_optimize():
    """Run VACUUM, ANALYZE, and PRAGMA optimize on the database"""
    try:
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

        return jsonify({
            'success': True,
            'message': 'Database optimized successfully',
            'size_before_mb': round(size_before / (1024 * 1024), 2),
            'size_after_mb': round(size_after / (1024 * 1024), 2),
            'duration_seconds': round(duration, 2)
        })
    except Exception as e:
        logger.error(f"Database optimize error: {e}")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


# =============================================================================
# IMAGE RESIZE / STANDARDIZATION
# =============================================================================

@bp.route('/api/maintenance/image-resize/start', methods=['POST'])
@admin_required
def api_image_resize_start():
    """Start bulk image standardization job."""
    try:
        from services.jobs import image_resize_job

        data = request.get_json(silent=True) or {}
        image_types = data.get('image_types', ['boxart', 'screenshots', 'boxart_3d', 'controllers'])

        result = image_resize_job.start(image_types=image_types)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Image resize start error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/maintenance/image-resize/status', methods=['GET'])
@login_required
def api_image_resize_status():
    """Poll image resize job status."""
    try:
        from services.jobs import image_resize_job
        status = image_resize_job.get_status()
        status['success'] = True
        return jsonify(status)
    except Exception as e:
        logger.error(f"Image resize status error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/maintenance/image-resize/cancel', methods=['POST'])
@admin_required
def api_image_resize_cancel():
    """Cancel running image resize job."""
    try:
        from services.jobs import image_resize_job
        result = image_resize_job.cancel()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Image resize cancel error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/restart', methods=['POST'])
@admin_required
def api_restart():
    """Restart server"""
    def restart():
        import time
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=restart).start()

    return jsonify({'success': True, 'message': 'Server restarting...'})
