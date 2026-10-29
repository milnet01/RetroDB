# =============================================================================
# RETRODB - Cheats Blueprint (PASS-59-155 §4.7)
# =============================================================================
#   GET  /api/games/<id>/cheats     the game page's Cheats panel
#   PUT  /api/games/<id>/cheats     switch cheats on; pick the player's list
#   GET  /api/cheats/packs          Settings > Emulators: each pack's state
#   POST /api/cheats/packs/<pack>   download a pack (the player downloads job)
#   POST /api/cheats/import         copy a folder's cheat files into the store
# =============================================================================

import logging

from flask import Blueprint, request
from flask_babel import gettext as _

from services import cheats
from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required, admin_required, permission_required

logger = logging.getLogger(__name__)

bp = Blueprint('cheats', __name__)


@bp.route('/api/games/<int:game_id>/cheats', methods=['GET'])
@login_required
@permission_required('view')
@handle_api_errors
def api_game_cheats(game_id):
    view = cheats.game_view(game_id)
    if view is None:
        return error(_('Game not found'), 404)
    return success(view)


@bp.route('/api/games/<int:game_id>/cheats', methods=['PUT'])
@login_required
@permission_required('edit')
@handle_api_errors
def api_put_game_cheats(game_id):
    """Body {enabled: [name, ...], source?: str}. With `source` alone, the
    player's new list keeps its own switches."""
    data = request.get_json(silent=True) or {}
    enabled, source = data.get('enabled'), data.get('source')
    if ((enabled is None and source is None)
            or (enabled is not None and (not isinstance(enabled, list)
                                         or not all(isinstance(n, str) for n in enabled)))
            or (source is not None and not isinstance(source, str))):
        return error(_('Send the names of the cheats to switch on.'), 400)
    if cheats.game_view(game_id) is None:
        return error(_('Game not found'), 404)
    try:
        cheats.save(game_id, enabled, source)
    except cheats.CheatError as e:
        return error(str(e), 400)
    return success(cheats.game_view(game_id))


@bp.route('/api/cheats/packs', methods=['GET'])
@login_required
@permission_required('manage_settings')
@handle_api_errors
def api_cheat_packs():
    sources = cheats.pack_sources()
    return success(packs=[dict(sources.get(p, {}), pack=p, url=url)
                          for p, url in cheats.PACKS.items()])


@bp.route('/api/cheats/packs/<pack>', methods=['POST'])
@login_required
@admin_required
@handle_api_errors
def api_download_cheat_pack(pack):
    """Queue the download; poll /api/player/cores/status."""
    from services.jobs import player_cores_job
    from services.jobs.player_cores import CHEATS
    if pack not in cheats.PACKS:
        return error(_('No such cheat pack.'), 404)
    return success(job_id=player_cores_job.request([(CHEATS + pack, None)], force=True))


@bp.route('/api/cheats/import', methods=['POST'])
@login_required
@admin_required
@handle_api_errors
def api_import_cheats():
    """Body {path}: a folder on this computer, only read."""
    path = (request.get_json(silent=True) or {}).get('path')
    if not isinstance(path, str):
        return error(_('Enter a folder to import.'), 400)
    try:
        return success(cheats.import_folder(path))
    except cheats.CheatError as e:
        return error(str(e), 400)
