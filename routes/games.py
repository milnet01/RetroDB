# =============================================================================
# RETRODB - Games Blueprint
# =============================================================================
# Handles game pages, game API endpoints, HLTB lookup, and game management.
# =============================================================================

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, g
import os
import re
import json
import logging
import time
import threading
from datetime import datetime, timezone

import config
import settings_manager
from services.database import query, execute
from services.auth import login_required, editor_required
from services.security import safe_filename
from services.game_utils import (
    generate_sort_title, map_esrb_to_pegi, map_rating, infer_rating_from_content,
    reset_game_title_from_filename,
    is_ra_supported, get_ra_supported_systems, normalize_platform_name,
    get_preferred_rating, get_all_ratings,
    RATING_SYSTEM_KEYS, RATING_SYSTEMS,
)
from services.game_query import (
    escape_like, get_retroachievements_info, get_trophy_info_for_game,
    get_bonus_discs_for_game, _get_filter_options, _build_games_query,
)

logger = logging.getLogger(__name__)

bp = Blueprint('games', __name__)

# Scraper manager with graceful fallback when scrapers are unavailable
try:
    from scraper.scraper_manager import scraper_manager
    search_games = scraper_manager.search_games
    fetch_game_details = scraper_manager.fetch_game_details
    apply_metadata_to_game = scraper_manager.apply_metadata
    SCRAPER_AVAILABLE = True
