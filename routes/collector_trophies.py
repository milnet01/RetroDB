# =============================================================================
# RETRODB - Collector Trophies Blueprint
# =============================================================================
# Gamification system that awards trophies based on collection milestones.
# Tracks progress across game count, systems, scraping, completion, media
# coverage, release-era spread, achievement earning, storage, manufacturers,
# iconic systems, and HLTB playtime.
#
# Trophies roll up into a "Collector Rank" (Pixel Rookie -> ROM Legend) via a
# PSN-style weighting (Bronze=10, Silver=25, Gold=50, Platinum=100). The rank
# is surfaced in the sidebar next to the username on every page, and on the
# /collector-trophies page itself.
# =============================================================================

import logging
import re
from datetime import datetime, timezone

from flask import Blueprint, render_template, jsonify, g

from services.api_helpers import handle_api_errors, success
from services.auth import login_required, permission_required
from services.database import query, execute
from services.formatters import get_manufacturer

logger = logging.getLogger(__name__)

bp = Blueprint('collector_trophies', __name__)


# =============================================================================
# TROPHY DEFINITIONS
# =============================================================================

def _t(id_, name, description, icon, tier, category, threshold, stat):
    """Compact trophy-definition constructor - keeps the list below readable."""
    return {
        'id': id_, 'name': name, 'description': description, 'icon': icon,
        'tier': tier, 'category': category, 'threshold': threshold, 'stat': stat,
    }


