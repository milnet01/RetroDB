# =============================================================================
# RETRODB - Emulators Blueprint
# =============================================================================
# CRUD on the `emulators` table and the `system_emulators` mapping.
# Mirrors routes/controllers.py.  Admin-only mutations.
# =============================================================================

import logging

from flask import Blueprint, render_template, request
from flask_babel import gettext as _

from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required, admin_required, permission_required
from services.database import query, execute
from services.emulator_adapters import bios_status
from services.launch_resolver import _mapping_resolves, _resolve_binary
from services.launcher.base import LaunchResolutionError
from services.standalone_settings import settings_for
from settings_manager import get_setting

logger = logging.getLogger(__name__)

bp = Blueprint('emulators', __name__)


# -----------------------------------------------------------------------------
# Page route
# -----------------------------------------------------------------------------

@bp.route('/settings/emulators', methods=['GET'])
@login_required
@admin_required
def page_emulators_settings():
    from services import player_cores, player_install
    player_row = player_cores.player_row()
    return render_template(
        'settings_emulators.html',
        # PASS-59-139: Get RetroArch, where libretro builds it.
        retroarch_install_supported=bool(player_row) and player_install.host() is not None,
        retroarch_installed_version=(player_install.installed_version()
                                     if player_install.program() else None),
        # PASS-59-81 §4.5: the player's core panel, once its program is found.
        player_found=bool(player_row) and _listed(player_row),
        player_platform_supported=player_cores.buildbot_dir() is not None,
        player_core_downloads=get_setting('player_core_downloads', True),
        retroarch_binary=get_setting('retroarch_binary', ''),
        retroarch_cores_dir=get_setting('retroarch_cores_dir', ''),
        emulator_scan_paths=get_setting(
            'emulator_scan_paths',
            '/mnt/Emulators:~/Downloads:~/.local/bin:/opt'),
    )


# -----------------------------------------------------------------------------
# Read
# -----------------------------------------------------------------------------

@bp.route('/api/emulators', methods=['GET'])
@login_required
@handle_api_errors
def api_list_emulators():
    rows = query("SELECT * FROM emulators ORDER BY name")
    return success(emulators=[dict(r) for r in rows if _listed(r)])


def _listed(emu) -> bool:
    """Every row but the bundled player's while its program is not found:
    an entry for software the user cannot have yet only confuses
    (user, 2026-10-22)."""
    if not emu.get('is_player'):
        return True
    try:
        _resolve_binary(emu, None)
    except LaunchResolutionError:
        return False
    return True


@bp.route('/api/emulators/for-system/<int:system_id>', methods=['GET'])
@login_required
@handle_api_errors
def api_emulators_for_system(system_id):
    """Return the system's mapped emulators with default flagged.  Used by
    the per-game override <select> in the edit modal."""
    rows = query("""
        SELECT e.id, e.name, se.is_default, se.retroarch_core, se.extra_args
        FROM system_emulators se
        JOIN emulators e ON e.id = se.emulator_id
        WHERE se.system_id = ? AND e.enabled = 1
        ORDER BY se.is_default DESC, e.name
    """, (system_id,))
    return success(emulators=[dict(r) for r in rows])


# -----------------------------------------------------------------------------
# Create / Update / Delete (admin-only)
# -----------------------------------------------------------------------------

def _validate_emulator_payload(data, require_all=True):
    name = (data.get('name') or '').strip()
    binary_name = (data.get('binary_name') or '').strip()
    args_template = data.get('args_template') or ''
    if require_all and not (name and binary_name and args_template):
        return None, error(_('name, binary_name, args_template are required'), 400)
    return {
        'name':                 name or None,
        'binary_name':          binary_name or None,
        'binary_path_override': data.get('binary_path_override') or None,
        'args_template':        args_template or None,
        'is_retroarch':         int(bool(data.get('is_retroarch'))),
        'description':          data.get('description'),
        'enabled':              int(bool(data.get('enabled', True))),
    }, None


@bp.route('/api/emulators', methods=['POST'])
@login_required
@admin_required
@handle_api_errors
def api_create_emulator():
    fields, err = _validate_emulator_payload(request.get_json() or {}, require_all=True)
    if err:
        return err
    new_id = execute("""
        INSERT INTO emulators
        (name, binary_name, binary_path_override, args_template, is_retroarch,
         description, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
    """, (fields['name'], fields['binary_name'], fields['binary_path_override'],
          fields['args_template'], fields['is_retroarch'],
          fields['description'], fields['enabled']))
    return success(id=new_id), 201


@bp.route('/api/emulators/<int:emulator_id>', methods=['PUT'])
@login_required
@admin_required
@handle_api_errors
def api_update_emulator(emulator_id):
    fields, err = _validate_emulator_payload(request.get_json() or {}, require_all=False)
    if err:
        return err
    sets, args = [], []
    for k, v in fields.items():
        if v is None and k not in ('binary_path_override', 'description'):
            continue
        sets.append(f"{k} = ?")
        args.append(v)
    sets.append("updated_at = datetime('now')")
    if not sets:
        return error(_('nothing to update'), 400)
    args.append(emulator_id)
    execute(f"UPDATE emulators SET {', '.join(sets)} WHERE id = ?", tuple(args))
    return success()


@bp.route('/api/emulators/<int:emulator_id>', methods=['DELETE'])
@login_required
@admin_required
@handle_api_errors
def api_delete_emulator(emulator_id):
    # FK CASCADE on system_emulators handles the mapping; emulator_override_id
    # on games becomes orphaned (intentional — admin should reassign first).
    execute("DELETE FROM emulators WHERE id = ?", (emulator_id,))
    return success()


