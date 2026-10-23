# =============================================================================
# RETRODB - Games Blueprint
# =============================================================================
# Handles game pages, game API endpoints, HLTB lookup, and game management.
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, g, make_response, abort
from flask_babel import gettext as _
import hashlib
import os
import json
import logging
from datetime import datetime, timezone

import config
import settings_manager
from services.database import query, execute, safe_column
from services.auth import login_required, editor_required, has_permission, permission_required
from services.api_helpers import handle_api_errors, success, error
from services.game_utils import (
    reset_game_title_from_filename,
    get_ra_supported_systems,
    get_preferred_rating, get_all_ratings,
    normalize_players_value,
    RATING_SYSTEMS, RATING_SYSTEM_KEYS,
)
from services.game_query import (
    escape_like, get_retroachievements_info, get_trophy_info_for_game,
    get_bonus_discs_for_game, _get_filter_options, _build_games_query,
    invalidate_filter_cache, VERSION_COLUMNS,
)
from services.analytics import invalidate_analytics_cache
from services.launch_resolver import keyboard_core, launch_checker, rom_launch_problem
from services.game_metadata_service import (
    build_game_card,
    apply_hybrid_metadata_to_game,
    normalize_game_edit, cross_map_ratings,
)
from services import apply_progress, upscale_queue

# Single source of truth for the completion-status whitelist, shared by the
# single-edit endpoint (api_update_completion) and bulk-edit (Pass 48.5 — bulk
# edit previously wrote completion_status without validating it).
VALID_COMPLETION_STATUSES = (
    'not_started', 'in_progress', 'played', 'completed', '100_percent',
)
from services.achievement_linking import (
    build_rpcs3_trophy_map, lookup_rpcs3_info,
)
from services.game_media_service import (
    ALLOWED_IMAGE_EXT, ALLOWED_VIDEO_EXT, image_dir,
    remove_media_file, save_upload, save_screenshots, try_standardize,
)

logger = logging.getLogger(__name__)

bp = Blueprint('games', __name__)

# Scraper manager with graceful fallback when scrapers are unavailable.
# The apply path is served by services.game_metadata_service (imported above)
# so routes/games.py and both bulk-scrape sites share one code path. Search
# stays on the manager — it's an orchestration concern, not merge.
try:
    from scraper.scraper_manager import scraper_manager
    search_games = scraper_manager.search_games
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False

    def search_games(*args, **kwargs):
        return []


@bp.route('/games')
@login_required
def all_games():
    """All games listing page — lightweight shell, data loaded via /api/games"""
    try:
        systems = query("""
            SELECT s.*, COUNT(g.id) AS rom_count
            FROM systems s
            LEFT JOIN games g ON s.id = g.system_id
            GROUP BY s.id
            HAVING rom_count > 0
            ORDER BY s.name COLLATE NOCASE
        """)

        counts = query("""
            SELECT
                -- PASS-59-106: a version group is one game; total_roms counts rows.
                COUNT(DISTINCT CASE WHEN (is_bonus_disc = 0 OR is_bonus_disc IS NULL)
                                    THEN COALESCE(version_group_id, -id) END) AS total_games,
                COUNT(CASE WHEN (is_bonus_disc = 0 OR is_bonus_disc IS NULL) THEN 1 END) AS total_roms,
                COUNT(CASE WHEN scraped = 0 AND (is_bonus_disc = 0 OR is_bonus_disc IS NULL) THEN 1 END) AS total_missing,
                COUNT(CASE WHEN is_bonus_disc = 1 THEN 1 END) AS bonus_count
            FROM games
        """, one=True)
        total_games = counts['total_games']
        total_roms = counts['total_roms']
        total_missing = counts['total_missing']
        bonus_count = counts['bonus_count']

        ra_systems = get_ra_supported_systems()
        filter_options = _get_filter_options()

        # Get available first letters for alphabet nav
        letter_rows = query("""
            SELECT DISTINCT UPPER(SUBSTR(COALESCE(sort_title, title), 1, 1)) AS letter
            FROM games
            WHERE is_bonus_disc = 0 OR is_bonus_disc IS NULL
        """)
        available_letters = [r['letter'] for r in letter_rows if r['letter']]

        return render_template('all_games.html',
                             systems=systems,
                             total_games=total_games,
                             total_roms=total_roms,
                             total_missing=total_missing,
                             bonus_count=bonus_count,
                             ra_systems=ra_systems,
                             filter_options=filter_options,
                             available_letters=available_letters)
    except Exception as e:
        logger.error(f"All games error: {e}")
        return f"Error loading games: {e}", 500


def _add_can_launch(games, rows):
    """PASS-59-91 §4.5 — mark each card the caller can start from the list:
    they hold the launch permission, the game's emulator mapping resolves, and
    its ROM passes the launch's own file checks. `games` and `rows` are
    parallel lists."""
    allowed = has_permission(settings_manager.get_setting('launch_required_permission', 'launch'))
    can_launch = launch_checker() if allowed else None
    for card, row in zip(games, rows):
        card['can_launch'] = bool(
            can_launch
            and can_launch(row['system_id'], row['emulator_override_id'])
            and not rom_launch_problem(row['rom_path']))


@bp.route('/api/games')
@login_required
@handle_api_errors
def api_games():
    """Paginated games API for the all-games page"""
    # Floor page at 1: a 0/negative page makes offset = (page-1)*per_page
    # negative, which SQLite clamps to 0 but leaves total_pages/has_more math
    # wrong, silently serving page-1 data for page=0.
    page = max(request.args.get('page', 1, type=int), 1)
    per_page = min(max(request.args.get('per_page', 100, type=int), 1), 200)

    params = {k: request.args.get(k) for k in
              ('system', 'system_type', 'genre', 'franchise', 'developer',
               'publisher', 'modes', 'perspective', 'dimension', 'rating', 'source', 'search', 'letter',
               'show_bonus', 'ra_only', 'sort',
               'not_genre', 'not_franchise', 'not_developer', 'not_publisher',
               'not_modes', 'not_perspective', 'not_dimension', 'not_rating')
              if request.args.get(k)}
    # PASS-53-2 — the Unscraped filter button; same flag as /api/games/ids
    if request.args.get('unscraped') == '1':
        params['_unscraped'] = True

    # Count queries — PASS-59-106: `total` counts cards (one per version
    # group), `total_roms` every row, under the same filters.
    count_sql, count_vals = _build_games_query(params, count_only=True)
    total = query(count_sql, tuple(count_vals), one=True)['total']
    roms_sql, roms_vals = _build_games_query(params, count_only=True, group_versions=False)
    total_roms = query(roms_sql, tuple(roms_vals), one=True)['total']

    # Data query with pagination (Pass 31.1 — scope the psn subquery to caller).
    data_sql, data_vals = _build_games_query(params, user_id=g.user['id'])
    offset = (page - 1) * per_page
    data_sql += " LIMIT ? OFFSET ?"
    data_vals.extend([per_page, offset])
    rows = query(data_sql, tuple(data_vals))

    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    try:
        rpcs3_trophy_map = build_rpcs3_trophy_map(rows)
    except Exception as e:
        logger.debug(f"RPCS3 trophy lookup skipped: {e}")
        rpcs3_trophy_map = {}

    games = [
        build_game_card(row, lookup_rpcs3_info(row, rpcs3_trophy_map), include_source_flag=True)
        for row in rows
    ]
    _add_can_launch(games, rows)

    return success(
        games=games,
        total=total,
        total_roms=total_roms,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        has_more=page < total_pages,
    )