TROPHY_DEFINITIONS = [
    # -------------------------------------------------------------------------
    # COLLECTION - raw game count, system count, genre/franchise/manufacturer
    # -------------------------------------------------------------------------
    _t('first_game',          'First Steps',          'Add your first game',                    '\U0001F3AE',           'bronze',   'collection',      1,     'game_count'),
    _t('ten_games',           'Getting Started',      'Reach 10 games',                         '\U0001F4DA',           'bronze',   'collection',      10,    'game_count'),
    _t('five_systems',        'Multi-Platform',       'Have games across 5 systems',            '\U0001F579️',     'bronze',   'collection',      5,     'system_count'),
    _t('hundred_games',       'Century Club',         'Reach 100 games',                        '\U0001F4AF',           'silver',   'collection',      100,   'game_count'),
    _t('ten_systems',         'System Collector',     'Have games across 10 systems',           '\U0001F5A5️',     'silver',   'collection',      10,    'system_count'),
    _t('five_hundred_games',  'Serious Collector',    'Reach 500 games',                        '\U0001F48E',           'silver',   'collection',      500,   'game_count'),
    _t('thousand_games',      'Grand Collector',      'Reach 1,000 games',                      '\U0001F451',           'gold',     'collection',      1000,  'game_count'),
    _t('twenty_systems',      'Platform Master',      'Have games across 20 systems',           '\U0001F30D',           'gold',     'collection',      20,    'system_count'),
    _t('five_thousand',       'Legendary Hoarder',    'Reach 5,000 games',                      '\U0001F525',           'platinum', 'collection',      5000,  'game_count'),
    _t('thirty_systems',      'Universal Collector',  'Span 30+ systems',                       '\U0001F680',           'platinum', 'collection',      30,    'system_count'),
    _t('genre_hopper',        'Genre Hopper',         'Games in 5 different genres',            '\U0001F3AD',           'bronze',   'collection',      5,     'distinct_genres'),
    _t('renaissance_gamer',   'Renaissance Gamer',    'Games in 15 different genres',           '\U0001F3A8',           'silver',   'collection',      15,    'distinct_genres'),
    _t('brand_loyalty',       'Brand Loyalty',        '5 games in the same franchise',          '\U0001F91D',           'bronze',   'collection',      5,     'max_franchise_count'),
    _t('franchise_fan',       'Franchise Fan',        '10 games in the same franchise',         '\U0001F4AA',           'silver',   'collection',      10,    'max_franchise_count'),
    _t('franchise_obsessed',  'Franchise Obsessed',   '20 games in the same franchise',         '\U0001F4E3',           'gold',     'collection',      20,    'max_franchise_count'),
    _t('big_three',           'Big Three',            'Own a Nintendo, a Sony, and a Microsoft game', '\U0001F3DB️', 'gold', 'collection',      1,     'has_big_three'),
    _t('hardware_historian',  'Hardware Historian',   'Games from 8+ different manufacturers',  '\U0001F3DB️',     'platinum', 'collection',      8,     'distinct_manufacturers'),

    # -------------------------------------------------------------------------
    # DISCOVERY - scraping, wishlist, imports, critic darlings
    # -------------------------------------------------------------------------
    _t('first_scrape',        'Data Hunter',          'Scrape your first game',                 '\U0001F50D',           'bronze',   'discovery',       1,     'scraped_count'),
    _t('fifty_scraped',       'Metadata Maven',       'Scrape 50 games',                        '\U0001F4E1',           'silver',   'discovery',       50,    'scraped_count'),
    _t('all_scraped_100',     'Completionist Curator','100% metadata coverage',                 '\U0001F4DC',           'gold',     'discovery',       100,   'scraped_percentage'),
    _t('wishing_well',        'Wishing Well',         'Add your first wishlist item',           '\U0001F31F',           'bronze',   'discovery',       1,     'wishlist_count'),
    _t('import_initiate',     'Import Initiate',      'Import your first Steam/Xbox/PSN/CLZ game','\U0001F4E5',         'bronze',   'discovery',       1,     'has_platform_import'),
    _t('critics_pick',        "Critic's Pick",        'Own a game rated 90+',                   '\U0001F3C5',           'bronze',   'discovery',       1,     'critics_pick_90_count'),
    _t('highly_acclaimed',    'Highly Acclaimed',     'Own 10 games rated 90+',                 '\U0001F947',           'silver',   'discovery',       10,    'critics_pick_90_count'),
    _t('masterpiece',         'Masterpiece Collection','Own 25 games rated 90+',                '\U0001F3C6',           'gold',     'discovery',       25,    'critics_pick_90_count'),

    # -------------------------------------------------------------------------
    # COMPLETION - played-through games
    # -------------------------------------------------------------------------
    _t('first_complete',      'Finisher',             'Complete your first game',               '✅',               'bronze',   'completion',      1,     'completed_count'),
    _t('ten_complete',        'Dedicated Player',     'Complete 10 games',                      '\U0001F3C5',           'silver',   'completion',      10,    'completed_count'),
    _t('fifty_complete',      'True Gamer',           'Complete 50 games',                      '\U0001F3C6',           'gold',     'completion',      50,    'completed_count'),
    _t('hundred_complete',    'Living Legend',        'Complete 100 games',                     '⭐',               'platinum', 'completion',      100,   'completed_count'),

    # -------------------------------------------------------------------------
    # MEDIA - boxart / screenshots / video / fanart coverage
    # -------------------------------------------------------------------------
    _t('picture_perfect',     'Picture Perfect',      'First game with boxart',                 '\U0001F5BC️',     'bronze',   'media',           1,     'boxart_count'),
    _t('snapshot',            'Snapshot',             '10 games with screenshots',              '\U0001F4F8',           'bronze',   'media',           10,    'screenshots_count'),
    _t('art_gallery',         'Art Gallery',          '100 games with boxart',                  '\U0001F5BC️',     'silver',   'media',           100,   'boxart_count'),
    _t('cinematographer',     'Cinematographer',      '25 games with video',                    '\U0001F3AC',           'silver',   'media',           25,    'video_count'),
    _t('complete_collection', 'Complete Collection',  '1,000 games with boxart',                '\U0001F4BF',           'gold',     'media',           1000,  'boxart_count'),
    _t('museum_quality',      'Museum Quality',       '500 games with full media (boxart+desc+screenshots+fanart)', '\U0001F3DB️', 'platinum', 'media', 500, 'full_media_count'),

    # -------------------------------------------------------------------------
    # ERA - release-date spread
    # -------------------------------------------------------------------------
    _t('time_traveler',       'Time Traveler',        'Games from 3 different decades',         '⏳',               'bronze',   'era',             3,     'distinct_decades'),
    _t('history_buff',        'History Buff',         'Games from 5 different decades',         '\U0001F4DC',           'silver',   'era',             5,     'distinct_decades'),
    _t('chronicler',          'Chronicler',           'Games from every decade 1970s-2020s',    '\U0001F5D3️',     'gold',     'era',             1,     'has_all_decades'),
    _t('vintage_vault',       'Vintage Vault',        'Own a game released before 1980',        '\U0001F3F0',           'platinum', 'era',             1,     'has_pre_1980'),

    # -------------------------------------------------------------------------
    # ACHIEVEMENTS - unified across RetroAchievements / Steam / Xbox / PSN
    # -------------------------------------------------------------------------
    _t('first_blood',         'First Blood',          'Earn your first achievement',            '\U0001F52A',           'bronze',   'achievements',    1,     'total_achievements_earned'),
    _t('achievement_hunter',  'Achievement Hunter',   'Earn 100 achievements',                  '\U0001F3F9',           'silver',   'achievements',    100,   'total_achievements_earned'),
    _t('first_platinum',      'First Platinum',       '100% complete your first game',          '\U0001F947',           'silver',   'achievements',    1,     'full_completion_count'),
    _t('trophy_wall',         'Trophy Wall',          'Earn 1,000 achievements',                '\U0001F3C6',           'gold',     'achievements',    1000,  'total_achievements_earned'),
    _t('perfectionist',       'Perfectionist',        '100% complete 10 games',                 '\U0001F4AF',           'gold',     'achievements',    10,    'full_completion_count'),
    _t('achievement_legend',  'Achievement Legend',   'Earn 5,000 achievements',                '\U0001F451',           'platinum', 'achievements',    5000,  'total_achievements_earned'),

    # -------------------------------------------------------------------------
    # STORAGE - total ROM bytes on disk
    # -------------------------------------------------------------------------
    _t('filling_up',          'Filling Up',           '10 GB of ROMs',                          '\U0001F4BE',           'bronze',   'storage',         10,    'total_storage_gb'),
    _t('serious_storage',     'Serious Storage',      '100 GB of ROMs',                         '\U0001F4BD',           'silver',   'storage',         100,   'total_storage_gb'),
    _t('data_archive',        'Data Archive',         '1 TB of ROMs',                           '\U0001F4C0',           'gold',     'storage',         1024,  'total_storage_gb'),
    _t('petabyte_club',       'Petabyte Club',        '10 TB of ROMs',                          '\U0001F5C4️',     'platinum', 'storage',         10240, 'total_storage_gb'),

    # -------------------------------------------------------------------------
    # PLAYTIME - summed HLTB main-story estimates across the library
    # -------------------------------------------------------------------------
    _t('weekend_gamer',       'Weekend Gamer',        '1,000 h of HLTB main-story in library',  '\U0001F3AE',           'silver',   'playtime',        1000,  'total_hltb_hours'),
    _t('life_savings',        'Life Savings',         '10,000 h of HLTB main-story in library', '⏱️',         'gold',     'playtime',        10000, 'total_hltb_hours'),
    _t('immortal_gamer',      'Immortal Gamer',       '100,000 h of HLTB main-story',           '\U0001F9DF',           'platinum', 'playtime',        100000,'total_hltb_hours'),

    # -------------------------------------------------------------------------
    # MANUFACTURER LOYALISTS - per-manufacturer game counts
    # -------------------------------------------------------------------------
    _t('nintendo_fan',        'Nintendo Fan',         '10 games from Nintendo systems',         '\U0001F344',           'bronze',   'manufacturer',    10,    'nintendo_count'),
    _t('nintendo_devotee',    'Nintendo Devotee',     '100 games from Nintendo systems',        '\U0001F407',           'silver',   'manufacturer',    100,   'nintendo_count'),
    _t('sony_fan',            'Sony Fan',             '10 games from Sony systems',             '\U0001F3AE',           'bronze',   'manufacturer',    10,    'sony_count'),
    _t('sony_devotee',        'Sony Devotee',         '100 games from Sony systems',            '\U0001F576️',     'silver',   'manufacturer',    100,   'sony_count'),
    _t('sega_fan',            'Sega Fan',             '10 games from Sega systems',             '\U0001F4A5',           'bronze',   'manufacturer',    10,    'sega_count'),
    _t('sega_devotee',        'Sega Devotee',         '100 games from Sega systems',            '\U0001F994',           'silver',   'manufacturer',    100,   'sega_count'),
    _t('microsoft_fan',       'Microsoft Fan',        '10 games from Microsoft systems',        '\U0001FA9F',           'bronze',   'manufacturer',    10,    'microsoft_count'),
    _t('microsoft_devotee',   'Microsoft Devotee',    '100 games from Microsoft systems',       '\U0001F7E2',           'silver',   'manufacturer',    100,   'microsoft_count'),
    _t('atari_fan',           'Atari Fan',            '10 games from Atari systems',            '\U0001F579️',     'bronze',   'manufacturer',    10,    'atari_count'),
    _t('atari_devotee',       'Atari Devotee',        '100 games from Atari systems',           '\U0001F47E',           'silver',   'manufacturer',    100,   'atari_count'),
    _t('snk_fan',             'SNK Fan',              '5 games from SNK systems',               '\U0001F94A',           'bronze',   'manufacturer',    5,     'snk_count'),
    _t('snk_devotee',         'SNK Devotee',          '25 games from SNK systems',              '\U0001F945',           'silver',   'manufacturer',    25,    'snk_count'),
    _t('nec_fan',             'NEC Fan',              '5 games from NEC systems (TG16/PCE)',    '\U0001F4BB',           'bronze',   'manufacturer',    5,     'nec_count'),
    _t('nec_devotee',         'NEC Devotee',          '25 games from NEC systems',              '\U0001F5A8️',     'silver',   'manufacturer',    25,    'nec_count'),

    # -------------------------------------------------------------------------
    # ICONIC-SYSTEM LOYALISTS - specific consoles
    # -------------------------------------------------------------------------
    _t('nes_loyalist',        'NES Loyalist',         '10 NES games',                           '\U0001F4E6',           'bronze',   'system_loyalist', 10,    'nes_count'),
    _t('snes_master',         'SNES Master',          '10 SNES games',                          '\U0001F308',           'bronze',   'system_loyalist', 10,    'snes_count'),
    _t('genesis_ruler',       'Genesis Ruler',        '10 Genesis / Mega Drive games',          '⚜️',         'bronze',   'system_loyalist', 10,    'genesis_count'),
    _t('playstation_master',  'PlayStation Master',   '10 PlayStation (PS1) games',             '◇',               'bronze',   'system_loyalist', 10,    'psx_count'),
]


