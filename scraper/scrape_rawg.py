# =============================================================================
# RAWG.io SCRAPER
# =============================================================================
# Fetches game metadata from RAWG.io API
# API Documentation: https://rawg.io/apidocs
# =============================================================================

import logging
import os
import sys

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.base_scraper import http_get, safe_json, rate_limit
import config as _config

# Pass 45.14 — cap RAWG JSON response, mirroring RA + AI + ScreenScraper.
_RAWG_MAX_BYTES = getattr(_config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.rawg.io/api"

# Platform mapping from ES-DE folder names to RAWG platform IDs
# Full list: https://api.rawg.io/api/platforms?key=YOUR_KEY
PLATFORM_MAP = {
    # Nintendo
    'nes': 49,            # NES
    'famicom': 49,
    'snes': 79,           # SNES
    'superfamicom': 79,
    'n64': 83,            # Nintendo 64
    'gc': 105,            # GameCube
    'gamecube': 105,
    'wii': 11,            # Wii
    'wiiu': 10,           # Wii U
    'switch': 7,          # Nintendo Switch
    'gb': 26,             # Game Boy
    'gameboy': 26,
    'gbc': 43,            # Game Boy Color
    'gba': 24,            # Game Boy Advance
    'nds': 9,             # Nintendo DS
    'n3ds': 8,            # Nintendo 3DS
    '3ds': 8,
    'virtualboy': 105,    # Virtual Boy (mapped to GameCube as fallback)
    
    # Sony
    'psx': 27,            # PlayStation
    'ps1': 27,
    'playstation': 27,
    'ps2': 15,            # PlayStation 2
    'ps3': 16,            # PlayStation 3
    'ps4': 18,            # PlayStation 4
    'ps5': 187,           # PlayStation 5
    'psp': 17,            # PlayStation Portable
    'psvita': 19,         # PlayStation Vita
    'vita': 19,
    
    # Sega
    'genesis': 167,       # Sega Genesis/Mega Drive
    'megadrive': 167,
    'mastersystem': 74,   # Sega Master System
    'sms': 74,
    'segacd': 119,        # Sega CD
    'sega32x': 117,       # Sega 32X
    '32x': 117,
    'saturn': 107,        # Sega Saturn
    'dreamcast': 106,     # Sega Dreamcast
    'dc': 106,
    'gamegear': 77,       # Sega Game Gear
    'gg': 77,
    
    # Other
    'pcengine': 55,       # PC Engine/TurboGrafx-16
    'tg16': 55,
    'turbografx16': 55,
    'neogeo': 12,         # Neo Geo
    'neogeocd': 12,
    'arcade': 4,          # Arcade
    'mame': 4,
    'fbneo': 4,
    'atari2600': 23,      # Atari 2600
    'atari5200': 31,      # Atari 5200
    'atari7800': 28,      # Atari 7800
    'atarilynx': 46,      # Atari Lynx
    'lynx': 46,
    'atarijaguar': 112,   # Atari Jaguar
    'jaguar': 112,
    'atarist': 25,        # Atari ST
    'colecovision': 111,  # ColecoVision
    'intellivision': 115, # Intellivision
    '3do': 111,           # 3DO (mapped to ColecoVision as fallback - no direct 3DO in RAWG)
    
    # Microsoft
    'xbox': 80,           # Xbox
    'xbox360': 14,        # Xbox 360
    'xboxone': 1,         # Xbox One
    'xboxseriesx': 186,   # Xbox Series X/S
    
    # PC
    'pc': 4,              # PC
    'dos': 171,           # DOS
    'amiga': 166,         # Amiga
    'c64': 75,            # Commodore 64
}

def _get_api_key():
    """Get the RAWG API key from saved settings, falling back to config.py."""
    from scraper.scraper_manager import get_api_key
    return get_api_key('rawg', 'RAWG_API_KEY')


def _make_request(endpoint, params=None, max_retries=2):
    """Make a request to RAWG API with retry logic"""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("RAWG API key not configured")
        return None

    if params is None:
        params = {}

    params['key'] = api_key

    url = f"{BASE_URL}/{endpoint}"

    response = http_get(url, params=params, timeout=20, retries=max_retries, max_bytes=_RAWG_MAX_BYTES)

    if response is None:
        logger.warning(f"RAWG request failed (no response): {url}")
        return None

    if response.status_code == 200:
        return safe_json(response)
    else:
        logger.warning(f"RAWG request failed: {response.status_code} - URL: {url}")
        return None


def search_games(title, system_folder=None, limit=10):
    """Search for games on RAWG"""
    results = []
    
    params = {
        'search': title,
        'page_size': limit,
        'search_precise': 'true',  # More precise search results
        'exclude_additions': 'true',  # Exclude DLCs/editions from results
    }
    
    # Add platform filter if available
    if system_folder:
        platform_id = PLATFORM_MAP.get(system_folder.lower())
        if platform_id:
            params['platforms'] = platform_id
    
    platform_id = PLATFORM_MAP.get(system_folder.lower()) if system_folder else None
    logger.info(f"RAWG: Searching with platform_id={platform_id} for system_folder={system_folder}")

    data = _make_request('games', params)

    # Fallback 1: if precise search returns 0 results, retry without search_precise
    if data and 'results' in data and len(data['results']) == 0:
        logger.info(f"RAWG precise search returned 0 results for '{title}', retrying with fuzzy search")
        params.pop('search_precise', None)
        data = _make_request('games', params)

    # Fallback 2: if platform-filtered search still returns 0, retry without platform filter
    # RAWG has poor platform coverage for retro systems (e.g. C64 games listed under Amiga)
    if data and 'results' in data and len(data['results']) == 0 and 'platforms' in params:
        logger.info(f"RAWG platform-filtered search returned 0 results for '{title}', retrying without platform filter")
        params.pop('platforms', None)
        data = _make_request('games', params)

    if not data or 'results' not in data:
        logger.warning(f"RAWG search returned no data for '{title}'")
        return results
    
    for game in data['results']:
        # Extract platforms
        platforms = []
        platform_match = False
        matched_platform_name = None
        
        if game.get('platforms'):
            for p in game['platforms']:
                plat = p.get('platform', {})
                plat_info = {
                    'id': plat.get('id'),
                    'name': plat.get('name', '')
                }
                if platform_id and plat.get('id') == platform_id:
                    platform_match = True
                    matched_platform_name = plat.get('name', '')
                    # Put matched platform first
                    platforms.insert(0, plat_info)
                else:
                    platforms.append(plat_info)
        
        # Build result
        result = {
            'id': game.get('id'),
            'slug': game.get('slug'),
            'name': game.get('name', ''),
            'description': '',  # Not available in search results
            'source': 'rawg',
            'release_date': game.get('released', ''),
            'platforms': platforms,
            'image': game.get('background_image'),
            'platform_match': platform_match,
            'matched_platform': matched_platform_name,  # Specific matched platform
            'rating': game.get('rating'),  # RAWG user rating (0-5)
            'metacritic': game.get('metacritic'),  # Metacritic score
            'esrb_rating': game.get('esrb_rating', {}).get('slug') if game.get('esrb_rating') else None
        }
        
        results.append(result)
    
    # Rate limit - RAWG free tier has 20,000 requests/month
    rate_limit(0.3)
    
    return results


def get_game_details(game_id):
    """Get detailed information about a specific game by ID or slug"""
    data = _make_request(f'games/{game_id}')
    
    if not data:
        return None
    
    game = data
    
    # Extract developers
    developers = []
    if game.get('developers'):
        developers = [d.get('name') for d in game['developers'] if d.get('name')]
    
    # Extract publishers
    publishers = []
    if game.get('publishers'):
        publishers = [p.get('name') for p in game['publishers'] if p.get('name')]
    
    # Extract genres
    genres = []
    if game.get('genres'):
        genres = [g.get('name') for g in game['genres'] if g.get('name')]
    
    # Extract tags (can be useful for additional categorization)
    tags = []
    if game.get('tags'):
        # Only get English tags
        tags = [t.get('name') for t in game['tags'][:10] if t.get('name') and t.get('language') == 'eng']
    
    # Extract ESRB rating
    esrb_rating = None
    if game.get('esrb_rating'):
        esrb_map = {
            'everyone': 'E',
            'everyone-10-plus': 'E10+',
            'teen': 'T',
            'mature': 'M',
            'adults-only': 'AO',
            'rating-pending': 'RP'
        }
        esrb_slug = game['esrb_rating'].get('slug', '')
        esrb_rating = esrb_map.get(esrb_slug, game['esrb_rating'].get('name', ''))
    
    # Get screenshots
    screenshot_urls = []
    # Need separate API call for screenshots
    screenshots_data = _make_request(f'games/{game_id}/screenshots')
    if screenshots_data and 'results' in screenshots_data:
        screenshot_urls = [s.get('image') for s in screenshots_data['results'][:5] if s.get('image')]
    
    # Determine player count from tags
    players = 1
    if game.get('tags'):
        for tag in game['tags']:
            tag_name = tag.get('name', '').lower()
            if 'multiplayer' in tag_name or 'co-op' in tag_name:
                players = 2
                break
            if '4 player' in tag_name or 'four player' in tag_name:
                players = 4
                break
    
    # Game modes
    modes = []
    if game.get('tags'):
        for tag in game['tags']:
            tag_name = tag.get('name', '').lower()
            if tag_name in ['singleplayer', 'single-player']:
                modes.append('Single-Player')
            elif tag_name in ['multiplayer', 'multi-player']:
                modes.append('Multiplayer')
            elif 'co-op' in tag_name or 'coop' in tag_name:
                modes.append('Co-op')
            elif 'online' in tag_name and 'multiplayer' in tag_name:
                modes.append('Online Multiplayer')
    
    # Convert RAWG rating (0-5) to 0-100 scale for consistency
    user_score = None
    user_score_count = None
    if game.get('rating'):
        user_score = round(game['rating'] * 20, 1)  # Convert 0-5 to 0-100
        user_score_count = game.get('ratings_count', 0)

    # Fetch game series for franchise data (separate API call)
    franchise = None
    series_data = _make_request(f'games/{game_id}/game-series', {'page_size': 5})
    if series_data and series_data.get('count', 0) > 0:
        # The series endpoint returns related games; the series name is implied
        # by the shared games. Use the first result's name pattern if available.
        series_names = [g.get('name', '') for g in series_data.get('results', []) if g.get('name')]
        if series_names:
            # Find common prefix among series game names for franchise identification
            from os.path import commonprefix
            prefix = commonprefix(series_names + [game.get('name', '')]).strip().rstrip(':- ')
            if prefix and len(prefix) >= 3:
                franchise = prefix

    # RAWG's detail endpoint returns alternative_names as a flat list of strings
    # (no region metadata). Keep them verbatim so the merger can dedupe.
    alternative_names = []
    for alt in game.get('alternative_names') or []:
        if isinstance(alt, str) and alt.strip():
            alternative_names.append(alt.strip())

    result = {
        'id': game.get('id'),
        'slug': game.get('slug'),
        'name': game.get('name', ''),
        'description': game.get('description_raw', ''),  # Plain text description
        'release_date': game.get('released', ''),
        'developer': ', '.join(developers) if developers else None,
        'publisher': ', '.join(publishers) if publishers else None,
        'genre': ', '.join(genres) if genres else None,
        'esrb_rating': esrb_rating,
        'players': players,
        'modes': ', '.join(modes) if modes else None,
        'boxart_url': game.get('background_image'),
        'fanart_url': game.get('background_image_additional'),  # Secondary image for fanart
        'screenshot_urls': screenshot_urls,
        'metacritic': game.get('metacritic'),  # Critic score (0-100)
        'user_score': user_score,  # Converted to 0-100 scale
        'user_score_count': user_score_count,
        'playtime': game.get('playtime'),  # Average playtime in hours
        'website': game.get('website'),
        'franchise': franchise,
        'alternative_names': alternative_names,
        'source': 'rawg'
    }

    rate_limit(0.3)  # Rate limiting

    return result


def check_api_status():
    """Check if RAWG API is available"""
    if not _get_api_key():
        return False

    data = _make_request('games', {'page_size': 1})
    return data is not None


# =============================================================================
# MAIN (for testing)
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    print("Testing RAWG API...")
    
    if check_api_status():
        print("✅ API is working")
        
        results = search_games("Super Mario World", "snes")
        print(f"\nSearch results for 'Super Mario World':")
        for r in results[:3]:
            print(f"  - {r['name']} ({r['release_date']}) [ID: {r['id']}] ESRB: {r.get('esrb_rating')}")
        
        if results:
            details = get_game_details(results[0]['id'])
            if details:
                print(f"\nDetails for {details['name']}:")
                print(f"  Developer: {details['developer']}")
                print(f"  Publisher: {details['publisher']}")
                print(f"  Genre: {details['genre']}")
                print(f"  ESRB: {details['esrb_rating']}")
                print(f"  Metacritic: {details['metacritic']}")
                print(f"  User Score: {details['user_score']}")
    else:
        print("❌ API not available")
