# =============================================================================
# RETRODB - Controllers Blueprint
# =============================================================================
# Handles controller management - CRUD operations and system assignments.
# =============================================================================

from flask import Blueprint, request, jsonify
import logging

from services.database import query, execute
from services.auth import login_required, editor_required
from services.api_helpers import handle_api_errors

logger = logging.getLogger(__name__)

bp = Blueprint('controllers', __name__)

# =============================================================================
# SYSTEM DEFAULT CONTROLLER MAPPING
# =============================================================================

# System folder to default controller mapping
SYSTEM_DEFAULT_CONTROLLER = {
    # Nintendo Consoles
    'nes': 'NES Controller',
    'famicom': 'NES Controller',
    'fds': 'NES Controller',
    'snes': 'SNES Controller',
    'superfamicom': 'SNES Controller',
    'n64': 'Nintendo 64 Controller',
    'gamecube': 'GameCube Controller',
    'wii': 'Wii Remote',
    'wiiu': 'Wii U GamePad',
    'virtualboy': 'Virtual Boy Controller',

    # Nintendo Handhelds
    'gb': 'Game Boy',
    'gbc': 'Game Boy',
    'gba': 'Game Boy Advance',
    'nds': 'Nintendo DS',
    '3ds': 'Nintendo 3DS',
    'pokemini': 'Game Boy',

    # Sega Consoles
    'mastersystem': 'Sega Master System Controller',
    'sms': 'Sega Master System Controller',
    'sg-1000': 'Sega Master System Controller',
    'genesis': 'Sega Genesis 6-Button Controller',
    'megadrive': 'Sega Genesis 6-Button Controller',
    'segacd': 'Sega Genesis 6-Button Controller',
    '32x': 'Sega Genesis 6-Button Controller',
    'saturn': 'Sega Saturn Controller',
    'dreamcast': 'Sega Dreamcast Controller',

    # Sega Handhelds
    'gamegear': 'Sega Game Gear',
    'gg': 'Sega Game Gear',

    # Sony Consoles
    'psx': 'PlayStation DualShock',
    'ps2': 'PlayStation 2 DualShock 2',
    'ps3': 'PlayStation 3 Sixaxis/DualShock 3',

    # Sony Handhelds
    'psp': 'PlayStation Portable',
    'vita': 'PlayStation Vita',
    'psvita': 'PlayStation Vita',

    # Atari Consoles
    'atari2600': 'Atari 2600 Joystick',
    'atari5200': 'Atari 5200 Controller',
    'atari7800': 'Atari 7800 Joystick',
    'jaguar': 'Atari Jaguar Controller',
    'jaguarcd': 'Atari Jaguar Controller',

    # Atari Handhelds
    'lynx': 'Atari Lynx',
    'atarilynx': 'Atari Lynx',

    # NEC
    'tg16': 'TurboGrafx-16 Controller',
    'pcengine': 'TurboGrafx-16 Controller',
    'pcenginecd': 'TurboGrafx-16 Controller',
    'supergrafx': 'TurboGrafx-16 Controller',

    # SNK
    'neogeo': 'Neo Geo Controller',
    'neogeocd': 'Neo Geo Controller',
    'neogeocdjp': 'Neo Geo Controller',
    'ngp': 'Neo Geo Pocket',
    'ngpc': 'Neo Geo Pocket',

    # Other Consoles
    '3do': '3DO Controller',
    'colecovision': 'ColecoVision Controller',
    'coleco': 'ColecoVision Controller',
    'intellivision': 'Intellivision Controller',
    'vectrex': 'Vectrex Controller',

    # Bandai
    'wonderswan': 'WonderSwan',
    'wonderswancolor': 'WonderSwan',
    'wswan': 'WonderSwan',
    'wswanc': 'WonderSwan',

    # Computers - Default to Keyboard & Mouse
    'amiga': 'Keyboard & Mouse',
    'amiga600': 'Keyboard & Mouse',
    'amiga1200': 'Keyboard & Mouse',
    'amigacd32': 'Keyboard & Mouse',
    'amstradcpc': 'Keyboard & Mouse',
    'apple2': 'Keyboard & Mouse',
    'apple2gs': 'Keyboard & Mouse',
    'atari800': 'Keyboard & Mouse',
    'atarist': 'Keyboard & Mouse',
    'c64': 'Keyboard & Mouse',
    'c128': 'Keyboard & Mouse',
    'dos': 'Keyboard & Mouse',
    'pc': 'Keyboard & Mouse',
    'pc88': 'Keyboard & Mouse',
    'pc98': 'Keyboard & Mouse',
    'msx': 'Keyboard & Mouse',
    'msx2': 'Keyboard & Mouse',
    'scummvm': 'Keyboard & Mouse',
    'x68000': 'Keyboard & Mouse',
    'zxspectrum': 'Keyboard & Mouse',

    # Arcade
    'arcade': 'Arcade Stick (Generic)',
    'mame': 'Arcade Stick (Generic)',
    'fbneo': 'Arcade Stick (Generic)',
    'fba': 'Arcade Stick (Generic)',
    'naomi': 'Arcade Stick (Generic)',
    'atomiswave': 'Arcade Stick (Generic)',
    'cps1': 'Arcade Stick (Generic)',
    'cps2': 'Arcade Stick (Generic)',
    'cps3': 'Arcade Stick (Generic)',
}

