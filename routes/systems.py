# =============================================================================
# RETRODB - Systems Blueprint
# =============================================================================
# Handles system pages and system management APIs.
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
import os
import logging

import config
from services.database import get_db, query, execute, execute_many
from services.auth import login_required, admin_required
from services.game_utils import find_image_file, is_ra_supported, get_ra_supported_systems

logger = logging.getLogger(__name__)

bp = Blueprint('systems', __name__)

# =============================================================================
# SYSTEM TYPE MAPPING
# =============================================================================

# System type mapping based on folder names
SYSTEM_TYPE_MAP = {
    # Consoles
    'nes': 'Console', 'snes': 'Console', 'n64': 'Console', 'gc': 'Console', 'gamecube': 'Console', 'wii': 'Console', 'wiiu': 'Console',
    'switch': 'Console', 'genesis': 'Console', 'megadrive': 'Console', 'megadrivejp': 'Console',
    'mastersystem': 'Console', 'sms': 'Console', 'mark3': 'Console',
    'saturn': 'Console', 'saturnjp': 'Console', 'dreamcast': 'Console',
    'segacd': 'Console', 'megacd': 'Console', 'megacdjp': 'Console',
    'sega32x': 'Console', 'sega32xjp': 'Console', 'sega32xna': 'Console', '32x': 'Console', 'sg-1000': 'Console',
    'psx': 'Console', 'ps2': 'Console', 'ps3': 'Console', 'ps4': 'Console', 'ps5': 'Console',
    'xbox': 'Console', 'xbox360': 'Console', 'xboxone': 'Console', 'xboxseriesx': 'Console',
    'tg16': 'Console', 'tg-cd': 'Console', 'pcengine': 'Console', 'pcenginecd': 'Console', 'supergrafx': 'Console',
    'pcfx': 'Console',  # NEC PC-FX is a console, not a computer
    '3do': 'Console', 'jaguar': 'Console', 'jaguarcd': 'Console', 'colecovision': 'Console', 'coleco': 'Console',
    'intellivision': 'Console', 'channelf': 'Console', 'odyssey2': 'Console', 'videopac': 'Console', 'vectrex': 'Console',
    'atari2600': 'Console', 'atari5200': 'Console', 'atari7800': 'Console',
    'neogeo': 'Console', 'neogeocd': 'Console', 'neogeocdjp': 'Console',
    'fds': 'Console', 'famicom': 'Console', 'superfamicom': 'Console', 'sfc': 'Console',
    'satellaview': 'Console', 'sufami': 'Console',
    'virtualboy': 'Console', 'pokemini': 'Console', 'uzebox': 'Console',
    'supervision': 'Console', 'megaduck': 'Console',
    'astrocade': 'Console', 'astrocde': 'Console',  # Bally Astrocade (ES-DE uses astrocde)
    'cdimono1': 'Console', 'cdi': 'Console',  # Philips CD-i
    'cdtv': 'Console',  # Commodore CDTV
    'gx4000': 'Console',  # Amstrad GX4000
    'scv': 'Console',  # Epoch Super Cassette Vision
    'supracan': 'Console',  # Funtech Super A'Can
    'multivision': 'Console',  # Othello Multivision
    'pv1000': 'Console',  # Casio PV-1000
    'crvision': 'Console',  # VTech CreatiVision
    'vsmile': 'Console',  # VTech V.Smile
    'arcadia': 'Console',  # Emerson Arcadia 2001

    # Handhelds
    'gb': 'Handheld', 'gbc': 'Handheld', 'gba': 'Handheld', 'nds': 'Handheld', '3ds': 'Handheld', 'n3ds': 'Handheld',
    'psp': 'Handheld', 'vita': 'Handheld', 'psvita': 'Handheld',
    'gamegear': 'Handheld', 'gg': 'Handheld', 'ngp': 'Handheld', 'ngpc': 'Handheld',
    'lynx': 'Handheld', 'atarilynx': 'Handheld', 'wonderswan': 'Handheld', 'wonderswancolor': 'Handheld',
    'wswan': 'Handheld', 'wswanc': 'Handheld',
    'gw': 'Handheld', 'gameandwatch': 'Handheld',
    'gp32': 'Handheld', 'gp2x': 'Handheld',  # GamePark handhelds
    'gamate': 'Handheld',  # Bit Corporation Gamate
    'gmaster': 'Handheld',  # Hartung Game Master
    'gamecom': 'Handheld',  # Tiger Game.com
    'ngage': 'Handheld',  # Nokia N-Gage
    'arduboy': 'Handheld',  # Arduboy
    'lcdgames': 'Handheld',  # LCD handheld games
    'palm': 'Handheld',  # Palm OS
    'j2me': 'Handheld',  # Java ME mobile
    'symbian': 'Handheld',  # Symbian mobile
    'sgb': 'Handheld',  # Super Game Boy

    # Computers
    'amiga': 'Computer', 'amiga600': 'Computer', 'amiga1200': 'Computer', 'amigacd32': 'Computer',
    'amstradcpc': 'Computer', 'apple2': 'Computer', 'apple2gs': 'Computer',
    'atari800': 'Computer', 'atarist': 'Computer', 'atarixe': 'Computer',
    'c64': 'Computer', 'c128': 'Computer',
    'coco': 'Computer', 'dos': 'Computer', 'pc': 'Computer', 'pc88': 'Computer', 'pc98': 'Computer',
    'msx': 'Computer', 'msx1': 'Computer', 'msx2': 'Computer', 'msxturbor': 'Computer',
    'samcoupe': 'Computer', 'x68000': 'Computer', 'x1': 'Computer',
    'zxspectrum': 'Computer', 'spectrum': 'Computer', 'zx81': 'Computer', 'zxnext': 'Computer',
    'electron': 'Computer', 'bbcmicro': 'Computer', 'archimedes': 'Computer', 'atom': 'Computer',
    'dragon32': 'Computer', 'tanodragon': 'Computer',
    'ti99': 'Computer', 'trs-80': 'Computer', 'vic20': 'Computer',
    'sharp': 'Computer', 'fm7': 'Computer', 'fmtowns': 'Computer', 'adam': 'Computer',
    'pet': 'Computer', 'plus4': 'Computer', 'oric': 'Computer',
    'thomson': 'Computer', 'to8': 'Computer', 'mo5': 'Computer', 'moto': 'Computer',
    'macintosh': 'Computer', 'mac': 'Computer',
    'windows': 'Computer',  # Microsoft Windows
    'spectravideo': 'Computer',  # Spectravideo SV-3x8
    'zmachine': 'Computer',  # Z-Machine text adventures
    # Launchers/platforms (PC-based, not engines)
    'desktop': 'Computer', 'emulators': 'Computer', 'epic': 'Computer',
    'kodi': 'Computer', 'lutris': 'Computer', 'mess': 'Computer', 'steam': 'Computer',

    # Engines & Frameworks
    'ags': 'Engine',  # Adventure Game Studio
    'chailove': 'Engine',  # ChaiLove framework
    'doom': 'Engine',  # Doom engine
    'easyrpg': 'Engine',  # RPG Maker player
    'flash': 'Engine',  # Flash games
    'lowresnx': 'Engine',  # LowRes NX fantasy console
    'lutro': 'Engine',  # Lutro game framework
    'mugen': 'Engine',  # M.U.G.E.N. engine
    'openbor': 'Engine',  # OpenBOR engine
    'pico8': 'Engine',  # PICO-8 fantasy console
    'tic80': 'Engine',  # TIC-80 fantasy console
    'wasm4': 'Engine',  # WASM-4 fantasy console
    'ports': 'Engine',  # Source ports
    'quake': 'Engine',  # Quake engine
    'scummvm': 'Engine',  # ScummVM
    'solarus': 'Engine',  # Solarus engine
    'vircon32': 'Engine',  # Vircon32 virtual console

    # Arcade
    'arcade': 'Arcade', 'mame': 'Arcade', 'mame-advmame': 'Arcade', 'fbneo': 'Arcade', 'fba': 'Arcade',
    'naomi': 'Arcade', 'naomi2': 'Arcade', 'naomigd': 'Arcade', 'atomiswave': 'Arcade',
    'cps': 'Arcade', 'cps1': 'Arcade', 'cps2': 'Arcade', 'cps3': 'Arcade',
    'model1': 'Arcade', 'model2': 'Arcade', 'model3': 'Arcade',
    'sega': 'Arcade', 'segamodel': 'Arcade',
    'daphne': 'Arcade', 'laserdisc': 'Arcade',
    'neogeoaes': 'Arcade', 'consolearcade': 'Arcade',
    'stv': 'Arcade',  # Sega Titan Video
    'triforce': 'Arcade',  # Nintendo/Sega/Namco arcade
    'type-x': 'Arcade',  # Taito Type X
    'vpinball': 'Arcade',  # Virtual Pinball
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def update_system_types(cursor):
    """Auto-populate system types based on folder names"""
    cursor.execute("SELECT id, folder FROM systems WHERE system_type IS NULL OR system_type = ''")
    systems = cursor.fetchall()

    for system in systems:
        folder = system['folder'].lower()
        system_type = SYSTEM_TYPE_MAP.get(folder, None)

        # Try partial matching
        if not system_type:
            for key, stype in SYSTEM_TYPE_MAP.items():
                if key in folder or folder in key:
                    system_type = stype
                    break

        if system_type:
            cursor.execute("UPDATE systems SET system_type = ? WHERE id = ?",
                          (system_type, system['id']))
    # Note: caller is responsible for commit/close


# =============================================================================
# SYSTEM PAGES
# =============================================================================

@bp.route('/systems')
@login_required
def systems():
    """Systems listing page"""
    try:
        systems_list = query("""
            SELECT s.*,
                   COUNT(g.id) AS rom_count,
                   SUM(CASE WHEN g.scraped = 0 THEN 1 ELSE 0 END) AS missing_count
            FROM systems s
            LEFT JOIN games g ON s.id = g.system_id
            GROUP BY s.id
            HAVING rom_count > 0
            ORDER BY s.name COLLATE NOCASE
        """)

        # Build RA and trophy support info per system
        ra_systems = set(get_ra_supported_systems())
        local_trophy_folders = {'ps3'}  # Systems with local trophy support (RPCS3)

        system_features = {}
        for s in systems_list:
            folder = s['folder'].lower()
            system_features[s['id']] = {
                'ra_supported': folder in ra_systems,
                'local_trophies': folder in local_trophy_folders
            }

        return render_template('systems.html', systems=systems_list, system_specs=config.SYSTEM_SPECS,
                             system_features=system_features)
    except Exception as e:
        logger.error(f"Systems error: {e}")
        return f"Error loading systems: {e}", 500


@bp.route('/system/<int:system_id>')
@login_required
def system_games(system_id):
    """Games listing for a specific system — lightweight shell, data loaded via /api/games"""
    try:
        system = query("SELECT * FROM systems WHERE id = ?", (system_id,), one=True)
        if not system:
            flash("System not found", "error")
            return redirect(url_for('systems.systems'))

        counts = query("""
            SELECT
                COUNT(CASE WHEN (is_bonus_disc = 0 OR is_bonus_disc IS NULL) THEN 1 END) AS total_games,
                COUNT(CASE WHEN scraped = 0 AND (is_bonus_disc = 0 OR is_bonus_disc IS NULL) THEN 1 END) AS total_missing,
                COUNT(CASE WHEN is_bonus_disc = 1 THEN 1 END) AS bonus_count
            FROM games WHERE system_id = ?
        """, (system_id,), one=True)
        total_games = counts['total_games']
        total_missing = counts['total_missing']
        bonus_count = counts['bonus_count']

        # Check if system supports RetroAchievements
        ra_supported = is_ra_supported(system['folder'])

        # Get system-scoped filter options
        from routes.games import _get_filter_options
        filter_options = _get_filter_options(system_id=system_id)

        # Get available first letters for alphabet nav
        letter_rows = query("""
            SELECT DISTINCT UPPER(SUBSTR(COALESCE(sort_title, title), 1, 1)) AS letter
            FROM games
            WHERE system_id = ? AND (is_bonus_disc = 0 OR is_bonus_disc IS NULL)
        """, (system_id,))
        available_letters = [r['letter'] for r in letter_rows if r['letter']]

        return render_template('system_games.html',
                             system=system,
                             total_games=total_games,
                             total_missing=total_missing,
                             ra_supported=ra_supported,
                             bonus_count=bonus_count,
                             filter_options=filter_options,
                             available_letters=available_letters)
    except Exception as e:
        logger.error(f"System games error: {e}")
        return f"Error loading games: {e}", 500


# =============================================================================
# SYSTEM API ROUTES
# =============================================================================

@bp.route('/api/systems')
@login_required
def api_get_systems():
    """Get all systems for dropdowns"""
    try:
        systems = query("""
            SELECT id, name, folder, system_type
            FROM systems
            ORDER BY name COLLATE NOCASE
        """)
        return jsonify({
            'success': True,
            'systems': [dict(s) for s in systems]
        })
    except Exception as e:
        logger.error(f"Get systems error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


# DEPRECATED: This endpoint duplicates /api/systems (api_get_systems).
# Callers should migrate to /api/systems. Kept for backward compatibility.
@bp.route('/api/systems-list')
@login_required
def api_systems_list():
    """Get list of all systems for dropdown (deprecated — use /api/systems)"""
    try:
        systems = query("SELECT id, name, folder, system_type FROM systems ORDER BY name COLLATE NOCASE")
        return jsonify({'success': True, 'systems': [dict(s) for s in systems]})
    except Exception as e:
        logger.error(f"Error getting systems: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/update-system-type', methods=['POST'])
@admin_required
def api_update_system_type():
    """Update system type for a system"""
    try:
        data = request.get_json()
        system_id = data.get('system_id')
        system_type = data.get('system_type', '').strip()

        if not system_id:
            return jsonify({'success': False, 'error': 'System ID required'}), 400

        execute("UPDATE systems SET system_type = ? WHERE id = ?", (system_type, system_id))
        return jsonify({'success': True, 'message': f'System type updated to {system_type}'})
    except Exception as e:
        logger.error(f"Error updating system type: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/refresh-system-types', methods=['POST'])
@admin_required
def api_refresh_system_types():
    """Re-run system type auto-detection"""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Clear existing types and re-detect
        cursor.execute("UPDATE systems SET system_type = NULL")
        update_system_types(cursor)

        conn.commit()
        return jsonify({'success': True, 'message': 'System types refreshed'})
    except Exception as e:
        logger.error(f"Error refreshing system types: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500
    finally:
        if conn:
            conn.close()


@bp.route('/api/refresh-system-names', methods=['POST'])
@admin_required
def api_refresh_system_names():
    """Update system names from config mappings"""
    try:
        updated = 0
        systems = query("SELECT id, folder, name FROM systems")

        updates_list = []
        for system in systems:
            folder = system['folder']
            # Get mapped name from config
            mapped_name = config.SYSTEM_NAME_MAP.get(folder)

            if mapped_name and system['name'] != mapped_name:
                updates_list.append((mapped_name, system['id']))
                updated += 1
                logger.info(f"Updated name for {folder}: {system['name']} -> {mapped_name}")

        if updates_list:
            execute_many("UPDATE systems SET name = ? WHERE id = ?", updates_list)

        return jsonify({
            'success': True,
            'message': f'Updated {updated} system names',
            'updated': updated
        })
    except Exception as e:
        logger.error(f"Error refreshing system names: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/refresh-system-logos', methods=['POST'])
@admin_required
def api_refresh_system_logos():
    """Check for and update system logos that exist on disk"""
    try:
        updated = 0

        systems = query("SELECT id, folder, logo FROM systems")
        logo_dir = os.path.join(config.STATIC_PATH, 'images', 'systems')

        updates_list = []
        for system in systems:
            logo_filename, logo_path = find_image_file(logo_dir, system['folder'])

            if logo_filename:
                # Logo file exists - update database if not already set
                if system['logo'] != logo_filename:
                    updates_list.append((logo_filename, system['id']))
                    updated += 1
                    logger.info(f"Updated logo for {system['folder']}: {logo_filename}")

        if updates_list:
            execute_many("UPDATE systems SET logo = ? WHERE id = ?", updates_list)

        return jsonify({
            'success': True,
            'message': f'Updated {updated} system logos',
            'updated': updated
        })
    except Exception as e:
        logger.error(f"Error refreshing system logos: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/import-logos', methods=['POST'])
@admin_required
def api_import_logos():
    """Import system logos from ES-DE"""
    try:
        from scraper.scrape_esde import import_system_logos
        imported = import_system_logos()

        if imported > 0:
            # Update database to set logo paths
            conn = get_db()
            try:
                c = conn.cursor()

                # Get all systems and check for logo files (with multiple extensions)
                systems = query("SELECT id, folder FROM systems")
                logo_dir = os.path.join(config.IMAGE_PATH, 'systems')

                for system in systems:
                    logo_filename, logo_path = find_image_file(logo_dir, system['folder'])
                    if logo_filename:
                        c.execute("UPDATE systems SET logo = ? WHERE id = ?",
                                  (logo_filename, system['id']))

                conn.commit()
            finally:
                conn.close()

            return jsonify({
                'success': True,
                'imported': imported,
                'message': f'Imported {imported} system logos from ES-DE'
            })
        else:
            return jsonify({
                'success': True,
                'imported': 0,
                'message': 'No new logos found to import'
            })
    except ImportError:
        return jsonify({
            'success': False,
            'error': 'ES-DE scraper not available'
        }), 500
    except Exception as e:
        logger.error(f"Logo import error: {e}")
        return jsonify({
            'success': False,
            'error': 'An internal error occurred'
        }), 500


@bp.route('/api/calculate-storage', methods=['POST'])
@admin_required
def api_calculate_storage():
    """Calculate and update file sizes for all games"""
    try:
        games = query("SELECT id, rom_path FROM games WHERE file_size IS NULL OR file_size = 0")
        updated = 0

        for game in games:
            if game['rom_path'] and os.path.exists(game['rom_path']):
                try:
                    size = os.path.getsize(game['rom_path'])
                    execute("UPDATE games SET file_size = ? WHERE id = ?", (size, game['id']))
                    updated += 1
                except Exception as e:
                    logger.warning(f"Could not get size for {game['rom_path']}: {e}")

        return jsonify({
            'success': True,
            'updated': updated,
            'message': f'Updated file sizes for {updated} games'
        })
    except Exception as e:
        logger.error(f"Storage calculation error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})