# =============================================================================
# RANK SYSTEM - Trophy Points & Tiers
# =============================================================================
# Points follow PSN weighting: Bronze=10, Silver=25, Gold=50, Platinum=100.
# Tier thresholds are calibrated so the top rank ("ROM Legend") is reachable
# only by a collector who has earned the vast majority of trophies, while the
# middle ranks move at a meaningful cadence.

TIER_POINTS = {'bronze': 10, 'silver': 25, 'gold': 50, 'platinum': 100}

RANK_TIERS = [
    ('Pixel Rookie',          0),
    ('Cartridge Hunter',      50),
    ('Controller Enthusiast', 150),
    ('Collector',             300),
    ('Retro Curator',         500),
    ('Archivist',             800),
    ('Vault Keeper',          1150),
    ('Connoisseur',           1500),
    ('Grandmaster',           1900),
    ('ROM Legend',            2300),
]


def _trophy_points(trophy_row):
    """Return the point value of a trophy row if it's earned, else 0."""
    if not trophy_row.get('earned_at'):
        return 0
    return TIER_POINTS.get(trophy_row.get('tier', ''), 0)


def compute_collector_rank(trophies):
    """Given a list of trophy dicts, return rank metadata: current tier name
    + index, points earned, next tier threshold + name (None if already at
    top), and progress percent toward the next tier."""
    points = sum(_trophy_points(t) for t in trophies)

    # Find the highest tier whose threshold has been met
    current_idx = 0
    for i, (_, threshold) in enumerate(RANK_TIERS):
        if points >= threshold:
            current_idx = i
    current_name, current_threshold = RANK_TIERS[current_idx]

    # Next tier (if not already maxed)
    if current_idx + 1 < len(RANK_TIERS):
        next_name, next_threshold = RANK_TIERS[current_idx + 1]
        span = next_threshold - current_threshold
        progress_pct = int(round(((points - current_threshold) / span) * 100)) if span > 0 else 0
    else:
        next_name, next_threshold = None, None
        progress_pct = 100

    earned_count = sum(1 for t in trophies if t.get('earned_at'))
    return {
        'name': current_name,
        'tier_index': current_idx,
        'points': points,
        'next_name': next_name,
        'next_threshold': next_threshold,
        'progress_percent': progress_pct,
        'earned_count': earned_count,
        'total_count': len(trophies),
    }


