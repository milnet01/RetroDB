# =============================================================================
# RETRODB - Trophies Routes Blueprint
# =============================================================================
# Handles RPCS3 local trophies and PSN trophy integration.
# =============================================================================

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, g
import os
import logging
import json
import requests
import threading
import sqlite3
from datetime import datetime

import config
from services.database import get_db, query, execute
from services.auth import login_required, admin_required, get_user_settings
from services.jobs.base import _download_psn_trophy_image as download_psn_trophy_image

# PSN API imports
try:
    from psnawp_api import PSNAWP
    from psnawp_api.core.psnawp_exceptions import PSNAWPNotFoundError, PSNAWPAuthenticationError
    PSNAWP_AVAILABLE = True

    # Patch pyrate_limiter + PSNAWP compatibility issues:
    # 1. pyrate_limiter 4.x sync _try_acquire raises NotImplementedError on timeout param
    # 2. PSNAWP 3.x has inverted logic: `if try_acquire(): raise TooManyRequests` which
    #    blocks ALL requests when _try_acquire is patched to actually work (returns True
    #    on success, but PSNAWP treats True as "rate limited").
    # Fix: make _try_acquire always return False (PSNAWP interprets as "not rate limited,
    # proceed"). Our own 2.5s delay between games provides sufficient rate limiting.
    try:
        from pyrate_limiter import Limiter as _Limiter

        def _patched_try_acquire(self, name, weight=1, blocking=True, timeout=-1, _force_async=False):
            return False  # Always allow — PSNAWP checks `if try_acquire(): raise error`

        _Limiter._try_acquire = _patched_try_acquire
    except (ImportError, AttributeError):
        pass  # pyrate_limiter not available or API changed

except ImportError:
    PSNAWP_AVAILABLE = False
    PSNAWPNotFoundError = Exception  # Fallback for when not installed

logger = logging.getLogger('scraper')

bp = Blueprint('trophies', __name__)


PSN_TOKENS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'psn_tokens.json')