@bp.route('/api/games/ids')
@login_required
@handle_api_errors
def api_games_ids():
    """Lightweight endpoint returning only IDs matching current filters (for bulk select)."""
    params = {k: request.args.get(k) for k in
              ('system', 'system_type', 'genre', 'franchise', 'developer',
               'publisher', 'modes', 'perspective', 'dimension', 'rating', 'source', 'search', 'letter',
               'show_bonus', 'ra_only',
               'not_genre', 'not_franchise', 'not_developer', 'not_publisher',
               'not_modes', 'not_perspective', 'not_dimension', 'not_rating')
              if request.args.get(k)}

    # For select-unscraped, add scraped=0 filter
    if request.args.get('unscraped') == '1':
        params['_unscraped'] = True

    ids_sql, ids_vals = _build_games_query(params, ids_only=True)

    # Pass 25.8 — sanity LIMIT. This endpoint feeds bulk-select ("select every
    # filtered game on this page") so a 500-row cap would break a realistic
    # library; we pick a ceiling (20 000) that's one order of magnitude past
    # any plausible library size but still prevents a runaway response.
    ids_sql += f" LIMIT {20 * int(getattr(config, 'MAX_LIST_ROWS', 500))}"

    rows = query(ids_sql, tuple(ids_vals))
    ids = [r['id'] for r in rows]

    return success(ids=ids, total=len(ids))


@bp.route('/api/games/card-data')
@login_required
@handle_api_errors
def api_games_card_data():
    """Get card-compatible game data for specific game IDs (for live card refresh)."""
    ids_param = request.args.get('ids', '')
    if not ids_param:
        return error(_('No IDs provided'), 400)

    game_ids = []
    for part in ids_param.split(','):
        part = part.strip()
        if part.isdigit():
            game_ids.append(int(part))
    if not game_ids or len(game_ids) > 50:
        return error(_('Provide 1-50 valid IDs'), 400)

    # Pass 21.1: ETag short-circuit. Key off MAX(games.updated_at) for the
    # requested IDs — migration 004 guarantees every INSERT/UPDATE refreshes
    # it. If the client's If-None-Match matches, skip the heavy JOIN + JSON
    # serialisation entirely and return 304.
    sorted_ids = sorted(game_ids)
    max_updated_row = query(
        f"SELECT MAX(updated_at) AS m FROM games WHERE id IN ({','.join('?' * len(sorted_ids))})",
        tuple(sorted_ids),
        one=True,
    )
    max_updated = (max_updated_row or {}).get('m') or ''
    # Pass 40.5 — bake the user id into the ETag.  The response payload
    # includes per-user PSN + achievement progress (joins below), so a
    # globally-keyed ETag lets one user's browser serve another user's
    # progress as a 304.  CWE-524.
    etag_payload = f"cd:{g.user['id']}:{','.join(str(i) for i in sorted_ids)}:{max_updated}"
    etag = f'W/"{hashlib.md5(etag_payload.encode(), usedforsecurity=False).hexdigest()}"'
    if request.headers.get('If-None-Match') == etag:
        resp = make_response('', 304)
        resp.headers['ETag'] = etag
        resp.headers['Cache-Control'] = 'private, must-revalidate'
        return resp

    placeholders = ','.join('?' * len(game_ids))
    sql = f"""
        SELECT g.id, g.title, g.sort_title, g.system_id, g.emulator_override_id,
               g.boxart, g.boxart_3d,
               g.fanart, g.genre, g.franchise, g.developer, g.publisher,
               g.release_date, g.modes, g.esrb_rating, g.pegi_rating,
               g.cero_rating, g.usk_rating, g.acb_rating, g.fpb_rating,
               g.grac_rating, g.classind_rating, g.china_rating,
               g.critic_score, g.critic_score_count, g.user_score, g.user_score_count,
               g.completion_status, g.scraped, g.has_retroachievements,
               g.is_bonus_disc, g.rom_path, g.ra_achievement_count,
               s.name AS system_name, s.folder AS system_folder, s.system_type,
               COALESCE(bc.bonus_count, 0) AS bonus_count,
               {VERSION_COLUMNS},
               gap.earned_achievements,
               CASE WHEN COALESCE(gap.total_achievements, 0) > 0
                    THEN gap.total_achievements
                    ELSE g.ra_achievement_count END AS achievement_total,
               gap.completion_percentage AS achievement_pct,
               gap.source AS achievement_source,
               psn.psn_earned, psn.psn_total, psn.psn_progress
        FROM games g
        JOIN systems s ON g.system_id = s.id
        LEFT JOIN (
            SELECT parent_game_id, COUNT(*) AS bonus_count
            FROM games
            WHERE is_bonus_disc = 1
            GROUP BY parent_game_id
        ) bc ON bc.parent_game_id = g.id
        LEFT JOIN game_achievement_progress gap ON gap.game_id = g.id AND gap.user_id = ?
        LEFT JOIN (
            SELECT pg.linked_game_id,
                   (pg.earned_bronze + pg.earned_silver + pg.earned_gold + pg.earned_platinum) AS psn_earned,
                   COUNT(pt.id) AS psn_total,
                   pg.progress AS psn_progress
            FROM psn_games pg
            LEFT JOIN psn_trophies pt ON pt.psn_game_id = pg.id
            WHERE pg.linked_game_id IS NOT NULL
              AND pg.user_id = ?
            GROUP BY pg.linked_game_id
        ) psn ON psn.linked_game_id = g.id
        WHERE g.id IN ({placeholders})
    """
    rows = query(sql, (g.user['id'], g.user['id'], *game_ids))

    try:
        rpcs3_trophy_map = build_rpcs3_trophy_map(rows)
    except Exception:
        rpcs3_trophy_map = {}

    games = [
        build_game_card(row, lookup_rpcs3_info(row, rpcs3_trophy_map))
        for row in rows
    ]
    _add_can_launch(games, rows)

    resp = success(games=games)
    resp.headers['ETag'] = etag
    resp.headers['Cache-Control'] = 'private, must-revalidate'
    return resp


