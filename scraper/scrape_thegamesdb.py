# =============================================================================
# THEGAMESDB SCRAPER
# =============================================================================
# Primary scraper for game metadata - provides platform-specific boxart.
# Uses cached lookups for publishers/developers/genres to minimize API calls.
# =============================================================================

import os
import re
import logging
import sys
import time

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import IMAGE_PATH, TGDB_SYSTEM_MAP, TGDB_GENRE_MAP

from scraper.base_scraper import http_get, get_scraper_conn, download_image
import config as _config

# Pass 45.14 — every scraper API response cap, mirroring RA + AI + ScreenScraper.
_TGDB_MAX_BYTES = getattr(_config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)

logger = logging.getLogger(__name__)

# =============================================================================
# API BASE URL
# =============================================================================

TGDB_API_BASE = "https://api.thegamesdb.net"

# =============================================================================
# MODULE-LEVEL CACHES
# =============================================================================
# Publishers, developers, and genres are static lookup tables that rarely change.
# Caching them avoids 3 extra API calls per game during bulk scraping.

_publishers_cache = None
_developers_cache = None
_genres_cache = None
_allowance_info = None  # Last seen API allowance data

# =============================================================================
# API KEY RESOLUTION & REQUEST WRAPPER
# =============================================================================

def get_api_keys():
    """Get the best available TGDB API keys (public preferred, private fallback).

    Uses centralized get_api_key() from scraper_manager.
    Returns (public_key, private_key) tuple.
    """
    from .scraper_manager import get_api_key
    public_key = get_api_key('tgdb_public', 'THEGAMESDB_PUBLIC_API_KEY')
    private_key = get_api_key('tgdb', 'THEGAMESDB_API_KEY')
    return (public_key, private_key)


def _tgdb_request(url, params=None, timeout=30):
    """Make a TGDB API request with public key first, falling back to private key.

    Replaces the 'apikey' param with the public key, makes the request.
    If 403, retries with the private key.
    Tracks API allowance from response headers.
    Returns the requests.Response object, or None on total failure.
    """
    global _allowance_info

    if params is None:
        params = {}

    public_key, private_key = get_api_keys()

    # Try public key first (if available)
    keys_to_try = []
    if public_key:
        keys_to_try.append(('public', public_key))
    if private_key:
        keys_to_try.append(('private', private_key))

    if not keys_to_try:
        logger.error("No TGDB API keys configured")
        return None

    for key_type, key in keys_to_try:
        params['apikey'] = key
        response = http_get(url, params=params, timeout=timeout, retries=2, max_bytes=_TGDB_MAX_BYTES)

        if response is None:
            logger.error(f"TGDB request failed with {key_type} key (no response)")
            continue

        if response.status_code == 200:
            # Track API allowance from response
            try:
                data = response.json()
                if isinstance(data, dict):
                    remaining = data.get('remaining_monthly_allowance')
                    extra = data.get('extra_allowance')
                    if remaining is not None:
                        _allowance_info = {
                            'remaining_monthly': remaining,
                            'extra': extra or 0,
                            'timestamp': time.time()
                        }
                        if remaining < 100:
                            logger.warning(f"TGDB API allowance low: {remaining} remaining (+{extra or 0} extra)")
                        else:
                            logger.debug(f"TGDB API allowance: {remaining} remaining (+{extra or 0} extra)")
            except Exception:
                pass
            return response
        elif response.status_code == 403:
            logger.warning(f"TGDB {key_type} key returned 403, trying next key...")
            continue
        else:
            logger.warning(f"TGDB API returned status {response.status_code} with {key_type} key")
            return response

    logger.error("All TGDB API keys exhausted")
    return None


def get_api_allowance():
    """Get the last known API allowance info.

    Returns dict with 'remaining_monthly', 'extra', 'timestamp' or None.
    """
    return _allowance_info


def clear_caches():
    """Clear all module-level caches (useful for long-running sessions)."""
    global _publishers_cache, _developers_cache, _genres_cache
    _publishers_cache = None
    _developers_cache = None
    _genres_cache = None
    logger.info("TGDB lookup caches cleared")


# =============================================================================
# CACHED LOOKUP TABLES
# =============================================================================

