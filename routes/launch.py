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
#   POST /api/games/<id>/player-settings/reset  the player's Reset to recommended
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
from services import player
from services.launch_resolver import launches_on_player, resolve_launch_context
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
    # active() runs a finished player session's hook before this launch
    # writes any settings (PASS-59-64 §4.5).
    running = launcher.active()

    # One player session at a time: they share the player's config folder,
    # so a second session's saves would land on the wrong game (§4.5).
    if launches_on_player(game_id):
        player_ids = {r['id'] for r in query("SELECT id FROM emulators WHERE is_player = 1")}
        busy = next((h for h in running if h.emulator_id in player_ids), None)
        if busy and busy.game_id != game_id:
            return error(_('The player is already running another game'), 409,
                         existing_token=busy.token)

    # 409 if same game already running and policy is reject
    policy = get_setting('launch_concurrent_same_game', 'reject')
    existing = None
    for h in running:
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
# The player's per-game settings
# -----------------------------------------------------------------------------

@bp.route('/api/games/<int:game_id>/player-settings/reset', methods=['POST'])
@login_required
@permission_required('edit')
@handle_api_errors
def api_player_settings_reset(game_id):
    """Reset to recommended (PASS-59-64 §4.5): forget the settings kept
    from the player's menu; the next launch writes fresh ones."""
    if not query("SELECT 1 FROM games WHERE id = ?", (game_id,), one=True):
        return error(_('Game not found'), 404)
    player.reset(game_id)
    return success(message=_('Player settings reset to recommended'))


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