def _load_psn_tokens():
    """Load cached PSN OAuth tokens from file."""
    try:
        if os.path.exists(PSN_TOKENS_FILE):
            with open(PSN_TOKENS_FILE, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.debug(f"Could not load PSN token cache: {e}")
    return None


def _save_psn_tokens(token_response):
    """Save PSN OAuth tokens to file for reuse across restarts."""
    try:
        os.makedirs(os.path.dirname(PSN_TOKENS_FILE), exist_ok=True)
        with open(PSN_TOKENS_FILE, 'w') as f:
            json.dump(dict(token_response), f)
        logger.debug("PSN token cache saved")
    except OSError as e:
        logger.warning(f"Could not save PSN token cache: {e}")


def _clear_psn_tokens():
    """Remove cached PSN tokens."""
    try:
        if os.path.exists(PSN_TOKENS_FILE):
            os.remove(PSN_TOKENS_FILE)
            logger.debug("PSN token cache cleared")
    except OSError:
        pass


def create_psn_client(npsso):
    """Create an authenticated PSNAWP client with token caching.

    Tries cached refresh tokens first (valid ~2 months). Falls back to NPSSO
    if cached tokens are expired. Saves tokens after successful authentication.

    Args:
        npsso: The NPSSO cookie string.

    Returns:
        (psnawp, None) on success, (None, error_string) on failure.
    """
    if not PSNAWP_AVAILABLE:
        return None, "PSNAWP library not installed. Run: pip install psnawp"

    if not npsso:
        return None, "PSN NPSSO cookie not configured"

    # Try cached tokens first
    cached_tokens = _load_psn_tokens()
    if cached_tokens:
        try:
            import time as _time
            refresh_expires = cached_tokens.get('refresh_token_expires_at', 0)
            if refresh_expires > _time.time():
                psnawp = PSNAWP(npsso)
                psnawp.authenticator.token_response = cached_tokens
                # Validate by making a lightweight call
                psnawp.me().online_id
                # Save refreshed tokens (access token may have been renewed)
                _save_psn_tokens(psnawp.authenticator.token_response)
                logger.info("PSN authenticated using cached tokens")
                return psnawp, None
            else:
                logger.info("PSN cached refresh token expired, using NPSSO")
                _clear_psn_tokens()
        except Exception as e:
            logger.info(f"PSN cached tokens invalid ({e}), falling back to NPSSO")
            _clear_psn_tokens()

    # Fresh auth via NPSSO
    try:
        psnawp = PSNAWP(npsso)
        # Force authentication by making a call
        psnawp.me().online_id
        # Cache the tokens for future use
        if psnawp.authenticator.token_response:
            _save_psn_tokens(psnawp.authenticator.token_response)
            logger.info("PSN authenticated via NPSSO, tokens cached")
        return psnawp, None
    except PSNAWPAuthenticationError as e:
        logger.error(f"PSN authentication failed: {e}")
        return None, "PSN authentication failed. Your NPSSO may have expired."
    except Exception as e:
        logger.error(f"PSN connection error: {e}")
        return None, f"PSN connection error: {e}"


def get_psn_client():
    """Get authenticated PSN client using NPSSO from user settings."""
    npsso = ''
    if hasattr(g, 'user_settings') and g.user_settings:
        settings = dict(g.user_settings) if not isinstance(g.user_settings, dict) else g.user_settings
        npsso = settings.get('psn_npsso', '') or ''

    return create_psn_client(npsso)


def get_psn_username():
    """Get configured PSN username from settings"""
    if hasattr(g, 'user_settings') and g.user_settings:
        settings = dict(g.user_settings) if not isinstance(g.user_settings, dict) else g.user_settings
        return settings.get('psn_username', '') or ''
    return ''


def extract_psn_platform(title):
    """
    Extract platform string from PSNAWP TrophyTitle object.
    The title_platform can be a frozenset, enum, or string.
    """
    platform = 'PS4'  # Default
    
    try:
        if hasattr(title, 'title_platform') and title.title_platform:
            tp = title.title_platform
            # Handle frozenset (contains enum values like PlatformType.PS5)
            if isinstance(tp, frozenset):
                for item in tp:
                    item_str = str(item).upper()
                    if 'PS5' in item_str:
                        return 'PS5'
                    elif 'PS4' in item_str:
                        return 'PS4'
                    elif 'PS3' in item_str:
                        return 'PS3'
                    elif 'VITA' in item_str:
                        return 'PSVITA'
            else:
                # Single value - convert to string and check
                tp_str = str(tp).upper()
                if 'PS5' in tp_str:
                    return 'PS5'
                elif 'PS4' in tp_str:
                    return 'PS4'
                elif 'PS3' in tp_str:
                    return 'PS3'
                elif 'VITA' in tp_str:
                    return 'PSVITA'
        
        # Fallback to np_service_name
        if hasattr(title, 'np_service_name') and title.np_service_name:
            service = str(title.np_service_name).lower()
            if 'ps5' in service:
                return 'PS5'
            elif 'ps3' in service:
                return 'PS3'
            elif 'vita' in service:
                return 'PSVITA'
    except (AttributeError, TypeError, ValueError):
        pass  # Platform detection from various PSN API attributes may fail

    return platform


def _clean_title_for_matching(title):
    """Strip all special characters, trademarks, brackets etc. for title matching"""
    import re
    if not title:
        return ''
    # Remove trademark/registered symbols
    cleaned = title.replace('™', '').replace('®', '').replace('©', '')
    # Remove brackets and their content patterns like [PROTOTYPE] -> PROTOTYPE
    # But keep the text inside brackets
    cleaned = cleaned.replace('[', '').replace(']', '')
    cleaned = cleaned.replace('(', '').replace(')', '')
    # Remove colons, dashes used as separators
    cleaned = cleaned.replace(':', '').replace(' - ', ' ')
    # Remove other special characters
    cleaned = re.sub(r'[^\w\s]', '', cleaned)
    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()
    return cleaned


def find_linked_game_for_psn(title, platform):
    """Try to find a matching game in the RetroDB library"""
    import re
    # Clean title for matching - strip all special chars
    clean_title = _clean_title_for_matching(title)

    # Map PSN platform to system folder
    platform_map = {
        'PS3': 'ps3',
        'PS4': 'ps4',
        'PS5': 'ps5',
        'PSVITA': 'psvita',
        'PS Vita': 'psvita'
    }
    system_folder = platform_map.get(platform, '')

    # Try exact match with system (comparing cleaned versions of both titles)
    if system_folder:
        # Fetch all games for this system and compare cleaned titles in Python
        # This avoids SQLite's limited string functions and LIKE bracket issues
        games = query("""
            SELECT g.*, s.name as system_name, s.folder as system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE s.folder = ?
        """, (system_folder,))

        if games:
            for game in games:
                db_clean = _clean_title_for_matching(game['title'])
                if db_clean == clean_title:
                    return dict(game)

    # Try fuzzy match across all PlayStation systems
    # Fetch candidates and compare cleaned titles
    candidates = query("""
        SELECT g.*, s.name as system_name, s.folder as system_folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE s.folder IN ('ps3', 'ps4', 'ps5', 'psvita', 'psx', 'ps2')
    """)

    if candidates:
        # First pass: exact cleaned match (any platform)
        for game in candidates:
            db_clean = _clean_title_for_matching(game['title'])
            if db_clean == clean_title:
                return dict(game)

        # Second pass: one title contains the other
        for game in candidates:
            db_clean = _clean_title_for_matching(game['title'])
            if clean_title and db_clean and (clean_title in db_clean or db_clean in clean_title):
                return dict(game)

    return None


def calculate_rarity_class(rarity):
    """Calculate rarity label and CSS class from percentage"""
    if rarity is None:
        return 'common', 'Common'
    try:
        rarity = float(rarity)
    except (ValueError, TypeError):
        return 'common', 'Common'
    if rarity <= 5:
        return 'ultra-rare', 'Ultra Rare'
    elif rarity <= 15:
        return 'very-rare', 'Very Rare'
    elif rarity <= 30:
        return 'rare', 'Rare'
    else:
        return 'common', 'Common'


def trophy_type_to_letter(trophy_type):
    """Convert PSN API trophy type to single letter"""
    type_map = {
        'platinum': 'P',
        'gold': 'G', 
        'silver': 'S',
        'bronze': 'B'
    }
    return type_map.get(str(trophy_type).lower(), 'B')


# Global trophy cache - keyed by trophy_path to support multiple users
_trophy_cache = {}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_user_trophy_path():
    """Get trophy path for current user, or global if not logged in"""
    if g.user and g.user_settings and g.user_settings['rpcs3_trophy_path']:
        return g.user_settings['rpcs3_trophy_path']
    # Fall back to global setting (app.config includes settings.json override)
    from flask import current_app
    return current_app.config.get('RPCS3_TROPHY_PATH') or getattr(config, 'RPCS3_TROPHY_PATH', None)


def get_trophy_data(trophy_path=None):
    """Get trophy data from RPCS3 - uses per-user path if available"""
    global _trophy_cache
    
    if trophy_path is None:
        trophy_path = get_user_trophy_path()
    
    if not trophy_path or not os.path.exists(trophy_path):
        return {}, {'P': (0, 0), 'G': (0, 0), 'S': (0, 0), 'B': (0, 0)}
    
    # Return cached data if available for this path
    cache_key = trophy_path
    if cache_key in _trophy_cache:
        return _trophy_cache[cache_key].get('sets', {}), _trophy_cache[cache_key].get('totals', {'P': (0, 0), 'G': (0, 0), 'S': (0, 0), 'B': (0, 0)})
    
    try:
        from scraper.trophy_parser import TrophyManager
        manager = TrophyManager(trophy_path)
        trophy_sets = manager.load_all_trophy_sets()
        totals = manager.get_total_trophy_counts()
        
        _trophy_cache[cache_key] = {
            'sets': trophy_sets,
            'totals': totals
        }
        
        return trophy_sets, totals
    except Exception as e:
        logger.error(f"Error loading trophy data: {e}")
        return {}, {'P': (0, 0), 'G': (0, 0), 'S': (0, 0), 'B': (0, 0)}


def find_matching_game(trophy_title):
    """Find a matching game in RetroDB by title (local RPCS3 trophies = PS3)"""
    # Title aliases for common abbreviated names in trophy data
    title_aliases = {
        'MGSV:TPP': 'Metal Gear Solid V: The Phantom Pain',
        'MGSV:GZ': 'Metal Gear Solid V: Ground Zeroes',
        'MGS4': 'Metal Gear Solid 4: Guns of the Patriots',
        'GTAV': 'Grand Theft Auto V',
        'GTA V': 'Grand Theft Auto V',
        'RDR': 'Red Dead Redemption',
    }

    # Check if title is an alias
    search_title = title_aliases.get(trophy_title, trophy_title)
    clean_title = _clean_title_for_matching(search_title)

    # Pass 1: Exact cleaned match on PS3 only
    ps3_games = query("""
        SELECT g.*, s.name AS system_name, s.folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE s.folder = 'ps3'
    """)

    if ps3_games:
        for game in ps3_games:
            if _clean_title_for_matching(game['title']) == clean_title:
                return dict(game)

    # Pass 2: Exact cleaned match across all PlayStation systems
    all_ps_games = query("""
        SELECT g.*, s.name AS system_name, s.folder
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE s.folder IN ('ps3', 'ps4', 'ps5', 'psvita', 'psx', 'ps2')
    """)

    if all_ps_games:
        for game in all_ps_games:
            if _clean_title_for_matching(game['title']) == clean_title:
                return dict(game)

        # Pass 3: Substring match (one contains the other)
        for game in all_ps_games:
            db_clean = _clean_title_for_matching(game['title'])
            if clean_title and db_clean and (clean_title in db_clean or db_clean in clean_title):
                return dict(game)

    return None


@bp.route('/trophies')
@login_required
def trophies():
    """Trophy collection page - per-user trophy data"""
    trophy_path = get_user_trophy_path()
    
    if not trophy_path:
        flash('Please configure your RPCS3 Trophy Path in your profile settings to view trophies', 'info')
        return render_template('local_trophies.html',
                             trophy_sets={},
                             totals={'P': (0, 0), 'G': (0, 0), 'S': (0, 0), 'B': (0, 0)},
                             games_data={},
                             trophy_path_configured=False)
    
    trophy_sets, totals = get_trophy_data(trophy_path)
    
    # Match trophy sets with RetroDB games
    games_data = {}
    for npwr_id, ts in trophy_sets.items():
        game = find_matching_game(ts.title)
        games_data[npwr_id] = game
    
    # Sort trophy sets alphabetically by title
    sorted_trophy_sets = dict(sorted(trophy_sets.items(), key=lambda x: x[1].title.lower()))
    
    return render_template('local_trophies.html',
                         trophy_sets=sorted_trophy_sets,
                         totals=totals,
                         games_data=games_data,
                         trophy_path_configured=True)

@bp.route('/trophies/<npwr_id>')
@login_required
def trophy_game(npwr_id):
    """Individual game trophy page"""
    trophy_sets, _ = get_trophy_data()
    
    if npwr_id not in trophy_sets:
        flash('Trophy set not found', 'error')
        return redirect(url_for('.trophies'))
    
    trophy_set = trophy_sets[npwr_id]
    
    # Find matching RetroDB game
    game = find_matching_game(trophy_set.title)
    
    # Sort trophies
    from datetime import datetime
    unlocked = sorted([t for t in trophy_set.trophies if t.unlocked],
                     key=lambda t: t.unlock_timestamp or datetime.min, reverse=True)
    locked = sorted([t for t in trophy_set.trophies if not t.unlocked],
                   key=lambda t: (t.trophy_type != 'P', t.trophy_type != 'G', t.trophy_type != 'S', t.trophy_id))
    
    # Compute first/last trophy dates from unlocked list
    first_trophy_date = None
    last_trophy_date = None
    for t in unlocked:
        ts = t.unlock_timestamp
        if ts:
            if first_trophy_date is None or ts < first_trophy_date:
                first_trophy_date = ts
            if last_trophy_date is None or ts > last_trophy_date:
                last_trophy_date = ts

    return render_template('local_trophy_detail.html',
                         trophy_set=trophy_set,
                         npwr_id=npwr_id,
                         unlocked=unlocked,
                         locked=locked,
                         game=game,
                         first_trophy_date=first_trophy_date,
                         last_trophy_date=last_trophy_date)

@bp.route('/api/scan-trophies', methods=['POST'])
@admin_required
def api_scan_trophies():
    """Scan RPCS3 trophy folder and copy icons"""
    global _trophy_cache

    trophy_path = get_user_trophy_path()

    if not trophy_path:
        return jsonify({'success': False, 'error': 'RPCS3_TROPHY_PATH not configured'})

    if not os.path.exists(trophy_path):
        return jsonify({'success': False, 'error': f'Trophy path not found: {trophy_path}'})

    try:
        # Clear cache to force fresh scan
        cache_key = trophy_path
        if cache_key in _trophy_cache:
            del _trophy_cache[cache_key]

        # Load all trophy sets
        from scraper.trophy_parser import TrophyManager
        manager = TrophyManager(trophy_path)
        trophy_sets = manager.load_all_trophy_sets()
        totals = manager.get_total_trophy_counts()

        # Cache the results
        _trophy_cache[cache_key] = {
            'sets': trophy_sets,
            'totals': totals
        }

        # Calculate stats for response
        total_games = len(trophy_sets)
        total_trophies = sum(totals[t][1] for t in totals)
        unlocked_trophies = sum(totals[t][0] for t in totals)

        return jsonify({
            'success': True,
            'games_found': total_games,
            'total_trophies': total_trophies,
            'unlocked_trophies': unlocked_trophies,
            'message': f'Scanned {total_games} games with {unlocked_trophies}/{total_trophies} trophies unlocked'
        })
    except Exception as e:
        logger.error(f"Trophy scan error: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


# -----------------------------------------------------------------------------
# PSN TROPHY ROUTES
# -----------------------------------------------------------------------------

@bp.route('/psn-trophies')
@login_required
def psn_trophies():
    """PSN Trophy collection page — lightweight metadata only (games loaded via API)"""
    # Use g.user_settings which is already loaded by load_user()
    psn_username = ''
    psn_npsso = ''

    if g.user_settings:
        # Convert to dict if needed for reliable access
        settings = dict(g.user_settings) if not isinstance(g.user_settings, dict) else g.user_settings
        psn_username = settings.get('psn_username', '') or ''
        psn_npsso = settings.get('psn_npsso', '') or ''

    # Check if PSN is configured
    if not psn_username or not psn_npsso:
        return render_template('psn_trophies.html',
                             psn_configured=False,
                             psn_username='',
                             psn_profile=None,
                             stats={},
                             platform_counts={},
                             total_games=0,
                             available_letters=[])

    # Aggregate stats via SQL (no need to load all game rows)
    stats_row = query("""
        SELECT
            COUNT(*) as total_games,
            COALESCE(SUM(earned_platinum), 0) as platinum_earned,
            COALESCE(SUM(total_platinum), 0) as platinum_total,
            COALESCE(SUM(earned_gold), 0) as gold_earned,
            COALESCE(SUM(total_gold), 0) as gold_total,
            COALESCE(SUM(earned_silver), 0) as silver_earned,
            COALESCE(SUM(total_silver), 0) as silver_total,
            COALESCE(SUM(earned_bronze), 0) as bronze_earned,
            COALESCE(SUM(total_bronze), 0) as bronze_total,
            COALESCE(SUM(earned_trophies), 0) as total_earned,
            COALESCE(SUM(total_trophies), 0) as total_trophies
        FROM psn_games
    """, one=True)

    stats = dict(stats_row) if stats_row else {
        'total_games': 0, 'platinum_earned': 0, 'platinum_total': 0,
        'gold_earned': 0, 'gold_total': 0, 'silver_earned': 0, 'silver_total': 0,
        'bronze_earned': 0, 'bronze_total': 0, 'total_earned': 0, 'total_trophies': 0
    }
    total_games = stats['total_games']

    # Platform counts via SQL
    platform_rows = query("""
        SELECT platform, COUNT(*) as cnt FROM psn_games GROUP BY platform
    """)
    platforms = {r['platform']: r['cnt'] for r in platform_rows} if platform_rows else {}
    platform_counts = {
        'ps5': platforms.get('PS5', 0),
        'ps4': platforms.get('PS4', 0),
        'ps3': platforms.get('PS3', 0),
        'vita': platforms.get('PSVITA', 0) + platforms.get('Vita', 0)
    }

    # Available first-letters for alphabet nav
    letter_rows = query("SELECT DISTINCT UPPER(SUBSTR(title, 1, 1)) AS letter FROM psn_games")
    available_letters = [r['letter'] for r in letter_rows] if letter_rows else []

    # Get sync status
    sync_status = query("SELECT * FROM psn_sync_status LIMIT 1", one=True)

    # Build profile info from sync status
    sync_status_dict = dict(sync_status) if sync_status else {}
    psn_profile = {
        'online_id': psn_username,
        'avatar_url': sync_status_dict.get('avatar_url') or None,
        'trophy_level': sync_status_dict.get('trophy_level') or 0,
        'last_sync': sync_status_dict.get('last_full_sync') if sync_status_dict else None
    }

    return render_template('psn_trophies.html',
                         psn_configured=True,
                         psn_username=psn_username,
                         psn_profile=psn_profile,
                         stats=stats,
                         platform_counts=platform_counts,
                         total_games=total_games,
                         available_letters=available_letters)


@bp.route('/api/psn/games')
@login_required
def api_psn_games():
    """Paginated PSN games API for the PSN trophies page"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = min(request.args.get('per_page', 60, type=int), 200)
        search = request.args.get('search', '').strip()
        letter = request.args.get('letter', '').strip()
        sort = request.args.get('sort', 'name-asc').strip()
        platform = request.args.get('platform', '').strip()

        where_clauses = []
        params = []

        # Search filter
        if search:
            escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where_clauses.append("pg.title LIKE ? ESCAPE '\\'")
            params.append(f'%{escaped}%')

        # Platform filter
        if platform:
            where_clauses.append("LOWER(pg.platform) = ?")
            params.append(platform.lower())

        # Letter filter
        if letter:
            if letter == '#':
                where_clauses.append("UPPER(SUBSTR(pg.title, 1, 1)) NOT BETWEEN 'A' AND 'Z'")
            else:
                where_clauses.append("UPPER(SUBSTR(pg.title, 1, 1)) = ?")
                params.append(letter.upper())

        where_sql = (' WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''

        # Sort
        sort_map = {
            'name-asc': 'pg.title COLLATE NOCASE ASC',
            'name-desc': 'pg.title COLLATE NOCASE DESC',
            'progress-desc': 'pg.progress DESC, pg.title COLLATE NOCASE ASC',
            'progress-asc': 'pg.progress ASC, pg.title COLLATE NOCASE ASC',
            'recent': 'pg.last_trophy_earned DESC, pg.title COLLATE NOCASE ASC',
            'platform': 'pg.platform ASC, pg.title COLLATE NOCASE ASC',
        }
        order_sql = sort_map.get(sort, sort_map['name-asc'])

        # Count
        count_sql = f"SELECT COUNT(*) as total FROM psn_games pg{where_sql}"
        total = query(count_sql, tuple(params), one=True)['total']

        # Data query with pagination
        offset = (page - 1) * per_page
        data_sql = f"SELECT pg.* FROM psn_games pg{where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?"
        data_params = params + [per_page, offset]
        rows = query(data_sql, tuple(data_params))

        total_pages = (total + per_page - 1) // per_page if total > 0 else 1

        games = []
        for r in (rows or []):
            games.append({
                'npwr_id': r['npwr_id'],
                'title': r['title'],
                'platform': r['platform'],
                'icon_url': r['icon_url'],
                'progress': r['progress'] or 0,
                'platinum_earned': r['earned_platinum'] or 0,
                'platinum_total': r['total_platinum'] or 0,
                'gold_earned': r['earned_gold'] or 0,
                'gold_total': r['total_gold'] or 0,
                'silver_earned': r['earned_silver'] or 0,
                'silver_total': r['total_silver'] or 0,
                'bronze_earned': r['earned_bronze'] or 0,
                'bronze_total': r['total_bronze'] or 0,
                'trophies_synced': r['trophies_synced'] or 0,
                'last_trophy_earned': r['last_trophy_earned'],
            })

        return jsonify({
            'games': games,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': total_pages,
            'has_more': page < total_pages,
        })

    except Exception as e:
        logger.error(f"API PSN games error: {e}")
        return jsonify({'error': 'An internal error occurred'}), 500


@bp.route('/api/psn/games/ids')
@login_required
def api_psn_games_ids():
    """Lightweight endpoint returning only npwr_id list for bulk selection"""
    try:
        search = request.args.get('search', '').strip()
        letter = request.args.get('letter', '').strip()
        platform = request.args.get('platform', '').strip()
        filter_type = request.args.get('filter_type', '').strip()

        where_clauses = []
        params = []

        if search:
            escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where_clauses.append("pg.title LIKE ? ESCAPE '\\'")
            params.append(f'%{escaped}%')

        if platform:
            where_clauses.append("LOWER(pg.platform) = ?")
            params.append(platform.lower())

        if letter:
            if letter == '#':
                where_clauses.append("UPPER(SUBSTR(pg.title, 1, 1)) NOT BETWEEN 'A' AND 'Z'")
            else:
                where_clauses.append("UPPER(SUBSTR(pg.title, 1, 1)) = ?")
                params.append(letter.upper())

        if filter_type == 'not_synced':
            where_clauses.append("(pg.trophies_synced IS NULL OR pg.trophies_synced = 0)")
        elif filter_type == 'incomplete':
            where_clauses.append("(pg.progress IS NULL OR pg.progress < 100)")

        where_sql = (' WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
        sql = f"SELECT pg.npwr_id FROM psn_games pg{where_sql} ORDER BY pg.title COLLATE NOCASE ASC"
        rows = query(sql, tuple(params))

        ids = [r['npwr_id'] for r in rows] if rows else []

        return jsonify({'ids': ids, 'count': len(ids)})

    except Exception as e:
        logger.error(f"API PSN games IDs error: {e}")
        return jsonify({'error': 'An internal error occurred'}), 500


@bp.route('/psn-trophies/<npwr_id>')
@login_required
def psn_trophy_detail(npwr_id):
    """PSN Trophy detail page for a specific game"""
    # Get PSN game
    psn_game = query("SELECT * FROM psn_games WHERE npwr_id = ?", (npwr_id,), one=True)
    
    if not psn_game:
        flash('PSN game not found', 'error')
        return redirect(url_for('.psn_trophies'))
    
    psn_game = dict(psn_game)
    
    # Get linked RetroDB game if exists
    game = None
    if psn_game.get('linked_game_id'):
        game_row = query("""
            SELECT g.*, s.name as system_name, s.folder as system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.id = ?
        """, (psn_game['linked_game_id'],), one=True)
        if game_row:
            game = dict(game_row)
    
    # Get all trophies for this game
    trophies = query("""
        SELECT * FROM psn_trophies
        WHERE psn_game_id = ?
        ORDER BY group_id, trophy_id
    """, (psn_game['id'],))
    
    trophies_list = [dict(t) for t in trophies] if trophies else []
    
    # Add rarity class to each trophy first
    for t in trophies_list:
        rarity_class, rarity_label = calculate_rarity_class(t.get('rarity'))
        t['rarity_class'] = rarity_class
        t['rarity_label'] = rarity_label
    
    # Get trophy groups ordered
    trophy_groups = query("""
        SELECT DISTINCT group_id, group_name
        FROM psn_trophies
        WHERE psn_game_id = ?
        ORDER BY group_id
    """, (psn_game['id'],))
    groups_list = [dict(g) for g in trophy_groups] if trophy_groups else []
    
    # Build group order map (default/base game first, then DLC in order)
    # 'default' gets order 0, DLC groups like '001', '002' get 1, 2, etc.
    group_order = {'default': 0}
    dlc_order = 1
    for g in groups_list:
        gid = g.get('group_id') or 'default'
        if gid != 'default':
            group_order[gid] = dlc_order
            dlc_order += 1
    
    # Helper to sort by trophy type priority
    def trophy_sort_key(t):
        return (
            t.get('trophy_type') != 'P',
            t.get('trophy_type') != 'G', 
            t.get('trophy_type') != 'S',
            t.get('trophy_id', 0)
        )
    
    # Organize unlocked trophies by group
    unlocked_by_group = {}
    for t in trophies_list:
        if t.get('earned'):
            gid = t.get('group_id') or 'default'
            gname = t.get('group_name') or 'Base Game'
            if gid not in unlocked_by_group:
                unlocked_by_group[gid] = {'name': gname, 'trophies': [], 'order': group_order.get(gid, 99)}
            unlocked_by_group[gid]['trophies'].append(t)
    
    # Sort trophies within each unlocked group by earned date (newest first)
    for gid in unlocked_by_group:
        unlocked_by_group[gid]['trophies'].sort(key=lambda t: t.get('earned_date') or '', reverse=True)
    
    # Organize locked trophies by group
    locked_by_group = {}
    
    # Smart DLC detection: if platinum is earned, locked trophies must be DLC
    platinum_earned = any(
        t.get('trophy_type') == 'P' and bool(t.get('earned')) 
        for t in trophies_list
    )
    locked_count = sum(1 for t in trophies_list if not bool(t.get('earned')))
    logger.info(f"PSN Trophy Detail - platinum_earned: {platinum_earned}, total: {len(trophies_list)}, locked: {locked_count}")
    
    # Debug: log first few trophies to understand data format
    for i, t in enumerate(trophies_list[:5]):
        logger.info(f"  Trophy {i}: type={repr(t.get('trophy_type'))}, earned={repr(t.get('earned'))}, group_id={repr(t.get('group_id'))}, group_name={repr(t.get('group_name'))}")
    
    for t in trophies_list:
        if not bool(t.get('earned')):
            raw_gid = t.get('group_id')
            raw_gname = t.get('group_name')
            
            # PSN group_id scheme:
            # - 'default' = Base Game
            # - '001' = DLC Pack 1
            # - '002' = DLC Pack 2, etc.
            gid = raw_gid or 'default'
            
            # Determine proper group name based on group_id pattern
            if gid == 'default':
                gname = 'Base Game'
            elif gid.isdigit() and len(gid) == 3:
                # Pattern like '001', '002' - these are DLC packs
                dlc_num = int(gid)
                # Use stored name if it's not generic 'Base Game', otherwise auto-name
                if raw_gname and raw_gname != 'Base Game':
                    gname = raw_gname
                else:
                    gname = f'DLC Trophy Pack {dlc_num}'
            else:
                # Unknown pattern, use stored or fallback
                gname = raw_gname or 'Unknown'
            
            if gid not in locked_by_group:
                locked_by_group[gid] = {'name': gname, 'trophies': [], 'order': group_order.get(gid, 99)}
            locked_by_group[gid]['trophies'].append(t)
    
    # Sort trophies within each locked group by type priority
    for gid in locked_by_group:
        locked_by_group[gid]['trophies'].sort(key=trophy_sort_key)
    
    # Convert to sorted lists for template
    unlocked_groups = sorted(unlocked_by_group.items(), key=lambda x: x[1]['order'])
    locked_groups = sorted(locked_by_group.items(), key=lambda x: x[1]['order'])
    
    # Also keep flat lists for stats/backwards compatibility
    unlocked_trophies = [t for t in trophies_list if t.get('earned')]
    locked_trophies = [t for t in trophies_list if not t.get('earned')]
    
    # Calculate stats
    stats = {
        'earned': psn_game.get('earned_trophies', 0),
        'total': psn_game.get('total_trophies', 0),
        'platinum_earned': psn_game.get('earned_platinum', 0),
        'platinum_total': psn_game.get('total_platinum', 0),
        'gold_earned': psn_game.get('earned_gold', 0),
        'gold_total': psn_game.get('total_gold', 0),
        'silver_earned': psn_game.get('earned_silver', 0),
        'silver_total': psn_game.get('total_silver', 0),
        'bronze_earned': psn_game.get('earned_bronze', 0),
        'bronze_total': psn_game.get('total_bronze', 0)
    }
    
    # Check if game has DLC:
    # - Multiple distinct group_ids from database, OR
    # - Inferred DLC (platinum earned but locked trophies exist), OR
    # - Any non-default group_id in locked_by_group
    has_dlc = (
        len(groups_list) > 1 or 
        'dlc_inferred' in locked_by_group or
        (platinum_earned and len(locked_trophies) > 0)
    )
    
    logger.info(f"PSN Trophy Detail - has_dlc: {has_dlc}, groups_list: {len(groups_list)}, dlc_inferred in locked: {'dlc_inferred' in locked_by_group}")
    logger.info(f"  locked_by_group keys: {list(locked_by_group.keys())}")
    for gid, gdata in locked_by_group.items():
        logger.info(f"  Group '{gid}': name='{gdata['name']}', count={len(gdata['trophies'])}")
    
    # Get HLTB data from linked game (shared data source)
    hltb_data = None
    if game and game.get('playtime_estimate'):
        # Parse playtime_estimate string: "Main: Xh | Main+Extras: Yh | 100%: Zh"
        playtime_str = game['playtime_estimate']
        times = {'main_story': '--', 'main_extra': '--', 'completionist': '--'}
        for part in playtime_str.split(' | '):
            if part.startswith('Main:'):
                times['main_story'] = part.replace('Main:', '').strip()
            elif part.startswith('Main+Extras:'):
                times['main_extra'] = part.replace('Main+Extras:', '').strip()
            elif part.startswith('100%:'):
                times['completionist'] = part.replace('100%:', '').strip()

        hltb_data = {
            'title': game.get('hltb_match_name'),
            'platform': game.get('hltb_match_platform'),
            'confidence': game.get('hltb_match_confidence'),
            'main_story': times['main_story'],
            'main_extra': times['main_extra'],
            'completionist': times['completionist']
        }

    return render_template('psn_trophy_detail.html',
                         psn_game=psn_game,
                         game=game,
                         unlocked_trophies=unlocked_trophies,
                         locked_trophies=locked_trophies,
                         unlocked_groups=unlocked_groups,
                         locked_groups=locked_groups,
                         has_dlc=has_dlc,
                         stats=stats,
                         trophy_groups=groups_list,
                         hltb_data=hltb_data)


# -----------------------------------------------------------------------------
# PSN API ROUTES
# -----------------------------------------------------------------------------

_psn_sync_state = {
    'running': False,
    'phase': 'idle',
    'total': 0,
    'current': 0,
    'current_game': '',
    'games_synced': 0,
    'images_downloaded': 0,
    'error': None
}
_psn_sync_lock = threading.Lock()


@bp.route('/api/psn/sync', methods=['POST'])
@login_required
def api_psn_sync_all():
    """Start PSN trophy sync as a background job"""
    global _psn_sync_state

    with _psn_sync_lock:
        if _psn_sync_state['running']:
            return jsonify({'success': False, 'error': 'Sync already in progress'})

        psnawp, error = get_psn_client()
        if error:
            return jsonify({'success': False, 'error': error})

        _psn_sync_state.update({
            'running': True, 'phase': 'connecting', 'total': 0, 'current': 0,
            'current_game': 'Connecting to PSN...', 'games_synced': 0,
            'images_downloaded': 0, 'error': None
        })

    t = threading.Thread(target=_run_psn_full_sync, args=(psnawp,), daemon=True)
    t.start()

    return jsonify({'success': True, 'started': True})


@bp.route('/api/psn/sync/status')
@login_required
def api_psn_sync_status():
    """Get current PSN full sync progress"""
    with _psn_sync_lock:
        state = dict(_psn_sync_state)
    return jsonify({'success': True, **state})


def _run_psn_full_sync(psnawp):
    """Background worker for full PSN sync with image downloads"""
    global _psn_sync_state

    try:
        client = psnawp.me()
        username = client.online_id

        with _psn_sync_lock:
            _psn_sync_state['phase'] = 'fetching'
            _psn_sync_state['current_game'] = 'Fetching game list from PSN...'

        # Fetch trophy level and avatar URL from PSN profile
        trophy_level = 0
        avatar_url = None
        try:
            summary = client.trophy_summary()
            trophy_level = summary.trophy_level or 0
        except Exception as e:
            logger.warning(f"Could not fetch PSN trophy summary: {e}")
        try:
            profile = client.get_profile_legacy()
            avatars = profile.get('avatarUrls', [])
            if avatars:
                # Use the largest avatar available
                avatar_url = avatars[-1].get('avatarUrl') or avatars[0].get('avatarUrl')
        except Exception as e:
            logger.warning(f"Could not fetch PSN avatar: {e}")

        trophy_titles = list(client.trophy_titles())
        total = len(trophy_titles)
        with _psn_sync_lock:
            _psn_sync_state['total'] = total
            _psn_sync_state['phase'] = 'syncing'

        # Use shared connection factory for consistent PRAGMAs (WAL, 30s busy_timeout, etc.)
        from services.jobs.base import _get_conn, _commit_with_retry
        conn = _get_conn()

        try:
            conn.execute("""
                INSERT OR REPLACE INTO psn_sync_status
                    (id, username, sync_in_progress, last_full_sync, trophy_level, avatar_url)
                VALUES (1, ?, 1, datetime('now'), ?, ?)
            """, (username, trophy_level, avatar_url))
            _commit_with_retry(conn)

            # Pre-fetch all PS games for linking
            all_ps_games = conn.execute("""
                SELECT g.id, g.title, s.folder FROM games g
                JOIN systems s ON g.system_id = s.id
                WHERE s.folder IN ('ps3', 'ps4', 'ps5', 'psvita', 'psx', 'ps2')
            """).fetchall()

            ps_by_folder = {}
            for g in all_ps_games:
                folder = g['folder']
                if folder not in ps_by_folder:
                    ps_by_folder[folder] = []
                ps_by_folder[folder].append(g)

            platform_map = {'PS3': 'ps3', 'PS4': 'ps4', 'PS5': 'ps5', 'PSVITA': 'psvita', 'PS Vita': 'psvita'}

            for i, title in enumerate(trophy_titles):
                with _psn_sync_lock:
                    _psn_sync_state['current'] = i + 1

                try:
                    npwr_id = title.np_communication_id
                    with _psn_sync_lock:
                        _psn_sync_state['current_game'] = title.title_name

                    earned_counts = {
                        'platinum': title.earned_trophies.platinum if title.earned_trophies else 0,
                        'gold': title.earned_trophies.gold if title.earned_trophies else 0,
                        'silver': title.earned_trophies.silver if title.earned_trophies else 0,
                        'bronze': title.earned_trophies.bronze if title.earned_trophies else 0
                    }
                    total_counts = {
                        'platinum': title.defined_trophies.platinum if title.defined_trophies else 0,
                        'gold': title.defined_trophies.gold if title.defined_trophies else 0,
                        'silver': title.defined_trophies.silver if title.defined_trophies else 0,
                        'bronze': title.defined_trophies.bronze if title.defined_trophies else 0
                    }

                    total_earned = sum(earned_counts.values())
                    total_trophies_count = sum(total_counts.values())
                    progress = int((total_earned / total_trophies_count * 100) if total_trophies_count > 0 else 0)

                    platform = extract_psn_platform(title)
                    icon_url = title.title_icon_url if hasattr(title, 'title_icon_url') else None

                    # Find linked game (background-safe, uses pre-fetched data)
                    linked_game_id = None
                    clean_title = _clean_title_for_matching(title.title_name)
                    sf = platform_map.get(platform, '')

                    if clean_title:
                        if sf and sf in ps_by_folder:
                            for g in ps_by_folder[sf]:
                                if _clean_title_for_matching(g['title']) == clean_title:
                                    linked_game_id = g['id']
                                    break

                        if not linked_game_id:
                            for g in all_ps_games:
                                if _clean_title_for_matching(g['title']) == clean_title:
                                    linked_game_id = g['id']
                                    break

                        if not linked_game_id:
                            for g in all_ps_games:
                                db_clean = _clean_title_for_matching(g['title'])
                                if db_clean and (clean_title in db_clean or db_clean in clean_title):
                                    linked_game_id = g['id']
                                    break

                    conn.execute("""
                        INSERT INTO psn_games (
                            npwr_id, title, platform, icon_url, progress,
                            earned_platinum, earned_gold, earned_silver, earned_bronze,
                            total_platinum, total_gold, total_silver, total_bronze,
                            total_trophies, earned_trophies, last_updated, linked_game_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
                        ON CONFLICT(npwr_id) DO UPDATE SET
                            title = excluded.title,
                            platform = excluded.platform,
                            icon_url = excluded.icon_url,
                            progress = excluded.progress,
                            earned_platinum = excluded.earned_platinum,
                            earned_gold = excluded.earned_gold,
                            earned_silver = excluded.earned_silver,
                            earned_bronze = excluded.earned_bronze,
                            total_platinum = excluded.total_platinum,
                            total_gold = excluded.total_gold,
                            total_silver = excluded.total_silver,
                            total_bronze = excluded.total_bronze,
                            total_trophies = excluded.total_trophies,
                            earned_trophies = excluded.earned_trophies,
                            last_updated = datetime('now'),
                            linked_game_id = COALESCE(excluded.linked_game_id, psn_games.linked_game_id)
                    """, (
                        npwr_id, title.title_name, platform, icon_url, progress,
                        earned_counts['platinum'], earned_counts['gold'],
                        earned_counts['silver'], earned_counts['bronze'],
                        total_counts['platinum'], total_counts['gold'],
                        total_counts['silver'], total_counts['bronze'],
                        total_trophies_count, total_earned, linked_game_id
                    ))

                    # Batch commit every 25 games instead of per-game
                    if (i + 1) % 25 == 0:
                        _commit_with_retry(conn)

                    # Download game icon
                    if icon_url:
                        result = download_psn_trophy_image(npwr_id, icon_url)
                        if result:
                            with _psn_sync_lock:
                                _psn_sync_state['images_downloaded'] += 1

                    with _psn_sync_lock:
                        _psn_sync_state['games_synced'] += 1

                except Exception as game_error:
                    logger.warning(f"Error syncing PSN game {title.title_name}: {game_error}")
                    continue

            # Final commit for remaining games + sync status update
            with _psn_sync_lock:
                games_synced = _psn_sync_state['games_synced']
            conn.execute("""
                UPDATE psn_sync_status SET sync_in_progress = 0, total_games = ?
                WHERE id = 1
            """, (games_synced,))
            _commit_with_retry(conn)
        finally:
            conn.close()

        with _psn_sync_lock:
            _psn_sync_state['phase'] = 'complete'
            _psn_sync_state['running'] = False

    except Exception as e:
        logger.error(f"PSN sync error: {e}")
        with _psn_sync_lock:
            _psn_sync_state['phase'] = 'error'
            _psn_sync_state['error'] = 'PSN sync failed. Check logs for details.'
            _psn_sync_state['running'] = False
        try:
            from services.jobs.base import _get_conn as _get_err_conn
            err_conn = _get_err_conn()
            err_conn.execute("UPDATE psn_sync_status SET sync_in_progress = 0 WHERE id = 1")
            err_conn.commit()
            err_conn.close()
        except Exception:
            pass  # Best-effort cleanup during error recovery


@bp.route('/api/psn/sync/<npwr_id>', methods=['POST'])
@login_required
def api_psn_sync_game(npwr_id):
    """Sync trophies for a specific PSN game"""
    psnawp, error = get_psn_client()
    
    if error:
        return jsonify({'success': False, 'error': error})
    
    # Get PSN game from database
    psn_game = query("SELECT * FROM psn_games WHERE npwr_id = ?", (npwr_id,), one=True)
    
    if not psn_game:
        return jsonify({'success': False, 'error': 'Game not found'})
    
    psn_game = dict(psn_game)
    
    try:
        client = psnawp.me()
        
        # Get all trophy titles and find the specific game
        trophy_titles = list(client.trophy_titles())
        
        # Find the matching game
        target_title = None
        for title in trophy_titles:
            if title.np_communication_id == npwr_id:
                target_title = title
                break
        
        if not target_title:
            return jsonify({'success': False, 'error': 'Game not found in your PSN trophy list'})
        
        # Get trophy counts
        earned_counts = {
            'platinum': target_title.earned_trophies.platinum if target_title.earned_trophies else 0,
            'gold': target_title.earned_trophies.gold if target_title.earned_trophies else 0,
            'silver': target_title.earned_trophies.silver if target_title.earned_trophies else 0,
            'bronze': target_title.earned_trophies.bronze if target_title.earned_trophies else 0
        }
        
        total_counts = {
            'platinum': target_title.defined_trophies.platinum if target_title.defined_trophies else 0,
            'gold': target_title.defined_trophies.gold if target_title.defined_trophies else 0,
            'silver': target_title.defined_trophies.silver if target_title.defined_trophies else 0,
            'bronze': target_title.defined_trophies.bronze if target_title.defined_trophies else 0
        }
        
        total_earned = sum(earned_counts.values())
        total_trophies = sum(total_counts.values())
        progress = int((total_earned / total_trophies * 100) if total_trophies > 0 else 0)
        
        # Get icon URL
        icon_url = None
        if hasattr(target_title, 'title_icon_url') and target_title.title_icon_url:
            icon_url = target_title.title_icon_url
        
        # Extract platform using helper
        platform = extract_psn_platform(target_title)
        
        # Update game in database
        execute("""
            UPDATE psn_games SET
                title = ?,
                platform = ?,
                icon_url = COALESCE(?, icon_url),
                progress = ?,
                earned_platinum = ?,
                earned_gold = ?,
                earned_silver = ?,
                earned_bronze = ?,
                total_platinum = ?,
                total_gold = ?,
                total_silver = ?,
                total_bronze = ?,
                total_trophies = ?,
                earned_trophies = ?,
                last_updated = datetime('now'),
                trophies_synced = 1
            WHERE npwr_id = ?
        """, (
            target_title.title_name,
            platform,
            icon_url,
            progress,
            earned_counts['platinum'],
            earned_counts['gold'],
            earned_counts['silver'],
            earned_counts['bronze'],
            total_counts['platinum'],
            total_counts['gold'],
            total_counts['silver'],
            total_counts['bronze'],
            total_trophies,
            total_earned,
            npwr_id
        ))

        # Download game icon locally
        if icon_url:
            download_psn_trophy_image(npwr_id, icon_url)

        # Sync individual trophies
        trophies_synced = 0
        first_trophy_date = None
        last_trophy_date = None
        
        try:
            logger.info(f"Attempting to sync individual trophies for {npwr_id}")
            
            # title_platform is a frozenset of PlatformType enums - extract one
            title_platform = target_title.title_platform
            if title_platform and len(title_platform) > 0:
                # Get first platform from the frozenset
                platform_enum = next(iter(title_platform))
                logger.info(f"Using platform_enum: {platform_enum}, type: {type(platform_enum)}")
            else:
                logger.warning(f"No platform found for {npwr_id}, skipping trophy sync")
                raise Exception("No platform available")
            
            # Get trophies using the proper PlatformType enum
            # include_progress=True is required to get earned status and dates
            # trophy_group_id="all" fetches ALL trophy groups including DLC
            trophies = list(client.trophies(
                np_communication_id=npwr_id, 
                platform=platform_enum, 
                trophy_group_id="all",  # CRITICAL: "all" gets base game + DLC trophies
                include_progress=True
            ))
            
            logger.info(f"Total trophies fetched: {len(trophies)}")
            
            # Fetch trophy group summaries to get proper DLC names
            # PSN provides group names via trophy_groups_summary, not individual trophies
            group_names_from_api = {'default': 'Base Game'}
            try:
                groups_summary = client.trophy_groups_summary(npwr_id, platform=platform_enum)
                if hasattr(groups_summary, 'trophy_groups'):
                    for g in groups_summary.trophy_groups:
                        gid = getattr(g, 'trophy_group_id', None)
                        gname = getattr(g, 'trophy_group_name', None)
                        if gid and gname:
                            group_names_from_api[gid] = gname
                            logger.info(f"Group from API: {gid} -> {gname}")
            except Exception as ge:
                logger.warning(f"Could not fetch trophy groups summary: {ge}")
            
            # Track DLC groups for auto-naming
            dlc_group_counter = 0
            seen_groups = {}  # group_id -> group_name
            
            # Check for existing custom names (user-edited)
            existing_groups = query("""
                SELECT DISTINCT group_id, group_name FROM psn_trophies
                WHERE psn_game_id = ? AND group_id != 'default'
            """, (psn_game['id'],))
            custom_group_names = {g['group_id']: g['group_name'] for g in existing_groups} if existing_groups else {}
            
            for trophy in trophies:
                try:
                    # Extract trophy data
                    trophy_id = trophy.trophy_id if hasattr(trophy, 'trophy_id') else None
                    if trophy_id is None:
                        continue
                    
                    # Debug: log trophy attributes for first trophy
                    if trophies_synced == 0:
                        logger.info(f"Trophy object type: {type(trophy)}")
                        logger.info(f"Trophy attributes: {[a for a in dir(trophy) if not a.startswith('_')]}")
                    
                    # Get group info from API
                    group_id = getattr(trophy, 'trophy_group_id', None) or 'default'
                    
                    # Debug: log group info for first 5 trophies
                    if trophies_synced < 5:
                        api_name = group_names_from_api.get(group_id, 'NOT_FOUND')
                        logger.info(f"Trophy {trophy_id}: group_id={repr(group_id)}, api_name={repr(api_name)}")
                    
                    # Determine final group name - priority order:
                    # 1. User-edited custom name
                    # 2. API-provided group name (from trophy_groups_summary)
                    # 3. Auto-generated DLC name
                    if group_id == 'default':
                        group_name = 'Base Game'
                    elif group_id in custom_group_names and custom_group_names[group_id] != 'Base Game':
                        # Preserve user-edited name (but not stale "Base Game" from old sync)
                        group_name = custom_group_names[group_id]
                    elif group_id in group_names_from_api:
                        # Use API-provided name from trophy_groups_summary
                        group_name = group_names_from_api[group_id]
                    elif group_id in seen_groups:
                        # Already assigned a name this sync
                        group_name = seen_groups[group_id]
                    else:
                        # Auto-generate name for unnamed DLC based on group_id pattern
                        if group_id.isdigit() and len(group_id) == 3:
                            dlc_num = int(group_id)
                            group_name = f"DLC Trophy Pack {dlc_num}"
                        else:
                            dlc_group_counter += 1
                            group_name = f"DLC Set {dlc_group_counter}"
                        seen_groups[group_id] = group_name
                    
                    # Get trophy details
                    trophy_name = getattr(trophy, 'trophy_name', '') or ''
                    trophy_detail = getattr(trophy, 'trophy_detail', '') or ''
                    
                    # Get trophy type - handle enum properly
                    trophy_type_raw = getattr(trophy, 'trophy_type', None)
                    trophy_type_str = 'bronze'  # default
                    if trophy_type_raw is not None:
                        # Try .name attribute first (for enums like TrophyType.GOLD)
                        if hasattr(trophy_type_raw, 'name'):
                            trophy_type_str = trophy_type_raw.name.lower()
                        elif hasattr(trophy_type_raw, 'value'):
                            trophy_type_str = str(trophy_type_raw.value).lower()
                        else:
                            trophy_type_str = str(trophy_type_raw).lower()
                            # Handle enum format like "TrophyType.GOLD"
                            if '.' in trophy_type_str:
                                trophy_type_str = trophy_type_str.split('.')[-1].lower()
                    trophy_type = trophy_type_to_letter(trophy_type_str)
                    
                    trophy_icon = getattr(trophy, 'trophy_icon_url', None)

                    # Download trophy icon locally
                    if trophy_icon:
                        download_psn_trophy_image(npwr_id, trophy_icon, trophy_id=trophy_id)

                    # Earned status - check multiple possible attributes
                    earned = getattr(trophy, 'earned', None)
                    if earned is None:
                        earned = getattr(trophy, 'is_earned', None)
                    if earned is None:
                        earned = False
                    
                    # Debug log for first few trophies - show trophy type details
                    if trophies_synced < 3:
                        logger.info(f"Trophy {trophy_id}: name='{trophy_name}', raw_type={type(trophy_type_raw).__name__}:{trophy_type_raw}, str={trophy_type_str}, letter={trophy_type}, earned={earned}")
                    
                    earned_date = None
                    if hasattr(trophy, 'earned_date_time') and trophy.earned_date_time:
                        earned_date = trophy.earned_date_time.isoformat()
                        # If we have an earned date, the trophy must be earned
                        earned = True
                    
                    # Track first and last trophy dates
                    if earned and earned_date:
                        if first_trophy_date is None or earned_date < first_trophy_date:
                            first_trophy_date = earned_date
                        if last_trophy_date is None or earned_date > last_trophy_date:
                            last_trophy_date = earned_date
                    
                    # Rarity
                    rarity = getattr(trophy, 'trophy_earn_rate', None)
                    rarity_class, rarity_label = calculate_rarity_class(rarity)
                    
                    # Upsert trophy - use DELETE + INSERT as fallback for older DBs without UNIQUE constraint
                    try:
                        execute("""
                            INSERT INTO psn_trophies (
                                psn_game_id, trophy_id, group_id, group_name,
                                name, description, trophy_type, icon_url,
                                rarity, rarity_label, earned, earned_date
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(psn_game_id, trophy_id) DO UPDATE SET
                                group_id = excluded.group_id,
                                group_name = excluded.group_name,
                                name = excluded.name,
                                description = excluded.description,
                                trophy_type = excluded.trophy_type,
                                icon_url = excluded.icon_url,
                                rarity = excluded.rarity,
                                rarity_label = excluded.rarity_label,
                                earned = excluded.earned,
                                earned_date = excluded.earned_date
                        """, (
                            psn_game['id'],
                            trophy_id,
                            group_id,
                            group_name,
                            trophy_name,
                            trophy_detail,
                            trophy_type,
                            trophy_icon,
                            rarity,
                            rarity_label,
                            1 if earned else 0,
                            earned_date
                        ))
                    except Exception as upsert_error:
                        if 'ON CONFLICT' in str(upsert_error):
                            # Fallback: DELETE then INSERT for DBs without UNIQUE constraint
                            execute("DELETE FROM psn_trophies WHERE psn_game_id = ? AND trophy_id = ?",
                                    (psn_game['id'], trophy_id))
                            execute("""
                                INSERT INTO psn_trophies (
                                    psn_game_id, trophy_id, group_id, group_name,
                                    name, description, trophy_type, icon_url,
                                    rarity, rarity_label, earned, earned_date
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                psn_game['id'],
                                trophy_id,
                                group_id,
                                group_name,
                                trophy_name,
                                trophy_detail,
                                trophy_type,
                                trophy_icon,
                                rarity,
                                rarity_label,
                                1 if earned else 0,
                                earned_date
                            ))
                        else:
                            raise
                    
                    trophies_synced += 1
                    
                except Exception as te:
                    logger.warning(f"Error syncing trophy: {te}")
                    continue
            
            # Update first and last trophy dates if we found any
            if first_trophy_date or last_trophy_date:
                execute("""
                    UPDATE psn_games SET 
                        first_trophy_earned = COALESCE(?, first_trophy_earned),
                        last_trophy_earned = COALESCE(?, last_trophy_earned)
                    WHERE npwr_id = ?
                """, (first_trophy_date, last_trophy_date, npwr_id))
                    
        except Exception as te:
            logger.warning(f"Could not sync individual trophies for {npwr_id}: {te}")
            import traceback
            logger.warning(f"Trophy sync traceback: {traceback.format_exc()}")
            # Continue anyway - game counts are updated
        
        return jsonify({
            'success': True,
            'progress': progress,
            'earned': total_earned,
            'total': total_trophies,
            'trophies_synced': trophies_synced,
            'message': f'Synced {target_title.title_name}: {total_earned}/{total_trophies} trophies ({progress}%)'
        })
        
    except PSNAWPNotFoundError:
        return jsonify({'success': False, 'error': 'Game not found on PSN'})
    except Exception as e:
        logger.error(f"PSN game sync error for {npwr_id}: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/psn/link-game', methods=['POST'])
@login_required
def api_psn_link_game():
    """Link a PSN game to a RetroDB game"""
    data = request.get_json()
    npwr_id = data.get('npwr_id')
    game_id = data.get('game_id')

    if not npwr_id:
        return jsonify({'success': False, 'error': 'Missing npwr_id'})

    try:
        execute("""
            UPDATE psn_games
            SET linked_game_id = ?
            WHERE npwr_id = ?
        """, (game_id if game_id else None, npwr_id))

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/psn/search-games')
@login_required
def api_psn_search_games():
    """Search RetroDB games for manual linking from PSN trophy pages"""
    search_query = request.args.get('q', '').strip()

    if not search_query or len(search_query) < 2:
        return jsonify({'results': []})

    try:
        # Search across all PlayStation systems by default
        escaped = search_query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        search_term = f"%{escaped}%"
        games = query("""
            SELECT g.id, g.title, g.boxart, s.name as system_name, s.folder as system_folder
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.title LIKE ? ESCAPE '\\'
            ORDER BY
                CASE WHEN s.folder IN ('ps3', 'ps4', 'ps5', 'psvita', 'ps2', 'psx') THEN 0 ELSE 1 END,
                g.title COLLATE NOCASE
            LIMIT 20
        """, (search_term,))

        results = []
        if games:
            for g in games:
                results.append({
                    'id': g['id'],
                    'title': g['title'],
                    'system': g['system_name'],
                    'folder': g['system_folder'],
                    'boxart': g['boxart']
                })

        return jsonify({'results': results})

    except Exception as e:
        logger.error(f"PSN game search error: {e}")
        return jsonify({'results': [], 'error': 'An internal error occurred'})


@bp.route('/api/psn/save-hltb', methods=['POST'])
@login_required
def api_psn_save_hltb():
    """Save HLTB match for a PSN game"""
    data = request.get_json()
    npwr_id = data.get('npwr_id')
    hltb_id = data.get('hltb_id')
    hltb_title = data.get('hltb_title')
    hltb_main = data.get('hltb_main')
    hltb_extra = data.get('hltb_extra')
    hltb_complete = data.get('hltb_complete')
    
    if not npwr_id:
        return jsonify({'success': False, 'error': 'Missing npwr_id'})
    
    try:
        execute("""
            UPDATE psn_games 
            SET hltb_id = ?, hltb_title = ?, hltb_main = ?, hltb_extra = ?, hltb_complete = ?
            WHERE npwr_id = ?
        """, (hltb_id, hltb_title, hltb_main, hltb_extra, hltb_complete, npwr_id))
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/psn/edit-group-name', methods=['POST'])
@login_required
def api_psn_edit_group_name():
    """Edit a trophy group name (for DLC sets)"""
    data = request.get_json()
    npwr_id = data.get('npwr_id')
    group_id = data.get('group_id')
    new_name = data.get('name', '').strip()
    
    if not npwr_id or not group_id:
        return jsonify({'success': False, 'error': 'Missing npwr_id or group_id'})
    
    if not new_name:
        return jsonify({'success': False, 'error': 'Name cannot be empty'})
    
    try:
        # Get PSN game ID
        psn_game = query("SELECT id FROM psn_games WHERE npwr_id = ?", (npwr_id,), one=True)
        if not psn_game:
            return jsonify({'success': False, 'error': 'PSN game not found'})
        
        psn_game_id = psn_game['id']
        
        # Update all trophies in this group with the new name
        execute("""
            UPDATE psn_trophies 
            SET group_name = ?
            WHERE psn_game_id = ? AND group_id = ?
        """, (new_name, psn_game_id, group_id))
        
        logger.info(f"Updated group name for {npwr_id} group {group_id} to '{new_name}'")
        
        return jsonify({'success': True, 'name': new_name})
        
    except Exception as e:
        logger.error(f"Error updating group name: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/psn/status')
@login_required
def api_psn_status():
    """Get PSN configuration and sync status"""
    # Check if library is available
    if not PSNAWP_AVAILABLE:
        return jsonify({
            'success': False,
            'configured': False,
            'error': 'PSNAWP library not installed. Run: pip install psnawp'
        })

    user_settings = get_user_settings(g.user['id'])

    # Handle both dict and sqlite3.Row
    if user_settings:
        if isinstance(user_settings, dict):
            psn_username = user_settings.get('psn_username', '')
            psn_npsso = user_settings.get('psn_npsso', '')
        else:
            psn_username = user_settings['psn_username'] if 'psn_username' in user_settings.keys() else ''
            psn_npsso = user_settings['psn_npsso'] if 'psn_npsso' in user_settings.keys() else ''
    else:
        psn_username = ''
        psn_npsso = ''

    configured = bool(psn_username and psn_npsso)

    if not configured:
        return jsonify({
            'success': True,
            'configured': False,
            'username': '',
            'game_count': 0
        })

    # Test the connection (uses token cache)
    try:
        psnawp, error = create_psn_client(psn_npsso)
        if error:
            return jsonify({
                'success': False,
                'configured': True,
                'error': error
            })
        client = psnawp.me()
        online_id = client.online_id

        # Get game count
        try:
            titles = list(client.title_stats())
            game_count = len(titles)
        except (requests.RequestException, OSError, ValueError) as e:
            logger.warning(f"Failed to fetch PSN title stats: {e}")
            game_count = 0

        return jsonify({
            'success': True,
            'configured': True,
            'username': online_id,
            'game_count': game_count
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'configured': True,
            'error': 'An internal error occurred'
        })


@bp.route('/api/psn/token-info')
@login_required
def api_psn_token_info():
    """Get PSN token expiration information for the settings UI."""
    import time as _time

    cached = _load_psn_tokens()
    if not cached:
        return jsonify({'has_token': False})

    refresh_expires = cached.get('refresh_token_expires_at', 0)
    access_expires = cached.get('access_token_expires_at', 0)
    now = _time.time()

    if refresh_expires <= now:
        return jsonify({'has_token': False, 'expired': True})

    return jsonify({
        'has_token': True,
        'expired': False,
        'refresh_expires_at': refresh_expires,
        'days_remaining': max(0, int((refresh_expires - now) / 86400)),
        'access_valid': access_expires > now
    })


@bp.route('/api/psn/save-npsso', methods=['POST'])
@login_required
def api_psn_save_npsso():
    """Quick-save NPSSO token from the setup wizard (saves + tests in one step)."""
    data = request.get_json()
    npsso = (data.get('npsso') or '').strip()
    username = (data.get('username') or '').strip()

    if not npsso:
        return jsonify({'success': False, 'error': 'No NPSSO token provided'})

    # Save to user settings
    from services.database import get_db
    db = get_db()
    db.execute("UPDATE user_settings SET psn_npsso = ?, psn_username = ? WHERE user_id = ?",
               (npsso, username, g.user['id']))
    db.commit()

    # Test the connection
    psnawp, error = create_psn_client(npsso)
    if error:
        return jsonify({'success': False, 'error': error})

    try:
        online_id = psnawp.me().online_id
        # Update username if we got it from PSN
        if online_id and not username:
            db.execute("UPDATE user_settings SET psn_username = ? WHERE user_id = ?",
                       (online_id, g.user['id']))
            db.commit()
        return jsonify({'success': True, 'username': online_id or username})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Connection failed: {e}'})


# -----------------------------------------------------------------------------
# PSN BULK REFRESH API ROUTES
# -----------------------------------------------------------------------------

@bp.route('/api/psn/bulk-refresh/start', methods=['POST'])
@login_required
def api_psn_bulk_refresh_start():
    """Start a bulk PSN trophy refresh job"""
    from services.jobs import psn_refresh_job

    data = request.get_json()
    npwr_ids = data.get('npwr_ids', [])
    return_url = data.get('return_url', '/psn-trophies')

    if not npwr_ids:
        return jsonify({'success': False, 'error': 'No games selected'})

    # Get user's NPSSO token
    npsso = ''
    if g.user_settings:
        settings = dict(g.user_settings) if not isinstance(g.user_settings, dict) else g.user_settings
        npsso = settings.get('psn_npsso', '') or ''

    if not npsso:
        return jsonify({'success': False, 'error': 'PSN NPSSO not configured'})

    result = psn_refresh_job.start(npwr_ids, npsso, return_url)
    return jsonify(result)


@bp.route('/api/psn/bulk-refresh/status')
@login_required
def api_psn_bulk_refresh_status():
    """Get status of PSN bulk refresh job"""
    from services.jobs import psn_refresh_job
    return jsonify({'success': True, **psn_refresh_job.get_status()})


@bp.route('/api/psn/bulk-refresh/pause', methods=['POST'])
@login_required
def api_psn_bulk_refresh_pause():
    """Pause the PSN bulk refresh job"""
    from services.jobs import psn_refresh_job
    return jsonify(psn_refresh_job.pause())


@bp.route('/api/psn/bulk-refresh/resume', methods=['POST'])
@login_required
def api_psn_bulk_refresh_resume():
    """Resume the PSN bulk refresh job"""
    from services.jobs import psn_refresh_job
    return jsonify(psn_refresh_job.resume())


@bp.route('/api/psn/bulk-refresh/cancel', methods=['POST'])
@login_required
def api_psn_bulk_refresh_cancel():
    """Cancel the PSN bulk refresh job"""
    from services.jobs import psn_refresh_job
    return jsonify(psn_refresh_job.cancel())