def _get_publishers():
    """Fetch and cache all publisher names (single API call, reused across games)."""
    global _publishers_cache
    if _publishers_cache is not None:
        return _publishers_cache

    try:
        response = _tgdb_request(f"{TGDB_API_BASE}/v1/Publishers", params={}, timeout=15)
        if response and response.status_code == 200:
            data = response.json()
            _publishers_cache = data.get('data', {}).get('publishers', {})
            logger.info(f"Cached {len(_publishers_cache)} TGDB publishers")
            return _publishers_cache
    except Exception as e:
        logger.warning(f"Failed to fetch publishers: {e}")

    _publishers_cache = {}
    return _publishers_cache


def _get_developers():
    """Fetch and cache all developer names (single API call, reused across games)."""
    global _developers_cache
    if _developers_cache is not None:
        return _developers_cache

    try:
        response = _tgdb_request(f"{TGDB_API_BASE}/v1/Developers", params={}, timeout=15)
        if response and response.status_code == 200:
            data = response.json()
            _developers_cache = data.get('data', {}).get('developers', {})
            logger.info(f"Cached {len(_developers_cache)} TGDB developers")
            return _developers_cache
    except Exception as e:
        logger.warning(f"Failed to fetch developers: {e}")

    _developers_cache = {}
    return _developers_cache


def _get_genres():
    """Fetch and cache all genre names (single API call, reused across games)."""
    global _genres_cache
    if _genres_cache is not None:
        return _genres_cache

    try:
        response = _tgdb_request(f"{TGDB_API_BASE}/v1/Genres", params={}, timeout=15)
        if response and response.status_code == 200:
            data = response.json()
            _genres_cache = data.get('data', {}).get('genres', {})
            logger.info(f"Cached {len(_genres_cache)} TGDB genres")
            return _genres_cache
    except Exception as e:
        logger.warning(f"Failed to fetch genres: {e}")

    _genres_cache = {}
    return _genres_cache


def _resolve_names(ids, cache_fn, entity_key='name'):
    """Resolve a list of entity IDs to names using a cached lookup table."""
    if not ids:
        return ''
    lookup = cache_fn()
    names = []
    for eid in ids:
        info = lookup.get(str(eid), {})
        if info:
            names.append(info.get(entity_key, str(eid)))
        else:
            names.append(str(eid))
    return ', '.join(names)


def _resolve_genre_names(genre_ids):
    """Resolve genre IDs to names, with fallback to local TGDB_GENRE_MAP."""
    if not genre_ids:
        return []
    lookup = _get_genres()
    names = []
    for gid in genre_ids:
        info = lookup.get(str(gid), {})
        if info:
            names.append(info.get('name', str(gid)))
        elif isinstance(gid, int) and gid in TGDB_GENRE_MAP:
            names.append(TGDB_GENRE_MAP[gid])
        else:
            names.append(str(gid))
    return names


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def extract_region_from_title(title):
    """Extract region from game title parentheses"""
    if not title:
        return None

    region_patterns = {
        r'\(USA\)': 'USA',
        r'\(US\)': 'USA',
        r'\(Europe\)': 'Europe',
        r'\(EU\)': 'Europe',
        r'\(Japan\)': 'Japan',
        r'\(JP\)': 'Japan',
        r'\(World\)': 'World',
        r'\(PAL\)': 'PAL',
        r'\(NTSC\)': 'NTSC',
        r'\(USA, Europe\)': 'USA/Europe',
        r'\(Japan, USA\)': 'Japan/USA',
    }

    for pattern, region in region_patterns.items():
        if re.search(pattern, title, re.IGNORECASE):
            return region

    return None

# =============================================================================
# SYSTEM ID MAPPING
# =============================================================================

def get_system_id(system_name):
    """Get TheGamesDB system ID from system name"""
    if not system_name:
        return None

    # Clean the system name
    system_lower = system_name.lower().strip()

    logger.debug(f"Looking up system ID for: '{system_name}' -> '{system_lower}'")

    # Direct mapping
    if system_lower in TGDB_SYSTEM_MAP:
        return TGDB_SYSTEM_MAP[system_lower]

    # Try removing common prefixes
    prefixes = ['sony ', 'microsoft ', 'nintendo ', 'sega ', 'atari ', 'snk ']
    for prefix in prefixes:
        if system_lower.startswith(prefix):
            cleaned = system_lower[len(prefix):].strip()
            if cleaned in TGDB_SYSTEM_MAP:
                return TGDB_SYSTEM_MAP[cleaned]

    # Try partial match
    for key, value in TGDB_SYSTEM_MAP.items():
        if key in system_lower or system_lower in key:
            return value

    logger.warning(f"Could not find system ID for: {system_name}")
    return None