# =============================================================================
# CONTROLLERS API
# =============================================================================

@bp.route('/api/controllers')
@login_required
@handle_api_errors
def api_get_all_controllers():
    """Get all controllers from the global library, sorted alphabetically"""
    # Get all controllers
    controllers = query("""
        SELECT c.id, c.name, c.manufacturer, c.release_year, c.description,
               c.button_layout, c.image, c.sort_order
        FROM controllers c
        ORDER BY c.manufacturer COLLATE NOCASE, c.name COLLATE NOCASE
    """)

    # For each controller, get all associated systems
    result = []
    for c in controllers:
        ctrl = dict(c)

        # Get systems from junction table
        systems = query("""
            SELECT s.id, s.name
            FROM systems s
            JOIN system_controllers sc ON s.id = sc.system_id
            WHERE sc.controller_id = ?
            ORDER BY s.name COLLATE NOCASE
        """, (ctrl['id'],))

        ctrl['system_ids'] = [s['id'] for s in systems]
        ctrl['system_names'] = [s['name'] for s in systems]
        ctrl['system_name'] = ', '.join(ctrl['system_names']) if ctrl['system_names'] else None

        result.append(ctrl)

    return jsonify({'success': True, 'controllers': result})


@bp.route('/api/controllers/by-system/<int:system_id>')
@login_required
@handle_api_errors
def api_get_controllers_for_system(system_id):
    """Get controllers compatible with a specific system"""
    # First check if there are system-specific controller mappings
    controllers = query("""
        SELECT c.id, c.name, c.manufacturer, c.release_year, c.description,
               c.button_layout, c.image, c.sort_order
        FROM controllers c
        JOIN system_controllers sc ON c.id = sc.controller_id
        WHERE sc.system_id = ?
        ORDER BY c.manufacturer COLLATE NOCASE, c.name COLLATE NOCASE
    """, (system_id,))

    # If no specific mappings, return all controllers
    if not controllers:
        controllers = query("""
            SELECT id, name, manufacturer, release_year, description,
                   button_layout, image, sort_order
            FROM controllers
            ORDER BY manufacturer COLLATE NOCASE, name COLLATE NOCASE
        """)

    return jsonify({'success': True, 'controllers': [dict(c) for c in controllers]})


