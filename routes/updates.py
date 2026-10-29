# =============================================================================
# RETRODB - Self-updater routes (PASS-59-169)
# =============================================================================
# Admin-only. The page code maps the `reason` codes to its own
# text, so these replies carry codes, not sentences.
#
#   GET  /api/updates/status     current + latest version, job, last result
#   POST /api/updates/check      ask GitHub now
#   POST /api/updates/download   download + verify the latest release
#   POST /api/updates/install    back up, hand over to the helper, restart
#   POST /api/updates/dismiss    forget the last install's outcome
#
# Contract: docs/specs/PASS-59-169-self-updater.md §6.
# =============================================================================

import config
from flask import Blueprint
from flask_babel import gettext as _

from services import updater
from services.api_helpers import error, handle_api_errors, success
from services.auth import admin_required

bp = Blueprint('updates', __name__)


@bp.route('/api/updates/status')
@admin_required
@handle_api_errors
def api_update_status():
    return success(**updater.status())


@bp.route('/api/updates/check', methods=['POST'])
@admin_required
@handle_api_errors
def api_update_check():
    updater.check(force=True)
    return success(**updater.status())


@bp.route('/api/updates/download', methods=['POST'])
@admin_required
@handle_api_errors
def api_update_download():
    st = updater.status()
    if not st['available']:
        return error(_('No newer version is available'), 409, reason='not_available')
    cached = updater.check()
    result = updater.job.start(cached['release'])
    if not result['success']:
        return error(_('This update cannot be installed here'), 409, reason=result['error'])
    return success(**updater.status())


@bp.route('/api/updates/install', methods=['POST'])
@admin_required
@handle_api_errors
def api_update_install():
    from server_port import resolve_server_port
    port = resolve_server_port(default=config.SERVER_PORT, use_saved=True)
    result = updater.install(port)
    if not result['success']:
        return error(_('This update cannot be installed here'), 409, reason=result['error'])
    return success()


@bp.route('/api/updates/dismiss', methods=['POST'])
@admin_required
@handle_api_errors
def api_update_dismiss():
    updater.dismiss_result()
    return success()