@bp.route('/game/<int:game_id>', methods=['GET', 'POST'])
@login_required
def game_detail(game_id):
    """Individual game detail and scraping page"""
    try:
        game = query("""
            SELECT g.*, s.name AS system_name, s.folder AS system_folder, s.id AS system_id
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,), one=True)

        if not game:
            flash(_("Game not found"), "error")
            return redirect(url_for('games.all_games'))

        # Get full system info
        system = query("SELECT * FROM systems WHERE id = ?", (game['system_id'],), one=True)

        search_results = None
        message = None

        if request.method == 'POST':
            action = request.form.get('action')

            # Pass 31.8 — the sibling JSON route /api/game/<id>/edit uses
            # @editor_required; this form-POST dispatcher must match it so
            # viewer role can't mutate games by POSTing multipart/form-data.
            # 'search' is read-only and left unguarded.
            if action in ('apply', 'edit_metadata', 'reset') and not has_permission('edit'):
                abort(403)

            if action == 'search':
                title = request.form.get('title', game['title'])
                system_name = game['system_name']

                try:
                    logger.info(f"Searching for: '{title}' on {system_name}")
                    search_results = search_games(title, system_name, limit=10)

                    if not search_results:
                        message = "No results found. Try modifying the search title."
                    else:
                        tgdb_count = sum(1 for r in search_results if r.get('source') == 'thegamesdb')
                        igdb_count = sum(1 for r in search_results if r.get('source') == 'igdb')
                        esde_count = sum(1 for r in search_results if r.get('source') == 'esde')
                        message = f"Found {len(search_results)} results (ES-DE: {esde_count}, TGDB: {tgdb_count}, IGDB: {igdb_count})"
                except Exception as e:
                    message = "An error occurred during search"
                    logger.error(f"Search error: {e}")

            elif action == 'edit_metadata':
                try:
                    # Pass 42.1 — normalize through the shared helper so the
                    # form-POST and JSON edit paths agree on every transform
                    # (strip + empty-as-None, release_date validation, players
                    # coercion, rating cross-map, sort_title auto-generation,
                    # similar_games re-join).  controller_support has a custom
                    # text override that takes priority over the dropdown,
                    # so it is built before the helper runs.
                    controller_support_input = (
                        request.form.get('edit_controller_support_custom', '').strip()
                        or request.form.get('edit_controller_support', '').strip()
                    )
                    _form_keys = (
                        'title', 'sort_title', 'publisher', 'developer',
                        'genre', 'release_date', 'region', 'franchise',
                        'other_platforms', 'modes', 'campaign', 'game_structure',
                        'perspective', 'dimension', 'players',
                        'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
                        'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
                        'china_rating',
                        'save_type', 'similar_games', 'edition', 'description',
                        'launch_args_override',
                    )
                    _payload = {
                        k: request.form.get(f'edit_{k}', '')
                        for k in _form_keys
                    }
                    _payload['controller_support'] = controller_support_input
                    _normalized = normalize_game_edit(_payload)
                    title = _normalized.get('title') or ''
                    sort_title = _normalized.get('sort_title') or ''
                    publisher = _normalized.get('publisher') or ''
                    developer = _normalized.get('developer') or ''
                    genre = _normalized.get('genre') or ''
                    release_date = _normalized.get('release_date') or ''
                    region = _normalized.get('region') or ''
                    franchise = _normalized.get('franchise') or ''
                    other_platforms = _normalized.get('other_platforms') or ''
                    modes = _normalized.get('modes') or ''
                    campaign = _normalized.get('campaign') or ''
                    game_structure = _normalized.get('game_structure') or ''
                    perspective = _normalized.get('perspective') or ''
                    dimension = _normalized.get('dimension') or ''
                    controller_support = _normalized.get('controller_support') or ''
                    players = _normalized.get('players')
                    esrb_rating = _normalized.get('esrb_rating') or ''
                    pegi_rating = _normalized.get('pegi_rating') or ''
                    cero_rating = _normalized.get('cero_rating') or ''
                    usk_rating = _normalized.get('usk_rating') or ''
                    acb_rating = _normalized.get('acb_rating') or ''
                    fpb_rating = _normalized.get('fpb_rating') or ''
                    grac_rating = _normalized.get('grac_rating') or ''
                    classind_rating = _normalized.get('classind_rating') or ''
                    china_rating = _normalized.get('china_rating') or ''
                    save_type = _normalized.get('save_type') or ''
                    similar_games = _normalized.get('similar_games') or ''
                    edition = _normalized.get('edition') or ''
                    description = _normalized.get('description') or ''

                    # Pass 44 — multi-emulator launch overrides. INTEGER column,
                    # parsed separately because normalize_game_edit() only
                    # handles strings.
                    # PASS-59-149 — no Launch section (no ROM file to play)
                    # sends neither field; keep what the game has.
                    has_launch_section = 'edit_emulator_override_id' in request.form
                    emu_override_raw = request.form.get('edit_emulator_override_id', '').strip()
                    try:
                        emulator_override_id = int(emu_override_raw) if emu_override_raw else None
                    except ValueError:
                        emulator_override_id = None
                    if not has_launch_section:
                        emulator_override_id = game['emulator_override_id']
                    # PASS-59-53 — the args reach the emulator's argv, so only
                    # manage_settings may change them (PASS-59-64 §4.2).
                    if has_permission('manage_settings') and has_launch_section:
                        launch_args_override = _normalized.get('launch_args_override')
                    else:
                        launch_args_override = game['launch_args_override']

                    boxart_filename = game['boxart']
                    boxart_3d_filename = game['boxart_3d'] if game['boxart_3d'] else ''
                    fanart_filename = game['fanart']
                    screenshots = game['screenshots'] or ''
                    video_filename = game['video'] if game['video'] else ''

                    if request.form.get('remove_boxart') == '1' and boxart_filename:
                        remove_media_file(boxart_filename, 'boxart')
                        boxart_filename = ''
                    if request.form.get('remove_boxart_3d') == '1' and boxart_3d_filename:
                        remove_media_file(boxart_3d_filename, 'boxart_3d')
                        boxart_3d_filename = ''
                    if request.form.get('remove_fanart') == '1' and fanart_filename:
                        remove_media_file(fanart_filename, 'fanart')
                        fanart_filename = ''
                    if request.form.get('remove_video') == '1' and video_filename:
                        remove_media_file(video_filename, 'video')
                        video_filename = ''

                    uploaded = save_upload(request.files.get('custom_boxart'), image_dir('boxart'), game_id, 'custom', ALLOWED_IMAGE_EXT)
                    if uploaded:
                        boxart_filename = uploaded
                        try_standardize(os.path.join(image_dir('boxart'), uploaded), 'boxart')

                    uploaded = save_upload(request.files.get('custom_boxart_3d'), image_dir('boxart_3d'), game_id, 'custom_3d', ALLOWED_IMAGE_EXT)
                    if uploaded:
                        boxart_3d_filename = uploaded
                        try_standardize(os.path.join(image_dir('boxart_3d'), uploaded), 'boxart_3d')

                    uploaded = save_upload(request.files.get('custom_fanart'), image_dir('fanart'), game_id, 'custom_fanart', ALLOWED_IMAGE_EXT)
                    if uploaded:
                        fanart_filename = uploaded

                    video_upload = request.files.get('custom_video')
                    uploaded = save_upload(video_upload, os.path.join(config.STATIC_PATH, 'videos'), game_id, 'custom', ALLOWED_VIDEO_EXT)
                    if uploaded:
                        video_filename = uploaded
                    elif video_upload and video_upload.filename:
                        flash(_("Video not saved: it must be an MP4, WebM or OGG file "
                                "of up to %(mb)s MB.",
                                mb=config.MAX_VIDEO_SIZE // (1024 * 1024)), "error")

                    screenshots = save_screenshots(
                        request.files.getlist('custom_screenshots'),
                        game_id,
                        screenshots,
                    )

                    # Update database
                    execute("""
                        UPDATE games SET
                            title = ?,
                            sort_title = NULLIF(?, ''),
                            publisher = NULLIF(?, ''),
                            developer = NULLIF(?, ''),
                            genre = NULLIF(?, ''),
                            release_date = NULLIF(?, ''),
                            region = NULLIF(?, ''),
                            franchise = NULLIF(?, ''),
                            other_platforms = NULLIF(?, ''),
                            modes = NULLIF(?, ''),
                            campaign = NULLIF(?, ''),
                            game_structure = NULLIF(?, ''),
                            perspective = NULLIF(?, ''),
                            dimension = NULLIF(?, ''),
                            controller_support = NULLIF(?, ''),
                            players = NULLIF(?, ''),
                            esrb_rating = NULLIF(?, ''),
                            pegi_rating = NULLIF(?, ''),
                            cero_rating = NULLIF(?, ''),
                            usk_rating = NULLIF(?, ''),
                            acb_rating = NULLIF(?, ''),
                            fpb_rating = NULLIF(?, ''),
                            grac_rating = NULLIF(?, ''),
                            classind_rating = NULLIF(?, ''),
                            china_rating = NULLIF(?, ''),
                            save_type = NULLIF(?, ''),
                            similar_games = NULLIF(?, ''),
                            edition = NULLIF(?, ''),
                            description = NULLIF(?, ''),
                            boxart = NULLIF(?, ''),
                            boxart_3d = NULLIF(?, ''),
                            fanart = NULLIF(?, ''),
                            screenshots = NULLIF(?, ''),
                            video = NULLIF(?, ''),
                            emulator_override_id = ?,
                            launch_args_override = ?
                        WHERE id = ?
                    """, (
                        title or game['title'],
                        sort_title,
                        publisher, developer, genre, release_date,
                        region, franchise, other_platforms, modes, campaign, game_structure, perspective, dimension, controller_support, players,
                        esrb_rating, pegi_rating, cero_rating, usk_rating, acb_rating, fpb_rating, grac_rating, classind_rating,
                        china_rating,
                        save_type, similar_games, edition, description,
                        boxart_filename, boxart_3d_filename, fanart_filename, screenshots, video_filename,
                        emulator_override_id, launch_args_override,
                        game_id
                    ))

                    message = "Metadata updated successfully!"

                    # Pass 42.1 — match api_game_edit's cache discipline.  The
                    # filter + analytics caches were stale until the next
                    # full-rescrape if the user edited only via the form.
                    invalidate_filter_cache()
                    invalidate_analytics_cache()

                    game = query("""
                        SELECT g.*, s.name AS system_name, s.folder AS system_folder
                        FROM games g
                        JOIN systems s ON g.system_id = s.id
                        WHERE g.id = ?
                    """, (game_id,), one=True)

                except Exception as e:
                    message = "An error occurred updating metadata"
                    logger.error(f"Edit metadata error: {e}", exc_info=True)

            elif action == 'reset':
                try:
                    # Reset all metadata
                    execute("""
                        UPDATE games SET
                            publisher = NULL, developer = NULL, release_date = NULL,
                            genre = NULL, rating = NULL, esrb_rating = NULL, pegi_rating = NULL,
                            cero_rating = NULL, usk_rating = NULL, acb_rating = NULL,
                            fpb_rating = NULL, grac_rating = NULL, classind_rating = NULL,
                            china_rating = NULL,
                            players = NULL, modes = NULL, description = NULL,
                            boxart = NULL, boxart_3d = NULL, screenshots = NULL,
                            fanart = NULL, video = NULL, manual = NULL,
                            region = NULL, franchise = NULL, similar_games = NULL,
                            playtime_estimate = NULL, controller_support = NULL, save_type = NULL,
                            scrape_history = NULL, critic_score = NULL, critic_score_count = NULL,
                            user_score = NULL, user_score_count = NULL,
                            hltb_match_name = NULL, hltb_match_platform = NULL, hltb_match_confidence = NULL,
                            scraped = 0
                        WHERE id = ?
                    """, (game_id,))

                    new_title = reset_game_title_from_filename(game_id)
                    # Pass 34.7: log the destructive reset.
                    user_id = (g.user or {}).get('id') if g.user else None
                    logger.info(
                        "game_reset game_id=%s title=%r user_id=%s",
                        game_id, game['title'], user_id,
                    )
                    message = f"All metadata cleared. Title reset to: {new_title}"

                    game = query("""
                        SELECT g.*, s.name AS system_name, s.folder AS system_folder
                        FROM games g
                        JOIN systems s ON g.system_id = s.id
                        WHERE g.id = ?
                    """, (game_id,), one=True)

                except Exception as e:
                    message = "An error occurred resetting metadata"
                    logger.error(f"Reset error: {e}")

        # Parse scrape_history JSON if present
        if game is None:
            flash(_("Game not found after update"), "error")
            return redirect(url_for('games.all_games'))

        game_dict = dict(game)
        if game_dict.get('scrape_history'):
            try:
                game_dict['scrape_history'] = json.loads(game_dict['scrape_history'])
            except (ValueError, TypeError):
                game_dict['scrape_history'] = []
        else:
            game_dict['scrape_history'] = []

        # Validate screenshot files exist on disk — filter out stale references
        if game_dict.get('screenshots'):
            ss_dir = os.path.join(config.IMAGE_PATH, 'screenshots')
            ss_list = [s.strip() for s in game_dict['screenshots'].split(',') if s.strip()]
            valid_ss = [s for s in ss_list if os.path.exists(os.path.join(ss_dir, s))]
            if len(valid_ss) < len(ss_list):
                missing = [s for s in ss_list if s not in valid_ss]
                logger.warning(f"Game {game_id}: removing stale screenshot refs: {missing}")
                new_val = ', '.join(valid_ss) if valid_ss else None
                game_dict['screenshots'] = new_val
                execute("UPDATE games SET screenshots = ? WHERE id = ?", (new_val, game_id))

        class GameObj:
            def __init__(self, d):
                for k, v in d.items():
                    setattr(self, k, v)
            def __getitem__(self, key):
                return getattr(self, key, None)
            def get(self, key, default=None):
                return getattr(self, key, default)

        game = GameObj(game_dict)

        bonus_discs = get_bonus_discs_for_game(game_id)

        parent_game = None
        if game_dict.get('is_bonus_disc') and game_dict.get('parent_game_id'):
            parent_game = query("""
                SELECT id, title, boxart FROM games WHERE id = ?
            """, (game_dict['parent_game_id'],), one=True)

        # Compute preferred rating for display
        pref_sys = settings_manager.load_settings().get('preferred_rating_system', 'esrb')
        pref_rating_val, pref_rating_img, pref_rating_crossmapped = get_preferred_rating(game, pref_sys)
        pref_rating_name = RATING_SYSTEMS.get(pref_sys, {}).get('name', pref_sys.upper())
        pref_rating_region = RATING_SYSTEMS.get(pref_sys, {}).get('region', '')
        all_ratings = get_all_ratings(game)

        # Achievement & trophy progress for the caller (Pass 31.2).
        achievement_progress = query("""
            SELECT earned_achievements, total_achievements,
                   completion_percentage, source
            FROM game_achievement_progress WHERE game_id = ? AND user_id = ?
        """, (game_id, g.user['id']), one=True)

        # PSN trophy progress (if linked).
        # psn_games has two parallel column families — `defined_*` (legacy,
        # never populated by any writer) and `total_*` (canonical, written
        # by every sync path). Alias `total_*` -> the `defined_*` names the
        # template expects so per-category breakdowns stop rendering as
        # "earned / 0". The `defined_*` columns themselves can be dropped
        # in a future migration pass.
        # Pass 31.1 — show the caller's own PSN progress for this game.
        psn_progress = query("""
            SELECT pg.id, pg.npwr_id, pg.progress,
                   pg.earned_bronze, pg.earned_silver, pg.earned_gold, pg.earned_platinum,
                   pg.total_bronze   AS defined_bronze,
                   pg.total_silver   AS defined_silver,
                   pg.total_gold     AS defined_gold,
                   pg.total_platinum AS defined_platinum,
                   (pg.earned_bronze + pg.earned_silver + pg.earned_gold + pg.earned_platinum) AS earned_total,
                   pg.total_trophies AS defined_total
            FROM psn_games pg
            WHERE pg.linked_game_id = ? AND pg.user_id = ?
        """, (game_id, g.user['id']), one=True)

        # Steam achievement count (Pass 31.2 — per user).
        steam_counts = None
        if game_dict.get('steam_app_id'):
            steam_counts = query("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN achieved = 1 THEN 1 ELSE 0 END) AS earned
                FROM steam_achievements WHERE game_id = ? AND user_id = ?
            """, (game_id, g.user['id']), one=True)
            if steam_counts and not steam_counts['total']:
                steam_counts = None

        # Xbox achievement count (Pass 31.2 — per user).
        xbox_counts = None
        if game_dict.get('xbox_title_id'):
            xbox_counts = query("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN achieved = 1 THEN 1 ELSE 0 END) AS earned,
                       SUM(CASE WHEN achieved = 1 THEN gamerscore ELSE 0 END) AS earned_gs,
                       SUM(gamerscore) AS total_gs
                FROM xbox_achievements WHERE game_id = ? AND user_id = ?
            """, (game_id, g.user['id']), one=True)
            if xbox_counts and not xbox_counts['total']:
                xbox_counts = None

        # Decode alternate_titles (stored as JSON list of {title, region?,
        # note?, source?}). PASS-59-105: re-normalize so names stored with a
        # raw source tag show a region too, name each region in the user's
        # language, and list region-tagged names first, grouped by region.
        from scraper.metadata_normalizer import merge_alt_titles
        from services.i18n import region_display_name
        from flask_babel import get_locale
        alternate_titles = merge_alt_titles(game_dict.get('alternate_titles'), [])
        for alt in alternate_titles:
            if alt.get('region'):
                alt['region_label'] = region_display_name(alt['region'], get_locale())
        alternate_titles.sort(key=lambda a: (not a.get('region_label'), a.get('region_label') or ''))

        # PASS-59-106 §4.4 — the other regional versions this game is linked to.
        from scraper.metadata_normalizer import alt_title_region
        from services.version_groups import members as version_members, ai_summary
        versions = version_members(game_id) if game_dict.get('version_group_id') else []
        version_ai_summary = ai_summary(game_id) if len(versions) > 1 else None
        for version in versions:
            code, _note = alt_title_region(version['region_label'])
            version['region_name'] = (region_display_name(code, get_locale()) if code
                                      else version['region_label'])

        return render_template('game_detail.html',
                             game=game,
                             system=system,
                             search_results=search_results,
                             message=message,
                             bonus_discs=bonus_discs,
                             parent_game=parent_game,
                             versions=versions,
                             version_ai_summary=version_ai_summary,
                             alternate_titles=alternate_titles,
                             pref_rating={'value': pref_rating_val, 'image': pref_rating_img,
                                          'crossmapped': pref_rating_crossmapped, 'name': pref_rating_name,
                                          'region': pref_rating_region, 'system': pref_sys},
                             all_ratings=all_ratings,
                             retroachievements=get_retroachievements_info(game['title'], game['system_folder']),
                             trophy_info=get_trophy_info_for_game(game['title'], game['system_name']),
                             achievement_progress=achievement_progress,
                             psn_progress=psn_progress,
                             steam_counts=steam_counts,
                             xbox_counts=xbox_counts,
                             # PASS-59-149 — the cards' rule: an imported game
                             # with no ROM file has nothing to play.
                             can_play=rom_launch_problem(game['rom_path']) is None,
                             # PASS-59-152 — its hotkeys wait behind Scroll Lock.
                             keyboard_play=keyboard_core(game['system_id'],
                                                         game['emulator_override_id']),
                             # PASS-59-153 — its images still await upscaling.
                             upscale_pending=upscale_queue.pending_status(game_id)[1])
    except Exception as e:
        logger.error(f"Game detail error: {e}", exc_info=True)
        return f"Error loading game: {e}", 500


# =============================================================================
# GAME API ROUTES
# =============================================================================

@bp.route('/api/game/<int:game_id>/detail')
@login_required
def api_game_detail(game_id):
    """Get game detail for modal display"""
    game = query("""
        SELECT g.*, s.name AS system_name, s.folder AS system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)

    if not game:
        return error(_('Game not found'), 404)

    bonus_count = query(
        "SELECT COUNT(*) as cnt FROM games WHERE parent_game_id = ?",
        (game_id,), one=True
    )['cnt']

    # Achievement progress data (Pass 31.2 — per user).
    gap = query("""
        SELECT earned_achievements, total_achievements,
               completion_percentage, source
        FROM game_achievement_progress WHERE game_id = ? AND user_id = ?
    """, (game_id, g.user['id']), one=True)

    # PSN trophies (Pass 31.1 — scope to caller).
    psn = query("""
        SELECT (pg.earned_bronze + pg.earned_silver + pg.earned_gold + pg.earned_platinum) AS psn_earned,
               COUNT(pt.id) AS psn_total
        FROM psn_games pg
        LEFT JOIN psn_trophies pt ON pt.psn_game_id = pg.id
        WHERE pg.linked_game_id = ? AND pg.user_id = ?
        GROUP BY pg.linked_game_id
    """, (game_id, g.user['id']), one=True)

    try:
        rpcs3_info = lookup_rpcs3_info(game, build_rpcs3_trophy_map([game]))
    except Exception:
        rpcs3_info = None

    screenshots = []
    if game['screenshots']:
        ss_dir = os.path.join(config.IMAGE_PATH, 'screenshots')
        screenshots = [s.strip() for s in game['screenshots'].split(',') if s.strip()]
        valid_ss = [s for s in screenshots if os.path.exists(os.path.join(ss_dir, s))]
        if len(valid_ss) < len(screenshots):
            missing = [s for s in screenshots if s not in valid_ss]
            logger.warning(f"Game {game_id}: removing stale screenshot refs: {missing}")
            new_val = ', '.join(valid_ss) if valid_ss else None
            execute("UPDATE games SET screenshots = ? WHERE id = ?", (new_val, game_id))
        screenshots = valid_ss

    return success(
        game={
            'id': game['id'],
            'title': game['title'],
            'sort_title': game['sort_title'],
            'system_id': game['system_id'],
            'system_name': game['system_name'],
            'system_folder': game['system_folder'],
            'release_date': game['release_date'],
            'description': game['description'],
            'publisher': game['publisher'],
            'developer': game['developer'],
            'genre': game['genre'],
            'franchise': game['franchise'],
            'similar_games': game['similar_games'],
            'edition': game['edition'],
            'region': game['region'],
            'modes': game['modes'],
            'campaign': game['campaign'],
            'game_structure': game['game_structure'],
            'perspective': game['perspective'],
            'dimension': game['dimension'],
            'controller_support': game['controller_support'],
            'save_type': game['save_type'],
            'other_platforms': game['other_platforms'],
            'boxart': game['boxart'],
            'boxart_3d': game['boxart_3d'],
            'fanart': game['fanart'],
            'screenshots': screenshots[:5],
            'video': game['video'],
            'esrb_rating': game['esrb_rating'],
            'pegi_rating': game['pegi_rating'],
            'cero_rating': game.get('cero_rating'),
            'usk_rating': game.get('usk_rating'),
            'acb_rating': game.get('acb_rating'),
            'fpb_rating': game.get('fpb_rating'),
            'grac_rating': game.get('grac_rating'),
            'classind_rating': game.get('classind_rating'),
            'china_rating': game.get('china_rating'),
            'critic_score': game['critic_score'],
            'user_score': game['user_score'],
            'players': game['players'],
            'completion_status': game['completion_status'],
            'has_retroachievements': game['has_retroachievements'],
            'ra_achievement_count': game['ra_achievement_count'],
            'achievement_earned': gap['earned_achievements'] if gap else None,
            'achievement_total': (gap['total_achievements'] if gap and gap['total_achievements']
                                  else game['ra_achievement_count']),
            'achievement_source': gap['source'] if gap else None,
            'psn_earned': psn['psn_earned'] if psn else None,
            'psn_total': psn['psn_total'] if psn else None,
            'rpcs3_earned': rpcs3_info['earned'] if rpcs3_info else None,
            'rpcs3_total': rpcs3_info['total'] if rpcs3_info else None,
            'bonus_disc_count': bonus_count,
            'scraped': game['scraped'],
            'playtime_estimate': game['playtime_estimate'],
            'hltb_match_name': game['hltb_match_name'],
            'hltb_match_platform': game['hltb_match_platform'],
            'hltb_match_confidence': game['hltb_match_confidence']
        },
    )