def get_current_rank():
    """Cheap query for the context processor - reads just enough from
    collector_trophies to compute the rank badge shown in the sidebar.
    Safe to call even before the table has been populated (returns a
    sensible zeroed rank).

    Pass 31.3 — scopes to the current user. Anonymous / pre-login contexts
    get a zeroed rank rather than a cross-user aggregate.
    """
    user_id = g.user['id'] if getattr(g, 'user', None) else None
    if not user_id:
        return {
            'name': RANK_TIERS[0][0], 'tier_index': 0, 'points': 0,
            'next_name': RANK_TIERS[1][0], 'next_threshold': RANK_TIERS[1][1],
            'progress_percent': 0, 'earned_count': 0, 'total_count': len(TROPHY_DEFINITIONS),
        }
    try:
        rows = query(
            "SELECT tier, earned_at FROM collector_trophies WHERE user_id = ?",
            (user_id,),
        )
    except Exception:
        rows = []
    if not rows:
        return {
            'name': RANK_TIERS[0][0], 'tier_index': 0, 'points': 0,
            'next_name': RANK_TIERS[1][0], 'next_threshold': RANK_TIERS[1][1],
            'progress_percent': 0, 'earned_count': 0, 'total_count': len(TROPHY_DEFINITIONS),
        }
    return compute_collector_rank(rows)