# =============================================================================
# SEARCH GAMES
# =============================================================================

def search_games(title, system_name=None, limit=10):
    """Search games on TheGamesDB"""
    system_id = get_system_id(system_name)

    try:
        url = f"{TGDB_API_BASE}/v1.1/Games/ByGameName"
        params = {
            'name': title,
            'fields': 'id,game_title,release_date,platform,region_id',
            'include': 'platform'
        }

        if system_id:
            params['filter[platform]'] = str(system_id)

        logger.info(f"Searching TGDB: '{title}' (System: {system_name}, ID: {system_id})")

        response = _tgdb_request(url, params=params, timeout=30)

        if response and response.status_code == 200:
            data = response.json()

            if data.get('code') == 200 and 'data' in data:
                games = data['data'].get('games', [])

                # Get platform names from include data
                platforms_data = data.get('include', {}).get('platform', {}).get('data', {})

                results = []
                for game in games[:limit]:
                    if isinstance(game, dict):
                        game_id = game.get('id')
                        game_title = game.get('game_title', title)
                        platform_id = game.get('platform')

                        # Get platform name
                        platform_name = system_name or ''
                        if platform_id and str(platform_id) in platforms_data:
                            platform_name = platforms_data[str(platform_id)].get('name', platform_name)

                        # Check if platform matches what we searched for
                        platform_match = False
                        if system_id and platform_id:
                            platform_match = (str(platform_id) == str(system_id))

                        # Extract region from title or region_id
                        region = extract_region_from_title(game_title)
                        if not region:
                            region_id = game.get('region_id')
                            if region_id:
                                region_map = {1: 'USA', 2: 'Europe', 3: 'Japan', 4: 'World'}
                                region = region_map.get(region_id)

                        if game_id:
                            results.append({
                                'id': str(game_id),
                                'name': game_title,
                                'release_date': game.get('release_date', ''),
                                'platform': platform_name,
                                'platforms': [{'name': platform_name}] if platform_name else [],
                                'region': region,
                                'source': 'thegamesdb',
                                'platform_match': platform_match,
                                'matched_platform': platform_name if platform_match else None
                            })

                logger.info(f"TGDB found {len(results)} results")
                return results
        elif response:
            logger.warning(f"TGDB API returned status {response.status_code}")
        else:
            logger.warning("TGDB API request failed (no keys available)")

    except Exception as e:
        logger.error(f"TGDB search error: {e}")

    return []

# =============================================================================
# FETCH GAME DETAILS
# =============================================================================

def fetch_game_details(game_id):
    """Fetch detailed game information from TheGamesDB.

    Uses cached publisher/developer/genre lookups to minimize API calls.
    Per-game cost: 2 API calls (game details + images) instead of 5.
    """
    try:
        url = f"{TGDB_API_BASE}/v1/Games/ByGameID"
        params = {
            'id': game_id,
            'fields': 'players,publishers,genres,overview,rating,platform,developers',
            'include': 'boxart,platform'
        }

        logger.info(f"Fetching TGDB details for game ID: {game_id}")

        response = _tgdb_request(url, params=params, timeout=30)

        if response and response.status_code == 200:
            data = response.json()

            if data.get('code') == 200 and 'data' in data:
                games = data['data'].get('games', [])

                if games:
                    game = games[0]

                    # Resolve publisher/developer/genre names from cached lookups
                    publisher_str = _resolve_names(game.get('publishers', []), _get_publishers)
                    developer_str = _resolve_names(game.get('developers', []), _get_developers)
                    genre_names = _resolve_genre_names(game.get('genres', []))

                    # Process boxart
                    boxart_url = None
                    include_data = data.get('include', {})
                    boxart_data = include_data.get('boxart', {})

                    base_url = boxart_data.get('base_url', {}).get('original', '')
                    game_boxart = boxart_data.get('data', {}).get(str(game_id), [])

                    for art in game_boxart:
                        if art.get('side') == 'front':
                            boxart_url = base_url + art.get('filename', '')
                            break

                    # If no front boxart, try any boxart
                    if not boxart_url and game_boxart:
                        boxart_url = base_url + game_boxart[0].get('filename', '')

                    # Get screenshots and fanart from separate images endpoint
                    screenshot_urls, fanart_urls = _fetch_game_images(game_id)

                    result = {
                        'id': game_id,
                        'name': game.get('game_title', ''),
                        'release_date': game.get('release_date', ''),
                        'publisher': publisher_str,
                        'developer': developer_str,
                        'genres': genre_names,
                        'players': game.get('players', 1),
                        'rating': game.get('rating', ''),
                        'summary': game.get('overview', ''),
                        'boxart_url': boxart_url,
                        'screenshot_urls': screenshot_urls,
                        'fanart_urls': fanart_urls,
                    }

                    logger.info(f"TGDB details fetched successfully for: {result['name']}")
                    return result

        logger.warning(f"Failed to fetch TGDB details for game ID: {game_id}")
        return None

    except Exception as e:
        logger.error(f"TGDB fetch details error: {e}")
        return None


