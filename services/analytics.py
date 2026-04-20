# =============================================================================
# RETRODB - Analytics Data Helpers
# =============================================================================
# Pure data-layer helpers for the /analytics page. Each function returns
# chart-ready lists/dicts — no Flask/request/session state is touched.
# =============================================================================

import re

import settings_manager
from services.database import query
from services.formatters import format_size, get_manufacturer
from services.game_utils import RATING_SYSTEMS, RATING_VALUES


def _get_analytics_stats():
    """Get basic analytics counts, storage, and completion rate."""
    total_games = query("SELECT COUNT(*) as count FROM games", one=True)['count']
    total_systems = query("SELECT COUNT(*) as count FROM systems", one=True)['count']

    storage_row = query("SELECT SUM(COALESCE(file_size, 0)) as total FROM games", one=True)
    total_bytes = storage_row['total'] or 0

    completion_counts = query("""
        SELECT completion_status, COUNT(*) as count
        FROM games
        GROUP BY completion_status
    """)
    completion_map = {row['completion_status'] or 'not_started': row['count'] for row in completion_counts}
    completed = completion_map.get('completed', 0) + completion_map.get('100_percent', 0)
    completion_rate = round((completed / total_games * 100) if total_games > 0 else 0, 1)

    stats = {
        'total_games': total_games,
        'total_systems': total_systems,
        'total_storage': format_size(total_bytes),
        'completion_rate': completion_rate
    }

    completion_data = [
        completion_map.get('not_started', 0) + completion_map.get(None, 0),
        completion_map.get('in_progress', 0),
        completion_map.get('played', 0),
        completion_map.get('completed', 0),
        completion_map.get('100_percent', 0)
    ]

    return total_games, stats, completion_data


def _get_manufacturer_data():
    """Get games by manufacturer using a single JOIN query."""
    rows = query("""
        SELECT s.folder, COUNT(g.id) as game_count
        FROM systems s
        JOIN games g ON s.id = g.system_id
        GROUP BY s.id
    """)
    manufacturer_counts = {}
    for row in rows:
        mfr = get_manufacturer(row['folder'])
        manufacturer_counts[mfr] = manufacturer_counts.get(mfr, 0) + row['game_count']

    sorted_mfrs = sorted(manufacturer_counts.items(), key=lambda x: x[1], reverse=True)
    return [m[0] for m in sorted_mfrs[:10]], [m[1] for m in sorted_mfrs[:10]]


def _get_decade_data():
    """Get games grouped by release decade using SQL aggregation."""
    rows = query("""
        SELECT (CAST(SUBSTR(release_date, 1, 4) AS INTEGER) / 10 * 10) || 's' AS decade,
               COUNT(*) AS cnt
        FROM games
        WHERE release_date IS NOT NULL
          AND LENGTH(release_date) >= 4
          AND SUBSTR(release_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
        GROUP BY decade
        ORDER BY decade
    """)
    return [r['decade'] for r in rows], [r['cnt'] for r in rows]


def _get_genre_data():
    """Get top 10 genres by game count."""
    genre_counts = {}
    games_with_genre = query("SELECT genre FROM games WHERE genre IS NOT NULL AND genre != ''")
    for game in games_with_genre:
        for genre in game['genre'].split(','):
            genre = genre.strip()
            if genre:
                genre_counts[genre] = genre_counts.get(genre, 0) + 1

    sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return [g[0] for g in sorted_genres], [g[1] for g in sorted_genres]


def _get_storage_by_system():
    """Get storage by system using a single GROUP BY query."""
    rows = query("""
        SELECT s.name, SUM(COALESCE(g.file_size, 0)) as total_size
        FROM systems s
        JOIN games g ON s.id = g.system_id
        WHERE g.file_size IS NOT NULL AND g.file_size > 0
        GROUP BY s.id
        HAVING total_size > 0
        ORDER BY total_size DESC
        LIMIT 15
    """)
    storage_labels = [r['name'] for r in rows]
    storage_data = [round(r['total_size'] / (1024**3), 2) for r in rows]
    return storage_labels, storage_data