@bp.route('/api/controllers', methods=['POST'])
@editor_required
@handle_api_errors
def api_add_controller():
    """Add a new controller to the global library"""
    data = request.get_json()
    name = data.get('name', '').strip()
    # Support both single system_id and multiple system_ids
    system_ids = data.get('system_ids', [])
    if not system_ids and data.get('system_id'):
        system_ids = [data.get('system_id')]
    manufacturer = data.get('manufacturer', '').strip() or 'Other'
    release_year = data.get('release_year')
    description = data.get('description', '').strip()
    button_layout = data.get('button_layout', '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'Controller name is required'}), 400

    # Check for duplicates
    existing = query("SELECT id FROM controllers WHERE name = ?", (name,), one=True)
    if existing:
        return jsonify({'success': False, 'error': f'Controller "{name}" already exists'}), 400

    # Get max sort order
    result = query("SELECT MAX(sort_order) as max_order FROM controllers", one=True)
    sort_order = (result['max_order'] or 0) + 1

    # Insert controller (without system_id - we use junction table now)
    controller_id = execute("""
        INSERT INTO controllers (name, manufacturer, release_year, description, button_layout, sort_order)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, manufacturer, release_year, description, button_layout, sort_order))

    # Add system associations to junction table
    for sys_id in system_ids:
        if sys_id:
            try:
                execute("""
                    INSERT OR IGNORE INTO system_controllers (system_id, controller_id)
                    VALUES (?, ?)
                """, (int(sys_id), controller_id))
            except Exception as e:
                logger.warning(f"Could not add system {sys_id} to controller {controller_id}: {e}")

    return jsonify({'success': True, 'message': f'Added controller "{name}"', 'id': controller_id})


@bp.route('/api/controllers/<int:controller_id>', methods=['DELETE'])
@editor_required
@handle_api_errors
def api_delete_controller(controller_id):
    """Delete a controller"""
    # Clear any default_controller_id references first
    execute("UPDATE systems SET default_controller_id = NULL WHERE default_controller_id = ?", (controller_id,))
    # Remove from junction table
    execute("DELETE FROM system_controllers WHERE controller_id = ?", (controller_id,))
    # Delete the controller
    execute("DELETE FROM controllers WHERE id = ?", (controller_id,))
    return jsonify({'success': True})


@bp.route('/api/controllers/<int:controller_id>', methods=['PUT'])
@editor_required
@handle_api_errors
def api_update_controller(controller_id):
    """Update an existing controller"""
    data = request.get_json()
    name = data.get('name', '').strip()
    # Support both single system_id and multiple system_ids
    system_ids = data.get('system_ids', [])
    if not system_ids and data.get('system_id'):
        system_ids = [data.get('system_id')]
    manufacturer = data.get('manufacturer', '').strip() or 'Other'
    release_year = data.get('release_year')
    description = data.get('description', '').strip()
    button_layout = data.get('button_layout', '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'Controller name is required'}), 400

    # Check controller exists
    existing = query("SELECT id FROM controllers WHERE id = ?", (controller_id,), one=True)
    if not existing:
        return jsonify({'success': False, 'error': 'Controller not found'}), 404

    # Check for name conflicts with other controllers
    duplicate = query("SELECT id FROM controllers WHERE name = ? AND id != ?", (name, controller_id), one=True)
    if duplicate:
        return jsonify({'success': False, 'error': f'Another controller named "{name}" already exists'}), 400

    # Update controller (without system_id - we use junction table)
    execute("""
        UPDATE controllers
        SET name = ?, manufacturer = ?, release_year = ?, description = ?, button_layout = ?
        WHERE id = ?
    """, (name, manufacturer, release_year, description, button_layout, controller_id))

    # Update system associations - remove old ones and add new ones
    execute("DELETE FROM system_controllers WHERE controller_id = ?", (controller_id,))
    for sys_id in system_ids:
        if sys_id:
            try:
                execute("""
                    INSERT OR IGNORE INTO system_controllers (system_id, controller_id)
                    VALUES (?, ?)
                """, (int(sys_id), controller_id))
            except Exception as e:
                logger.warning(f"Could not add system {sys_id} to controller {controller_id}: {e}")

    return jsonify({'success': True, 'message': f'Updated controller "{name}"'})


@bp.route('/api/controllers/<int:controller_id>', methods=['GET'])
@login_required
@handle_api_errors
def api_get_controller(controller_id):
    """Get a single controller by ID"""
    controller = query("""
        SELECT c.id, c.name, c.manufacturer, c.release_year, c.description,
               c.button_layout, c.image, c.sort_order
        FROM controllers c
        WHERE c.id = ?
    """, (controller_id,), one=True)

    if not controller:
        return jsonify({'success': False, 'error': 'Controller not found'}), 404

    ctrl = dict(controller)

    # Get systems from junction table
    systems = query("""
        SELECT s.id, s.name
        FROM systems s
        JOIN system_controllers sc ON s.id = sc.system_id
        WHERE sc.controller_id = ?
        ORDER BY s.name COLLATE NOCASE
    """, (controller_id,))

    ctrl['system_ids'] = [s['id'] for s in systems]
    ctrl['system_names'] = [s['name'] for s in systems]
    ctrl['system_name'] = ', '.join(ctrl['system_names']) if ctrl['system_names'] else None

    return jsonify({
        'success': True,
        'controller': ctrl
    })


@bp.route('/api/systems/<int:system_id>/controllers')
@login_required
@handle_api_errors
def api_get_system_controllers(system_id):
    """Get controllers available for a system (associated + universal) and its default controllers"""
    # Get controllers that are either:
    # 1. Associated with this specific system via junction table
    # 2. Universal (not associated with any system)
    controllers = query("""
        SELECT DISTINCT c.id, c.name, c.manufacturer, c.release_year,
               CASE WHEN sc.controller_id IS NOT NULL THEN 1 ELSE 0 END as is_system_specific
        FROM controllers c
        LEFT JOIN system_controllers sc ON c.id = sc.controller_id AND sc.system_id = ?
        WHERE sc.controller_id IS NOT NULL
           OR c.id NOT IN (SELECT DISTINCT controller_id FROM system_controllers)
        ORDER BY c.manufacturer COLLATE NOCASE, c.name COLLATE NOCASE
    """, (system_id,))

    # Get the system's default controllers (can be multiple)
    default_controllers = query("""
        SELECT c.id, c.name, c.manufacturer
        FROM controllers c
        JOIN system_controllers sc ON c.id = sc.controller_id
        WHERE sc.system_id = ? AND sc.is_default = 1
        ORDER BY c.name COLLATE NOCASE
    """, (system_id,))

    # For backwards compatibility, also include legacy default_controller_id
    legacy_default = query("SELECT default_controller_id FROM systems WHERE id = ?", (system_id,), one=True)

    default_list = [{'id': c['id'], 'name': c['name'], 'manufacturer': c['manufacturer']} for c in default_controllers]

    # If no defaults in junction table but legacy default exists, include it
    if not default_list and legacy_default and legacy_default['default_controller_id']:
        ctrl = query("SELECT id, name, manufacturer FROM controllers WHERE id = ?",
                    (legacy_default['default_controller_id'],), one=True)
        if ctrl:
            default_list = [{'id': ctrl['id'], 'name': ctrl['name'], 'manufacturer': ctrl['manufacturer']}]

    return jsonify({
        'success': True,
        'controllers': [dict(c) for c in controllers],
        'default_controllers': default_list,
        # For backwards compatibility
        'default_controller': default_list[0] if default_list else None
    })


@bp.route('/api/systems/<int:system_id>/default-controllers', methods=['POST'])
@editor_required
@handle_api_errors
def api_set_system_default_controllers(system_id):
    """Set multiple default controllers for a system"""
    data = request.get_json()
    controller_ids = data.get('controller_ids', [])

    # Verify system exists
    system = query("SELECT id, name FROM systems WHERE id = ?", (system_id,), one=True)
    if not system:
        return jsonify({'success': False, 'error': 'System not found'}), 404

    # Clear existing defaults for this system
    execute("UPDATE system_controllers SET is_default = 0 WHERE system_id = ?", (system_id,))

    # Also clear legacy default_controller_id
    execute("UPDATE systems SET default_controller_id = NULL WHERE id = ?", (system_id,))

    # Set new defaults
    for controller_id in controller_ids:
        if controller_id:
            # First ensure the controller-system association exists
            existing = query("""
                SELECT id FROM system_controllers
                WHERE system_id = ? AND controller_id = ?
            """, (system_id, controller_id), one=True)

            if existing:
                execute("""
                    UPDATE system_controllers SET is_default = 1
                    WHERE system_id = ? AND controller_id = ?
                """, (system_id, controller_id))
            else:
                # Create the association with is_default = 1
                execute("""
                    INSERT INTO system_controllers (system_id, controller_id, is_default)
                    VALUES (?, ?, 1)
                """, (system_id, controller_id))

    return jsonify({'success': True, 'message': f'Set {len(controller_ids)} default controller(s)'})


@bp.route('/api/systems/<int:system_id>/default-controller', methods=['POST'])
@editor_required
@handle_api_errors
def api_set_system_default_controller(system_id):
    """Set the default controller for a system (legacy single-controller endpoint)"""
    data = request.get_json()
    controller_id = data.get('controller_id')

    # Verify system exists
    system = query("SELECT id, name FROM systems WHERE id = ?", (system_id,), one=True)
    if not system:
        return jsonify({'success': False, 'error': 'System not found'}), 404

    # Verify controller exists (if provided)
    if controller_id:
        controller = query("SELECT id, name FROM controllers WHERE id = ?", (controller_id,), one=True)
        if not controller:
            return jsonify({'success': False, 'error': 'Controller not found'}), 404

    # Clear existing defaults
    execute("UPDATE system_controllers SET is_default = 0 WHERE system_id = ?", (system_id,))
    execute("UPDATE systems SET default_controller_id = NULL WHERE id = ?", (system_id,))

    if controller_id:
        # Ensure association exists and set as default
        existing = query("""
            SELECT id FROM system_controllers
            WHERE system_id = ? AND controller_id = ?
        """, (system_id, controller_id), one=True)

        if existing:
            execute("""
                UPDATE system_controllers SET is_default = 1
                WHERE system_id = ? AND controller_id = ?
            """, (system_id, controller_id))
        else:
            execute("""
                INSERT INTO system_controllers (system_id, controller_id, is_default)
                VALUES (?, ?, 1)
            """, (system_id, controller_id))

    return jsonify({'success': True, 'message': 'Default controller updated'})


@bp.route('/api/systems/assign-default-controllers', methods=['POST'])
@editor_required
@handle_api_errors
def api_assign_default_controllers():
    """Auto-assign default controllers to systems based on manufacturer matching"""
    assigned = 0

    # Get all systems without a default controller
    systems = query("SELECT id, name, folder FROM systems WHERE default_controller_id IS NULL")

    # Controller name patterns to match to system folders
    controller_mappings = {
        # Nintendo
        'nes': ['NES Controller', 'Nintendo NES'],
        'snes': ['SNES Controller', 'Nintendo SNES'],
        'n64': ['N64 Controller', 'Nintendo 64'],
        'gc': ['GameCube Controller'],
        'gamecube': ['GameCube Controller'],
        'wii': ['Wii Remote', 'Wiimote'],
        'wiiu': ['Wii U GamePad'],
        'switch': ['Nintendo Switch Pro', 'Joy-Con'],
        'gb': ['Game Boy'],
        'gba': ['Game Boy Advance'],
        'gbc': ['Game Boy Color', 'Game Boy'],
        'nds': ['Nintendo DS'],
        '3ds': ['Nintendo 3DS'],
        'virtualboy': ['Virtual Boy Controller'],
        # Sega
        'genesis': ['Sega Genesis', 'Mega Drive', '6-Button'],
        'megadrive': ['Sega Genesis', 'Mega Drive', '6-Button'],
        'mastersystem': ['Sega Master System'],
        'sms': ['Sega Master System'],
        'saturn': ['Sega Saturn'],
        'dreamcast': ['Dreamcast Controller'],
        'dc': ['Dreamcast Controller'],
        'gamegear': ['Game Gear'],
        'segacd': ['Sega Genesis', 'Mega Drive'],
        'sega32x': ['Sega Genesis', 'Mega Drive'],
        # Sony
        'psx': ['PlayStation', 'DualShock', 'PS1'],
        'ps1': ['PlayStation', 'DualShock', 'PS1'],
        'ps2': ['DualShock 2', 'PlayStation 2'],
        'ps3': ['DualShock 3', 'SIXAXIS', 'PlayStation 3'],
        'psp': ['PSP'],
        'psvita': ['PS Vita'],
        # Atari
        'atari2600': ['Atari Joystick', 'Atari 2600'],
        'atari5200': ['Atari 5200'],
        'atari7800': ['Atari 7800', 'Atari Joystick'],
        'atarijaguar': ['Atari Jaguar'],
        'atarilynx': ['Atari Lynx'],
        # Other
        'turbografx16': ['TurboGrafx-16', 'PC Engine'],
        'pcengine': ['TurboGrafx-16', 'PC Engine'],
        'neogeo': ['Neo Geo', 'AES'],
        'neogeopocket': ['Neo Geo Pocket'],
        '3do': ['3DO Controller'],
        'colecovision': ['ColecoVision'],
        'intellivision': ['Intellivision'],
        'vectrex': ['Vectrex'],
        'wonderswan': ['WonderSwan'],
        'msx': ['MSX'],
        'xbox': ['Xbox Controller', 'Duke'],
        'xbox360': ['Xbox 360'],
    }

    for system in systems:
        folder_lower = system['folder'].lower().replace('-', '').replace('_', '').replace(' ', '')

        # Try to find a matching controller
        matched_controller = None
        for folder_pattern, controller_names in controller_mappings.items():
            if folder_pattern in folder_lower:
                # Search for any matching controller
                for ctrl_name in controller_names:
                    ctrl = query("""
                        SELECT id FROM controllers
                        WHERE name LIKE ?
                        ORDER BY id LIMIT 1
                    """, (f'%{ctrl_name}%',), one=True)
                    if ctrl:
                        matched_controller = ctrl['id']
                        break
                if matched_controller:
                    break

        if matched_controller:
            execute("UPDATE systems SET default_controller_id = ? WHERE id = ?",
                   (matched_controller, system['id']))
            assigned += 1

    return jsonify({'success': True, 'assigned': assigned})
