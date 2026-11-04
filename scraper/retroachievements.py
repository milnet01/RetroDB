# =============================================================================
# RETROACHIEVEMENTS INTEGRATION
# =============================================================================
# Checks if games have RetroAchievements support
# API Documentation: https://api-docs.retroachievements.org/
# =============================================================================

import logging
import hashlib
import os
import sys

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from .base_scraper import http_get
from services.achievement_linking import NO_RA_MATCH, match_ra_game_for_file, ra_link_info

logger = logging.getLogger(__name__)

def get_ra_credentials():
    """Get RetroAchievements credentials via centralized scraper_manager, falling back to config.py"""
    from .scraper_manager import get_api_key
    username = get_api_key('ra_username', 'RETROACHIEVEMENTS_USERNAME')
    api_key = get_api_key('ra_apikey', 'RETROACHIEVEMENTS_API_KEY')
    return username, api_key

# RetroAchievements console ids (rcheevos rc_consoles.h) by ES-DE folder name
RA_CONSOLE_MAP = {
    'nes': 7,           # Nintendo Entertainment System
    'snes': 3,          # Super Nintendo Entertainment System
    'n64': 2,           # Nintendo 64
    'gamecube': 16,     # Nintendo GameCube
    'gc': 16,           # Nintendo GameCube (alternate folder name)
    'wii': 19,          # Nintendo Wii
    'gb': 4,            # Game Boy
    'gbc': 6,           # Game Boy Color
    'gba': 5,           # Game Boy Advance
    'nds': 18,          # Nintendo DS
    'genesis': 1,       # Sega Genesis/Mega Drive
    'megadrive': 1,
    'mastersystem': 11, # Sega Master System
    'gamegear': 15,     # Sega Game Gear
    'segacd': 9,        # Sega CD
    'sega32x': 10,      # Sega 32X
    'saturn': 39,       # Sega Saturn
    'dreamcast': 40,    # Sega Dreamcast
    'psx': 12,          # Sony PlayStation
    'ps2': 21,          # Sony PlayStation 2
    'psp': 41,          # Sony PSP
    'pcengine': 8,      # PC Engine/TurboGrafx-16
    'tg16': 8,
    'tg-16': 8,
    'pcenginecd': 76,   # PC Engine CD
    # No 'neogeo': RA lists no such console, and 14 is the Neo Geo Pocket.
    'neogeocd': 56,     # Neo Geo CD
    'neogeocdjp': 56,
    # MAME/Arcade (ID 27) excluded - limited RA support, causes over-matching
    'atari2600': 25,    # Atari 2600
    'atari7800': 51,    # Atari 7800
    'atarilynx': 13,    # Atari Lynx
    'atarijaguar': 17,  # Atari Jaguar
    'colecovision': 44, # ColecoVision
    'intellivision': 45,# Intellivision
    'vectrex': 46,      # Vectrex
    'wonderswan': 53,   # WonderSwan
    'wonderswancolor': 53,
    'ngp': 14,          # Neo Geo Pocket
    'ngpc': 14,
    'virtualboy': 28,   # Virtual Boy
    'pokemini': 24,     # Pokemon Mini
    '3do': 43,          # 3DO
    'pc88': 47,         # PC-8800
    'pc98': 48,         # PC-9800
    'pcfx': 49,         # PC-FX
    'amstradcpc': 37,   # Amstrad CPC
    'apple2': 38,       # Apple II
    'msx': 29,          # MSX
    'sg-1000': 33,      # Sega SG-1000
    'sg1000': 33,
    'fds': 81,          # Famicom Disk System
    'channelf': 57,     # Fairchild Channel F
    'odyssey2': 23,     # Magnavox Odyssey 2
    'videopac': 23,
    'atarijaguarcd': 77,# Atari Jaguar CD
    'megaduck': 69,     # Mega Duck
    'supervision': 63,  # Watara Supervision
    'wasm4': 72,        # WASM-4
    'arduboy': 71,      # Arduboy
    # Other folder names for the same consoles
    'sfc': 3, 'snesna': 3, 'famicom': 7,
    'megacd': 9, 'megacdjp': 9, 'megadrivejp': 1,
    'saturnjp': 39, 'sega32xjp': 10, 'sega32xna': 10,
    'mark3': 11, 'tg-cd': 76, 'supergrafx': 8,
    'msx1': 29, 'msx2': 29,
}


