# =============================================================================
# RETRODB - Consolidated Game Imports Blueprint
# =============================================================================
# Unified tabbed page for all game import sources: CLZ, Steam, Xbox, PSN.
# Backend API routes are kept in their original blueprints (clz_import,
# platform_import). This blueprint provides the unified UI and redirects.
#
# Routes:
#   GET /game-imports  - Unified tabbed import page
# =============================================================================

import logging

from flask import Blueprint, render_template, request

from services.auth import login_required

logger = logging.getLogger(__name__)

bp = Blueprint('game_imports', __name__)


@bp.route('/game-imports')
@login_required
def game_imports_page():
    """Render the unified game imports page with tabs."""
    # Determine which tab to activate (default: clz)
    active_tab = request.args.get('tab', 'clz')
    if active_tab not in ('clz', 'steam', 'xbox', 'psn'):
        active_tab = 'clz'

    return render_template('game_imports.html', active_tab=active_tab)