def _fetch_game_images(game_id):
    """Fetch screenshots and fanart for a game from the Images endpoint.

    Returns (screenshot_urls, fanart_urls) tuple.
    """
    screenshot_urls = []
    fanart_urls = []

    try:
        images_url = f"{TGDB_API_BASE}/v1/Games/Images"
        images_params = {
            'games_id': game_id,
            'filter[type]': 'screenshot,fanart'
        }
        images_response = _tgdb_request(images_url, params=images_params, timeout=15)
        if images_response and images_response.status_code == 200:
            images_data = images_response.json()

            # Handle different API response formats
            data = images_data.get('data', {})
            if isinstance(data, list):
                logger.warning("TGDB images API returned list instead of dict")
            elif isinstance(data, dict):
                base_url_data = data.get('base_url', {})
                if isinstance(base_url_data, dict):
                    images_base_url = base_url_data.get('original', '')
                else:
                    images_base_url = ''

                images_dict = data.get('images', {})
                if isinstance(images_dict, dict):
                    game_images = images_dict.get(str(game_id), [])

                    for img in game_images:
                        if isinstance(img, dict):
                            img_type = img.get('type', '').lower()
                            if 'screenshot' in img_type:
                                screenshot_urls.append(images_base_url + img.get('filename', ''))
                            elif 'fanart' in img_type:
                                fanart_urls.append(images_base_url + img.get('filename', ''))

                    logger.info(f"Found {len(screenshot_urls)} screenshots, {len(fanart_urls)} fanart for game {game_id}")
    except Exception as e:
        logger.warning(f"Failed to fetch images: {e}")

    return screenshot_urls, fanart_urls


# =============================================================================
# FETCH GAMES BY PLATFORM (BULK DISCOVERY)
# =============================================================================

def fetch_games_by_platform(platform_id, page=1, fields=None, include=None):
    """Fetch all games for a TGDB platform ID with pagination.

    Args:
        platform_id: TGDB platform ID (e.g. 12 for PS3).
        page: Page number (starts at 1).
        fields: Comma-separated field list (default: basic fields).
        include: Comma-separated include list (default: 'platform').

    Returns:
        Dict with 'games' list, 'count' total, 'pages' dict, or None on error.
    """
    try:
        url = f"{TGDB_API_BASE}/v1/Games/ByPlatformID"
        params = {
            'id': str(platform_id),
            'fields': fields or 'id,game_title,release_date,platform,region_id,overview',
            'include': include or 'platform',
            'page': str(page)
        }

        logger.info(f"Fetching TGDB games for platform {platform_id} (page {page})")

        response = _tgdb_request(url, params=params, timeout=30)

        if response and response.status_code == 200:
            data = response.json()
            if data.get('code') == 200 and 'data' in data:
                games = data['data'].get('games', [])
                count = data['data'].get('count', len(games))
                pages = data.get('pages', {})
                platforms_data = data.get('include', {}).get('platform', {}).get('data', {})

                results = []
                for game in games:
                    if isinstance(game, dict) and game.get('id'):
                        pid = game.get('platform')
                        platform_name = ''
                        if pid and str(pid) in platforms_data:
                            platform_name = platforms_data[str(pid)].get('name', '')

                        results.append({
                            'id': str(game['id']),
                            'name': game.get('game_title', ''),
                            'release_date': game.get('release_date', ''),
                            'platform': platform_name,
                            'platform_id': pid,
                            'overview': game.get('overview', ''),
                            'source': 'thegamesdb',
                        })

                logger.info(f"TGDB platform {platform_id}: {len(results)} games on page {page} ({count} total)")
                return {
                    'games': results,
                    'count': count,
                    'pages': pages,
                    'current_page': page,
                }

        logger.warning(f"Failed to fetch TGDB games for platform {platform_id}")
        return None

    except Exception as e:
        logger.error(f"TGDB fetch by platform error: {e}")
        return None