# -----------------------------------------------------------------------------
# system_emulators mapping (admin-only)
# -----------------------------------------------------------------------------

@bp.route('/api/system_emulators', methods=['GET'])
@login_required
@admin_required
@handle_api_errors
def api_list_system_emulators():
    """Every mapping with its system and emulator names, whether it resolves
    and its BIOS status (PASS-59-91 §4.3, §4.4)."""
    emulators = {e['id']: e for e in query("SELECT * FROM emulators")}
    rows = query("""
        SELECT se.*, s.name AS system_name, s.folder AS system_folder
        FROM system_emulators se
        JOIN systems s ON s.id = se.system_id
        ORDER BY s.name, se.is_default DESC, se.id
    """)
    mappings = []
    for r in rows:
        emu = emulators.get(r['emulator_id'])
        mappings.append(dict(
            r,
            emulator_name=emu['name'] if emu else None,
            resolves=_mapping_resolves(emu, r),
            bios=bios_status(emu, r),
            has_settings=bool(settings_for(emu['binary_name'] if emu else '')),
        ))
    return success(mappings=mappings)


@bp.route('/api/system_emulators', methods=['POST'])
@login_required
@admin_required
@handle_api_errors
def api_map_system_emulator():
    """Body: {system_id, emulator_id, is_default?, retroarch_core?, extra_args?}"""
    data = request.get_json() or {}
    system_id = data.get('system_id')
    emulator_id = data.get('emulator_id')
    if not (system_id and emulator_id):
        return error(_('system_id and emulator_id required'), 400)

    is_default = int(bool(data.get('is_default')))
    if is_default:
        execute("UPDATE system_emulators SET is_default = 0 WHERE system_id = ?",
                (system_id,))

    new_id = execute("""
        INSERT INTO system_emulators
        (system_id, emulator_id, is_default, retroarch_core, extra_args)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(system_id, emulator_id) DO UPDATE SET
          is_default = excluded.is_default,
          retroarch_core = excluded.retroarch_core,
          extra_args = excluded.extra_args
    """, (system_id, emulator_id, is_default,
          data.get('retroarch_core'), data.get('extra_args')))
    return success(id=new_id), 201


@bp.route('/api/system_emulators/<int:mapping_id>', methods=['DELETE'])
@login_required
@admin_required
@handle_api_errors
def api_delete_system_emulator(mapping_id):
    execute("DELETE FROM system_emulators WHERE id = ?", (mapping_id,))
    return success()


# -----------------------------------------------------------------------------
# Per-game settings for DuckStation, PCSX2 and RPCS3 (PASS-59-91 §4.6)
# -----------------------------------------------------------------------------

def _put_choices(emulator_id, scope, scope_id, *, allow_flags):
    """Apply a body of {setting: value | null}; an error response or None."""
    from services import standalone_settings
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        return error(_('Send at least one setting.'), 400)
    table = standalone_settings.table_for(emulator_id, scope, scope_id)
    for setting, value in data.items():
        spec = table.get(setting)
        if not spec:
            return error(_('RetroDB does not manage that setting for this emulator.'), 400)
        if 'flag' in spec and not allow_flags:
            return error(_('Fullscreen is set per system, in Settings > Emulators.'), 400)
        if value is not None and value not in standalone_settings.choice_keys(spec):
            return error(_('That value is not one of the choices.'), 400)
    for setting, value in data.items():
        standalone_settings.set_choice(emulator_id, scope, scope_id, setting, value)
    return None


@bp.route('/api/games/<int:game_id>/emulator-settings', methods=['GET'])
@login_required
@permission_required('view')
@handle_api_errors
def api_game_emulator_settings(game_id):
    from services import standalone_settings
    view = standalone_settings.game_view(game_id)
    if view is None:
        return error(_('Game not found'), 404)
    return success(view)


@bp.route('/api/games/<int:game_id>/emulator-settings', methods=['PUT'])
@login_required
@permission_required('edit')
@handle_api_errors
def api_put_game_emulator_settings(game_id):
    """Body {setting: value | null}; null removes the game's choice. A flag
    setting is an argv input, admin-only per system (PASS-59-64 §3.14)."""
    from services import standalone_settings
    view = standalone_settings.game_view(game_id)
    if view is None:
        return error(_('Game not found'), 404)
    if not view['emulator'] or not view['settings']:
        return error(_('RetroDB manages per-game settings for DuckStation, PCSX2 and RPCS3 only.'), 400)
    problem = _put_choices(view['emulator']['id'], 'game', game_id, allow_flags=False)
    return problem or success(standalone_settings.game_view(game_id))


@bp.route('/api/systems/<int:system_id>/emulator-settings/<int:emulator_id>', methods=['GET'])
@login_required
@permission_required('manage_settings')
@handle_api_errors
def api_system_emulator_settings(system_id, emulator_id):
    from services import standalone_settings
    view = standalone_settings.system_view(system_id, emulator_id)
    if view is None:
        return error(_('Emulator not found'), 404)
    return success(view)


@bp.route('/api/systems/<int:system_id>/emulator-settings/<int:emulator_id>', methods=['PUT'])
@login_required
@permission_required('manage_settings')
@handle_api_errors
def api_put_system_emulator_settings(system_id, emulator_id):
    from services import standalone_settings
    if standalone_settings.system_view(system_id, emulator_id) is None:
        return error(_('Emulator not found'), 404)
    problem = _put_choices(emulator_id, 'system', system_id, allow_flags=True)
    return problem or success(standalone_settings.system_view(system_id, emulator_id))
