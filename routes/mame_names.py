# =============================================================================
# RETRODB - MAME Names Blueprint (PASS-59-227)
# =============================================================================
# ROM Tools > MAME Names: the page and the job's controls. Admin only, because
# it reads files anywhere on the computer.
# =============================================================================

import os

from flask import Blueprint, jsonify, render_template, request
from flask_babel import gettext as _

from services.api_helpers import handle_api_errors, error
from services.auth import admin_required

bp = Blueprint('mame_names', __name__)


@bp.route('/tools/mame-names')
@admin_required
def mame_names_page():
    return render_template('mame_names.html')


def _file_or_none(value):
    path = value.strip() if isinstance(value, str) else ''
    return path if path and os.path.isfile(path) else None


@bp.route('/api/mame-names/start', methods=['POST'])
@admin_required
@handle_api_errors
def api_mame_names_start():
    from services.jobs import mame_names_job
    data = request.get_json(silent=True) or {}
    typed = [data.get('list_path'), data.get('extra_list_path'), data.get('category_path')]
    if any(isinstance(p, str) and p.strip() and not _file_or_none(p) for p in typed):
        return error(_('One of those files was not found.'), 400)
    lists = [p for p in map(_file_or_none, typed[:2]) if p]
    if not lists:
        return error(_('Choose a MAME list first.'), 400)
    result = mame_names_job.start(lists, _file_or_none(typed[2]))
    if not result['success']:
        return error(_('MAME Names is already running.'), 409)
    return jsonify(result)


@bp.route('/api/mame-names/status')
@admin_required
@handle_api_errors
def api_mame_names_status():
    from services.jobs import mame_names_job
    return jsonify({'success': True, **mame_names_job.get_status()})


@bp.route('/api/mame-names/cancel', methods=['POST'])
@admin_required
@handle_api_errors
def api_mame_names_cancel():
    from services.jobs import mame_names_job
    return jsonify(mame_names_job.cancel())