# =============================================================================
# STATS GATHERING
# =============================================================================

def _gather_collection_stats(user_id=None):
    """Query the database for every stat referenced by TROPHY_DEFINITIONS.
    Returns a dict of stat_name -> current_value. Each trophy looks its
    threshold stat up by key, so adding a new trophy means adding one
    entry here.

    Pass 31.3 — `user_id` (required for per-user stats) scopes psn_games
    and wishlist counts to the caller. The games/systems/scraped stats stay
    library-wide because the `games` table is shared schema (not per-user).
    Achievement stats (RA/Steam/Xbox) are still library-wide pending Pass
    31.2 which adds user_id to those tables.
    """
    stats = {}

    # --- Basic counts ---
    stats['game_count']       = query("SELECT COUNT(*) AS c FROM games", one=True)['c']
    stats['system_count']     = query("SELECT COUNT(DISTINCT system_id) AS c FROM games", one=True)['c']
    stats['scraped_count']    = query("SELECT COUNT(*) AS c FROM games WHERE description IS NOT NULL AND description != ''", one=True)['c']
    stats['completed_count']  = query("SELECT COUNT(*) AS c FROM games WHERE completion_status IN ('completed', '100_percent')", one=True)['c']
    stats['scraped_percentage'] = (
        int(round((stats['scraped_count'] / stats['game_count']) * 100))
        if stats['game_count'] > 0 else 0
    )

    # --- Media coverage ---
    stats['boxart_count']      = query("SELECT COUNT(*) AS c FROM games WHERE boxart IS NOT NULL AND boxart != ''", one=True)['c']
    stats['screenshots_count'] = query("SELECT COUNT(*) AS c FROM games WHERE screenshots IS NOT NULL AND screenshots != ''", one=True)['c']
    stats['video_count']       = query("SELECT COUNT(*) AS c FROM games WHERE video IS NOT NULL AND video != ''", one=True)['c']
    stats['full_media_count']  = query("""
        SELECT COUNT(*) AS c FROM games
        WHERE boxart IS NOT NULL AND boxart != ''
          AND description IS NOT NULL AND description != ''
          AND screenshots IS NOT NULL AND screenshots != ''
          AND fanart IS NOT NULL AND fanart != ''
    """, one=True)['c']

    # --- Era (release-date spread) ---
    decade_rows = query("""
        SELECT DISTINCT (CAST(SUBSTR(release_date, 1, 4) AS INTEGER) / 10 * 10) AS decade
        FROM games
        WHERE release_date IS NOT NULL AND LENGTH(release_date) >= 4
          AND SUBSTR(release_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
    """)
    decades = {r['decade'] for r in decade_rows if r['decade']}
    stats['distinct_decades']  = len(decades)
    stats['has_all_decades']   = 1 if all(d in decades for d in (1970, 1980, 1990, 2000, 2010, 2020)) else 0
    stats['has_pre_1980']      = 1 if query("""
        SELECT 1 FROM games
        WHERE release_date IS NOT NULL AND LENGTH(release_date) >= 4
          AND SUBSTR(release_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
          AND CAST(SUBSTR(release_date, 1, 4) AS INTEGER) < 1980
        LIMIT 1
    """, one=True) else 0

    # --- Achievements (RA + Steam + Xbox + PSN, unified, per user via Pass 31.2) ---
    if user_id is not None:
        ra_earned = query(
            "SELECT COALESCE(SUM(earned_achievements), 0) AS s "
            "FROM game_achievement_progress WHERE user_id = ?",
            (user_id,), one=True,
        )['s']
        steam_earned = query(
            "SELECT COUNT(*) AS c FROM steam_achievements "
            "WHERE achieved = 1 AND user_id = ?",
            (user_id,), one=True,
        )['c']
        xbox_earned = query(
            "SELECT COUNT(*) AS c FROM xbox_achievements "
            "WHERE achieved = 1 AND user_id = ?",
            (user_id,), one=True,
        )['c']
        psn_earned = query("""
            SELECT COALESCE(SUM(earned_bronze + earned_silver + earned_gold + earned_platinum), 0) AS s
            FROM psn_games WHERE user_id = ?
        """, (user_id,), one=True)['s']
    else:
        ra_earned = steam_earned = xbox_earned = psn_earned = 0
    stats['total_achievements_earned'] = (ra_earned or 0) + (steam_earned or 0) + (xbox_earned or 0) + (psn_earned or 0)

    if user_id is not None:
        ra_full = query(
            "SELECT COUNT(*) AS c FROM game_achievement_progress "
            "WHERE completion_percentage >= 100 AND user_id = ?",
            (user_id,), one=True,
        )['c']
        psn_full = query(
            "SELECT COUNT(*) AS c FROM psn_games WHERE progress >= 100 AND user_id = ?",
            (user_id,), one=True,
        )['c']
    else:
        ra_full = psn_full = 0
    stats['full_completion_count'] = (ra_full or 0) + (psn_full or 0)

    # --- Storage (GB, rounded down) ---
    total_bytes = query("SELECT COALESCE(SUM(file_size), 0) AS s FROM games WHERE file_size IS NOT NULL AND file_size > 0", one=True)['s']
    stats['total_storage_gb'] = int((total_bytes or 0) / (1024 ** 3))

    # --- Playtime (HLTB main-story estimate, hours, parsed from free text) ---
    hltb_rows = query("SELECT playtime_estimate FROM games WHERE playtime_estimate IS NOT NULL AND playtime_estimate != ''")
    total_hours = 0.0
    for r in hltb_rows:
        m = re.search(r'Main[^:]*:\s*([\d.½]+)', r['playtime_estimate'] or '')
        if m:
            val = m.group(1).replace('½', '.5')
            try:
                total_hours += float(val)
            except ValueError:
                pass
    stats['total_hltb_hours'] = int(total_hours)

    # --- Collection: genres, franchise concentration, manufacturer spread ---
    # Pass 45.9 — loop variable was named `g`, which shadows `flask.g` for
    # the rest of the request scope (and corrupts every helper that reads
    # `from flask import g; g.user`). Same regression Pass 41.8.A swept
    # across the codebase. Renamed to `genre_part`.
    genre_rows = query("SELECT genre FROM games WHERE genre IS NOT NULL AND genre != ''")
    genres = set()
    for r in genre_rows:
        for genre_part in (r['genre'] or '').split(','):
            genre_part = genre_part.strip()
            if genre_part:
                genres.add(genre_part)
    stats['distinct_genres'] = len(genres)

    max_fran = query("""
        SELECT COUNT(*) AS c FROM games
        WHERE franchise IS NOT NULL AND franchise != ''
        GROUP BY franchise
        ORDER BY c DESC
        LIMIT 1
    """, one=True)
    stats['max_franchise_count'] = max_fran['c'] if max_fran else 0

    mfr_rows = query("""
        SELECT s.folder, COUNT(g.id) AS cnt
        FROM systems s
        JOIN games g ON g.system_id = s.id
        GROUP BY s.id
    """)
    mfr_counts = {}
    for r in mfr_rows:
        m = get_manufacturer(r['folder'])
        mfr_counts[m] = mfr_counts.get(m, 0) + r['cnt']

    stats['distinct_manufacturers'] = sum(1 for m, c in mfr_counts.items() if c > 0 and m != 'Other')
    stats['has_big_three'] = 1 if all(mfr_counts.get(m, 0) > 0 for m in ('Nintendo', 'Sony', 'Microsoft')) else 0

    stats['nintendo_count']  = mfr_counts.get('Nintendo', 0)
    stats['sony_count']      = mfr_counts.get('Sony', 0)
    stats['sega_count']      = mfr_counts.get('Sega', 0)
    stats['microsoft_count'] = mfr_counts.get('Microsoft', 0)
    stats['atari_count']     = mfr_counts.get('Atari', 0)
    stats['snk_count']       = mfr_counts.get('SNK', 0)
    stats['nec_count']       = mfr_counts.get('NEC', 0)

    # --- Iconic-system loyalists (specific consoles) ---
    sys_rows = query("""
        SELECT s.folder, COUNT(g.id) AS cnt
        FROM systems s
        JOIN games g ON g.system_id = s.id
        WHERE s.folder IN ('nes','snes','genesis','megadrive','psx')
        GROUP BY s.folder
    """)
    sys_counts = {r['folder']: r['cnt'] for r in sys_rows}
    stats['nes_count']     = sys_counts.get('nes', 0)
    stats['snes_count']    = sys_counts.get('snes', 0)
    stats['genesis_count'] = sys_counts.get('genesis', 0) + sys_counts.get('megadrive', 0)
    stats['psx_count']     = sys_counts.get('psx', 0)

    # --- Discovery: wishlist, imports, critic-rated ---
    # Pass 31.3 — wishlist is owner-scoped (Pass 27.1).
    if user_id is not None:
        stats['wishlist_count'] = query(
            "SELECT COUNT(*) AS c FROM wishlist WHERE owner_id = ?",
            (user_id,), one=True,
        )['c']
    else:
        stats['wishlist_count'] = query("SELECT COUNT(*) AS c FROM wishlist", one=True)['c']

    stats['has_platform_import'] = 1 if query("""
        SELECT 1 FROM games
        WHERE rom_path LIKE 'steam_import/%'
           OR rom_path LIKE 'xbox_import/%'
           OR rom_path LIKE 'psn_import/%'
           OR rom_path LIKE 'clz_import/%'
        LIMIT 1
    """, one=True) else 0

    stats['critics_pick_90_count'] = query(
        "SELECT COUNT(*) AS c FROM games WHERE critic_score >= 90",
        one=True
    )['c']

    return stats