def _get_top_systems():
    """Get top 15 systems with game count, storage, and manufacturer in a single query."""
    rows = query("""
        SELECT s.id, s.name, s.folder,
               COUNT(g.id) as game_count,
               SUM(COALESCE(g.file_size, 0)) as total_size
        FROM systems s
        LEFT JOIN games g ON s.id = g.system_id
        GROUP BY s.id
        HAVING game_count > 0
        ORDER BY game_count DESC
        LIMIT 15
    """)

    top_systems_list = []
    for row in rows:
        sys_dict = dict(row)
        sys_dict['manufacturer'] = get_manufacturer(row['folder'])
        total_size = row['total_size'] or 0
        sys_dict['storage_formatted'] = format_size(total_size)
        sys_dict['avg_size_formatted'] = format_size(total_size // row['game_count']) if row['game_count'] > 0 else "N/A"
        top_systems_list.append(sys_dict)

    return top_systems_list


def _get_largest_games():
    """Get the 20 largest games by file size."""
    largest_games = query("""
        SELECT g.id, g.title, g.rom_path, g.file_size, s.name as system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.file_size IS NOT NULL AND g.file_size > 0
        ORDER BY g.file_size DESC
        LIMIT 20
    """)

    largest_list = []
    for game in largest_games:
        g = dict(game)
        g['size_formatted'] = format_size(game['file_size'])
        largest_list.append(g)

    return largest_list


def _get_ra_statistics(total_games):
    """Get RetroAchievements stats and per-system coverage."""
    ra_total = query("SELECT COUNT(*) as count FROM games WHERE has_retroachievements = 1", one=True)['count']
    ra_percentage = round((ra_total / total_games * 100) if total_games > 0 else 0, 1)

    ra_by_system = query("""
        SELECT s.name, s.folder,
               COUNT(g.id) as total_games,
               SUM(CASE WHEN g.has_retroachievements = 1 THEN 1 ELSE 0 END) as ra_games
        FROM systems s
        JOIN games g ON s.id = g.system_id
        GROUP BY s.id
        HAVING ra_games > 0
        ORDER BY ra_games DESC
        LIMIT 12
    """)

    ra_system_labels = [s['name'] for s in ra_by_system]
    ra_system_data = [s['ra_games'] for s in ra_by_system]
    ra_system_totals = [s['total_games'] for s in ra_by_system]

    ra_coverage = []
    for s in ra_by_system:
        coverage = round((s['ra_games'] / s['total_games'] * 100) if s['total_games'] > 0 else 0, 1)
        ra_coverage.append({
            'name': s['name'],
            'ra_games': s['ra_games'],
            'total_games': s['total_games'],
            'coverage': coverage
        })

    return ra_total, ra_percentage, ra_system_labels, ra_system_data, ra_system_totals, ra_coverage


def _get_score_statistics():
    """Get review score stats, distribution, and per-system averages."""
    score_stats_query = query("""
        SELECT
            COUNT(CASE WHEN critic_score IS NOT NULL AND critic_score > 0 THEN 1 END) as games_with_critic,
            COUNT(CASE WHEN user_score IS NOT NULL AND user_score > 0 THEN 1 END) as games_with_user,
            AVG(CASE WHEN critic_score IS NOT NULL AND critic_score > 0 THEN critic_score END) as avg_critic,
            AVG(CASE WHEN user_score IS NOT NULL AND user_score > 0 THEN user_score END) as avg_user
        FROM games
    """, one=True)

    score_stats = {
        'games_with_critic': score_stats_query['games_with_critic'] or 0,
        'games_with_user': score_stats_query['games_with_user'] or 0,
        'avg_critic': round(score_stats_query['avg_critic'], 1) if score_stats_query['avg_critic'] else None,
        'avg_user': round(score_stats_query['avg_user'], 1) if score_stats_query['avg_user'] else None
    }

    score_dist_labels = ['0-10', '11-20', '21-30', '31-40', '41-50', '51-60', '61-70', '71-80', '81-90', '91-100']
    dist_row = query("""
        SELECT
            COUNT(CASE WHEN critic_score >= 0 AND critic_score <= 10 THEN 1 END) as bin0,
            COUNT(CASE WHEN critic_score > 10 AND critic_score <= 20 THEN 1 END) as bin1,
            COUNT(CASE WHEN critic_score > 20 AND critic_score <= 30 THEN 1 END) as bin2,
            COUNT(CASE WHEN critic_score > 30 AND critic_score <= 40 THEN 1 END) as bin3,
            COUNT(CASE WHEN critic_score > 40 AND critic_score <= 50 THEN 1 END) as bin4,
            COUNT(CASE WHEN critic_score > 50 AND critic_score <= 60 THEN 1 END) as bin5,
            COUNT(CASE WHEN critic_score > 60 AND critic_score <= 70 THEN 1 END) as bin6,
            COUNT(CASE WHEN critic_score > 70 AND critic_score <= 80 THEN 1 END) as bin7,
            COUNT(CASE WHEN critic_score > 80 AND critic_score <= 90 THEN 1 END) as bin8,
            COUNT(CASE WHEN critic_score > 90 AND critic_score <= 100 THEN 1 END) as bin9
        FROM games
    """, one=True)
    score_dist_data = [dist_row[f'bin{i}'] for i in range(10)]

    score_by_system = query("""
        SELECT s.name,
               AVG(g.critic_score) as avg_critic,
               AVG(g.user_score) as avg_user,
               COUNT(CASE WHEN g.critic_score IS NOT NULL AND g.critic_score > 0 THEN 1 END) as count
        FROM systems s
        JOIN games g ON s.id = g.system_id
        WHERE g.critic_score IS NOT NULL AND g.critic_score > 0
        GROUP BY s.id
        HAVING count >= 5
        ORDER BY avg_critic DESC
        LIMIT 10
    """)

    score_system_labels = [s['name'] for s in score_by_system]
    score_system_critic = [round(s['avg_critic'], 1) if s['avg_critic'] else 0 for s in score_by_system]
    score_system_user = [round(s['avg_user'], 1) if s['avg_user'] else 0 for s in score_by_system]

    top_rated_games = query("""
        SELECT g.id, g.title, g.critic_score, g.user_score, s.name as system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.critic_score IS NOT NULL AND g.critic_score > 0
        ORDER BY g.critic_score DESC
        LIMIT 10
    """)

    lowest_rated_games = query("""
        SELECT g.id, g.title, g.critic_score, g.user_score, s.name as system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.critic_score IS NOT NULL AND g.critic_score > 0
        ORDER BY g.critic_score ASC
        LIMIT 10
    """)

    return (score_stats, score_dist_labels, score_dist_data,
            score_system_labels, score_system_critic, score_system_user,
            top_rated_games, lowest_rated_games)


def _get_rating_data():
    """Get rating distribution for the user's preferred system and per-system maturity breakdown."""
    settings = settings_manager.load_settings()
    pref_key = settings.get('preferred_rating_system', 'esrb')
    if pref_key not in RATING_SYSTEMS:
        pref_key = 'esrb'
    sys_info = RATING_SYSTEMS[pref_key]
    db_col = sys_info['db_column']
    sys_name = sys_info['name']
    ordered_values = RATING_VALUES.get(pref_key, [])

    rating_counts = query(f"""
        SELECT {db_col} as rating, COUNT(*) as count
        FROM games
        WHERE {db_col} IS NOT NULL AND {db_col} != ''
        GROUP BY {db_col}
        ORDER BY count DESC
    """)
    rating_labels = [r['rating'] for r in rating_counts]
    rating_data = [r['count'] for r in rating_counts]
    rating_total = sum(rating_data)
    top_rating = rating_labels[0] if rating_labels else 'N/A'

    no_rating_count = query("""
        SELECT COUNT(*) as count FROM games
        WHERE (esrb_rating IS NULL OR esrb_rating = '')
        AND (pegi_rating IS NULL OR pegi_rating = '')
        AND (cero_rating IS NULL OR cero_rating = '')
        AND (usk_rating IS NULL OR usk_rating = '')
        AND (acb_rating IS NULL OR acb_rating = '')
        AND (fpb_rating IS NULL OR fpb_rating = '')
        AND (grac_rating IS NULL OR grac_rating = '')
        AND (classind_rating IS NULL OR classind_rating = '')
    """, one=True)['count']

    rating_by_system = query("""
        SELECT s.name,
               SUM(CASE WHEN g.esrb_rating IN ('E', 'EC') OR g.pegi_rating IN ('PEGI 3', 'PEGI 7')
                   OR g.cero_rating = 'A' OR g.usk_rating IN ('0', '6')
                   OR g.acb_rating IN ('G', 'PG') OR g.grac_rating = 'ALL'
                   OR g.classind_rating IN ('L', '10')
                   THEN 1 ELSE 0 END) as family,
               SUM(CASE WHEN g.esrb_rating IN ('E10+', 'T') OR g.pegi_rating IN ('PEGI 12', 'PEGI 16')
                   OR g.cero_rating IN ('B', 'C') OR g.usk_rating IN ('12', '16')
                   OR g.acb_rating IN ('M', 'MA15+') OR g.grac_rating IN ('12', '15')
                   OR g.classind_rating IN ('12', '14', '16')
                   THEN 1 ELSE 0 END) as teen,
               SUM(CASE WHEN g.esrb_rating IN ('M', 'AO') OR g.pegi_rating = 'PEGI 18'
                   OR g.cero_rating IN ('D', 'Z') OR g.usk_rating = '18'
                   OR g.acb_rating = 'R18+' OR g.grac_rating = '18'
                   OR g.classind_rating = '18'
                   THEN 1 ELSE 0 END) as mature
        FROM systems s
        JOIN games g ON s.id = g.system_id
        WHERE (g.esrb_rating IS NOT NULL AND g.esrb_rating != '')
           OR (g.pegi_rating IS NOT NULL AND g.pegi_rating != '')
           OR (g.cero_rating IS NOT NULL AND g.cero_rating != '')
           OR (g.usk_rating IS NOT NULL AND g.usk_rating != '')
           OR (g.acb_rating IS NOT NULL AND g.acb_rating != '')
           OR (g.fpb_rating IS NOT NULL AND g.fpb_rating != '')
           OR (g.grac_rating IS NOT NULL AND g.grac_rating != '')
           OR (g.classind_rating IS NOT NULL AND g.classind_rating != '')
        GROUP BY s.id
        HAVING (family + teen + mature) >= 5
        ORDER BY (family + teen + mature) DESC
        LIMIT 12
    """)

    rating_system_labels = [r['name'] for r in rating_by_system]
    rating_system_family = [r['family'] for r in rating_by_system]
    rating_system_teen = [r['teen'] for r in rating_by_system]
    rating_system_mature = [r['mature'] for r in rating_by_system]

    return (pref_key, sys_name, rating_labels, rating_data, rating_total,
            top_rating, ordered_values, no_rating_count,
            rating_system_labels, rating_system_family, rating_system_teen, rating_system_mature)


def _get_developer_publisher_data():
    """Get top developers and publishers by game count."""
    dev_rows = query("SELECT developer FROM games WHERE developer IS NOT NULL AND developer != ''")
    dev_counts = {}
    for row in dev_rows:
        for dev in row['developer'].split(','):
            dev = dev.strip()
            if dev:
                dev_counts[dev] = dev_counts.get(dev, 0) + 1
    sorted_devs = sorted(dev_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    dev_labels = [d[0] for d in sorted_devs]
    dev_data = [d[1] for d in sorted_devs]

    pub_rows = query("SELECT publisher FROM games WHERE publisher IS NOT NULL AND publisher != ''")
    pub_counts = {}
    for row in pub_rows:
        for pub in row['publisher'].split(','):
            pub = pub.strip()
            if pub:
                pub_counts[pub] = pub_counts.get(pub, 0) + 1
    sorted_pubs = sorted(pub_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    pub_labels = [p[0] for p in sorted_pubs]
    pub_data = [p[1] for p in sorted_pubs]

    return dev_labels, dev_data, pub_labels, pub_data


def _get_franchise_data():
    """Get top franchises by game count."""
    rows = query("SELECT franchise FROM games WHERE franchise IS NOT NULL AND franchise != ''")
    counts = {}
    for row in rows:
        for f in row['franchise'].split(','):
            f = f.strip()
            if f:
                counts[f] = counts.get(f, 0) + 1
    sorted_f = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:15]
    return [f[0] for f in sorted_f], [f[1] for f in sorted_f]


def _get_gameplay_data():
    """Get perspective, dimension, modes, and player count distributions."""
    persp_rows = query("SELECT perspective FROM games WHERE perspective IS NOT NULL AND perspective != ''")
    persp_counts = {}
    for row in persp_rows:
        for p in row['perspective'].split(','):
            p = p.strip()
            if p:
                persp_counts[p] = persp_counts.get(p, 0) + 1
    sorted_persp = sorted(persp_counts.items(), key=lambda x: x[1], reverse=True)
    persp_labels = [p[0] for p in sorted_persp]
    persp_data = [p[1] for p in sorted_persp]

    dim_rows = query("SELECT dimension FROM games WHERE dimension IS NOT NULL AND dimension != ''")
    dim_counts = {}
    for row in dim_rows:
        for d in row['dimension'].split(','):
            d = d.strip()
            if d:
                dim_counts[d] = dim_counts.get(d, 0) + 1
    sorted_dim = sorted(dim_counts.items(), key=lambda x: x[1], reverse=True)
    dim_labels = [d[0] for d in sorted_dim]
    dim_data = [d[1] for d in sorted_dim]

    mode_rows = query("SELECT modes FROM games WHERE modes IS NOT NULL AND modes != ''")
    mode_counts = {}
    for row in mode_rows:
        for m in row['modes'].split(','):
            m = m.strip()
            if m:
                mode_counts[m] = mode_counts.get(m, 0) + 1
    sorted_modes = sorted(mode_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    mode_labels = [m[0] for m in sorted_modes]
    mode_data = [m[1] for m in sorted_modes]

    player_rows = query("""
        SELECT
            CASE
                WHEN players = 1 THEN '1 Player'
                WHEN players = 2 THEN '2 Players'
                WHEN players BETWEEN 3 AND 4 THEN '3-4 Players'
                WHEN players >= 5 THEN '5+ Players'
            END as player_group,
            COUNT(*) as count
        FROM games
        WHERE players IS NOT NULL AND players > 0
        GROUP BY player_group
        ORDER BY MIN(players)
    """)
    player_labels = [r['player_group'] for r in player_rows]
    player_data = [r['count'] for r in player_rows]

    return (persp_labels, persp_data, dim_labels, dim_data,
            mode_labels, mode_data, player_labels, player_data)


def _get_playtime_data():
    """Get HLTB playtime statistics."""
    rows = query("SELECT title, playtime_estimate, system_id FROM games WHERE playtime_estimate IS NOT NULL AND playtime_estimate != ''")

    main_hours = []
    for row in rows:
        est = row.get('playtime_estimate', '')
        match = re.search(r'Main[^:]*:\s*([\d.½]+)', est)
        if match:
            val = match.group(1).replace('½', '.5')
            try:
                main_hours.append(float(val))
            except ValueError:
                pass

    buckets = {'< 5h': 0, '5-10h': 0, '10-20h': 0, '20-40h': 0, '40-60h': 0, '60-100h': 0, '100h+': 0}
    for h in main_hours:
        if h < 5:
            buckets['< 5h'] += 1
        elif h < 10:
            buckets['5-10h'] += 1
        elif h < 20:
            buckets['10-20h'] += 1
        elif h < 40:
            buckets['20-40h'] += 1
        elif h < 60:
            buckets['40-60h'] += 1
        elif h < 100:
            buckets['60-100h'] += 1
        else:
            buckets['100h+'] += 1

    length_labels = list(buckets.keys())
    length_data = list(buckets.values())

    avg_length = round(sum(main_hours) / len(main_hours), 1) if main_hours else 0
    games_with_hltb = len(main_hours)

    return length_labels, length_data, avg_length, games_with_hltb


def _get_metadata_quality():
    """Get metadata completeness for radar chart and progress bars."""
    fields = query("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) as description,
            SUM(CASE WHEN boxart IS NOT NULL AND boxart != '' THEN 1 ELSE 0 END) as boxart,
            SUM(CASE WHEN genre IS NOT NULL AND genre != '' THEN 1 ELSE 0 END) as genre,
            SUM(CASE WHEN developer IS NOT NULL AND developer != '' THEN 1 ELSE 0 END) as developer,
            SUM(CASE WHEN publisher IS NOT NULL AND publisher != '' THEN 1 ELSE 0 END) as publisher,
            SUM(CASE WHEN release_date IS NOT NULL AND release_date != '' THEN 1 ELSE 0 END) as release_date,
            SUM(CASE WHEN screenshots IS NOT NULL AND screenshots != '' THEN 1 ELSE 0 END) as screenshots,
            SUM(CASE WHEN fanart IS NOT NULL AND fanart != '' THEN 1 ELSE 0 END) as fanart,
            SUM(CASE WHEN video IS NOT NULL AND video != '' THEN 1 ELSE 0 END) as video,
            SUM(CASE WHEN manual IS NOT NULL AND manual != '' THEN 1 ELSE 0 END) as manual,
            SUM(CASE WHEN playtime_estimate IS NOT NULL AND playtime_estimate != '' THEN 1 ELSE 0 END) as hltb,
            SUM(CASE WHEN (critic_score IS NOT NULL AND critic_score > 0) THEN 1 ELSE 0 END) as ratings,
            SUM(CASE WHEN modes IS NOT NULL AND modes != '' THEN 1 ELSE 0 END) as modes,
            SUM(CASE WHEN region IS NOT NULL AND region != '' THEN 1 ELSE 0 END) as region
        FROM games
    """, one=True)

    total = fields['total'] or 1
    quality = {}
    for field_name in ['description', 'boxart', 'genre', 'developer', 'publisher',
                        'release_date', 'screenshots', 'fanart', 'video', 'manual',
                        'hltb', 'ratings', 'modes', 'region']:
        quality[field_name] = round((fields[field_name] or 0) / total * 100, 1)

    return quality


def _get_year_data():
    """Get game counts per release year (not decade)."""
    rows = query("""
        SELECT SUBSTR(release_date, 1, 4) as year, COUNT(*) as count
        FROM games
        WHERE release_date IS NOT NULL AND LENGTH(release_date) >= 4
        AND CAST(SUBSTR(release_date, 1, 4) AS INTEGER) BETWEEN 1970 AND 2030
        GROUP BY year
        ORDER BY year
    """)
    return [r['year'] for r in rows], [r['count'] for r in rows]


def _get_region_data():
    """Get region distribution."""
    rows = query("SELECT region FROM games WHERE region IS NOT NULL AND region != ''")
    counts = {}
    for row in rows:
        for r in row['region'].split(','):
            r = r.strip()
            if r:
                counts[r] = counts.get(r, 0) + 1
    sorted_r = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return [r[0] for r in sorted_r], [r[1] for r in sorted_r]


def _get_collection_growth():
    """Get collection growth over time using created_at or ID as fallback."""
    rows = query("""
        SELECT SUBSTR(created_at, 1, 7) as month, COUNT(*) as count
        FROM games
        WHERE created_at IS NOT NULL AND created_at != ''
        GROUP BY month
        ORDER BY month
    """)
    if rows:
        labels = [r['month'] for r in rows]
        cumulative = []
        total = 0
        for r in rows:
            total += r['count']
            cumulative.append(total)
        return labels, cumulative

    total_count = query("SELECT COUNT(*) as c FROM games", one=True)['c']
    if total_count == 0:
        return [], []
    batch_size = max(total_count // 20, 1)
    labels = []
    cumulative = []
    for i in range(0, total_count, batch_size):
        labels.append(f"Batch {len(labels) + 1}")
        cumulative.append(min(i + batch_size, total_count))
    return labels, cumulative


def _get_score_scatter():
    """Get critic vs user score data for scatter plot."""
    rows = query("""
        SELECT title, critic_score, user_score
        FROM games
        WHERE critic_score IS NOT NULL AND critic_score > 0
        AND user_score IS NOT NULL AND user_score > 0
        LIMIT 200
    """)
    scatter_data = []
    for r in rows:
        user = r['user_score']
        if user <= 10:
            user = user * 10
        scatter_data.append({
            'x': round(r['critic_score'], 1),
            'y': round(user, 1),
            'title': r['title'][:30]
        })
    return scatter_data


def _get_minor_analytics():
    """Get save type, media completeness, bonus discs, editions data."""
    save_rows = query("SELECT save_type FROM games WHERE save_type IS NOT NULL AND save_type != ''")
    save_counts = {}
    for row in save_rows:
        for s in row['save_type'].split(','):
            s = s.strip()
            if s:
                save_counts[s] = save_counts.get(s, 0) + 1
    sorted_saves = sorted(save_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    save_labels = [s[0] for s in sorted_saves]
    save_data = [s[1] for s in sorted_saves]

    bonus_count = query("SELECT COUNT(*) as c FROM games WHERE is_bonus_disc = 1", one=True)['c']

    edition_rows = query("SELECT edition FROM games WHERE edition IS NOT NULL AND edition != ''")
    edition_count = len(edition_rows)

    return save_labels, save_data, bonus_count, edition_count
