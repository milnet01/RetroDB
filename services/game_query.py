# =============================================================================
# RETRODB - Game Query Helpers
# =============================================================================
# Shared helpers for building game-list queries: SQL LIKE escaping, filter
# option aggregation with in-memory caching, and the master WHERE/JOIN builder.
# Extracted from routes/games.py so the query logic can be reused and tested
# independently from the HTTP layer.
# =============================================================================

import logging
import threading
import time

from services.database import query
from services.game_utils import RATING_SYSTEM_KEYS, RATING_SYSTEMS

logger = logging.getLogger(__name__)


def escape_like(value):
    """Escape special SQL LIKE characters so %, _, \\ are matched literally."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def get_retroachievements_info(game_title, system_folder):
    """Get RetroAchievements info for a game."""
    try:
        from scraper.retroachievements import check_retroachievements
        return check_retroachievements(game_title, system_folder)
    except ImportError:
        logger.debug("RetroAchievements module not available")
        return None
    except Exception as e:
        logger.debug(f"RetroAchievements lookup failed: {e}")
        return None


def get_trophy_info_for_game(game_title, system_name):
    """Get RPCS3 trophy info for a PS3 game."""
    if 'playstation 3' not in system_name.lower() and 'ps3' not in system_name.lower():
        return None, None

    try:
        from routes.trophies import get_trophy_data
        trophy_sets, _ = get_trophy_data()
        if not trophy_sets:
            return None, None

        TROPHY_TITLE_ALIASES = {
            'Grand Theft Auto IV': 'GTA IV',
            'Grand Theft Auto V': 'GTA V',
        }

        clean_game_title = game_title.replace('™', '').replace('®', '').strip().lower()

        for npwr_id, ts in trophy_sets.items():
            trophy_title = ts['title'].replace('™', '').replace('®', '').strip()

            if clean_game_title == trophy_title.lower():
                return npwr_id, ts

            for alias_from, alias_to in TROPHY_TITLE_ALIASES.items():
                if clean_game_title == alias_from.lower() and alias_to.lower() in trophy_title.lower():
                    return npwr_id, ts

        return None, None
    except Exception as e:
        logger.debug(f"Trophy lookup failed: {e}")
        return None, None


def get_bonus_discs_for_game(parent_game_id):
    """Get all bonus discs linked to a parent game."""
    return query("""
        SELECT id, title, boxart, rom_path
        FROM games
        WHERE parent_game_id = ? AND is_bonus_disc = 1
        ORDER BY title
    """, (parent_game_id,))


# =============================================================================
# FILTER-OPTIONS CACHE
# =============================================================================

_filter_cache = {}
_filter_cache_time = {}
_filter_cache_lock = threading.Lock()
_FILTER_CACHE_TTL = 60
_FILTER_CACHE_MAX = 50


def invalidate_filter_cache():
    """Clear the filter options cache (call after game data changes)."""
    with _filter_cache_lock:
        _filter_cache.clear()
        _filter_cache_time.clear()


def _get_filter_options(system_id=None):
    """Get unique values for filter dropdowns (genre, franchise, developer, publisher, modes, rating).

    Fetches all five comma-separated fields in a single query to avoid 5 separate
    round-trips, then splits values in Python (necessary for comma-delimited data).
    Results are cached for 60 seconds to avoid re-computing on every page load.
    """
    cache_key = f"filter_{system_id or 'all'}"
    now = time.time()
    with _filter_cache_lock:
        if cache_key in _filter_cache and (now - _filter_cache_time.get(cache_key, 0)) < _FILTER_CACHE_TTL:
            return _filter_cache[cache_key]

    system_filter = ""
    params = ()
    if system_id:
        system_filter = " AND system_id = ?"
        params = (system_id,)

    rows = query(f"""
        SELECT genre, franchise, developer, publisher, modes, perspective, dimension
        FROM games
        WHERE (genre IS NOT NULL OR franchise IS NOT NULL
           OR developer IS NOT NULL OR publisher IS NOT NULL
           OR modes IS NOT NULL OR perspective IS NOT NULL
           OR dimension IS NOT NULL){system_filter}
    """, params)

    field_counts = {f: {} for f in ('genre', 'franchise', 'developer', 'publisher', 'modes', 'perspective', 'dimension')}
    for row in rows:
        for field in field_counts:
            raw = row[field]
            if raw:
                for v in raw.split(','):
                    v = v.strip()
                    if v:
                        field_counts[field][v] = field_counts[field].get(v, 0) + 1

    options = {f: sorted(counts.items(), key=lambda x: x[0].lower())
               for f, counts in field_counts.items()}

    for sys_key in RATING_SYSTEM_KEYS:
        col = RATING_SYSTEMS[sys_key]['db_column']
        if not col.isidentifier():
            continue
        rows = query(f"SELECT {col}, COUNT(*) as cnt FROM games WHERE {col} IS NOT NULL AND {col} != ''{system_filter} GROUP BY {col} ORDER BY {col}", params)
        options[sys_key] = [(r[col], r['cnt']) for r in rows]

    with _filter_cache_lock:
        if len(_filter_cache) >= _FILTER_CACHE_MAX:
            oldest_key = min(_filter_cache_time, key=_filter_cache_time.get)
            _filter_cache.pop(oldest_key, None)
            _filter_cache_time.pop(oldest_key, None)

        _filter_cache[cache_key] = options
        _filter_cache_time[cache_key] = now
    return options


def _build_games_query(params, count_only=False, ids_only=False, user_id=None):
    """Build dynamic WHERE clause for game queries from filter params.

    Returns (sql, bind_values) tuple. The SQL is either a SELECT for data,
    a COUNT, or an ids-only query depending on flags.

    Pass 31.1 — `user_id` (optional) scopes the psn_games/psn_trophies subquery
    to the caller so each user sees only their own PSN progress on game cards.
    COUNT and ids_only variants don't join the psn subquery, so user_id is
    ignored there. For callers that haven't been threaded through yet, a
    missing user_id preserves the historical "show everyone's PSN data"
    behavior — safe on a single-user install, visibly wrong on multi-user;
    audit any new caller that reads a card with psn.* columns.
    """
    conditions = []
    values = []

    show_bonus = params.get('show_bonus', '0') == '1'
    if not show_bonus:
        conditions.append("(g.is_bonus_disc = 0 OR g.is_bonus_disc IS NULL)")

    if params.get('system'):
        conditions.append("g.system_id = ?")
        values.append(params['system'])

    if params.get('system_type'):
        conditions.append("s.system_type = ?")
        values.append(params['system_type'])

    if params.get('genre'):
        conditions.append("g.genre LIKE ? ESCAPE '\\'")
        values.append(f"%{escape_like(params['genre'])}%")

    if params.get('franchise'):
        conditions.append("g.franchise LIKE ? ESCAPE '\\'")
        values.append(f"%{escape_like(params['franchise'])}%")

    if params.get('developer'):
        conditions.append("g.developer LIKE ? ESCAPE '\\'")
        values.append(f"%{escape_like(params['developer'])}%")

    if params.get('publisher'):
        conditions.append("g.publisher LIKE ? ESCAPE '\\'")
        values.append(f"%{escape_like(params['publisher'])}%")

    if params.get('modes'):
        conditions.append("g.modes LIKE ? ESCAPE '\\'")
        values.append(f"%{escape_like(params['modes'])}%")

    if params.get('perspective'):
        conditions.append("g.perspective LIKE ? ESCAPE '\\'")
        values.append(f"%{escape_like(params['perspective'])}%")

    if params.get('dimension'):
        conditions.append("g.dimension LIKE ? ESCAPE '\\'")
        values.append(f"%{escape_like(params['dimension'])}%")

    if params.get('rating'):
        rating_clauses = ' OR '.join(f"g.{RATING_SYSTEMS[k]['db_column']} = ?" for k in RATING_SYSTEM_KEYS)
        conditions.append(f"({rating_clauses})")
        values.extend([params['rating']] * len(RATING_SYSTEM_KEYS))

    for field in ('genre', 'franchise', 'developer', 'publisher', 'modes', 'perspective', 'dimension'):
        not_val = params.get(f'not_{field}')
        if not_val:
            conditions.append(f"(g.{field} NOT LIKE ? ESCAPE '\\' OR g.{field} IS NULL)")
            values.append(f"%{escape_like(not_val)}%")

    if params.get('not_rating'):
        for k in RATING_SYSTEM_KEYS:
            col = RATING_SYSTEMS[k]['db_column']
            conditions.append(f"(g.{col} != ? OR g.{col} IS NULL)")
            values.append(params['not_rating'])

    source = params.get('source')
    if source == 'clz':
        conditions.append("g.rom_path LIKE 'clz_import/%'")
    elif source == 'steam':
        conditions.append("g.rom_path LIKE 'steam_import/%'")
    elif source == 'xbox':
        conditions.append("g.rom_path LIKE 'xbox_import/%'")
    elif source == 'psn':
        conditions.append("g.rom_path LIKE 'psn_import/%'")
    elif source == 'rom':
        # Explicit inner parens: the AND chain must group before the OR with
        # IS NULL, otherwise SQL precedence still works but reads ambiguously.
        conditions.append("((g.rom_path NOT LIKE 'clz_import/%' AND g.rom_path NOT LIKE 'steam_import/%' AND g.rom_path NOT LIKE 'xbox_import/%' AND g.rom_path NOT LIKE 'psn_import/%') OR g.rom_path IS NULL)")

    if params.get('search'):
        conditions.append("(g.title LIKE ? ESCAPE '\\' OR COALESCE(g.sort_title, '') LIKE ? ESCAPE '\\')")
        escaped = params['search'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        search_val = f"%{escaped}%"
        values.extend([search_val] * 2)

    if params.get('letter'):
        letter = params['letter']
        if letter == '#':
            conditions.append("UPPER(SUBSTR(COALESCE(g.sort_title, g.title), 1, 1)) NOT BETWEEN 'A' AND 'Z'")
        else:
            conditions.append("UPPER(SUBSTR(COALESCE(g.sort_title, g.title), 1, 1)) = ?")
            values.append(letter.upper())

    if params.get('ra_only') == '1':
        conditions.append("g.has_retroachievements = 1")

    where = " AND ".join(conditions) if conditions else "1=1"

    if count_only:
        sql = f"SELECT COUNT(*) as total FROM games g JOIN systems s ON g.system_id = s.id WHERE {where}"
    elif ids_only:
        sql = f"SELECT g.id FROM games g JOIN systems s ON g.system_id = s.id WHERE {where} ORDER BY COALESCE(g.sort_title, g.title) COLLATE NOCASE"
    else:
        # Pass 31.1 / 31.2 — psn and gap joins scope by user_id when the
        # caller passes one, so each user sees only their own library
        # progress on game cards. Legacy call sites without user_id keep
        # their historical shape (which matches the pre-31 behavior).
        psn_user_clause = "AND pg.user_id = ?" if user_id is not None else ""
        gap_user_clause = "AND gap.user_id = ?" if user_id is not None else ""
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
            LEFT JOIN game_achievement_progress gap ON gap.game_id = g.id {gap_user_clause}
            LEFT JOIN (
                SELECT pg.linked_game_id,
                       (pg.earned_bronze + pg.earned_silver + pg.earned_gold + pg.earned_platinum) AS psn_earned,
                       COUNT(pt.id) AS psn_total,
                       pg.progress AS psn_progress
                FROM psn_games pg
                LEFT JOIN psn_trophies pt ON pt.psn_game_id = pg.id
                WHERE pg.linked_game_id IS NOT NULL
                  {psn_user_clause}
                GROUP BY pg.linked_game_id
            ) psn ON psn.linked_game_id = g.id
            WHERE {where}
            ORDER BY COALESCE(g.sort_title, g.title) COLLATE NOCASE
        """
        if user_id is not None:
            # gap JOIN and psn subquery each consume one user_id bind; both
            # land before the WHERE bindings (gap first since its clause
            # appears earlier in the SQL).
            values = [user_id, user_id, *values]

    return sql, values