@bp.route('/api/game/<int:game_id>/apply-metadata', methods=['POST'])
@editor_required
@handle_api_errors
def api_game_apply_metadata(game_id):
    """Start the Search Metadata apply in the background (PASS-59-108).

    Returns a task id; the page polls api_apply_metadata_progress for the
    gauge. Fallbacks are the ticked results, fetched by ID, plus AI; with
    none ticked, only AI (PASS-59-134).
    """
    data = request.get_json() or {}

    game = query("""
        SELECT g.id, s.folder AS system_folder
        FROM games g JOIN systems s ON g.system_id = s.id
        WHERE g.id = ?
    """, (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    source, _sep, source_id = (data.get('game_source') or '').partition('_')
    if not source or not source_id:
        return error(_('No game selected.'), 400)

    explicit_secondary = data.get('secondary_selections')
    if not isinstance(explicit_secondary, list):
        explicit_secondary = []

    task = apply_progress.start(
        game_id, apply_hybrid_metadata_to_game,
        db_game_id=game_id,
        primary_source=source,
        primary_id=source_id,
        system_folder=game['system_folder'] or '',
        explicit_secondary=explicit_secondary,
    )
    return success(task_id=task.id)


@bp.route('/api/apply-metadata/<task_id>')
@editor_required
@handle_api_errors
def api_apply_metadata_progress(task_id):
    """Progress of one background apply: percent, current step, finished."""
    task = apply_progress.get(task_id)
    if not task:
        return error(_('This metadata apply is no longer running.'), 404)

    snap = task.snapshot()
    if snap['finished']:
        if snap['applied']:
            # Flashed once, so it shows on the page the gauge reloads into.
            if not task.flashed:
                task.flashed = True
                result = task.result
                flash(_('Metadata applied from %(sources)s! '
                        '(%(filled)d fields filled, %(missing)d still missing)',
                        sources=', '.join(result.get('sources_used', [])),
                        filled=len(result.get('filled_fields', [])),
                        missing=len(result.get('missing_fields', []))), 'success')
        else:
            snap['error'] = _('Failed to apply metadata.')
    return jsonify({'success': True, **snap})


@bp.route('/api/game/<int:game_id>/edit', methods=['POST'])
@editor_required
@handle_api_errors
def api_game_edit(game_id):
    """Save game edits from modal"""
    data = request.get_json() or {}

    game = query("SELECT id, title FROM games WHERE id = ?", (game_id,), one=True)
    if not game:
        return error(_('Game not found'), 404)

    allowed_fields = [
        'title', 'sort_title', 'franchise', 'similar_games', 'edition',
        'release_date', 'region', 'publisher', 'developer',
        'genre', 'modes', 'players', 'campaign', 'game_structure', 'perspective', 'dimension',
        'controller_support', 'save_type', 'other_platforms',
        'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
        'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating', 'china_rating',
        'description'
    ]

    # Pass 42.1 — single source of truth shared with the form-POST edit
    # path: strip + empty-as-None, release_date validation, players coercion
    # (Pass 40.6), rating cross-map, sort_title auto-generation.
    payload = {k: data[k] for k in allowed_fields if k in data}
    normalized = normalize_game_edit(payload)
    # title is NOT NULL: a blank one keeps the stored title, as the
    # form-POST twin does (`title or game['title']`), so the rest still saves.
    if 'title' in normalized and not normalized['title']:
        del normalized['title']

    updates = []
    values = []
    for field in allowed_fields:
        if field in normalized:
            updates.append(f"{field} = ?")
            values.append(normalized[field])

    if not updates:
        return error(_('No fields to update'), 400)

    # Pass 34.7: structured observability on every mutation. Without this,
    # "who scrambled this game's metadata?" debugging has nothing to go on.
    # Fields only — values themselves stay out of logs to avoid PII leaks
    # and to keep lines bounded. user_id is resolved from g.user when the
    # caller is authenticated (editor_required guards this route).
    from flask import g as _flask_g
    user_id = getattr(_flask_g, 'user', None) and _flask_g.user.get('id')
    logger.info(
        "game_edit game_id=%s title=%r user_id=%s fields=%s",
        game_id, game['title'], user_id,
        [u.split(' = ')[0] for u in updates],
    )

    values.append(game_id)

    execute(f"""
        UPDATE games SET {', '.join(updates)} WHERE id = ?
    """, tuple(values))

    invalidate_filter_cache()
    invalidate_analytics_cache()

    return success()





@bp.route('/api/games/bulk-edit', methods=['POST'])
@editor_required
@handle_api_errors
def api_games_bulk_edit():
    """Bulk edit multiple games at once"""
    data = request.get_json() or {}
    game_ids = data.get('game_ids', [])
    fields = data.get('fields', {})
    field_modes = data.get('field_modes', {})

    if not game_ids:
        return error(_('No games selected'), 400)

    if not fields:
        return error(_('No fields to update'), 400)

    # Pass 48.5 — validate completion_status against the same whitelist the
    # single-edit endpoint enforces (bulk edit previously stored the raw value).
    if 'completion_status' in fields:
        cs = fields['completion_status']
        if cs not in ('', None) and cs not in VALID_COMPLETION_STATUSES:
            return error(_('Invalid completion status'), 400)

    # Pass 32.12: gate this set at a single safe_column() call site per
    # interpolation; the allowlist itself is frozen below so a future edit
    # can't bypass the validator by mutating the list in flight.
    bulk_allowed_fields = frozenset({
        'completion_status', 'genre', 'publisher', 'developer',
        'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
        'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating', 'china_rating',
        'region', 'players',
        'game_structure', 'perspective', 'dimension', 'campaign', 'franchise', 'modes',
    })

    # Fields that support append mode
    # region is a single-value, dropdown-driven field (not comma-separated
    # multi-value) — appending would corrupt it into "USA, Europe", which the
    # filters / default_region / detail display all treat as one value.
    appendable_fields = ['genre', 'publisher', 'developer', 'franchise', 'game_structure', 'perspective', 'dimension']

    # Separate append fields from replace fields
    append_fields = {}
    replace_updates = []
    replace_values = []

    for field, value in fields.items():
        if field not in bulk_allowed_fields:
            continue
        # Pass 32.12: every f-string insertion of `field` goes through
        # safe_column(). The allowlist check above already narrows the set,
        # but this makes the SQL interpolation contract explicit at the
        # insertion point instead of trusting an earlier comment.
        safe_field = safe_column(field, bulk_allowed_fields)
        if value == '':
            value = None

        mode = field_modes.get(field, 'replace')
        if mode == 'append' and safe_field in appendable_fields and value:
            append_fields[safe_field] = value
        else:
            if safe_field == 'players':
                # players is INTEGER; coerce ranges/junk to the max int like the
                # form-POST and JSON edit paths do, so bulk edit can't store a
                # string in the column.
                value = normalize_players_value(value)
            replace_updates.append(f"{safe_field} = ?")
            replace_values.append(value)

    if not replace_updates and not append_fields:
        return error(_('No valid fields to update'), 400)

    from services.database import get_db_with_context

    with get_db_with_context() as conn:
        cursor = conn.cursor()

        # Handle standard replace updates
        if replace_updates:
            placeholders = ','.join('?' for _ in game_ids)
            values = replace_values + list(game_ids)
            cursor.execute(f"""
                UPDATE games SET {', '.join(replace_updates)}
                WHERE id IN ({placeholders})
            """, tuple(values))

        # Handle append fields — batch updates per field. Pass 32.12:
        # re-validate through safe_column() at every interpolation site so
        # the contract holds even if the outer loop's allowlist logic is
        # ever refactored.
        if append_fields:
            placeholders = ','.join('?' for _ in game_ids)
            for field, new_value in append_fields.items():
                safe_field = safe_column(field, bulk_allowed_fields)
                # Games with empty field: set directly in one batch
                cursor.execute(
                    f"UPDATE games SET {safe_field} = ? WHERE id IN ({placeholders}) AND ({safe_field} IS NULL OR {safe_field} = '')",
                    (new_value, *game_ids)
                )
                # Games with existing values: check for duplicates, batch the appends
                rows = cursor.execute(
                    f"SELECT id, {safe_field} FROM games WHERE id IN ({placeholders}) AND {safe_field} IS NOT NULL AND {safe_field} != ''",
                    tuple(game_ids)
                ).fetchall()

                updates = []
                for row in rows:
                    current = row[1]
                    existing = [v.strip().lower() for v in current.split(',') if v.strip()]
                    if new_value.lower() not in existing:
                        updates.append((f"{current}, {new_value}", row[0]))

                if updates:
                    cursor.executemany(
                        f"UPDATE games SET {safe_field} = ? WHERE id = ?",
                        updates
                    )

        # Pass 48.5 — cross-map ratings like the single-edit path. When a bulk
        # edit set any rating system, fill each game's still-empty rating
        # systems from whatever ratings it now holds. cross_map_ratings only
        # fills empties, so a curated value in another system is never
        # overwritten (safe across a heterogeneous selection).
        rating_columns = [f'{k}_rating' for k in RATING_SYSTEM_KEYS]
        applied_ratings = [c for c in rating_columns if c in fields and c in bulk_allowed_fields]
        if applied_ratings:
            col_list = ', '.join(rating_columns)
            placeholders = ','.join('?' for _ in game_ids)
            rows = cursor.execute(
                f"SELECT id, {col_list} FROM games WHERE id IN ({placeholders})",
                tuple(game_ids),
            ).fetchall()
            for row in rows:
                current = {RATING_SYSTEM_KEYS[i]: (row[i + 1] or '') for i in range(len(RATING_SYSTEM_KEYS))}
                mapped = cross_map_ratings(current)
                changed = {
                    f'{k}_rating': mapped[k]
                    for k in RATING_SYSTEM_KEYS
                    if mapped.get(k) and mapped[k] != current[k]
                }
                if changed:
                    set_clause = ', '.join(
                        f"{safe_column(c, bulk_allowed_fields)} = ?" for c in changed
                    )
                    cursor.execute(
                        f"UPDATE games SET {set_clause} WHERE id = ?",
                        (*changed.values(), row[0]),
                    )

        conn.commit()

    # Pass 34.7: keep structured — user_id + field names + count only.
    from flask import g as _flask_g
    user_id = getattr(_flask_g, 'user', None) and _flask_g.user.get('id')
    logger.info(
        "games_bulk_edit count=%d user_id=%s fields=%s",
        len(game_ids), user_id, list(fields.keys()),
    )

    invalidate_filter_cache()
    invalidate_analytics_cache()

    return success(
        updated=len(game_ids),
    )



@bp.route('/api/game/<int:game_id>/completion', methods=['POST'])
@login_required
@permission_required('track_progress')
@permission_required('edit')
def api_update_completion(game_id):
    """Update game completion status.

    Pass 41.9 — drop @editor_required to login + 'track_progress' permission.
    Marking your own copy as played/completed is a self-tracking action.
    But the completion column is still global on `games`, so a write here
    changes every user's library: PASS-59-63 also requires 'edit' until the
    per-user move lands, then the 'edit' line goes.
    """
    try:
        data = request.get_json() or {}
        status = data.get('status', 'not_started')

        if status not in VALID_COMPLETION_STATUSES:
            return error(_('Invalid status'), 400)

        execute("UPDATE games SET completion_status = ? WHERE id = ?", (status, game_id))

        return success(status=status)
    except Exception as e:
        logger.error(f"Completion update error: {e}")
        return error(_('An internal error occurred'), 500)


@bp.route('/api/game/<int:game_id>/track-view', methods=['POST'])
@login_required
@permission_required('track_progress')
def api_track_view(game_id):
    """Track that a game was viewed (for recently viewed).

    Pass 41.9 — write into per-user `user_game_views` table (migration 010)
    instead of the shared `games.last_viewed` column. The shared-column
    shape leaked viewing history across users; the per-user upsert keys
    on (user_id, game_id) so each user's panel reflects only their own
    navigation.
    """
    try:
        user_id = g.user['id'] if g.user else None
        if user_id is None:
            return error(_('Not authenticated'), 401)
        now_iso = datetime.now(timezone.utc).isoformat()
        execute(
            "INSERT INTO user_game_views (user_id, game_id, last_viewed) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, game_id) DO UPDATE SET "
            "last_viewed = excluded.last_viewed",
            (user_id, game_id, now_iso),
        )
        return success()
    except Exception as e:
        logger.error(f"track-view error: {e}")
        return error(_('An internal error occurred'), 500)


# Pass 41.9 — `/api/recently-viewed` deleted. Zero callers (the dashboard
# uses an inline `query()` against `app.py:1008`, never this endpoint).
# The cross-user leak it formerly returned is now closed at source: the
# dashboard query joins `user_game_views` per-user (see app.py).


@bp.route('/api/filter-games')
@login_required
@handle_api_errors
def api_filter_games():
    """Filter games by genre, publisher, developer, franchise, or player mode"""
    filter_type = request.args.get('type', '')
    filter_value = request.args.get('value', '')
    sort_by = request.args.get('sort', 'title')

    if not filter_type or not filter_value:
        return error(_('Filter type and value required'), 400)

    column_map = {
        'genre': 'genre',
        'publisher': 'publisher',
        'developer': 'developer',
        'modes': 'modes',
        'franchise': 'franchise',
        'series': 'franchise'
    }

    column = column_map.get(filter_type)
    if not column:
        return error(_('Invalid filter type'), 400)

    if sort_by == 'release_date':
        order_clause = "ORDER BY g.release_date ASC, COALESCE(g.sort_title, g.title) COLLATE NOCASE"
    elif sort_by == 'platform':
        order_clause = "ORDER BY s.name COLLATE NOCASE, COALESCE(g.sort_title, g.title) COLLATE NOCASE"
    else:
        order_clause = "ORDER BY COALESCE(g.sort_title, g.title) COLLATE NOCASE"

    # Pass 25.8 — hard row cap. Previously uncapped; a filter matching every
    # genre on a 50 000-game library would ship every row in one response.
    limit_clause = f"LIMIT {int(getattr(config, 'MAX_LIST_ROWS', 500))}"

    if filter_type == 'modes':
        if 'single' in filter_value.lower():
            games = query(f"""
                SELECT g.*, s.name AS system_name
                FROM games g
                JOIN systems s ON g.system_id = s.id
                WHERE g.{column} LIKE '%Single%' OR g.players = 1
                {order_clause}
                {limit_clause}
            """)
        elif 'multi' in filter_value.lower():
            games = query(f"""
                SELECT g.*, s.name AS system_name
                FROM games g
                JOIN systems s ON g.system_id = s.id
                WHERE g.{column} LIKE '%Multi%' OR g.players > 1
                {order_clause}
                {limit_clause}
            """)
        else:
            games = query(f"""
                SELECT g.*, s.name AS system_name
                FROM games g
                JOIN systems s ON g.system_id = s.id
                WHERE g.{column} LIKE ? ESCAPE '\\'
                {order_clause}
                {limit_clause}
            """, (f'%{escape_like(filter_value)}%',))
    else:
        games = query(f"""
            SELECT g.*, s.name AS system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.{column} LIKE ? ESCAPE '\\'
            {order_clause}
            {limit_clause}
        """, (f'%{escape_like(filter_value)}%',))

    result_games = []
    # Pass 48.5 — loop var `row` (not `g`) to avoid shadowing `from flask import g`.
    for row in games:
        result_games.append({
            'id': row['id'],
            'title': row['title'],
            'system_name': row['system_name'],
            'boxart': row['boxart'],
            'genre': row['genre'],
            'release_date': row['release_date'],
            'publisher': row['publisher'],
            'developer': row['developer']
        })

    return success(games=result_games, sort=sort_by)


