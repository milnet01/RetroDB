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
from services.auth import login_required, admin_required
from services.database import query, execute
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
    return render_template(
        'settings_emulators.html',
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
    return success(emulators=[dict(r) for r in rows])


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