def fetch_all_games_by_platform(platform_id, max_pages=50):
    """Fetch ALL games for a platform by iterating through all pages.

    Args:
        platform_id: TGDB platform ID.
        max_pages: Safety limit on pages to fetch (default 50).

    Returns:
        List of all game dicts, or empty list on error.
    """
    all_games = []
    page = 1

    while page <= max_pages:
        result = fetch_games_by_platform(platform_id, page=page)
        if not result or not result['games']:
            break

        all_games.extend(result['games'])

        # Check if more pages exist
        pages = result.get('pages', {})
        next_page = pages.get('next')
        if next_page and isinstance(next_page, str):
            # Extract page number from next URL
            import urllib.parse
            parsed = urllib.parse.urlparse(next_page)
            query_params = urllib.parse.parse_qs(parsed.query)
            page = int(query_params.get('page', [page + 1])[0])
        elif page * 20 < result.get('count', 0):
            # Estimate: ~20 games per page
            page += 1
        else:
            break

    logger.info(f"TGDB platform {platform_id}: fetched {len(all_games)} total games")
    return all_games


# =============================================================================
# FETCH GAME UPDATES (INCREMENTAL SYNC)
# =============================================================================

def fetch_game_updates(last_edit_id=None, since_time=None, page=1):
    """Fetch games that have been updated since a given point.

    Use either last_edit_id (from a previous call) or since_time (Unix timestamp).

    Args:
        last_edit_id: The last edit ID from a previous updates call.
        since_time: Unix timestamp to fetch updates since.
        page: Page number for pagination.

    Returns:
        Dict with 'games' (list of updated game dicts), 'last_edit_id', 'pages',
        or None on error.
    """
    try:
        url = f"{TGDB_API_BASE}/v1/Games/Updates"
        params = {'page': str(page)}

        if last_edit_id:
            params['last_edit_id'] = str(last_edit_id)
        if since_time:
            params['time'] = str(int(since_time))

        logger.info(f"Fetching TGDB game updates (last_edit_id={last_edit_id}, since={since_time}, page={page})")

        response = _tgdb_request(url, params=params, timeout=30)

        if response and response.status_code == 200:
            data = response.json()
            if data.get('code') == 200 and 'data' in data:
                updates = data['data'].get('updates', [])
                pages = data.get('pages', {})

                games = []
                for update in updates:
                    if isinstance(update, dict):
                        games.append({
                            'id': str(update.get('edit_id', '')),
                            'game_id': update.get('game_id'),
                            'timestamp': update.get('timestamp'),
                            'type': update.get('type'),
                            'value': update.get('value'),
                        })

                # Get the last edit ID for next incremental call
                new_last_edit_id = None
                if games:
                    new_last_edit_id = max(int(g['id']) for g in games if g['id'])

                logger.info(f"TGDB updates: {len(games)} changes found (page {page})")
                return {
                    'games': games,
                    'last_edit_id': new_last_edit_id,
                    'pages': pages,
                    'current_page': page,
                }

        logger.warning("Failed to fetch TGDB game updates")
        return None

    except Exception as e:
        logger.error(f"TGDB fetch updates error: {e}")
        return None


# =============================================================================
# PLATFORM ENDPOINTS
# =============================================================================

