"""
HLTB (HowLongToBeat) lookup module for RetroDB

Uses the HowLongToBeat API directly via /api/finder endpoint.
"""

import logging
import time
import requests
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# Map RetroDB system folders to HLTB platform filter strings
SYSTEM_TO_HLTB_PLATFORM = {
    # Nintendo consoles
    'nes': 'NES', 'famicom': 'NES',
    'snes': 'Super Nintendo', 'superfamicom': 'Super Nintendo',
    'n64': 'Nintendo 64',
    'gc': 'Nintendo GameCube', 'gamecube': 'Nintendo GameCube',
    'wii': 'Wii', 'wiiu': 'Wii U',
    'switch': 'Nintendo Switch',
    # Nintendo handhelds
    'gb': 'Game Boy', 'gbc': 'Game Boy Color', 'gba': 'Game Boy Advance',
    'nds': 'Nintendo DS', 'n3ds': 'Nintendo 3DS',
    'virtualboy': 'Virtual Boy',
    # Sony
    'psx': 'PlayStation', 'ps2': 'PlayStation 2', 'ps3': 'PlayStation 3',
    'ps4': 'PlayStation 4', 'ps5': 'PlayStation 5',
    'psp': 'PlayStation Portable', 'psvita': 'PlayStation Vita',
    # Microsoft
    'xbox': 'Xbox', 'xbox360': 'Xbox 360',
    'xboxone': 'Xbox One', 'xboxseriesx': 'Xbox Series X/S',
    # Sega
    'mastersystem': 'Sega Master System', 'sms': 'Sega Master System',
    'genesis': 'Sega Mega Drive/Genesis', 'megadrive': 'Sega Mega Drive/Genesis',
    'segacd': 'Sega CD', 'sega32x': 'Sega 32X', '32x': 'Sega 32X',
    'saturn': 'Sega Saturn', 'dreamcast': 'Dreamcast',
    'gamegear': 'Sega Game Gear', 'gg': 'Sega Game Gear',
    # Atari
    'atari2600': 'Atari 2600', 'atari5200': 'Atari 5200', 'atari7800': 'Atari 7800',
    'atarilynx': 'Atari Lynx', 'lynx': 'Atari Lynx',
    'atarijaguar': 'Atari Jaguar', 'jaguar': 'Atari Jaguar',
    'atarist': 'Atari ST',
    # NEC
    'tg16': 'TurboGrafx-16', 'pcengine': 'TurboGrafx-16',
    'tg16cd': 'TurboGrafx-CD', 'pcenginecd': 'TurboGrafx-CD',
    # SNK
    'neogeo': 'Neo Geo', 'neogeocd': 'Neo Geo CD',
    'ngp': 'Neo Geo Pocket', 'ngpc': 'Neo Geo Pocket Color',
    # Computers
    'amiga': 'Amiga', 'amiga500': 'Amiga', 'amiga600': 'Amiga',
    'amiga1200': 'Amiga', 'amigacd32': 'Amiga',
    'c64': 'Commodore 64', 'c128': 'Commodore 64',
    'zxspectrum': 'ZX Spectrum', 'spectrum': 'ZX Spectrum',
    'amstradcpc': 'Amstrad CPC', 'cpc': 'Amstrad CPC',
    'msx': 'MSX', 'msx1': 'MSX', 'msx2': 'MSX',
    'apple2': 'Apple II', 'apple2gs': 'Apple II',
    'dos': 'PC', 'pc': 'PC', 'windows': 'PC', 'scummvm': 'PC',
    # Arcade / 3DO
    'arcade': 'Arcade',
    '3do': '3DO',
    # Mobile
    'ngage': 'N-Gage',
}

HLTB_BASE_URL = "https://howlongtobeat.com"
HLTB_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    'referer': 'https://howlongtobeat.com/',
    'Content-Type': 'application/json',
    'accept': '*/*',
    'origin': 'https://howlongtobeat.com'
}

