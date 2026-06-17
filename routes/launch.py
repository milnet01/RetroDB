# =============================================================================
# RETRODB - Launch Blueprint
# =============================================================================
# Endpoints for spawning and managing emulator processes.
#
#   POST /api/game/<id>/launch       resolves + spawns
#   GET  /api/launch/<token>/status  poll
#   POST /api/launch/<token>/kill    SIGTERM/SIGKILL
#   GET  /api/launches/active        list of running tokens (for nav badge)
#
# Spec §Routes.
# =============================================================================

import logging

from flask import Blueprint
from flask_babel import gettext as _

from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required, has_permission, permission_required
from services.launcher import get_launcher, LauncherError
from services.launcher.base import LaunchResolutionError
from services.launch_resolver import resolve_launch_context
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

@bp.route('/api/launches/active', methods=['GET'])
@login_required
@permission_required('view')
@handle_api_errors
def api_launches_active():
    handles = get_launcher().active()
    return success(launches=[_handle_to_dict(h) for h in handles])