except ImportError:
    SCRAPER_AVAILABLE = False

    def search_games(*args, **kwargs):
        return []

    def fetch_game_details(*args, **kwargs):
        return None

    def apply_metadata_to_game(*args, **kwargs):
        return False


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
                COUNT(CASE WHEN (is_bonus_disc = 0 OR is_bonus_disc IS NULL) THEN 1 END) AS total_games,
                COUNT(CASE WHEN scraped = 0 AND (is_bonus_disc = 0 OR is_bonus_disc IS NULL) THEN 1 END) AS total_missing,
                COUNT(CASE WHEN is_bonus_disc = 1 THEN 1 END) AS bonus_count
            FROM games
        """, one=True)
        total_games = counts['total_games']
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
                             total_missing=total_missing,
                             bonus_count=bonus_count,
                             ra_systems=ra_systems,
                             filter_options=filter_options,
                             available_letters=available_letters)
    except Exception as e:
        logger.error(f"All games error: {e}")
        return f"Error loading games: {e}", 500


@bp.route('/api/games')
@login_required
def api_games():
    """Paginated games API for the all-games page"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 100, type=int), 200)

        params = {k: request.args.get(k) for k in
                  ('system', 'system_type', 'genre', 'franchise', 'developer',
                   'publisher', 'modes', 'perspective', 'dimension', 'rating', 'source', 'search', 'letter',
                   'show_bonus', 'ra_only',
                   'not_genre', 'not_franchise', 'not_developer', 'not_publisher',
                   'not_modes', 'not_perspective', 'not_dimension', 'not_rating')
                  if request.args.get(k)}

        # Count query
        count_sql, count_vals = _build_games_query(params, count_only=True)
        total = query(count_sql, tuple(count_vals), one=True)['total']

        # Data query with pagination
        data_sql, data_vals = _build_games_query(params)
        offset = (page - 1) * per_page
        data_sql += " LIMIT ? OFFSET ?"
        data_vals.extend([per_page, offset])
        rows = query(data_sql, tuple(data_vals))

        total_pages = (total + per_page - 1) // per_page if total > 0 else 1

        # Build RPCS3 local trophy mapping for PS3 games
        rpcs3_trophy_map = {}
        has_ps3 = any(r['system_folder'] == 'ps3' for r in rows)
        if has_ps3:
            try:
                from routes.trophies import get_trophy_data, _clean_title_for_matching as _clean_trophy_title
                trophy_sets, _ = get_trophy_data()
                for npwr_id, ts in trophy_sets.items():
                    clean = _clean_trophy_title(ts.title)
                    total = len(ts.base_game_trophies)
                    earned = sum(1 for t in ts.base_game_trophies if t.unlocked)
                    if total > 0 and clean:
                        rpcs3_trophy_map[clean] = {'earned': earned, 'total': total}
            except Exception as e:
                logger.debug(f"RPCS3 trophy lookup skipped: {e}")

        games = []
        for g in rows:
            rp = g['rom_path'] or ''
            import_source = (
                'clz' if rp.startswith('clz_import/') else
                'steam' if rp.startswith('steam_import/') else
                'xbox' if rp.startswith('xbox_import/') else
                'psn' if rp.startswith('psn_import/') else
                None
            )

            # Match RPCS3 local trophies for PS3 games
            rpcs3_info = None
            if g['system_folder'] == 'ps3' and rpcs3_trophy_map:
                try:
                    clean_title = _clean_trophy_title(g['title'])
                    rpcs3_info = rpcs3_trophy_map.get(clean_title)
                except Exception:
                    pass

            games.append({
                'id': g['id'],
                'title': g['title'],
                'sort_title': g['sort_title'],
                'system_id': g['system_id'],
                'system_name': g['system_name'],
                'system_folder': g['system_folder'],
                'system_type': g['system_type'] or '',
                'boxart': g['boxart'],
                'boxart_3d': g['boxart_3d'],
                'fanart': g['fanart'],
                'genre': g['genre'],
                'franchise': g['franchise'],
                'developer': g['developer'],
                'publisher': g['publisher'],
                'release_date': g['release_date'],
                'modes': g['modes'],
                'esrb_rating': g['esrb_rating'],
                'pegi_rating': g['pegi_rating'],
                'cero_rating': g['cero_rating'],
                'usk_rating': g['usk_rating'],
                'acb_rating': g['acb_rating'],
                'fpb_rating': g['fpb_rating'],
                'grac_rating': g['grac_rating'],
                'classind_rating': g['classind_rating'],
                'critic_score': g['critic_score'],
                'critic_score_count': g['critic_score_count'],
                'user_score': g['user_score'],
                'user_score_count': g['user_score_count'],
                'completion_status': g['completion_status'],
                'scraped': g['scraped'],
                'has_retroachievements': g['has_retroachievements'],
                'is_bonus_disc': g['is_bonus_disc'],
                'bonus_count': g['bonus_count'],
                'is_clz_import': import_source == 'clz',
                'import_source': import_source,
                'achievement_earned': g['earned_achievements'],
                'achievement_total': g['achievement_total'],
                'achievement_pct': g['achievement_pct'],
                'achievement_source': g['achievement_source'],
                'psn_earned': g['psn_earned'],
                'psn_total': g['psn_total'],
                'rpcs3_earned': rpcs3_info['earned'] if rpcs3_info else None,
                'rpcs3_total': rpcs3_info['total'] if rpcs3_info else None,
            })

        return jsonify({
            'success': True,
            'games': games,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'has_more': page < total_pages,
        })

    except Exception as e:
        logger.error(f"API games error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/games/ids')
@login_required
def api_games_ids():
    """Lightweight endpoint returning only IDs matching current filters (for bulk select)."""
    try:
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

        # Append unscraped condition if requested
        if params.get('_unscraped'):
            ids_sql = ids_sql.replace("ORDER BY", "AND g.scraped = 0 ORDER BY")

        rows = query(ids_sql, tuple(ids_vals))
        ids = [r['id'] for r in rows]

        return jsonify({'success': True, 'ids': ids, 'total': len(ids)})
    except Exception as e:
        logger.error(f"API games/ids error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/games/card-data')
@login_required
def api_games_card_data():
    """Get card-compatible game data for specific game IDs (for live card refresh)."""
    try:
        ids_param = request.args.get('ids', '')
        if not ids_param:
            return jsonify({'success': False, 'error': 'No IDs provided'}), 400

        game_ids = []
        for part in ids_param.split(','):
            part = part.strip()
            if part.isdigit():
                game_ids.append(int(part))
        if not game_ids or len(game_ids) > 50:
            return jsonify({'success': False, 'error': 'Provide 1-50 valid IDs'}), 400

        placeholders = ','.join('?' * len(game_ids))
        sql = f"""
            SELECT g.id, g.title, g.sort_title, g.system_id, g.boxart, g.boxart_3d,
                   g.fanart, g.genre, g.franchise, g.developer, g.publisher,
                   g.release_date, g.modes, g.esrb_rating, g.pegi_rating,
                   g.cero_rating, g.usk_rating, g.acb_rating, g.fpb_rating,
                   g.grac_rating, g.classind_rating,
                   g.critic_score, g.critic_score_count, g.user_score, g.user_score_count,
                   g.completion_status, g.scraped, g.has_retroachievements,
                   g.is_bonus_disc, g.rom_path, g.ra_achievement_count,
                   s.name AS system_name, s.folder AS system_folder, s.system_type,
                   COALESCE(bc.bonus_count, 0) AS bonus_count,
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
            LEFT JOIN game_achievement_progress gap ON gap.game_id = g.id
            LEFT JOIN (
                SELECT pg.linked_game_id,
                       (pg.earned_bronze + pg.earned_silver + pg.earned_gold + pg.earned_platinum) AS psn_earned,
                       COUNT(pt.id) AS psn_total,
                       pg.progress AS psn_progress
                FROM psn_games pg
                LEFT JOIN psn_trophies pt ON pt.psn_game_id = pg.id
                WHERE pg.linked_game_id IS NOT NULL
                GROUP BY pg.linked_game_id
            ) psn ON psn.linked_game_id = g.id
            WHERE g.id IN ({placeholders})
        """
        rows = query(sql, tuple(game_ids))

        # Build RPCS3 local trophy mapping for PS3 games
        rpcs3_trophy_map = {}
        has_ps3 = any(r['system_folder'] == 'ps3' for r in rows)
        if has_ps3:
            try:
                from routes.trophies import get_trophy_data, _clean_title_for_matching as _clean_trophy_title
                trophy_sets, _ = get_trophy_data()
                for npwr_id, ts in trophy_sets.items():
                    clean = _clean_trophy_title(ts.title)
                    total = len(ts.base_game_trophies)
                    earned = sum(1 for t in ts.base_game_trophies if t.unlocked)
                    if total > 0 and clean:
                        rpcs3_trophy_map[clean] = {'earned': earned, 'total': total}
            except Exception:
                pass

        games = []
        for g in rows:
            rp = g['rom_path'] or ''
            import_source = (
                'clz' if rp.startswith('clz_import/') else
                'steam' if rp.startswith('steam_import/') else
                'xbox' if rp.startswith('xbox_import/') else
                'psn' if rp.startswith('psn_import/') else
                None
            )
            rpcs3_info = None
            if g['system_folder'] == 'ps3' and rpcs3_trophy_map:
                try:
                    from routes.trophies import _clean_title_for_matching as _clean_trophy_title
                    rpcs3_info = rpcs3_trophy_map.get(_clean_trophy_title(g['title']))
                except Exception:
                    pass

            games.append({
                'id': g['id'],
                'title': g['title'],
                'sort_title': g['sort_title'],
                'system_id': g['system_id'],
                'system_name': g['system_name'],
                'system_folder': g['system_folder'],
                'system_type': g['system_type'] or '',
                'boxart': g['boxart'],
                'boxart_3d': g['boxart_3d'],
                'fanart': g['fanart'],
                'genre': g['genre'],
                'franchise': g['franchise'],
                'developer': g['developer'],
                'publisher': g['publisher'],
                'release_date': g['release_date'],
                'modes': g['modes'],
                'esrb_rating': g['esrb_rating'],
                'pegi_rating': g['pegi_rating'],
                'cero_rating': g['cero_rating'],
                'usk_rating': g['usk_rating'],
                'acb_rating': g['acb_rating'],
                'fpb_rating': g['fpb_rating'],
                'grac_rating': g['grac_rating'],
                'classind_rating': g['classind_rating'],
                'critic_score': g['critic_score'],
                'critic_score_count': g['critic_score_count'],
                'user_score': g['user_score'],
                'user_score_count': g['user_score_count'],
                'completion_status': g['completion_status'],
                'scraped': g['scraped'],
                'has_retroachievements': g['has_retroachievements'],
                'is_bonus_disc': g['is_bonus_disc'],
                'bonus_count': g['bonus_count'],
                'import_source': import_source,
                'achievement_earned': g['earned_achievements'],
                'achievement_total': g['achievement_total'],
                'achievement_pct': g['achievement_pct'],
                'achievement_source': g['achievement_source'],
                'psn_earned': g['psn_earned'],
                'psn_total': g['psn_total'],
                'rpcs3_earned': rpcs3_info['earned'] if rpcs3_info else None,
                'rpcs3_total': rpcs3_info['total'] if rpcs3_info else None,
            })

        return jsonify({'success': True, 'games': games})
    except Exception as e:
        logger.error(f"API games/card-data error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


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
            flash("Game not found", "error")
            return redirect(url_for('games.all_games'))

        # Get full system info
        system = query("SELECT * FROM systems WHERE id = ?", (game['system_id'],), one=True)

        search_results = None
        message = None

        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'search':
                title = request.form.get('title', game['title'])
                system_name = game['system_name']

                try:
                    logger.info(f"Searching for: '{title}' on {system_name}")
                    search_results = search_games(title, system_name, limit=10)

                    if not search_results:
                        message = "No results found. Try modifying the search title."
                    else:
                        # Save results for hybrid scraping (cap to prevent session bloat)
                        session['last_search_results'] = search_results[:20]

                        tgdb_count = sum(1 for r in search_results if r.get('source') == 'thegamesdb')
                        igdb_count = sum(1 for r in search_results if r.get('source') == 'igdb')
                        esde_count = sum(1 for r in search_results if r.get('source') == 'esde')
                        message = f"Found {len(search_results)} results (ES-DE: {esde_count}, TGDB: {tgdb_count}, IGDB: {igdb_count})"
                except Exception as e:
                    message = "An error occurred during search"
                    logger.error(f"Search error: {e}")

            elif action == 'apply':
                game_source = request.form.get('game_source')
                use_hybrid = request.form.get('hybrid', 'true') == 'true'

                if not game_source:
                    message = "No game selected."
                else:
                    try:
                        source_parts = game_source.split('_')

                        if len(source_parts) >= 2:
                            source = source_parts[0]
                            source_id = '_'.join(source_parts[1:])
                            system_folder = game['system_folder'] if 'system_folder' in game.keys() else ''

                            if use_hybrid:
                                from scraper.scraper_manager import scraper_manager
                                all_results = session.get('last_search_results', [])

                                # Parse explicit secondary selections from UI checkboxes
                                explicit_secondary = None
                                secondary_json = request.form.get('secondary_selections', '')
                                if secondary_json:
                                    try:
                                        explicit_secondary = json.loads(secondary_json)
                                    except (json.JSONDecodeError, TypeError):
                                        logger.warning("Invalid secondary_selections JSON, ignoring")

                                result = scraper_manager.apply_hybrid_metadata(
                                    db_game_id=game_id,
                                    primary_source=source,
                                    primary_id=source_id,
                                    system_folder=system_folder,
                                    all_results=all_results,
                                    explicit_secondary=explicit_secondary
                                )

                                if result.get('success'):
                                    sources = ', '.join(result.get('sources_used', [source.upper()]))
                                    filled = len(result.get('filled_fields', []))
                                    missing = len(result.get('missing_fields', []))
                                    message = f"Metadata applied from {sources}! ({filled} fields filled, {missing} still missing)"

                                    game = query("""
                                        SELECT g.*, s.name AS system_name, s.folder AS system_folder
                                        FROM games g
                                        JOIN systems s ON g.system_id = s.id
                                        WHERE g.id = ?
                                    """, (game_id,), one=True)
                                else:
                                    message = "Failed to apply metadata."
                            else:
                                game_details = fetch_game_details(source_id, source, system_folder=system_folder)

                                if game_details:
                                    success = apply_metadata_to_game(game_id, game_details, source, system_folder=system_folder)

                                    if success:
                                        message = f"Metadata applied from {source.upper()}!"
                                        game = query("""
                                            SELECT g.*, s.name AS system_name, s.folder AS system_folder
                                            FROM games g
                                            JOIN systems s ON g.system_id = s.id
                                            WHERE g.id = ?
                                        """, (game_id,), one=True)
                                    else:
                                        message = f"Failed to apply metadata from {source.upper()}."
                                else:
                                    message = f"Failed to fetch details from {source.upper()}."
                        else:
                            message = "Invalid game selection."
                    except Exception as e:
                        message = "An error occurred applying metadata"
                        logger.error(f"Apply error: {e}", exc_info=True)

            elif action == 'edit_metadata':
                try:
                    # Get form data
                    title = request.form.get('edit_title', '').strip()
                    sort_title = request.form.get('edit_sort_title', '').strip()
                    publisher = request.form.get('edit_publisher', '').strip()
                    developer = request.form.get('edit_developer', '').strip()
                    genre = request.form.get('edit_genre', '').strip()
                    release_date = request.form.get('edit_release_date', '').strip()
                    if release_date and '/' in release_date:
                        release_date = release_date.replace('/', '-')
                    if release_date:
                        try:
                            datetime.strptime(release_date, '%Y-%m-%d')
                        except ValueError:
                            release_date = ''
                    region = request.form.get('edit_region', '').strip()
                    franchise = request.form.get('edit_franchise', '').strip()
                    other_platforms = request.form.get('edit_other_platforms', '').strip()
                    modes = request.form.get('edit_modes', '').strip()
                    campaign = request.form.get('edit_campaign', '').strip()
                    game_structure = request.form.get('edit_game_structure', '').strip()
                    perspective = request.form.get('edit_perspective', '').strip()
                    dimension = request.form.get('edit_dimension', '').strip()
                    controller_support_custom = request.form.get('edit_controller_support_custom', '').strip()
                    controller_support_dropdown = request.form.get('edit_controller_support', '').strip()
                    controller_support = controller_support_custom or controller_support_dropdown
                    players = request.form.get('edit_players', '').strip()
                    esrb_rating = request.form.get('edit_esrb_rating', '').strip()
                    pegi_rating = request.form.get('edit_pegi_rating', '').strip()
                    cero_rating = request.form.get('edit_cero_rating', '').strip()
                    usk_rating = request.form.get('edit_usk_rating', '').strip()
                    acb_rating = request.form.get('edit_acb_rating', '').strip()
                    fpb_rating = request.form.get('edit_fpb_rating', '').strip()
                    grac_rating = request.form.get('edit_grac_rating', '').strip()
                    classind_rating = request.form.get('edit_classind_rating', '').strip()
                    save_type = request.form.get('edit_save_type', '').strip()
                    similar_games = request.form.get('edit_similar_games', '').strip()
                    similar_games = ', '.join(part.strip() for part in similar_games.split(',') if part.strip())
                    edition = request.form.get('edit_edition', '').strip()
                    description = request.form.get('edit_description', '').strip()

                    if title and not sort_title:
                        sort_title = generate_sort_title(title)

                    # Cross-map empty rating fields from any available rating
                    # 'RP' (Rating Pending) is not a real maturity level — treat as empty
                    _rp_values = {'RP', 'rp'}
                    _local_ratings = {
                        'esrb': esrb_rating, 'pegi': pegi_rating, 'cero': cero_rating,
                        'usk': usk_rating, 'acb': acb_rating, 'fpb': fpb_rating,
                        'grac': grac_rating, 'classind': classind_rating,
                    }
                    for tgt_key in RATING_SYSTEM_KEYS:
                        if _local_ratings[tgt_key] and _local_ratings[tgt_key] not in _rp_values:
                            continue
                        for src_key in RATING_SYSTEM_KEYS:
                            if src_key == tgt_key or not _local_ratings[src_key] or _local_ratings[src_key] in _rp_values:
                                continue
                            mapped = map_rating(src_key, _local_ratings[src_key], tgt_key)
                            if mapped:
                                _local_ratings[tgt_key] = mapped
                                break
                    esrb_rating = _local_ratings['esrb']
                    pegi_rating = _local_ratings['pegi']
                    cero_rating = _local_ratings['cero']
                    usk_rating = _local_ratings['usk']
                    acb_rating = _local_ratings['acb']
                    fpb_rating = _local_ratings['fpb']
                    grac_rating = _local_ratings['grac']
                    classind_rating = _local_ratings['classind']

                    # Handle file uploads
                    boxart_filename = game['boxart']
                    boxart_3d_filename = game['boxart_3d'] if game['boxart_3d'] else ''
                    fanart_filename = game['fanart']
                    screenshots = game['screenshots'] or ''
                    video_filename = game['video'] if game['video'] else ''

                    # Handle file removals
                    def _resolve_media_path(filename, media_type):
                        """Resolve the filesystem path for a media file."""
                        if media_type == 'video':
                            if not filename.startswith('/') and not filename.startswith('videos/'):
                                return os.path.join(config.STATIC_PATH, 'videos', filename)
                            return os.path.join(config.STATIC_PATH, filename.lstrip('/'))
                        else:
                            subdir = media_type  # boxart, boxart_3d, fanart
                            if not filename.startswith('/') and not filename.startswith('images/'):
                                return os.path.join(config.IMAGE_PATH, subdir, filename)
                            return os.path.join(config.STATIC_PATH, filename.lstrip('/'))

                    if request.form.get('remove_boxart') == '1' and boxart_filename:
                        path = _resolve_media_path(boxart_filename, 'boxart')
                        if os.path.exists(path):
                            try:
                                os.remove(path)
                            except Exception as e:
                                logger.warning(f"Could not delete boxart {path}: {e}")
                        boxart_filename = ''

                    if request.form.get('remove_boxart_3d') == '1' and boxart_3d_filename:
                        path = _resolve_media_path(boxart_3d_filename, 'boxart_3d')
                        if os.path.exists(path):
                            try:
                                os.remove(path)
                            except Exception as e:
                                logger.warning(f"Could not delete boxart_3d {path}: {e}")
                        boxart_3d_filename = ''

                    if request.form.get('remove_fanart') == '1' and fanart_filename:
                        path = _resolve_media_path(fanart_filename, 'fanart')
                        if os.path.exists(path):
                            try:
                                os.remove(path)
                            except Exception as e:
                                logger.warning(f"Could not delete fanart {path}: {e}")
                        fanart_filename = ''

                    if request.form.get('remove_video') == '1' and video_filename:
                        path = _resolve_media_path(video_filename, 'video')
                        if os.path.exists(path):
                            try:
                                os.remove(path)
                            except Exception as e:
                                logger.warning(f"Could not delete video {path}: {e}")
                        video_filename = ''

                    # Handle file uploads
                    ALLOWED_IMAGE_EXT = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
                    ALLOWED_VIDEO_EXT = {'mp4', 'webm', 'ogg'}

                    def _save_upload(file_field, dest_dir, game_id, prefix, allowed_ext):
                        """Save an uploaded file if present and valid. Returns new filename or None."""
                        f = request.files.get(file_field)
                        if not f or not f.filename:
                            return None
                        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
                        if ext not in allowed_ext:
                            logger.warning(f"Upload rejected: {f.filename} — extension '{ext}' not allowed")
                            return None
                        os.makedirs(dest_dir, exist_ok=True)
                        new_filename = f"{game_id}_{prefix}.{ext}"
                        f.save(os.path.join(dest_dir, new_filename))
                        logger.info(f"Saved upload: {new_filename} to {dest_dir}")
                        return new_filename

                    img_dir = lambda subdir: os.path.join(config.IMAGE_PATH, subdir)

                    uploaded = _save_upload('custom_boxart', img_dir('boxart'), game_id, 'custom', ALLOWED_IMAGE_EXT)
                    if uploaded:
                        boxart_filename = uploaded
                        try:
                            from services.image_utils import standardize_downloaded_image
                            standardize_downloaded_image(os.path.join(img_dir('boxart'), uploaded), 'boxart')
                        except Exception as e:
                            logger.warning(f"Auto-resize boxart failed: {e}")

                    uploaded = _save_upload('custom_boxart_3d', img_dir('boxart_3d'), game_id, 'custom_3d', ALLOWED_IMAGE_EXT)
                    if uploaded:
                        boxart_3d_filename = uploaded
                        try:
                            from services.image_utils import standardize_downloaded_image
                            standardize_downloaded_image(os.path.join(img_dir('boxart_3d'), uploaded), 'boxart_3d')
                        except Exception as e:
                            logger.warning(f"Auto-resize boxart_3d failed: {e}")

                    uploaded = _save_upload('custom_fanart', img_dir('fanart'), game_id, 'custom_fanart', ALLOWED_IMAGE_EXT)
                    if uploaded:
                        fanart_filename = uploaded

                    uploaded = _save_upload('custom_video', os.path.join(config.STATIC_PATH, 'videos'), game_id, 'custom', ALLOWED_VIDEO_EXT)
                    if uploaded:
                        video_filename = uploaded

                    # Handle screenshot uploads (multiple files)
                    ss_files = request.files.getlist('custom_screenshots')
                    if ss_files and any(f.filename for f in ss_files):
                        ss_dir = img_dir('screenshots')
                        os.makedirs(ss_dir, exist_ok=True)
                        existing = [s.strip() for s in screenshots.split(',') if s.strip()] if screenshots else []
                        next_idx = len(existing) + 1
                        for f in ss_files:
                            if not f.filename:
                                continue
                            ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
                            if ext not in ALLOWED_IMAGE_EXT:
                                continue
                            ss_filename = f"{game_id}_ss{next_idx}.{ext}"
                            f.save(os.path.join(ss_dir, ss_filename))
                            existing.append(ss_filename)
                            next_idx += 1
                            logger.info(f"Saved screenshot: {ss_filename}")
                        screenshots = ','.join(existing)

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
                            save_type = NULLIF(?, ''),
                            similar_games = NULLIF(?, ''),
                            edition = NULLIF(?, ''),
                            description = NULLIF(?, ''),
                            boxart = NULLIF(?, ''),
                            boxart_3d = NULLIF(?, ''),
                            fanart = NULLIF(?, ''),
                            screenshots = NULLIF(?, ''),
                            video = NULLIF(?, '')
                        WHERE id = ?
                    """, (
                        title or game['title'],
                        sort_title,
                        publisher, developer, genre, release_date,
                        region, franchise, other_platforms, modes, campaign, game_structure, perspective, dimension, controller_support, players,
                        esrb_rating, pegi_rating, cero_rating, usk_rating, acb_rating, fpb_rating, grac_rating, classind_rating,
                        save_type, similar_games, edition, description,
                        boxart_filename, boxart_3d_filename, fanart_filename, screenshots, video_filename,
                        game_id
                    ))

                    message = "Metadata updated successfully!"

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
            flash("Game not found after update", "error")
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

        # Achievement & trophy progress for all platforms
        achievement_progress = query("""
            SELECT earned_achievements, total_achievements,
                   completion_percentage, source
            FROM game_achievement_progress WHERE game_id = ?
        """, (game_id,), one=True)

        # PSN trophy progress (if linked)
        psn_progress = query("""
            SELECT pg.id, pg.npwr_id, pg.progress,
                   pg.earned_bronze, pg.earned_silver, pg.earned_gold, pg.earned_platinum,
                   pg.defined_bronze, pg.defined_silver, pg.defined_gold, pg.defined_platinum,
                   (pg.earned_bronze + pg.earned_silver + pg.earned_gold + pg.earned_platinum) AS earned_total,
                   pg.total_trophies AS defined_total
            FROM psn_games pg
            WHERE pg.linked_game_id = ?
        """, (game_id,), one=True)

        # Steam achievement count (from steam_achievements table)
        steam_counts = None
        if game_dict.get('steam_app_id'):
            steam_counts = query("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN achieved = 1 THEN 1 ELSE 0 END) AS earned
                FROM steam_achievements WHERE game_id = ?
            """, (game_id,), one=True)
            if steam_counts and not steam_counts['total']:
                steam_counts = None

        # Xbox achievement count (from xbox_achievements table)
        xbox_counts = None
        if game_dict.get('xbox_title_id'):
            xbox_counts = query("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN achieved = 1 THEN 1 ELSE 0 END) AS earned,
                       SUM(CASE WHEN achieved = 1 THEN gamerscore ELSE 0 END) AS earned_gs,
                       SUM(gamerscore) AS total_gs
                FROM xbox_achievements WHERE game_id = ?
            """, (game_id,), one=True)
            if xbox_counts and not xbox_counts['total']:
                xbox_counts = None

        return render_template('game_detail.html',
                             game=game,
                             system=system,
                             search_results=search_results,
                             message=message,
                             bonus_discs=bonus_discs,
                             parent_game=parent_game,
                             pref_rating={'value': pref_rating_val, 'image': pref_rating_img,
                                          'crossmapped': pref_rating_crossmapped, 'name': pref_rating_name,
                                          'region': pref_rating_region, 'system': pref_sys},
                             all_ratings=all_ratings,
                             retroachievements=get_retroachievements_info(game['title'], game['system_folder']),
                             trophy_info=get_trophy_info_for_game(game['title'], game['system_name']),
                             achievement_progress=achievement_progress,
                             psn_progress=psn_progress,
                             steam_counts=steam_counts,
                             xbox_counts=xbox_counts)
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
        return jsonify({'success': False, 'error': 'Game not found'}), 404

    bonus_count = query(
        "SELECT COUNT(*) as cnt FROM games WHERE parent_game_id = ?",
        (game_id,), one=True
    )['cnt']

    # Achievement progress data
    gap = query("""
        SELECT earned_achievements, total_achievements,
               completion_percentage, source
        FROM game_achievement_progress WHERE game_id = ?
    """, (game_id,), one=True)

    # PSN trophies
    psn = query("""
        SELECT (pg.earned_bronze + pg.earned_silver + pg.earned_gold + pg.earned_platinum) AS psn_earned,
               COUNT(pt.id) AS psn_total
        FROM psn_games pg
        LEFT JOIN psn_trophies pt ON pt.psn_game_id = pg.id
        WHERE pg.linked_game_id = ?
        GROUP BY pg.linked_game_id
    """, (game_id,), one=True)

    # RPCS3 local trophies
    rpcs3_info = None
    if game['system_folder'] == 'ps3':
        try:
            from routes.trophies import get_trophy_data, _clean_title_for_matching
            trophy_sets, _ = get_trophy_data()
            clean_title = _clean_title_for_matching(game['title'])
            for _, ts in trophy_sets.items():
                if _clean_title_for_matching(ts.title) == clean_title:
                    total = len(ts.base_game_trophies)
                    earned = sum(1 for t in ts.base_game_trophies if t.unlocked)
                    if total > 0:
                        rpcs3_info = {'earned': earned, 'total': total}
                    break
        except Exception:
            pass

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

    return jsonify({
        'success': True,
        'game': {
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
        }
    })


@bp.route('/api/game/<int:game_id>/edit', methods=['POST'])
@login_required
def api_game_edit(game_id):
    """Save game edits from modal"""
    try:
        data = request.get_json() or {}

        game = query("SELECT id, title FROM games WHERE id = ?", (game_id,), one=True)
        if not game:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        allowed_fields = [
            'title', 'sort_title', 'franchise', 'similar_games', 'edition',
            'release_date', 'region', 'publisher', 'developer',
            'genre', 'modes', 'players', 'campaign', 'game_structure', 'perspective', 'dimension',
            'controller_support', 'save_type', 'other_platforms',
            'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
            'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
            'description'
        ]

        updates = []
        values = []

        for field in allowed_fields:
            if field in data:
                value = data[field]
                if value == '':
                    value = None
                if field == 'release_date' and value:
                    if '/' in value:
                        value = value.replace('/', '-')
                    try:
                        datetime.strptime(value, '%Y-%m-%d')
                    except ValueError:
                        value = None
                updates.append(f"{field} = ?")
                values.append(value)

        if not updates:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        values.append(game_id)

        execute(f"""
            UPDATE games SET {', '.join(updates)} WHERE id = ?
        """, tuple(values))

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Game edit error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/game/<int:game_id>/ai-fill', methods=['POST'])
@editor_required
def api_game_ai_fill(game_id):
    """Fill missing metadata fields using AI scraper with smart overwrite logic"""
    try:
        game = query("""
            SELECT g.*, s.name AS system_name, s.folder AS system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,), one=True)

        if not game:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        from scraper.scrape_ai import get_game_details as ai_get_details, VALIDATE_FIELDS
        from scraper.hybrid_scraper import should_use_default_controller, get_system_default_controller_name

        # Build existing metadata — blank out fields we want AI to always re-fill
        ai_fields = [
            'genre', 'description', 'developer', 'publisher', 'release_date',
            'players', 'modes', 'esrb_rating', 'pegi_rating', 'cero_rating',
            'usk_rating', 'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
            'region', 'franchise', 'similar_games', 'controller_support', 'save_type',
            'game_structure', 'perspective', 'dimension', 'campaign',
            'other_platforms', 'edition',
            'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
        ]
        # Integer fields that need type conversion before saving
        _int_fields = {'critic_score', 'critic_score_count', 'user_score', 'user_score_count', 'players'}
        existing_metadata = {}
        for field in ai_fields:
            existing_metadata[field] = str(game.get(field, '') or '') or ''

        # Force-request certain fields even when populated
        # similar_games: scraper data is unreliable, always ask AI
        existing_metadata['similar_games'] = ''
        # other_platforms: re-request when placeholder "Exclusive" (AI may know better)
        if (existing_metadata.get('other_platforms', '') or '').strip().lower() == 'exclusive':
            existing_metadata['other_platforms'] = ''
        # controller_support: only ask AI if no curated DB default exists for this system
        db_default_ctrl = get_system_default_controller_name(game['system_id'])
        if not db_default_ctrl and should_use_default_controller(existing_metadata.get('controller_support', '')):
            existing_metadata['controller_support'] = ''
        elif db_default_ctrl:
            # DB default exists — don't waste AI query on this field, post-fill will handle it
            existing_metadata['controller_support'] = db_default_ctrl

        # Call AI scraper
        ai_data = ai_get_details(
            game_id, game['title'], game['system_name'],
            game['system_folder'], existing_metadata=existing_metadata
        )

        if not ai_data:
            return jsonify({
                'success': False,
                'error': 'AI returned no data. Check your API key and provider settings.'
            })

        # Smart overwrite logic — collect all changes, apply in single UPDATE
        filled_fields = []
        all_updates = []
        all_values = []
        for field, value in ai_data.items():
            if field not in ai_fields or not value:
                continue
            current = str(game.get(field, '') or '').strip()
            should_apply = False

            if not current:
                # Empty field — always fill
                should_apply = True
            elif field == 'similar_games':
                # Always overwrite — AI data is more reliable
                should_apply = True
            elif field == 'other_platforms' and current.lower() == 'exclusive':
                # Overwrite placeholder
                should_apply = True
            elif field in VALIDATE_FIELDS and value != current:
                # AI validated an existing field and returned a correction
                should_apply = True
                logger.info(f"AI fill: correcting {field}: '{current}' → '{value}'")

            if should_apply:
                # Convert integer fields from string to int
                if field in _int_fields:
                    try:
                        value = int(float(value))
                    except (ValueError, TypeError):
                        continue
                all_updates.append(f"{field} = ?")
                all_values.append(value)
                filled_fields.append(field)

        # ----- Post-fill fixups (merged into same UPDATE) -----
        # Build a lookup of pending changes to check fixup conditions
        pending = dict(zip(filled_fields, all_values[: len(filled_fields)]))

        # 0. Sort title: generate from title if title exists
        title_val = (game.get('title', '') or '').strip()
        if title_val:
            new_sort = generate_sort_title(title_val)
            if new_sort and new_sort != (game.get('sort_title', '') or ''):
                all_updates.append("sort_title = ?")
                all_values.append(new_sort)

        # 1. Cross-map empty rating fields from any available rating
        # 'RP' (Rating Pending) is not a real maturity level — treat as empty
        _rp_values = {'RP', 'rp'}
        for tgt_key in RATING_SYSTEM_KEYS:
            tgt_col = RATING_SYSTEMS[tgt_key]['db_column']
            tgt_val = pending.get(tgt_col) or (game.get(tgt_col, '') or '').strip()
            if tgt_val and tgt_val not in _rp_values:
                continue
            for src_key in RATING_SYSTEM_KEYS:
                if src_key == tgt_key:
                    continue
                src_col = RATING_SYSTEMS[src_key]['db_column']
                src_val = pending.get(src_col) or (game.get(src_col, '') or '').strip()
                if src_val and src_val not in _rp_values:
                    mapped = map_rating(src_key, src_val, tgt_key)
                    if mapped:
                        all_updates.append(f"{tgt_col} = ?")
                        all_values.append(mapped)
                        filled_fields.append(tgt_col)
                        src_name = RATING_SYSTEMS[src_key]['name']
                        tgt_name = RATING_SYSTEMS[tgt_key]['name']
                        logger.info(f"AI fill: auto-mapped {src_name} '{src_val}' to {tgt_name} '{mapped}'")
                        break

        # 1b. Content-based rating inference (fallback when still no ratings)
        has_any_rating = any(
            (pending.get(RATING_SYSTEMS[k]['db_column']) or (game.get(RATING_SYSTEMS[k]['db_column'], '') or '').strip())
            not in ('', None, 'RP', 'rp')
            for k in RATING_SYSTEM_KEYS
        )
        if not has_any_rating:
            # Build a metadata dict combining pending changes with existing game data
            infer_data = {f: pending.get(f) or (game.get(f, '') or '').strip() for f in ai_fields}
            infer_data['system_folder'] = game.get('system_folder', '')
            inferred = infer_rating_from_content(infer_data)
            if inferred:
                for col, val in inferred.items():
                    all_updates.append(f"{col} = ?")
                    all_values.append(val)
                    filled_fields.append(col)
                logger.info(f"AI fill: inferred ratings from content ({len(inferred)} systems)")

        # 2. Controller: always prefer curated DB default over AI/scraped data
        ctrl = pending.get('controller_support') or (game.get('controller_support', '') or '').strip()
        if db_default_ctrl:
            if ctrl != db_default_ctrl:
                all_updates.append("controller_support = ?")
                all_values.append(db_default_ctrl)
                if 'controller_support' not in filled_fields:
                    filled_fields.append('controller_support')

        # 3. Franchise: clear "Standalone" placeholder
        franchise_val = pending.get('franchise') or (game.get('franchise', '') or '').strip()
        if franchise_val.lower() == 'standalone':
            all_updates.append("franchise = ?")
            all_values.append(None)
            if 'franchise' in filled_fields:
                filled_fields.remove('franchise')

        # 4. Other platforms: deduplicate and sort
        other_plats = pending.get('other_platforms') or (game.get('other_platforms', '') or '').strip()
        if other_plats and other_plats.lower() != 'exclusive':
            parts = [p.strip() for p in other_plats.split(',') if p.strip()]
            seen = set()
            unique = []
            for p in parts:
                if p.lower() not in seen:
                    seen.add(p.lower())
                    unique.append(p)
            sorted_str = ', '.join(sorted(unique))
            if sorted_str != other_plats:
                # Replace the pending other_platforms value in-place
                for i, u in enumerate(all_updates):
                    if u == "other_platforms = ?":
                        all_values[i] = sorted_str
                        break
                else:
                    all_updates.append("other_platforms = ?")
                    all_values.append(sorted_str)
                logger.info(f"AI fill: sorted platforms '{other_plats}' → '{sorted_str}'")

        # 5. Edition fallback: if still empty, set Standard Edition
        edition = pending.get('edition') or (game.get('edition', '') or '').strip()
        if not edition:
            all_updates.append("edition = ?")
            all_values.append('Standard Edition')
            if 'edition' not in filled_fields:
                filled_fields.append('edition')

        # Build scrape history entry
        import json as json_lib
        scrape_history_json = None
        if filled_fields:
            try:
                existing_history = []
                hist_raw = game.get('scrape_history')
                if hist_raw:
                    try:
                        existing_history = json_lib.loads(hist_raw)
                    except (ValueError, TypeError):
                        existing_history = []
                trackable = [
                    'genre', 'description', 'developer', 'publisher', 'release_date',
                    'players', 'modes', 'esrb_rating', 'pegi_rating', 'region',
                    'franchise', 'similar_games', 'controller_support', 'save_type',
                    'game_structure', 'perspective', 'dimension', 'campaign',
                    'other_platforms', 'edition',
                ]
                # Compute still-missing: check pending values first, then DB
                still_missing = []
                for f in trackable:
                    val = pending.get(f) or str(game.get(f, '') or '').strip()
                    if not val:
                        still_missing.append(f)
                history_entry = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'primary_source': 'AI Fill',
                    'sources_used': ['AI'],
                    'fields_filled': [f'{f} (AI)' for f in filled_fields],
                    'fields_missing': still_missing,
                    'scrape_mode': 'ai_fill'
                }
                existing_history.append(history_entry)
                scrape_history_json = json_lib.dumps(existing_history)
            except Exception as e:
                logger.warning(f"AI fill: failed to build scrape history: {e}")

        # Single atomic UPDATE for all changes (fields + fixups + history)
        if scrape_history_json is not None:
            all_updates.append("scrape_history = ?")
            all_values.append(scrape_history_json)

        if all_updates:
            all_values.append(game_id)
            execute(f"UPDATE games SET {', '.join(all_updates)} WHERE id = ?", tuple(all_values))

            # Verify the write took effect
            verify = query("SELECT esrb_rating, edition FROM games WHERE id = ?", (game_id,), one=True)
            if verify:
                v_esrb = (verify.get('esrb_rating', '') or '').strip()
                v_edition = (verify.get('edition', '') or '').strip()
                if 'esrb_rating' in filled_fields and not v_esrb:
                    logger.error(f"AI fill: VERIFICATION FAILED — esrb_rating not persisted for game {game_id}")
                if 'edition' in filled_fields and not v_edition:
                    logger.error(f"AI fill: VERIFICATION FAILED — edition not persisted for game {game_id}")

        # Re-fetch game for response
        updated_game = query("""
            SELECT g.*, s.name AS system_name, s.folder AS system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (game_id,), one=True)

        return jsonify({
            'success': True,
            'filled_fields': filled_fields,
            'filled_count': len(filled_fields),
            'game': {
                'id': updated_game['id'],
                'title': updated_game['title'],
                'genre': updated_game['genre'],
                'description': updated_game['description'],
                'developer': updated_game['developer'],
                'publisher': updated_game['publisher'],
                'release_date': updated_game['release_date'],
                'players': updated_game['players'],
                'modes': updated_game['modes'],
                'esrb_rating': updated_game['esrb_rating'],
                'pegi_rating': updated_game['pegi_rating'],
                'cero_rating': updated_game.get('cero_rating'),
                'usk_rating': updated_game.get('usk_rating'),
                'acb_rating': updated_game.get('acb_rating'),
                'fpb_rating': updated_game.get('fpb_rating'),
                'grac_rating': updated_game.get('grac_rating'),
                'classind_rating': updated_game.get('classind_rating'),
                'region': updated_game['region'],
                'franchise': updated_game['franchise'],
                'similar_games': updated_game['similar_games'],
                'controller_support': updated_game['controller_support'],
                'save_type': updated_game['save_type'],
                'game_structure': updated_game['game_structure'],
                'perspective': updated_game['perspective'],
                'dimension': updated_game['dimension'],
                'campaign': updated_game['campaign'],
                'other_platforms': updated_game['other_platforms'],
                'edition': updated_game['edition'],
            }
        })

    except ImportError:
        return jsonify({'success': False, 'error': 'AI scraper module not available'}), 500
    except Exception as e:
        logger.error(f"AI fill error for game {game_id}: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/games/bulk-edit', methods=['POST'])
@login_required
def api_games_bulk_edit():
    """Bulk edit multiple games at once"""
    try:
        data = request.get_json() or {}
        game_ids = data.get('game_ids', [])
        fields = data.get('fields', {})
        field_modes = data.get('field_modes', {})

        if not game_ids:
            return jsonify({'success': False, 'error': 'No games selected'}), 400

        if not fields:
            return jsonify({'success': False, 'error': 'No fields to update'}), 400

        bulk_allowed_fields = [
            'completion_status', 'genre', 'publisher', 'developer',
            'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
            'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
            'region', 'players',
            'game_structure', 'perspective', 'dimension', 'campaign', 'franchise', 'modes'
        ]

        # Fields that support append mode
        appendable_fields = ['genre', 'publisher', 'developer', 'franchise', 'region', 'game_structure', 'perspective', 'dimension']

        # Separate append fields from replace fields
        append_fields = {}
        replace_updates = []
        replace_values = []

        for field, value in fields.items():
            if field not in bulk_allowed_fields:
                continue
            if value == '':
                value = None

            mode = field_modes.get(field, 'replace')
            if mode == 'append' and field in appendable_fields and value:
                append_fields[field] = value
            else:
                replace_updates.append(f"{field} = ?")
                replace_values.append(value)

        if not replace_updates and not append_fields:
            return jsonify({'success': False, 'error': 'No valid fields to update'}), 400

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

            # Handle append fields — batch updates per field
            # field names are validated against bulk_allowed_fields whitelist — safe for SQL interpolation
            if append_fields:
                placeholders = ','.join('?' for _ in game_ids)
                for field, new_value in append_fields.items():
                    # Games with empty field: set directly in one batch
                    cursor.execute(
                        f"UPDATE games SET {field} = ? WHERE id IN ({placeholders}) AND ({field} IS NULL OR {field} = '')",
                        (new_value, *game_ids)
                    )
                    # Games with existing values: check for duplicates, batch the appends
                    rows = cursor.execute(
                        f"SELECT id, {field} FROM games WHERE id IN ({placeholders}) AND {field} IS NOT NULL AND {field} != ''",
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
                            f"UPDATE games SET {field} = ? WHERE id = ?",
                            updates
                        )

            conn.commit()

        logger.info(f"Bulk edit applied: {len(game_ids)} games, fields: {list(fields.keys())}")

        return jsonify({
            'success': True,
            'updated': len(game_ids)
        })

    except Exception as e:
        logger.error(f"Bulk edit error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/game/<int:game_id>/completion', methods=['POST'])
@login_required
def api_update_completion(game_id):
    """Update game completion status"""
    try:
        data = request.get_json() or {}
        status = data.get('status', 'not_started')

        valid_statuses = ['not_started', 'in_progress', 'played', 'completed', '100_percent']
        if status not in valid_statuses:
            return jsonify({'success': False, 'error': 'Invalid status'})

        execute("UPDATE games SET completion_status = ? WHERE id = ?", (status, game_id))

        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error(f"Completion update error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/game/<int:game_id>/track-view', methods=['POST'])
@login_required
def api_track_view(game_id):
    """Track that a game was viewed (for recently viewed)"""
    try:
        execute("UPDATE games SET last_viewed = ? WHERE id = ?",
               (datetime.now(timezone.utc).isoformat(), game_id))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/recently-viewed')
@login_required
def api_recently_viewed():
    """Get recently viewed games"""
    try:
        limit = request.args.get('limit', 10, type=int)
        games = query("""
            SELECT g.*, s.name as system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.last_viewed IS NOT NULL
            ORDER BY g.last_viewed DESC
            LIMIT ?
        """, (limit,))

        return jsonify({
            'success': True,
            'games': [dict(g) for g in games]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/filter-games')
@login_required
def api_filter_games():
    """Filter games by genre, publisher, developer, franchise, or player mode"""
    filter_type = request.args.get('type', '')
    filter_value = request.args.get('value', '')
    sort_by = request.args.get('sort', 'title')

    if not filter_type or not filter_value:
        return jsonify({'success': False, 'error': 'Filter type and value required'}), 400

    try:
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
            return jsonify({'success': False, 'error': 'Invalid filter type'}), 400

        if sort_by == 'release_date':
            order_clause = "ORDER BY g.release_date ASC, COALESCE(g.sort_title, g.title) COLLATE NOCASE"
        elif sort_by == 'platform':
            order_clause = "ORDER BY s.name COLLATE NOCASE, COALESCE(g.sort_title, g.title) COLLATE NOCASE"
        else:
            order_clause = "ORDER BY COALESCE(g.sort_title, g.title) COLLATE NOCASE"

        if filter_type == 'modes':
            if 'single' in filter_value.lower():
                games = query(f"""
                    SELECT g.*, s.name AS system_name
                    FROM games g
                    JOIN systems s ON g.system_id = s.id
                    WHERE g.{column} LIKE '%Single%' OR g.players = 1
                    {order_clause}
                """)
            elif 'multi' in filter_value.lower():
                games = query(f"""
                    SELECT g.*, s.name AS system_name
                    FROM games g
                    JOIN systems s ON g.system_id = s.id
                    WHERE g.{column} LIKE '%Multi%' OR g.players > 1
                    {order_clause}
                """)
            else:
                games = query(f"""
                    SELECT g.*, s.name AS system_name
                    FROM games g
                    JOIN systems s ON g.system_id = s.id
                    WHERE g.{column} LIKE ? ESCAPE '\\'
                    {order_clause}
                """, (f'%{escape_like(filter_value)}%',))
        else:
            games = query(f"""
                SELECT g.*, s.name AS system_name
                FROM games g
                JOIN systems s ON g.system_id = s.id
                WHERE g.{column} LIKE ? ESCAPE '\\'
                {order_clause}
            """, (f'%{escape_like(filter_value)}%',))

        result_games = []
        for g in games:
            result_games.append({
                'id': g['id'],
                'title': g['title'],
                'system_name': g['system_name'],
                'boxart': g['boxart'],
                'genre': g['genre'],
                'release_date': g['release_date'],
                'publisher': g['publisher'],
                'developer': g['developer']
            })

        return jsonify({'success': True, 'games': result_games, 'sort': sort_by})
    except Exception as e:
        logger.error(f"Filter API error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/games/search')
@login_required
def api_search_games():
    """Search games API for scraping"""
    title = request.args.get('title', '')
    system = request.args.get('system', '')
    folder = request.args.get('folder', '')

    if not title:
        return jsonify({'success': False, 'error': 'Title required'}), 400

    clean_title = title
    patterns_to_remove = [
        r'\(USA\)', r'\(Europe\)', r'\(Japan\)', r'\(World\)', r'\(En\)', r'\(Fr\)', r'\(De\)',
        r'\(U\)', r'\(E\)', r'\(J\)', r'\(UE\)', r'\(JU\)',
        r'\(Rev \d+\)', r'\(Rev[A-Z]\)', r'\(v\d+\.\d+\)',
        r'\[!\]', r'\[b\]', r'\[a\]', r'\[h\]', r'\[o\]', r'\[t\]',
        r'\(Disc \d+\)', r'\(Disk \d+\)',
        r'\(Beta\)', r'\(Proto\)', r'\(Demo\)', r'\(Sample\)',
        r'\(Unl\)', r'\(PD\)', r'\(Pirate\)',
    ]

    for pattern in patterns_to_remove:
        clean_title = re.sub(pattern, '', clean_title, flags=re.IGNORECASE)

    clean_title = re.sub(r'\s+', ' ', clean_title).strip()

    if len(clean_title) < 2:
        clean_title = title

    try:
        results = search_games(clean_title, system, system_folder=folder, limit=15)

        # Apply filename year-hint disambiguation when rom_path is provided
        rom_path = request.args.get('rom_path', '')
        if rom_path and results:
            from services.game_utils import extract_filename_hints
            from services.jobs.bulk_scrape import _extract_year_from_result
            hints = extract_filename_hints(rom_path)
            hint_year = hints.get('year')
            if hint_year:
                for r in results:
                    result_year = _extract_year_from_result(r)
                    if result_year and result_year == hint_year:
                        r['score'] = r.get('score', 0) + 50

        return jsonify({'success': True, 'results': results})
    except Exception as e:
        logger.error(f"API search error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


# =============================================================================
# LOCAL GAME SEARCH API
# =============================================================================

@bp.route('/api/games/find')
@login_required
def api_local_search_games():
    """Search local game library by title. Used by lists, compare, etc."""
    q = request.args.get('q', '').strip()
    limit = min(request.args.get('limit', 20, type=int), 50)

    if not q or len(q) < 2:
        return jsonify({'success': True, 'games': []})

    escaped_q = escape_like(q)
    games_list = query("""
        SELECT g.id, g.title, g.boxart, s.name AS system_name
        FROM games g
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE g.title LIKE ? ESCAPE '\\' COLLATE NOCASE
        ORDER BY g.title COLLATE NOCASE
        LIMIT ?
    """, (f'%{escaped_q}%', limit))

    return jsonify({'success': True, 'games': games_list or []})


# =============================================================================
# SIMILAR GAMES API
# =============================================================================

@bp.route('/api/games/<int:game_id>/similar')
@login_required
def api_similar_games(game_id):
    """Find similar games based on genre, developer, and franchise."""
    try:
        game = query("SELECT genre, developer, franchise, system_id FROM games WHERE id = ?", [game_id], one=True)
        if not game:
            return jsonify({'success': True, 'games': []})

        similar = []
        seen_ids = {game_id}

        # Match by franchise first (strongest signal)
        if game['franchise']:
            franchises = [f.strip() for f in game['franchise'].split(',') if f.strip()]
            for franchise in franchises[:2]:
                matches = query("""
                    SELECT g.id, g.title, g.boxart, s.name AS system_name
                    FROM games g JOIN systems s ON g.system_id = s.id
                    WHERE g.franchise LIKE ? AND g.id != ? AND g.is_bonus_disc = 0
                    ORDER BY g.title LIMIT 5
                """, [f'%{franchise}%', game_id])
                for m in matches:
                    if m['id'] not in seen_ids:
                        similar.append({'id': m['id'], 'title': m['title'], 'boxart': m['boxart'], 'system_name': m['system_name'], 'reason': f'Same franchise: {franchise}'})
                        seen_ids.add(m['id'])

        # Match by genre + developer
        if game['genre'] and game['developer']:
            genres = [g.strip() for g in game['genre'].split(',') if g.strip()]
            devs = [d.strip() for d in game['developer'].split(',') if d.strip()]
            if genres and devs:
                matches = query("""
                    SELECT g.id, g.title, g.boxart, s.name AS system_name
                    FROM games g JOIN systems s ON g.system_id = s.id
                    WHERE g.genre LIKE ? AND g.developer LIKE ? AND g.id != ? AND g.is_bonus_disc = 0
                    ORDER BY g.title LIMIT 5
                """, [f'%{genres[0]}%', f'%{devs[0]}%', game_id])
                for m in matches:
                    if m['id'] not in seen_ids:
                        similar.append({'id': m['id'], 'title': m['title'], 'boxart': m['boxart'], 'system_name': m['system_name'], 'reason': f'Same genre & developer'})
                        seen_ids.add(m['id'])

        # Match by genre on same system (weaker signal, fill remaining)
        if len(similar) < 8 and game['genre']:
            genres = [g.strip() for g in game['genre'].split(',') if g.strip()]
            if genres:
                placeholders = ','.join(['?'] * len(seen_ids))
                matches = query(f"""
                    SELECT g.id, g.title, g.boxart, s.name AS system_name
                    FROM games g JOIN systems s ON g.system_id = s.id
                    WHERE g.genre LIKE ? AND g.system_id = ? AND g.id NOT IN ({placeholders}) AND g.is_bonus_disc = 0
                    ORDER BY RANDOM() LIMIT ?
                """, [f'%{genres[0]}%', game['system_id']] + list(seen_ids) + [8 - len(similar)])
                for m in matches:
                    if m['id'] not in seen_ids:
                        similar.append({'id': m['id'], 'title': m['title'], 'boxart': m['boxart'], 'system_name': m['system_name'], 'reason': f'Similar genre on same system'})
                        seen_ids.add(m['id'])

        return jsonify({'success': True, 'games': similar[:8]})
    except Exception as e:
        logger.error(f"Similar games error: {e}")
        return jsonify({'success': True, 'games': []})


# =============================================================================
# GAME COMPARISON
# =============================================================================

@bp.route('/compare')
@login_required
def compare_games_page():
    """Side-by-side game comparison page."""
    game_ids = request.args.getlist('id', type=int)[:2]
    games = []
    if game_ids:
        placeholders = ','.join('?' for _ in game_ids)
        rows = query(f"""
            SELECT g.*, s.name AS system_name, s.folder AS system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id IN ({placeholders})
        """, tuple(game_ids))
        # Preserve requested order
        by_id = {r['id']: r for r in rows}
        games = [by_id[gid] for gid in game_ids if gid in by_id]
    return render_template('compare_games.html', games=games)


@bp.route('/api/games/compare')
@login_required
def api_compare_games():
    """Return comparison data for two games."""
    game_ids = request.args.getlist('id', type=int)
    if len(game_ids) < 2:
        return jsonify({'success': False, 'error': 'Two game IDs required'}), 400

    ids = game_ids[:2]
    placeholders = ','.join('?' for _ in ids)
    rows = query(f"""
        SELECT g.*, s.name AS system_name, s.folder AS system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id IN ({placeholders})
    """, tuple(ids))
    # Preserve requested order
    by_id = {r['id']: dict(r) for r in rows}
    results = [by_id[gid] for gid in ids if gid in by_id]

    if len(results) < 2:
        return jsonify({'success': False, 'error': 'One or both games not found'}), 404

    return jsonify({'success': True, 'games': results})


# =============================================================================
# GAME MANAGEMENT API ROUTES
# =============================================================================

@bp.route('/api/delete-game/<int:game_id>', methods=['DELETE', 'POST'])
@login_required
def api_delete_game(game_id):
    """Delete a game from the database"""
    try:
        game = query("SELECT id, title, rom_path FROM games WHERE id = ?", (game_id,), one=True)
        if not game:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        # Unlink any records that reference this game via foreign keys
        execute("UPDATE games SET parent_game_id = NULL, is_bonus_disc = 0 WHERE parent_game_id = ?", (game_id,))
        execute("UPDATE psn_games SET linked_game_id = NULL WHERE linked_game_id = ?", (game_id,))

        execute("DELETE FROM games WHERE id = ?", (game_id,))

        logger.info(f"Deleted game from database: {game['title']} (ID: {game_id})")

        return jsonify({
            'success': True,
            'message': f"Game '{game['title']}' deleted from database",
            'game_id': game_id
        })

    except Exception as e:
        logger.error(f"Delete game error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/rename-rom/<int:game_id>', methods=['POST'])
@login_required
def api_rename_rom(game_id):
    """Rename a ROM file on disk and update the database"""
    try:
        data = request.get_json()
        new_filename = data.get('new_filename', '').strip()

        if not new_filename:
            return jsonify({'success': False, 'error': 'No filename provided'}), 400

        invalid_chars = '<>:"/\\|?*'
        if any(c in new_filename for c in invalid_chars):
            return jsonify({'success': False, 'error': f'Filename contains invalid characters: {invalid_chars}'}), 400

        if '..' in new_filename:
            return jsonify({'success': False, 'error': 'Filename cannot contain path traversal sequences'}), 400

        game = query("SELECT id, title, rom_path FROM games WHERE id = ?", (game_id,), one=True)
        if not game:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        old_path = game['rom_path']

        if not os.path.exists(old_path):
            return jsonify({'success': False, 'error': f'ROM file not found on disk: {old_path}'}), 404

        directory = os.path.dirname(old_path)
        new_path = os.path.join(directory, new_filename)

        if os.path.exists(new_path) and new_path != old_path:
            return jsonify({'success': False, 'error': 'A file with that name already exists'}), 400

        try:
            os.rename(old_path, new_path)
            logger.info(f"Renamed ROM: {old_path} -> {new_path}")
        except OSError as e:
            logger.error(f"Failed to rename ROM file: {e}")
            return jsonify({'success': False, 'error': 'Failed to rename file'}), 500

        execute("UPDATE games SET rom_path = ? WHERE id = ?", (new_path, game_id))

        return jsonify({
            'success': True,
            'new_path': new_path,
            'new_filename': new_filename,
            'message': 'ROM file renamed successfully'
        })

    except Exception as e:
        logger.error(f"Rename ROM error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@bp.route('/api/delete-screenshot/<int:game_id>', methods=['POST'])
@login_required
def api_delete_screenshot(game_id):
    """Delete a screenshot from a game"""
    try:
        data = request.get_json()
        screenshot_to_delete = data.get('screenshot')

        if not screenshot_to_delete:
            return jsonify({'success': False, 'error': 'No screenshot specified'})

        if not safe_filename(screenshot_to_delete):
            return jsonify({'success': False, 'error': 'Invalid screenshot filename'}), 400

        game = query("SELECT screenshots FROM games WHERE id = ?", (game_id,), one=True)
        if not game:
            return jsonify({'success': False, 'error': 'Game not found'}), 404

        current = game['screenshots'] or ''
        screenshots = [s.strip() for s in current.split(',') if s.strip()]

        if screenshot_to_delete not in screenshots:
            return jsonify({'success': False, 'error': 'Screenshot not found'})

        screenshots.remove(screenshot_to_delete)
        new_screenshots = ','.join(screenshots)

        execute("UPDATE games SET screenshots = NULLIF(?, '') WHERE id = ?",
                (new_screenshots, game_id))

        screenshot_path = os.path.join(config.IMAGE_PATH, 'screenshots', screenshot_to_delete)
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)
            logger.info(f"Deleted screenshot file: {screenshot_to_delete}")

        return jsonify({
            'success': True,
            'remaining': len(screenshots),
            'screenshots': screenshots
        })

    except Exception as e:
        logger.error(f"Delete screenshot error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500