# Cache auth token to avoid repeated init requests
_auth_token = None
_auth_token_time = 0
_AUTH_TOKEN_TTL = 300  # 5 minutes


def _get_auth_token():
    """Get or refresh the HLTB auth token"""
    global _auth_token, _auth_token_time

    # Return cached token if still fresh
    if _auth_token and (time.time() - _auth_token_time) < _AUTH_TOKEN_TTL:
        return _auth_token

    try:
        init_url = f"{HLTB_BASE_URL}/api/finder/init?t={int(time.time() * 1000)}"
        resp = requests.get(init_url, headers=HLTB_HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            _auth_token = data.get('token', '')
            _auth_token_time = time.time()
            logger.debug(f"HLTB: Got new auth token")
            return _auth_token
        else:
            logger.warning(f"HLTB: Auth token request failed with status {resp.status_code}")
    except Exception as e:
        logger.error(f"HLTB: Failed to get auth token: {e}")

    return None


def _search_hltb(game_title, platform='', year=None):
    """Search HLTB for a game using the /api/finder endpoint.

    Args:
        game_title: Game title to search for
        platform: HLTB platform string (e.g. 'Commodore 64', 'PlayStation 2')
        year: Release year string to filter by (e.g. '1989')
    """
    token = _get_auth_token()
    if not token:
        logger.error("HLTB: No auth token available")
        return None

    range_year = {'min': '', 'max': ''}
    if year:
        range_year = {'min': str(year), 'max': str(year)}

    search_headers = {**HLTB_HEADERS, 'x-auth-token': token}
    payload = {
        'searchType': 'games',
        'searchTerms': game_title.split(),
        'searchPage': 1,
        'size': 20,
        'searchOptions': {
            'games': {
                'userId': 0,
                'platform': platform or '',
                'sortCategory': 'popular',
                'rangeCategory': 'main',
                'rangeTime': {'min': 0, 'max': 0},
                'gameplay': {'perspective': '', 'flow': '', 'genre': '', 'difficulty': ''},
                'rangeYear': range_year,
                'modifier': ''
            },
            'users': {'sortCategory': 'postcount'},
            'lists': {'sortCategory': 'follows'},
            'filter': '',
            'sort': 0,
            'randomizer': 0
        },
        'useCache': True
    }

    try:
        resp = requests.post(
            f"{HLTB_BASE_URL}/api/finder",
            headers=search_headers,
            json=payload,
            timeout=30
        )

        if resp.status_code == 403:
            # Token expired, clear cache and retry once
            global _auth_token, _auth_token_time
            _auth_token = None
            _auth_token_time = 0
            logger.info("HLTB: Token expired, refreshing...")
            token = _get_auth_token()
            if token:
                search_headers['x-auth-token'] = token
                resp = requests.post(
                    f"{HLTB_BASE_URL}/api/finder",
                    headers=search_headers,
                    json=payload,
                    timeout=30
                )

        if resp.status_code == 200:
            data = resp.json()
            return data.get('data', [])
        else:
            logger.warning(f"HLTB: Search failed with status {resp.status_code}")

    except Exception as e:
        logger.error(f"HLTB: Search request failed: {e}")

    return None


def format_playtime(hours):
    """Format hours into readable string"""
    if hours is None:
        return None

    try:
        hours = float(hours)
        if hours < 1:
            return f"{int(hours * 60)} mins"
        elif hours == int(hours):
            return f"{int(hours)} hrs"
        else:
            return f"{hours:.1f} hrs"
    except (ValueError, TypeError):
        return str(hours)


def _seconds_to_hours(seconds):
    """Convert HLTB API seconds to hours (or None if 0)"""
    if not seconds or seconds == 0:
        return None
    return round(seconds / 3600, 1)


def lookup_playtime(game_title, system_folder=None, year=None):
    """
    Look up playtime data from HowLongToBeat

    Args:
        game_title: Game title to search for
        system_folder: Optional system folder for platform filtering
        year: Optional release year string for filtering (e.g. '1989')

    Returns:
        dict with playtime data or None if not found
    """
    try:
        # Resolve HLTB platform from system folder
        hltb_platform = ''
        if system_folder:
            hltb_platform = SYSTEM_TO_HLTB_PLATFORM.get(system_folder.lower(), '')

        # Graduated fallback: try narrower filters first, widen if no good
        # title match is found.  A "good match" requires score >= 0.95
        # (near-exact title).  This prevents e.g. year=1994 returning only
        # "Art of Fighting 2" when the user searched "Art of Fighting" (1992).
        GOOD_MATCH = 0.95
        query_lower = game_title.lower()

        def _best_match(results):
            """Return (best_result, best_score) from a result list."""
            if not results:
                return None, 0.0
            best = results[0]
            best_s = 0.0
            for r in results:
                s = SequenceMatcher(None, query_lower, r.get('game_name', '').lower()).ratio()
                if s > best_s:
                    best_s = s
                    best = r
            return best, best_s

        search_steps = []
        if hltb_platform and year:
            search_steps.append(('platform+year', hltb_platform, year))
        if hltb_platform:
            search_steps.append(('platform', hltb_platform, None))
        if year:
            search_steps.append(('year', '', year))
        search_steps.append(('unfiltered', '', None))

        result = None
        best_score = 0.0
        for label, plat, yr in search_steps:
            raw = _search_hltb(game_title, platform=plat, year=yr)
            candidate, score = _best_match(raw)
            if candidate and score > best_score:
                result = candidate
                best_score = score
                logger.info(f"HLTB: [{label}] best={candidate.get('game_name', '')!r} score={score:.4f}")
            if best_score >= GOOD_MATCH:
                break  # exact/near-exact — no need to widen
            if candidate and best_score < GOOD_MATCH:
                logger.info(f"HLTB: [{label}] no good match (best={best_score:.4f}), widening search")

        if not result:
            logger.info(f"HLTB: No results for '{game_title}'")
            return None

        match_name = result.get('game_name', game_title)

        # Extract playtime values (API returns seconds, convert to hours)
        main_story = _seconds_to_hours(result.get('comp_main', 0))
        main_extra = _seconds_to_hours(result.get('comp_plus', 0))
        completionist = _seconds_to_hours(result.get('comp_100', 0))

        # Get platform info
        profile_platform = result.get('profile_platform', '')
        if isinstance(profile_platform, (list, tuple)):
            profile_platform = ', '.join(str(p) for p in profile_platform) if profile_platform else None

        # Detect platform mismatch: requested platform not in result's platform list
        platform_mismatch = False
        if hltb_platform and profile_platform:
            platform_str = str(profile_platform).lower()
            if hltb_platform.lower() not in platform_str:
                platform_mismatch = True
                logger.info(f"HLTB: Platform mismatch — requested '{hltb_platform}', result has '{profile_platform}'")

        # Release year and developer from API response
        release_world = result.get('release_world') or None
        profile_dev = result.get('profile_dev') or None

        # Use the score already computed during candidate selection
        confidence = best_score

        logger.info(f"HLTB: Found '{match_name}' for '{game_title}' "
                     f"(main={main_story}h, extra={main_extra}h, complete={completionist}h, "
                     f"confidence={confidence:.0%}, year={release_world}, dev={profile_dev})")

        return {
            'game_id': result.get('game_id'),
            'match_name': match_name,
            'match_platform': profile_platform,
            'match_confidence': round(confidence * 100),
            'platform_mismatch': platform_mismatch,
            'main_story': main_story,
            'main_plus_sides': main_extra,
            'completionist': completionist,
            'release_world': release_world,
            'profile_dev': profile_dev
        }

    except Exception as e:
        logger.error(f"HLTB lookup error for '{game_title}': {e}")
        return None