def fetch_platforms():
    """Fetch all available platforms from TGDB.

    Returns:
        Dict mapping platform_id (str) -> platform info dict, or empty dict.
        Each platform has: id, name, alias, icon, console, controller,
        developer, manufacturer, media, cpu, memory, graphics, sound,
        maxcontrollers, display, overview, youtube.
    """
    try:
        url = f"{TGDB_API_BASE}/v1/Platforms"
        params = {'fields': 'icon,console,controller,developer,manufacturer,media,cpu,memory,graphics,sound,maxcontrollers,display,overview,youtube'}

        logger.info("Fetching all TGDB platforms")

        response = _tgdb_request(url, params=params, timeout=30)

        if response and response.status_code == 200:
            data = response.json()
            if data.get('code') == 200 and 'data' in data:
                platforms = data['data'].get('platforms', {})
                logger.info(f"TGDB: fetched {len(platforms)} platforms")
                return platforms

        logger.warning("Failed to fetch TGDB platforms")
        return {}

    except Exception as e:
        logger.error(f"TGDB fetch platforms error: {e}")
        return {}


def fetch_platform_details(platform_id):
    """Fetch detailed info for a specific platform.

    Args:
        platform_id: TGDB platform ID.

    Returns:
        Platform info dict or None.
    """
    try:
        url = f"{TGDB_API_BASE}/v1/Platforms/ByPlatformID"
        params = {
            'id': str(platform_id),
            'fields': 'icon,console,controller,developer,manufacturer,media,cpu,memory,graphics,sound,maxcontrollers,display,overview,youtube'
        }

        logger.info(f"Fetching TGDB platform details for ID: {platform_id}")

        response = _tgdb_request(url, params=params, timeout=30)

        if response and response.status_code == 200:
            data = response.json()
            if data.get('code') == 200 and 'data' in data:
                platforms = data['data'].get('platforms', {})
                # Return the platform dict (keyed by ID string)
                platform = platforms.get(str(platform_id))
                if platform:
                    logger.info(f"TGDB platform: {platform.get('name', 'Unknown')}")
                    return platform

        logger.warning(f"Failed to fetch TGDB platform {platform_id}")
        return None

    except Exception as e:
        logger.error(f"TGDB fetch platform details error: {e}")
        return None


def fetch_platform_images(platform_id):
    """Fetch images for a platform (logos, icons, banners, boxart, etc.).

    Args:
        platform_id: TGDB platform ID (or comma-separated IDs).

    Returns:
        Dict with 'base_url' and 'images' list, or None on error.
    """
    try:
        url = f"{TGDB_API_BASE}/v1/Platforms/Images"
        params = {'platforms_id': str(platform_id)}

        logger.info(f"Fetching TGDB platform images for ID: {platform_id}")

        response = _tgdb_request(url, params=params, timeout=15)

        if response and response.status_code == 200:
            data = response.json()
            if data.get('code') == 200 and 'data' in data:
                result_data = data['data']
                base_url_data = result_data.get('base_url', {})
                base_url = base_url_data.get('original', '') if isinstance(base_url_data, dict) else ''
                images = result_data.get('images', {}).get(str(platform_id), [])

                logger.info(f"TGDB platform {platform_id}: found {len(images)} images")
                return {
                    'base_url': base_url,
                    'images': images,
                }

        logger.warning(f"Failed to fetch TGDB platform images for {platform_id}")
        return None

    except Exception as e:
        logger.error(f"TGDB fetch platform images error: {e}")
        return None


# =============================================================================
# APPLY METADATA
# =============================================================================

