# =============================================================================
# RETRODB - Launch Blueprint
# =============================================================================
# Endpoints for spawning and managing emulator processes.
#
#   POST /api/game/<id>/launch       resolves + spawns
#   GET  /api/launch/<token>/status  poll
#   POST /api/launch/<token>/kill    SIGTERM/SIGKILL
#   GET  /api/launches/active        list of running tokens (for nav badge)
#   POST /api/launch/<token>/disk-next  RetroArch: insert the next .m3u disk
#
# Spec §Routes.
# =============================================================================

import logging

from flask import Blueprint
from flask_babel import gettext as _

from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required, has_permission, permission_required
from services.database import query
from services.launcher import get_launcher, LauncherError
from services.launcher.base import LaunchResolutionError
from services.launch_resolver import resolve_launch_context
from services.retroarch_command import (
    RETROARCH_COMMAND_PORT, RetroArchNotListening, next_disk,
)
from services.standalone_settings import apply_for_launch
from settings_manager import get_setting

logger = logging.getLogger(__name__)

bp = Blueprint('launch', __name__)


def _handle_to_dict(h):
    return {
        'token':        h.token,
        'pid':          h.pid,
        'game_id':      h.game_id,
        'emulator_id':  h.emulator_id,
        'started_at':   h.started_at,
    }


def _status_to_dict(s):
    return {
        'state':       s.state,
        'exit_code':   s.exit_code,
        'runtime_s':   s.runtime_s,
        'stderr_tail': s.stderr_tail,
    }


# -----------------------------------------------------------------------------
# Launch
# -----------------------------------------------------------------------------

@bp.route('/api/game/<int:game_id>/launch', methods=['POST'])
@login_required
@handle_api_errors
def api_launch_game(game_id):
    """Resolve emulator + ROM, spawn the process, return a token for polling.

    Permission read at request time (not import time) so admins can change
    launch_required_permission without restarting Flask.
    """
    required = get_setting('launch_required_permission', 'launch')
    if not has_permission(required):
        return error(_('This action requires the "%(perm)s" permission') % {'perm': required}, 403)

    launcher = get_launcher()

    # 409 if same game already running and policy is reject
    policy = get_setting('launch_concurrent_same_game', 'reject')
    existing = None
    for h in launcher.active():
        if h.game_id == game_id:
            existing = h
            break
    if existing and policy == 'reject':
        return error(_('This game is already running'), 409,
                     existing_token=existing.token)
    if existing and policy == 'kill_and_relaunch':
        try:
            launcher.kill(existing.token, timeout_s=5.0)
        except LauncherError as e:
            return error(_('failed to kill prior instance: %(err)s') % {'err': e}, 500)

    # Resolve
    try:
        ctx = resolve_launch_context(game_id)
    except LaunchResolutionError as e:
        return error(str(e), 422)

    # PASS-59-91 §4.6 — write the per-game settings file before the emulator
    # reads it. Never raises; a settings problem does not stop the launch.
    apply_for_launch(game_id)

    # Launch
    try:
        h = launcher.launch(ctx)
    except LauncherError as e:
        return error(str(e), 500)

    payload = _handle_to_dict(h)
    payload['argv'] = ctx.argv
    return success(payload), 202


# -----------------------------------------------------------------------------
# Status
# -----------------------------------------------------------------------------

@bp.route('/api/launch/<token>/status', methods=['GET'])
@login_required
@permission_required('view')
@handle_api_errors
def api_launch_status(token):
    try:
        st = get_launcher().status(token)
    except LauncherError as e:
        return error(str(e), 404)
    return success(_status_to_dict(st))


# -----------------------------------------------------------------------------
# Kill
# -----------------------------------------------------------------------------

@bp.route('/api/launch/<token>/kill', methods=['POST'])
@login_required
@permission_required('launch')
@handle_api_errors
def api_launch_kill(token):
    try:
        st = get_launcher().kill(token, timeout_s=5.0)
    except LauncherError as e:
        return error(str(e), 404)
    return success(_status_to_dict(st))


# -----------------------------------------------------------------------------
# Active list
# -----------------------------------------------------------------------------

def _game_info(h):
    """Title, and whether the run can swap disks: RetroArch given a .m3u."""
    row = query("""
        SELECT g.title, g.rom_path, e.is_retroarch
        FROM games g LEFT JOIN emulators e ON e.id = ?
        WHERE g.id = ?
    """, (h.emulator_id, h.game_id), one=True)
    if not row:
        return {'title': '', 'disk_swap': False}
    return {
        'title': row['title'] or '',
        'disk_swap': bool(row['is_retroarch'])
                     and (row['rom_path'] or '').lower().endswith('.m3u'),
    }


@bp.route('/api/launches/active', methods=['GET'])
@login_required
@permission_required('view')
@handle_api_errors
def api_launches_active():
    handles = get_launcher().active()
    return success(launches=[{**_handle_to_dict(h), **_game_info(h)} for h in handles])


# -----------------------------------------------------------------------------
# Next disk
# -----------------------------------------------------------------------------

@bp.route('/api/launch/<token>/disk-next', methods=['POST'])
@login_required
@permission_required('launch')
@handle_api_errors
def api_launch_disk_next(token):
    handle = next((h for h in get_launcher().active() if h.token == token), None)
    if handle is None:
        return error(_('That game is no longer running'), 404)
    if not _game_info(handle)['disk_swap']:
        return error(_('This game has no disk list to swap through'), 409)
    try:
        next_disk()
    except RetroArchNotListening:
        return error(_(
            'RetroArch is not accepting commands. In RetroArch, turn on '
            'Settings > Network > Network Commands (port %(port)s).',
            port=RETROARCH_COMMAND_PORT), 409)
    return success(message=_('Next disk inserted'))