def _refresh_trophies(user_id=None):
    """Recalculate trophy progress for a single user.

    Pass 31.3 — rows are scoped by user_id. Calling without a user_id is
    refused so no-one accidentally writes shared rows (which was the
    pre-31 behavior that caused cross-user clobbering).
    """
    if user_id is None:
        raise ValueError("collector_trophies refresh requires a user_id")

    stats = _gather_collection_stats(user_id=user_id)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    newly_earned = 0
    total_earned = 0

    for trophy_def in TROPHY_DEFINITIONS:
        trophy_id = trophy_def['id']
        stat_key = trophy_def['stat']
        threshold = trophy_def['threshold']
        current_value = stats.get(stat_key, 0)

        progress = min(current_value, threshold)
        met = current_value >= threshold

        existing = query(
            "SELECT earned_at FROM collector_trophies WHERE id = ? AND user_id = ?",
            (trophy_id, user_id), one=True
        )

        if existing is not None:
            already_earned = existing['earned_at'] is not None
            if met and not already_earned:
                execute(
                    """UPDATE collector_trophies
                       SET progress = ?, earned_at = ?,
                           name = ?, description = ?, icon = ?, tier = ?,
                           category = ?, threshold = ?
                       WHERE id = ? AND user_id = ?""",
                    (progress, now, trophy_def['name'], trophy_def['description'],
                     trophy_def['icon'], trophy_def['tier'], trophy_def['category'],
                     threshold, trophy_id, user_id)
                )
                newly_earned += 1
                total_earned += 1
            elif met and already_earned:
                # Re-write fields every refresh so definition edits (name,
                # description, icon, tier, threshold) propagate without a
                # manual DELETE FROM collector_trophies.
                execute(
                    """UPDATE collector_trophies
                       SET progress = ?, name = ?, description = ?, icon = ?,
                           tier = ?, category = ?, threshold = ?
                       WHERE id = ? AND user_id = ?""",
                    (progress, trophy_def['name'], trophy_def['description'],
                     trophy_def['icon'], trophy_def['tier'], trophy_def['category'],
                     threshold, trophy_id, user_id)
                )
                total_earned += 1
            else:
                execute(
                    """UPDATE collector_trophies
                       SET progress = ?, name = ?, description = ?, icon = ?,
                           tier = ?, category = ?, threshold = ?
                       WHERE id = ? AND user_id = ?""",
                    (progress, trophy_def['name'], trophy_def['description'],
                     trophy_def['icon'], trophy_def['tier'], trophy_def['category'],
                     threshold, trophy_id, user_id)
                )
        else:
            earned_at = now if met else None
            if met:
                newly_earned += 1
                total_earned += 1
            execute(
                """INSERT INTO collector_trophies
                   (id, user_id, name, description, icon, tier, category, threshold, earned_at, progress)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trophy_id, user_id, trophy_def['name'], trophy_def['description'],
                    trophy_def['icon'], trophy_def['tier'], trophy_def['category'],
                    threshold, earned_at, progress,
                )
            )

    # Compute the rank after refresh so the API response reflects the new state
    all_trophies = query(
        "SELECT tier, earned_at FROM collector_trophies WHERE user_id = ?",
        (user_id,),
    )
    rank = compute_collector_rank(all_trophies)

    logger.info(
        "Collector trophies refreshed: %d total earned, %d newly earned, rank=%s (%d pts)",
        total_earned, newly_earned, rank['name'], rank['points']
    )

    return {
        'total_trophies': len(TROPHY_DEFINITIONS),
        'total_earned': total_earned,
        'newly_earned': newly_earned,
        'stats': stats,
        'rank': rank,
    }


# =============================================================================
# PAGE ROUTES
# =============================================================================

def _trophies_sorted(user_id):
    """Return the given user's trophies ordered by tier (plat -> bronze) then name."""
    return query(
        "SELECT * FROM collector_trophies WHERE user_id = ? ORDER BY "
        "CASE tier WHEN 'platinum' THEN 1 WHEN 'gold' THEN 2 "
        "WHEN 'silver' THEN 3 WHEN 'bronze' THEN 4 END, name",
        (user_id,),
    )


def _empty_trophies_from_definitions():
    """Pass 45.9 — Render in-memory trophy stubs from TROPHY_DEFINITIONS.

    Used by the GET handlers when the user has no rows yet, so a first-time
    visitor still sees the full trophy roster without GET writing 70 rows
    to the database (RFC 7231 says GET is safe — must not have observable
    side effects on shared state). The user gets a normal empty-progress
    rendering and the explicit POST /api/collector-trophies/refresh button
    is what materialises the rows + computes scores.

    Each stub mirrors the column shape of `collector_trophies` rows so the
    template can iterate them identically to DB rows: progress=0,
    earned_at=None.
    """
    tier_order = {'platinum': 1, 'gold': 2, 'silver': 3, 'bronze': 4}
    stubs = [
        {
            'id': td['id'],
            'name': td['name'],
            'description': td['description'],
            'icon': td['icon'],
            'tier': td['tier'],
            'category': td['category'],
            'threshold': td['threshold'],
            'progress': 0,
            'earned_at': None,
        }
        for td in TROPHY_DEFINITIONS
    ]
    stubs.sort(key=lambda t: (tier_order.get(t['tier'], 99), t['name']))
    return stubs


@bp.route('/collector-trophies')
@login_required
def collector_trophies_page():
    """Render the collector trophy showcase page.

    Pass 45.9 — GET no longer triggers _refresh_trophies on cold cache.
    The first visit renders an in-memory roster from TROPHY_DEFINITIONS
    (all unearned); the explicit POST /api/collector-trophies/refresh
    button is what writes rows and computes scores.
    """
    user_id = g.user['id']
    trophies = _trophies_sorted(user_id) or _empty_trophies_from_definitions()

    rank = compute_collector_rank(trophies)
    earned_count = rank['earned_count']
    total_count = rank['total_count']

    return render_template(
        'collector_trophies.html',
        trophies=trophies,
        earned_count=earned_count,
        total_count=total_count,
        rank=rank,
    )


# =============================================================================
# API ROUTES
# =============================================================================

@bp.route('/api/collector-trophies')
@login_required
def get_all_trophies():
    """Return the caller's collector trophies with their current status.

    Pass 45.9 — GET no longer mutates the DB. See `collector_trophies_page`
    for the rationale; same fix.
    """
    user_id = g.user['id']
    trophies = _trophies_sorted(user_id) or _empty_trophies_from_definitions()

    rank = compute_collector_rank(trophies)
    return jsonify({
        'trophies': trophies,
        'earned_count': rank['earned_count'],
        'total_count': rank['total_count'],
        'rank': rank,
    })


# `track_progress`, not `editor_required`. This recalculates the CALLER'S
# OWN trophy rows (user_id=g.user['id']) -- self-tracking, which auth.md
# grants to every signed-in role. Gated at editor it was worse than
# restrictive: it is the only writer of collector_trophies rows, so a
# player or viewer could never earn one, and the 302 the decorator returned
# made the failure unhandleable by the page's fetch() caller.
@bp.route('/api/collector-trophies/refresh', methods=['POST'])
@permission_required('track_progress')
@handle_api_errors
def refresh_trophies():
    """Recalculate the caller's trophy progress from current database state."""
    result = _refresh_trophies(user_id=g.user['id'])
    return success(
        message=f"{result['newly_earned']} new trophies earned!" if result['newly_earned']
                else 'Trophy progress updated.',
        **result,
    )