def apply_metadata_to_game(db_game_id, tgdb_data):
    """Apply TheGamesDB metadata to database game"""
    conn = None

    try:
        conn = get_scraper_conn()
        c = conn.cursor()

        logger.info(f"Applying TGDB metadata for game {db_game_id}")

        # Pass 48.5 — media fill-only invariant. As a hybrid *fallback* path this
        # must not overwrite curated boxart/fanart or replace the screenshots
        # column. Read current media so boxart/fanart download only when empty
        # and screenshots append (mirrors scrape_esde's "augment, don't replace").
        c.execute("SELECT boxart, screenshots, fanart FROM games WHERE id = ?", (db_game_id,))
        _existing = c.fetchone()
        existing_boxart = (_existing[0] if _existing else None) or ''
        existing_screenshots = (_existing[1] if _existing else None) or ''
        existing_fanart = (_existing[2] if _existing else None) or ''

        # Extract data with defaults
        publisher = tgdb_data.get('publisher', '') or ''
        developer = tgdb_data.get('developer', '') or ''
        release_date = tgdb_data.get('release_date', '') or ''

        # Format release date
        if release_date:
            date_patterns = [
                r'(\d{4})-(\d{2})-(\d{2})',
                r'(\d{4})/(\d{2})/(\d{2})',
                r'(\d{4})',
            ]

            for pattern in date_patterns:
                match = re.search(pattern, release_date)
                if match:
                    groups = match.groups()
                    if len(groups) == 3:
                        release_date = f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}"
                        break
                    elif len(groups) == 1:
                        release_date = f"{groups[0]}-01-01"
                        break

        # Process rating for ESRB/PEGI
        rating = tgdb_data.get('rating', '') or ''
        esrb_rating = ''
        pegi_rating = ''

        if rating:
            # Shared with the hybrid path (metadata_merger) so the two cannot
            # diverge again — this copy matched substrings and mis-assigned
            # four of the six real TGDB strings (Pass 59.19). No blind
            # fallback to the raw string: a value matching no ESRB code is not
            # an ESRB rating, and the raw text stays in the `rating` column.
            from services.game_utils import parse_esrb_code
            esrb_rating = parse_esrb_code(rating)

            if 'pegi' in rating.lower():
                numbers = re.findall(r'\d+', rating)
                if numbers:
                    pegi_rating = f"PEGI {numbers[0]}"

        # Genre — normalize to hyphenated canonical forms (FIELD_SCHEMAS). This
        # single-source apply is a fallback when the hybrid fetch fails; the
        # hybrid path normalizes, so do it here too to keep the genre-filter
        # canonical regardless of caller.
        from services.normalization import normalize_genre
        genres = tgdb_data.get('genres', [])
        if isinstance(genres, list):
            genre = normalize_genre(', '.join(str(g).strip() for g in genres if g))
        else:
            genre = normalize_genre(str(genres)) if genres else ''

        # Players — Pass 40.6: leave as None when TGDB doesn't supply a
        # value (or supplies one that doesn't parse).  COALESCE(?, players)
        # then preserves the curated DB value on re-scrape.
        players = None
        players_val = tgdb_data.get('players')
        if players_val:
            try:
                parsed = int(str(players_val))
                if parsed >= 1:
                    players = parsed
            except (ValueError, TypeError):
                players = None

        # Description
        description = tgdb_data.get('summary', '') or ''

        # Game title from scraped data
        scraped_title = tgdb_data.get('name', '') or tgdb_data.get('game_title', '')

        # Download boxart — fill-only: skip when the game already has boxart.
        boxart = None
        boxart_url = tgdb_data.get('boxart_url')
        if not existing_boxart and boxart_url:
            boxart = _download_tgdb_image(db_game_id, boxart_url, 'boxart')

        # Download screenshots, then append to existing (never replace).
        screenshots = []
        screenshot_urls = tgdb_data.get('screenshot_urls', [])
        for i, ss_url in enumerate(screenshot_urls[:5]):  # Limit to 5 screenshots
            ss_filename = _download_tgdb_image(db_game_id, ss_url, 'screenshots', suffix=f'_ss{i+1}')
            if ss_filename:
                screenshots.append(ss_filename)

        _existing_ss = [s for s in existing_screenshots.split(',') if s]
        _merged_ss = _existing_ss + [s for s in screenshots if s not in _existing_ss]
        screenshots_str = ','.join(_merged_ss) if _merged_ss else None

        # Download fanart (first one only) — fill-only: skip when present.
        fanart = None
        fanart_urls = tgdb_data.get('fanart_urls', [])
        if not existing_fanart and fanart_urls:
            fanart = _download_tgdb_image(db_game_id, fanart_urls[0], 'fanart', suffix='_fanart')

        # Log values
        logger.info(f"Update values for game {db_game_id}:")
        logger.info(f"  Title: {scraped_title}")
        logger.info(f"  Publisher: {publisher}")
        logger.info(f"  Developer: {developer}")
        logger.info(f"  Release Date: {release_date}")
        logger.info(f"  Genre: {genre}")
        logger.info(f"  ESRB: {esrb_rating}")
        logger.info(f"  PEGI: {pegi_rating}")
        logger.info(f"  Players: {players}")
        logger.info(f"  Boxart: {boxart}")
        logger.info(f"  Screenshots: {len(screenshots)}")
        logger.info(f"  Fanart: {fanart}")

        # Fill-only writes: COALESCE preserves prior scraped/curated values when
        # the TGDB response is empty for a field. Matches scrape_esde's pattern.
        def _trunc(value, limit):
            return str(value)[:limit] if value else None

        # modes_str follows the source signal: only emit when TGDB supplied
        # a player count, otherwise leave None so COALESCE preserves curated.
        from services.normalization import modes_from_player_count
        modes_str = modes_from_player_count(players) or None
        c.execute("""
            UPDATE games SET
                title = COALESCE(?, title),
                publisher = COALESCE(?, publisher),
                developer = COALESCE(?, developer),
                release_date = COALESCE(?, release_date),
                genre = COALESCE(?, genre),
                rating = COALESCE(?, rating),
                esrb_rating = COALESCE(?, esrb_rating),
                pegi_rating = COALESCE(?, pegi_rating),
                players = COALESCE(?, players),
                modes = COALESCE(?, modes),
                description = COALESCE(?, description),
                boxart = COALESCE(?, boxart),
                screenshots = COALESCE(?, screenshots),
                fanart = COALESCE(?, fanart),
                scraped = 1
            WHERE id = ?
        """, (
            _trunc(scraped_title, 255),
            _trunc(publisher, 255),
            _trunc(developer, 255),
            _trunc(release_date, 20),
            _trunc(genre, 500),
            _trunc(rating, 50),
            _trunc(esrb_rating, 50),
            _trunc(pegi_rating, 50),
            players if players else None,
            modes_str,
            _trunc(description, 2000),
            str(boxart) if boxart else None,
            screenshots_str,
            str(fanart) if fanart else None,
            db_game_id
        ))

        conn.commit()
        logger.info(f"Applied TGDB metadata to game {db_game_id}")
        return True

    except Exception as e:
        logger.error(f"Error applying TGDB metadata: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

# =============================================================================
# IMAGE DOWNLOAD
# =============================================================================

def _download_tgdb_image(db_game_id, image_url, image_type, suffix=''):
    """Download a TGDB image to IMAGE_PATH/<image_type>/.

    Pass 40.7 — delegates the actual fetch to base_scraper.download_image,
    which enforces the SSRF gate (validate_outbound_url +
    validate_redirect_chain), 50 MB streaming size cap, and partial-file
    cleanup on overflow.  The previous implementation bypassed all three
    via raw http_get + open().write(response.content), so a crafted TGDB
    response with an image URL redirecting to e.g. 169.254.169.254 (AWS
    IMDS) fetched cloud metadata into static/images/boxart/.  CWE-918.
    """
    if not image_url:
        return None

    try:
        # Make URL absolute (TGDB CDN sometimes returns relative paths).
        if image_url.startswith('//'):
            image_url = 'https:' + image_url
        elif not image_url.startswith('http'):
            if image_url.startswith('/'):
                image_url = f"https://cdn.thegamesdb.net{image_url}"
            else:
                image_url = f"https://cdn.thegamesdb.net/{image_url}"

        # Get file extension from URL or default to jpg, then translate to the
        # configured ingest format (e.g. WebP).
        url_ext = os.path.splitext(image_url.split('?')[0])[1] or '.jpg'
        from services.image_utils import preferred_image_extension
        ext = preferred_image_extension(image_type, url_ext)

        filename = f"{db_game_id}_tgdb{suffix}{ext}"
        local_dir = os.path.join(IMAGE_PATH, image_type)
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, filename)

        logger.info(f"Downloading image from: {image_url}")
        # download_image: SSRF-gated, redirect-validated, size-capped,
        # auto-finalizes (format normalize + responsive variants).
        if download_image(image_url, local_path, timeout=30):
            logger.info(f"Downloaded {image_type} for game {db_game_id}: {filename}")
            return filename
        return None

    except Exception as e:
        logger.warning(f"Failed to download image: {e}")
        return None
