# =============================================================================
# RETRODB - Game Search & Comparison Routes
# =============================================================================
# External scraper search, local-library search, similar-games recommendations,
# and side-by-side game comparison.
# =============================================================================

import logging
import re

from flask import Blueprint, render_template, request

from services.api_helpers import handle_api_errors, success, error
from services.auth import login_required
from services.database import query
from services.game_query import escape_like

logger = logging.getLogger(__name__)

bp = Blueprint('games_search', __name__)

# Scraper manager with graceful fallback when scrapers are unavailable
try:
    from scraper.scraper_manager import scraper_manager
    search_games = scraper_manager.search_games
except ImportError:
    def search_games(*args, **kwargs):
        return []


@bp.route('/api/games/search')
@login_required
@handle_api_errors
def api_search_games():
    """Search games API for scraping."""
    title = request.args.get('title', '')
    system = request.args.get('system', '')
    folder = request.args.get('folder', '')

    if not title:
        return error('Title required', 400)

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

    results = search_games(clean_title, system, system_folder=folder, limit=15)

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

    return success(results=results)


@bp.route('/api/games/find')
@login_required
def api_local_search_games():
    """Search local game library by title. Used by lists, compare, etc."""
    q = request.args.get('q', '').strip()
    limit = min(request.args.get('limit', 20, type=int), 50)

    if not q or len(q) < 2:
        return success(games=[])

    escaped_q = escape_like(q)
    games_list = query("""
        SELECT g.id, g.title, g.boxart, s.name AS system_name
        FROM games g
        LEFT JOIN systems s ON g.system_id = s.id
        WHERE g.title LIKE ? ESCAPE '\\' COLLATE NOCASE
        ORDER BY g.title COLLATE NOCASE
        LIMIT ?
    """, (f'%{escaped_q}%', limit))

    return success(games=games_list or [])


@bp.route('/api/games/<int:game_id>/similar')
@login_required
def api_similar_games(game_id):
    """Find similar games based on genre, developer, and franchise."""
    try:
        game = query("SELECT genre, developer, franchise, system_id FROM games WHERE id = ?", [game_id], one=True)
        if not game:
            return success(games=[])

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
                        similar.append({'id': m['id'], 'title': m['title'], 'boxart': m['boxart'], 'system_name': m['system_name'], 'reason': 'Same genre & developer'})
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
                        similar.append({'id': m['id'], 'title': m['title'], 'boxart': m['boxart'], 'system_name': m['system_name'], 'reason': 'Similar genre on same system'})
                        seen_ids.add(m['id'])

        return success(games=similar[:8])
    except Exception as e:
        logger.error(f"Similar games error: {e}")
        return success(games=[])


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
        by_id = {r['id']: r for r in rows}
        games = [by_id[gid] for gid in game_ids if gid in by_id]
    return render_template('compare_games.html', games=games)


@bp.route('/api/games/compare')
@login_required
def api_compare_games():
    """Return comparison data for two games."""
    game_ids = request.args.getlist('id', type=int)
    if len(game_ids) < 2:
        return error('Two game IDs required', 400)

    ids = game_ids[:2]
    placeholders = ','.join('?' for _ in ids)
    rows = query(f"""
        SELECT g.*, s.name AS system_name, s.folder AS system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.id IN ({placeholders})
    """, tuple(ids))
    by_id = {r['id']: dict(r) for r in rows}
    results = [by_id[gid] for gid in ids if gid in by_id]

    if len(results) < 2:
        return error('One or both games not found', 404)

    return success(games=results)