def get_ra_console_id(system_folder):
    """Get RetroAchievements console ID from ES-DE folder name"""
    return RA_CONSOLE_MAP.get(system_folder.lower())


def calculate_rom_hash(rom_path):
    """
    Calculate MD5 hash of ROM file for RetroAchievements lookup
    Note: RA uses specific hashing methods for different systems
    This is a simplified version using MD5, reading in chunks to avoid
    loading entire files into memory.
    """
    try:
        h = hashlib.md5(usedforsecurity=False)
        with open(rom_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.error(f"Error calculating ROM hash: {e}")
        return None


from collections import OrderedDict
import threading

# Pass 32.14: bound the console cache. Previously an unbounded dict — one
# entry per console_id ever queried, each entry a list of every RA game for
# that console (can be 2k+ entries). A bulk-scrape across many consoles
# could therefore pin many megabytes in memory for the 10-min TTL window.
_RA_CACHE_MAX_ENTRIES = 64
_ra_console_cache = OrderedDict()   # console_id → games list
_ra_console_cache_time = {}         # console_id → timestamp
_ra_console_cache_lock = threading.Lock()
_RA_CACHE_TTL = 600  # 10 minutes


def _ra_cache_set(console_id, games):
    with _ra_console_cache_lock:
        if console_id in _ra_console_cache:
            _ra_console_cache.move_to_end(console_id)
        _ra_console_cache[console_id] = games
        _ra_console_cache_time[console_id] = _time_now()
        while len(_ra_console_cache) > _RA_CACHE_MAX_ENTRIES:
            evict_id, _ = _ra_console_cache.popitem(last=False)
            _ra_console_cache_time.pop(evict_id, None)


def _ra_cache_get(console_id):
    import time as _time
    with _ra_console_cache_lock:
        if console_id not in _ra_console_cache:
            return None
        now = _time.time()
        if now - _ra_console_cache_time.get(console_id, 0) >= _RA_CACHE_TTL:
            _ra_console_cache.pop(console_id, None)
            _ra_console_cache_time.pop(console_id, None)
            return None
        _ra_console_cache.move_to_end(console_id)
        return _ra_console_cache[console_id]


def _time_now():
    import time as _time
    return _time.time()


def fetch_ra_game_list(console_id):
    """A console's games that have achievements, or None if RA could not say.

    An empty list counts as None: no console RA supports has no games, so it
    can only be a bad answer, and it must not read as "no game here has a set".
    """
    cached_games = _ra_cache_get(console_id)
    if cached_games is not None:
        logger.debug(f"Using cached RA game list for console {console_id} ({len(cached_games)} games)")
        return cached_games

    username, api_key = get_ra_credentials()
    if not api_key:
        logger.warning("RetroAchievements API key not configured")
        return None
    try:
        # Pass 32.14: bounded LRU + size cap on fetch.
        response = http_get(
            "https://retroachievements.org/API/API_GetGameList.php",
            params={
                'z': username,
                'y': api_key,
                'i': console_id,
                'f': 1,  # Only games with achievements
                'h': 1,  # With the hashes of the files it knows (PASS-59-217)
            },
            timeout=30,
            max_bytes=getattr(config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024),
        )

        # Pass 41.7.C — surface RetroAchievements 401 explicitly. The
        # generic non-200 return-None branch buried "stale RA API key"
        # under "no entry found"; users had no actionable hint. Log at
        # ERROR with the user-actionable fix (re-enter API key in
        # Settings → Scrapers) so the fault is visible in the log
        # file when the UI shows an empty result.
        if response is not None and response.status_code == 401:
            logger.error(
                "RetroAchievements API returned 401 for GetGameList "
                "(console_id=%s) — your RA API key is invalid or revoked. "
                "Re-enter the api_key in Settings → Scrapers.",
                console_id,
            )
        if response is None or response.status_code != 200:
            return None

        games = response.json()
    except Exception as e:
        logger.error(f"Error fetching RetroAchievements game list: {e}")
        return None

    if not games or not isinstance(games, list):
        logger.warning(f"RetroAchievements sent no game list for console {console_id}")
        return None
    _ra_cache_set(console_id, games)
    logger.debug(f"Cached RA game list for console {console_id} ({len(games)} games)")
    return games


def search_game_by_name(game_name, console_id, rom_path=None, system_folder=None,
                        alternate_titles=None):
    """A game's RA link details; NO_RA_MATCH if RA has no such game; None if RA
    could not be asked, which says nothing about the game."""
    games = fetch_ra_game_list(console_id)
    if games is None:
        return None
    match, copy_fits = match_ra_game_for_file(game_name, rom_path, system_folder, games,
                                              alternate_titles)
    if not match:
        return NO_RA_MATCH
    logger.info(f"RA match: '{game_name}' -> '{match.get('Title')}'")
    return {**ra_link_info(match), 'copy_fits': copy_fits}


def get_game_info(game_id):
    """
    Get detailed game info from RetroAchievements by game ID
    """
    username, api_key = get_ra_credentials()
    
    if not api_key:
        return None
    
    try:
        url = "https://retroachievements.org/API/API_GetGame.php"
        params = {
            'z': username,
            'y': api_key,
            'i': game_id,
        }
        
        response = http_get(url, params=params, timeout=30, max_bytes=getattr(config, "MAX_API_RESPONSE_BYTES", 10 * 1024 * 1024))

        # Pass 41.7.C — same pattern as GetGameList above; explicit 401 log.
        if response is not None and response.status_code == 401:
            logger.error(
                "RetroAchievements API returned 401 for GetGame "
                "(game_id=%s) — your RA API key is invalid or revoked. "
                "Re-enter the api_key in Settings → Scrapers.",
                game_id,
            )

        if response is not None and response.status_code == 200:
            data = response.json()

            return {
                'id': data.get('ID'),
                'title': data.get('Title'),
                'console_name': data.get('ConsoleName'),
                'achievement_count': data.get('NumAchievements', 0),
                'points': data.get('Points', 0),
                'has_achievements': data.get('NumAchievements', 0) > 0,
                'url': f"https://retroachievements.org/game/{data.get('ID')}",
                'image_icon': data.get('ImageIcon'),
                'image_title': data.get('ImageTitle'),
                'image_ingame': data.get('ImageIngame'),
                'image_box_art': data.get('ImageBoxArt'),
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting RA game info: {e}")
        return None


def get_user_game_progress(game_id, username=None):
    """
    Get user's progress for a specific game including individual achievements
    Returns detailed achievement info with unlocked status
    """
    ra_username, api_key = get_ra_credentials()
    
    # Use provided username or fall back to configured username
    target_user = username or ra_username
    
    if not api_key or not target_user:
        logger.warning("RetroAchievements credentials not configured")
        return None
    
    try:
        # API_GetGameInfoAndUserProgress gives us everything we need
        url = "https://retroachievements.org/API/API_GetGameInfoAndUserProgress.php"
        params = {
            'z': ra_username,  # Auth username
            'y': api_key,
            'u': target_user,  # Target user to get progress for
            'g': game_id,
        }

        response = http_get(url, params=params, timeout=30, max_bytes=getattr(config, "MAX_API_RESPONSE_BYTES", 10 * 1024 * 1024))

        # Pass 41.7.C — explicit 401 log (see GetGameList for context).
        if response is not None and response.status_code == 401:
            logger.error(
                "RetroAchievements API returned 401 for GetGameInfoAndUserProgress "
                "(game_id=%s, user=%s) — your RA API key is invalid or revoked. "
                "Re-enter the api_key in Settings → Scrapers.",
                game_id, target_user,
            )

        if response is not None and response.status_code == 200:
            data = response.json()

            # Parse achievements
            achievements = []
            achievements_raw = data.get('Achievements', {})
            
            if isinstance(achievements_raw, dict):
                for ach_id, ach in achievements_raw.items():
                    achievements.append({
                        'id': ach.get('ID'),
                        'title': ach.get('Title'),
                        'description': ach.get('Description'),
                        'points': ach.get('Points', 0),
                        'badge_name': ach.get('BadgeName'),
                        'badge_url': f"https://media.retroachievements.org/Badge/{ach.get('BadgeName')}.png" if ach.get('BadgeName') else None,
                        'badge_url_locked': f"https://media.retroachievements.org/Badge/{ach.get('BadgeName')}_lock.png" if ach.get('BadgeName') else None,
                        'display_order': ach.get('DisplayOrder', 0),
                        'date_earned': ach.get('DateEarned'),
                        'date_earned_hardcore': ach.get('DateEarnedHardcore'),
                        'is_unlocked': ach.get('DateEarned') is not None,
                        'is_unlocked_hardcore': ach.get('DateEarnedHardcore') is not None,
                        'type': ach.get('type', 'standard'),
                    })
            
            # Sort by display order
            achievements.sort(key=lambda x: (0 if x['is_unlocked'] else 1, x['display_order']))
            
            # Count unlocked
            unlocked_count = sum(1 for a in achievements if a['is_unlocked'])
            unlocked_hardcore = sum(1 for a in achievements if a['is_unlocked_hardcore'])
            total_points = sum(a['points'] for a in achievements)
            earned_points = sum(a['points'] for a in achievements if a['is_unlocked'])
            
            return {
                'game_id': data.get('ID'),
                'title': data.get('Title'),
                'console_name': data.get('ConsoleName'),
                'image_icon': f"https://media.retroachievements.org{data.get('ImageIcon')}" if data.get('ImageIcon') else None,
                'image_title': f"https://media.retroachievements.org{data.get('ImageTitle')}" if data.get('ImageTitle') else None,
                'image_ingame': f"https://media.retroachievements.org{data.get('ImageIngame')}" if data.get('ImageIngame') else None,
                'image_box_art': f"https://media.retroachievements.org{data.get('ImageBoxArt')}" if data.get('ImageBoxArt') else None,
                'achievements': achievements,
                'achievement_count': len(achievements),
                'unlocked_count': unlocked_count,
                'unlocked_hardcore': unlocked_hardcore,
                'total_points': total_points,
                'earned_points': earned_points,
                'completion_percentage': round((unlocked_count / len(achievements) * 100), 1) if achievements else 0,
                'url': f"https://retroachievements.org/game/{data.get('ID')}",
                'user_completion': data.get('UserCompletion'),
                'user_completion_hardcore': data.get('UserCompletionHardcore'),
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting user game progress: {e}")
        return None


def _earned_percent(awarded, players):
    """How rare an achievement is: the share of this game's players who earned it."""
    try:
        return round(int(awarded) / int(players) * 100, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def get_user_game_progress_custom(game_id, username, api_key):
    """
    Get user's progress for a specific game using custom credentials
    This allows per-user RetroAchievements tracking
    """
    if not api_key or not username:
        logger.warning("RetroAchievements credentials not provided")
        return None
    
    try:
        # API_GetGameInfoAndUserProgress gives us everything we need
        url = "https://retroachievements.org/API/API_GetGameInfoAndUserProgress.php"
        params = {
            'z': username,  # Auth username
            'y': api_key,
            'u': username,  # Target user to get progress for
            'g': game_id,
        }

        response = http_get(url, params=params, timeout=30, max_bytes=getattr(config, "MAX_API_RESPONSE_BYTES", 10 * 1024 * 1024))

        # Pass 41.7.C — explicit 401 log (see GetGameList for context).
        if response is not None and response.status_code == 401:
            logger.error(
                "RetroAchievements API returned 401 for GetGameInfoAndUserProgress "
                "(per-user creds, game_id=%s, user=%s) — RA API key invalid "
                "or revoked. Re-enter the api_key in Settings → Scrapers.",
                game_id, username,
            )

        if response is not None and response.status_code == 200:
            data = response.json()
            players = data.get('NumDistinctPlayers')

            # Parse achievements
            achievements = []
            achievements_raw = data.get('Achievements', {})
            
            if isinstance(achievements_raw, dict):
                for ach_id, ach in achievements_raw.items():
                    achievements.append({
                        'id': ach.get('ID'),
                        'title': ach.get('Title'),
                        'description': ach.get('Description'),
                        'points': ach.get('Points', 0),
                        'badge_name': ach.get('BadgeName'),
                        'badge_url': f"https://media.retroachievements.org/Badge/{ach.get('BadgeName')}.png" if ach.get('BadgeName') else None,
                        'badge_url_locked': f"https://media.retroachievements.org/Badge/{ach.get('BadgeName')}_lock.png" if ach.get('BadgeName') else None,
                        'display_order': ach.get('DisplayOrder', 0),
                        'date_earned': ach.get('DateEarned'),
                        'date_earned_hardcore': ach.get('DateEarnedHardcore'),
                        'is_unlocked': ach.get('DateEarned') is not None,
                        'is_unlocked_hardcore': ach.get('DateEarnedHardcore') is not None,
                        'type': ach.get('type', 'standard'),
                        'earned_percent': _earned_percent(ach.get('NumAwarded'), players),
                    })
            
            # Sort by display order
            achievements.sort(key=lambda x: (0 if x['is_unlocked'] else 1, x['display_order']))
            
            # Count unlocked
            unlocked_count = sum(1 for a in achievements if a['is_unlocked'])
            unlocked_hardcore = sum(1 for a in achievements if a['is_unlocked_hardcore'])
            total_points = sum(a['points'] for a in achievements)
            earned_points = sum(a['points'] for a in achievements if a['is_unlocked'])
            
            return {
                'game_id': data.get('ID'),
                'title': data.get('Title'),
                'console_name': data.get('ConsoleName'),
                'image_icon': f"https://media.retroachievements.org{data.get('ImageIcon')}" if data.get('ImageIcon') else None,
                'image_title': f"https://media.retroachievements.org{data.get('ImageTitle')}" if data.get('ImageTitle') else None,
                'image_ingame': f"https://media.retroachievements.org{data.get('ImageIngame')}" if data.get('ImageIngame') else None,
                'image_box_art': f"https://media.retroachievements.org{data.get('ImageBoxArt')}" if data.get('ImageBoxArt') else None,
                'achievements': achievements,
                'achievement_count': len(achievements),
                'player_count': players,
                'unlocked_count': unlocked_count,
                'unlocked_hardcore': unlocked_hardcore,
                'total_points': total_points,
                'earned_points': earned_points,
                'completion_percentage': round((unlocked_count / len(achievements) * 100), 1) if achievements else 0,
                'url': f"https://retroachievements.org/game/{data.get('ID')}",
                'user_completion': data.get('UserCompletion'),
                'user_completion_hardcore': data.get('UserCompletionHardcore'),
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting user game progress with custom credentials: {e}")
        return None


def get_user_summary(username=None):
    """
    Get user's overall RetroAchievements summary/profile
    """
    ra_username, api_key = get_ra_credentials()
    target_user = username or ra_username
    
    if not api_key or not target_user:
        return None
    
    try:
        url = "https://retroachievements.org/API/API_GetUserSummary.php"
        params = {
            'z': ra_username,
            'y': api_key,
            'u': target_user,
            'g': 5,  # Number of recent games
        }
        
        response = http_get(url, params=params, timeout=30, max_bytes=getattr(config, "MAX_API_RESPONSE_BYTES", 10 * 1024 * 1024))

        # Pass 41.7.C — explicit 401 log (see GetGameList for context).
        if response is not None and response.status_code == 401:
            logger.error(
                "RetroAchievements API returned 401 for GetUserSummary "
                "(user=%s) — your RA API key is invalid or revoked. "
                "Re-enter the api_key in Settings → Scrapers.",
                target_user,
            )

        if response is not None and response.status_code == 200:
            data = response.json()
            return {
                'username': data.get('User'),
                'total_points': data.get('TotalPoints', 0),
                'total_softcore_points': data.get('TotalSoftcorePoints', 0),
                'total_true_points': data.get('TotalTruePoints', 0),
                'rank': data.get('Rank'),
                'member_since': data.get('MemberSince'),
                'recent_games': data.get('RecentlyPlayedCount', 0),
                'user_pic': f"https://media.retroachievements.org{data.get('UserPic')}" if data.get('UserPic') else None,
                'status': data.get('Status'),
            }
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting user summary: {e}")
        return None


def check_retroachievements(game_title, system_folder, rom_path=None, alternate_titles=None):
    """What RetroAchievements says about a game; see search_game_by_name.

    None also means RA has no console for this folder or no key is set.
    """
    console_id = get_ra_console_id(system_folder)

    if not console_id:
        logger.debug(f"No RA console mapping for: {system_folder}")
        return None

    username, api_key = get_ra_credentials()
    if not api_key:
        logger.debug("RetroAchievements API key not configured")
        return None

    return search_game_by_name(game_title, console_id, rom_path, system_folder, alternate_titles)


# Test function
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Test search
    result = check_retroachievements("Super Mario 64", "n64")
    if result:
        print(f"Found: {result['title']}")
        print(f"Achievements: {result['achievement_count']}")
        print(f"URL: {result['url']}")
    else:
        print("No RetroAchievements entry found")
