# =============================================================================
# IGDB SCRAPER
# =============================================================================
# Fallback scraper for game metadata when TheGamesDB fails
# =============================================================================

import os
import logging
import threading
import sys

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config as _config

from scraper import service_limits
from scraper.base_scraper import http_post
from scraper.match_scorer import EXACT_TITLE_SCORE, calculate_title_match_score

logger = logging.getLogger(__name__)

# Pass 45.14 — cap IGDB / Twitch JSON response sizes; matches RA + AI precedent.
_IGDB_MAX_BYTES = getattr(_config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)

def _get_igdb_credentials():
    """Get IGDB credentials via centralized scraper_manager, falling back to config.py"""
    from .scraper_manager import get_api_key
    client_id = get_api_key('igdb_client_id', 'IGDB_CLIENT_ID')
    client_secret = get_api_key('igdb_client_secret', 'IGDB_CLIENT_SECRET')
    return client_id, client_secret

# =============================================================================
# AUTHENTICATION
# =============================================================================

_igdb_token_cache = {'token': None, 'expires_at': 0}
# Pass 45.13 — guard the cache mutation against concurrent background workers
# (bulk scrape runs IGDB in a thread pool). Without the lock, two threads
# hitting an expired token would each kick off a Twitch OAuth round trip and
# the second one would clobber the first's freshly-stored token. Mirrors the
# pattern in scraper/retroachievements.py:_ra_console_cache_lock.
_igdb_token_cache_lock = threading.Lock()


def igdb_auth():
    """Authenticate with IGDB via Twitch, with token caching."""
    import time

    # Pass 45.13 — read + refresh under the lock so two threads can't both
    # see "no cached token" simultaneously and both fire a Twitch OAuth call.
    with _igdb_token_cache_lock:
        # Return cached token if still valid (with 60s safety margin)
        if _igdb_token_cache['token'] and time.time() < _igdb_token_cache['expires_at'] - 60:
            return _igdb_token_cache['token']

        client_id, client_secret = _get_igdb_credentials()
        if not client_id or not client_secret:
            raise ValueError("IGDB credentials not configured. Set them in Settings → Scrapers.")
        try:
            r = http_post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    'client_id': client_id,
                    'client_secret': client_secret,
                    'grant_type': 'client_credentials'
                },
                timeout=10,
                retries=2,
                max_bytes=_IGDB_MAX_BYTES,
            )
            if r is None:
                raise ConnectionError("IGDB authentication request failed after retries")
            r.raise_for_status()
            data = r.json()
            token = data['access_token']
            expires_in = data.get('expires_in', 0)
            _igdb_token_cache['token'] = token
            _igdb_token_cache['expires_at'] = time.time() + expires_in
            logger.info(f"IGDB token cached, expires in {expires_in}s")
            return token
        except Exception as e:
            logger.error(f"IGDB authentication failed: {e}")
            raise

def igdb_request(endpoint, body, token):
    """Make request to IGDB API.

    Pass 41.5 — on a 401 response (Twitch revoked / expired the token earlier
    than the cached `expires_in` claimed), invalidate the token cache and
    retry once with a freshly-issued token. Without this, a stale token
    in the cache silently returns empty results for the rest of the scrape
    pass and the user sees "no IGDB results" with no obvious cause.
    """
    client_id, _ = _get_igdb_credentials()
    headers = {
        'Client-ID': client_id,
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json'
    }
    service_limits.wait_for_turn(service_limits.IGDB)
    r = http_post(
        f"https://api.igdb.com/v4/{endpoint}",
        data=body,
        headers=headers,
        timeout=30,
        retries=2,
        max_bytes=_IGDB_MAX_BYTES,
    )
    if r is None:
        raise ConnectionError(f"IGDB API request to {endpoint} failed after retries")
    if r.status_code == 401:
        logger.warning(
            "IGDB returned 401 for %s — clearing token cache and retrying once",
            endpoint,
        )
        # Pass 45.13 — clear the cache under the lock too, so a parallel
        # thread doesn't read the now-invalid token between our reset and
        # the igdb_auth() refresh below.
        with _igdb_token_cache_lock:
            _igdb_token_cache['token'] = None
            _igdb_token_cache['expires_at'] = 0
        fresh_token = igdb_auth()
        headers['Authorization'] = f'Bearer {fresh_token}'
        service_limits.wait_for_turn(service_limits.IGDB)
        r = http_post(
            f"https://api.igdb.com/v4/{endpoint}",
            data=body,
            headers=headers,
            timeout=30,
            retries=2,
            max_bytes=_IGDB_MAX_BYTES,
        )
        if r is None:
            raise ConnectionError(
                f"IGDB API request to {endpoint} failed after token refresh + retries"
            )
    r.raise_for_status()
    return r.json()

# =============================================================================
# SYSTEM ID MAPPING
# =============================================================================

# System folder or display name -> IGDB platform id. Lives here, not in
# config.py, because an update never rewrites an installed config.py.
IGDB_PLATFORM_MAP = {
    # NES
    'nes': 18, 'nintendo entertainment system': 18,
    # Family Computer
    'famicom': 99, 'nintendo famicom': 99,
    # Family Computer Disk System
    'fds': 51, 'famicom disk system': 51,
    # SNES
    'snes': 19, 'super nintendo entertainment system': 19, 'snesna': 19,
    # Super Famicom
    'sfc': 58, 'super famicom': 58,
    # Nintendo 64
    'n64': 4, 'nintendo 64': 4,
    # Nintendo 64DD
    'n64dd': 416, 'nintendo 64dd': 416,
    # Game Boy
    'gb': 33, 'game boy': 33,
    # Game Boy Color
    'gbc': 22, 'game boy color': 22,
    # Game Boy Advance
    'gba': 24, 'game boy advance': 24,
    # Nintendo DS
    'nds': 20, 'nintendo ds': 20,
    # Nintendo 3DS
    'n3ds': 37, 'nintendo 3ds': 37,
    # GameCube
    'gc': 21, 'nintendo gamecube': 21,
    # Wii
    'wii': 5, 'nintendo wii': 5,
    # Wii U
    'wiiu': 41, 'nintendo wii u': 41,
    # Switch
    'switch': 130, 'nintendo switch': 130,
    # Virtual Boy
    'virtualboy': 87, 'virtual boy': 87,
    # Satellaview
    'satellaview': 306,
    # Game & Watch
    'gameandwatch': 307, 'game & watch': 307,
    # Pokemon mini
    'pokemini': 166, 'pokemon mini': 166,
    # PlayStation
    'psx': 7, 'sony playstation': 7, 'playstation': 7,
    # PlayStation 2
    'ps2': 8, 'sony playstation 2': 8, 'playstation 2': 8,
    # PlayStation 3
    'ps3': 9, 'sony playstation 3': 9, 'playstation 3': 9,
    # PlayStation 4
    'ps4': 48, 'sony playstation 4': 48, 'playstation 4': 48,
    # PlayStation 5
    'ps5': 167, 'sony playstation 5': 167, 'playstation 5': 167,
    # PlayStation Portable
    'psp': 38, 'sony playstation portable': 38, 'playstation portable': 38,
    # PlayStation Vita
    'psvita': 46, 'sony playstation vita': 46, 'playstation vita': 46,
    # Sega Mega Drive/Genesis
    'genesis': 29, 'sega genesis': 29, 'megadrive': 29, 'sega mega drive': 29,
    'megadrivejp': 29, 'sega mega drive (japan)': 29,
    # Sega Master System/Mark III
    'mastersystem': 64, 'sega master system': 64, 'mark3': 64,
    # Sega CD
    'segacd': 78, 'sega cd': 78, 'megacd': 78, 'megacdjp': 78,
    # Sega 32X
    'sega32x': 30, 'sega 32x': 30, 'sega32xjp': 30, 'sega 32x (japan)': 30,
    'sega32xna': 30, 'sega 32x (north america)': 30,
    # Sega Saturn
    'saturn': 32, 'sega saturn': 32, 'saturnjp': 32, 'sega saturn (japan)': 32,
    # Dreamcast
    'dreamcast': 23, 'sega dreamcast': 23,
    # Game Gear
    'gamegear': 35, 'sega game gear': 35,
    # SG-1000
    'sg-1000': 84, 'sega sg-1000': 84,
    # Xbox
    'xbox': 11, 'microsoft xbox': 11,
    # Xbox 360
    'xbox360': 12, 'microsoft xbox 360': 12, 'xbox 360': 12,
    # Xbox One
    'xboxone': 49, 'microsoft xbox one': 49, 'xbox one': 49,
    # Atari 2600
    'atari2600': 59, 'atari 2600': 59,
    # Atari 5200
    'atari5200': 66, 'atari 5200': 66,
    # Atari 7800
    'atari7800': 60, 'atari 7800': 60,
    # Atari 8-bit
    'atari800': 65, 'atari 800': 65, 'atarixe': 65, 'atari xe': 65, 'atari 8-bit': 65,
    # Atari Jaguar
    'atarijaguar': 62, 'atari jaguar': 62,
    # Atari Jaguar CD
    'atarijaguarcd': 410, 'atari jaguar cd': 410,
    # Atari Lynx
    'atarilynx': 61, 'atari lynx': 61,
    # Atari ST/STE
    'atarist': 63, 'atari st': 63,
    # TurboGrafx-16/PC Engine
    'pcengine': 86, 'pc engine': 86, 'tg16': 86, 'turbografx-16': 86,
    # TurboGrafx-16/PC Engine CD
    'pcenginecd': 150, 'pc engine cd': 150, 'tg-cd': 150, 'turbografx-cd': 150,
    # PC Engine SuperGrafx
    'supergrafx': 128, 'pc engine supergrafx': 128,
    # PC-FX
    'pcfx': 274, 'pc-fx': 274,
    # PC-8800 Series
    'pc88': 125, 'nec pc-8801': 125, 'pc-8801': 125,
    # PC-9800 Series
    'pc98': 149, 'nec pc-9801': 149, 'pc-98': 149,
    # Neo Geo AES
    'neogeo': 80, 'snk neo geo': 80, 'neo geo': 80,
    # Neo Geo CD
    'neogeocd': 136, 'snk neo geo cd': 136, 'neogeocdjp': 136,
    'snk neo geo cd (japan)': 136, 'neo geo cd': 136,
    # Neo Geo Pocket
    'ngp': 119, 'neo geo pocket': 119,
    # Neo Geo Pocket Color
    'ngpc': 120, 'neo geo pocket color': 120,
    # Arcade
    'arcade': 52, 'mame': 52, 'mame-advmame': 52, 'fba': 52, 'fbneo': 52,
    'finalburn neo': 52, 'cps': 52, 'cps1': 52, 'cps2': 52, 'cps3': 52, 'model2': 52,
    'sega model 2': 52, 'model3': 52, 'sega model 3': 52, 'naomi': 52,
    'sega naomi': 52, 'naomi2': 52, 'sega naomi 2': 52, 'naomigd': 52,
    'atomiswave': 52, 'stv': 52, 'sega titan video': 52,
    # Windows PC
    'pc': 6, 'ibm pc': 6, 'windows': 6, 'microsoft windows': 6, 'windows3x': 6,
    'windows 3.x': 6, 'windows9x': 6, 'windows 9x': 6,
    # DOS
    'dos': 13, 'ms-dos': 13,
    # Mac
    'macintosh': 14, 'apple macintosh': 14,
    # Apple II
    'apple2': 75, 'apple ii': 75,
    # Apple IIGS
    'apple2gs': 115, 'apple iigs': 115,
    # Commodore 64
    'c64': 15, 'commodore 64': 15,
    # Amiga
    'amiga': 16, 'commodore amiga': 16, 'amiga600': 16, 'amiga1200': 16,
    # Amiga CD32
    'amigacd32': 114, 'commodore amiga cd32': 114,
    # Commodore CDTV
    'cdtv': 158, 'commodore cdtv': 158,
    # Amstrad CPC
    'amstradcpc': 25, 'amstrad cpc': 25,
    # Amstrad GX4000
    'gx4000': 506, 'amstrad gx4000': 506,
    # MSX
    'msx': 27, 'msx1': 27,
    # MSX2
    'msx2': 53,
    # ZX Spectrum
    'zxspectrum': 26, 'zx spectrum': 26,
    # Sinclair ZX81
    'zx81': 373, 'sinclair zx81': 373,
    # BBC Micro
    'bbcmicro': 69, 'bbc micro': 69,
    # Acorn Electron
    'electron': 134, 'acorn electron': 134,
    # Acorn Archimedes
    'archimedes': 116, 'acorn archimedes': 116,
    # Commodore VIC-20
    'vic20': 71, 'commodore vic-20': 71,
    # Commodore Plus/4
    'plus4': 94, 'commodore plus/4': 94,
    # Dragon 32/64
    'dragon32': 153,
    # TRS-80 Color Computer
    'coco': 151, 'trs-80 color computer': 151,
    # TRS-80
    'trs-80': 126,
    # TI-99
    'ti99': 129, 'texas instruments ti-99/4a': 129,
    # FM-7
    'fm7': 152, 'fujitsu fm-7': 152,
    # FM Towns
    'fmtowns': 118, 'fm towns': 118,
    # Sharp X1
    'x1': 77, 'sharp x1': 77,
    # Sharp X68000
    'x68000': 121, 'sharp x68000': 121,
    # 3DO
    '3do': 50, '3do interactive multiplayer': 50,
    # ColecoVision
    'colecovision': 68,
    # Intellivision
    'intellivision': 67, 'mattel intellivision': 67,
    # Vectrex
    'vectrex': 70,
    # WonderSwan
    'wonderswan': 57, 'bandai wonderswan': 57, 'wonder swan': 57,
    # WonderSwan Color
    'wonderswancolor': 123, 'bandai wonderswan color': 123, 'wonder swan color': 123,
    # Philips CD-i
    'cdimono1': 117, 'philips cd-i': 117,
    # N-Gage
    'ngage': 42, 'nokia n-gage': 42,
    # Odyssey 2 / Videopac
    'odyssey2': 133, 'magnavox odyssey 2': 133, 'videopac': 133,
    'philips videopac': 133,
    # Fairchild Channel F
    'channelf': 127, 'fairchild channel f': 127,
    # Bally Astrocade
    'astrocde': 91, 'bally astrocade': 91, 'astrocade': 91,
    # Arcadia 2001
    'arcadia': 473, 'emerson arcadia 2001': 473,
    # Super Cassette Vision
    'scv': 376, 'epoch super cassette vision': 376,
    # Gamate
    'gamate': 378, 'bit corporation gamate': 378,
    # Game.com
    'gamecom': 379, 'tiger game.com': 379,
    # Watara Supervision
    'supervision': 415, 'watara supervision': 415,
    # Mega Duck
    'megaduck': 408,
    # Palm OS
    'palm': 417, 'palm os': 417,
    # Super A'Can
    'supracan': 480, "funtech super a'can": 480,
    # V.Smile
    'vsmile': 439, 'vtech v.smile': 439,
    # Uzebox
    'uzebox': 504,
    # Arduboy
    'arduboy': 438,
}


def get_platform_id(system_name):
    """IGDB platform for this system, or None if it has no exact entry.

    Exact only: matching part of a name searched "PC Engine SuperGrafx" as NES,
    because "nes" is inside "pcenginesupergrafx".
    """
    if not system_name:
        return None
    return IGDB_PLATFORM_MAP.get(system_name.lower().strip())

# =============================================================================
# SEARCH GAMES
# =============================================================================

_SEARCH_FIELDS = ('id, name, game_type, first_release_date, platforms.id, platforms.name, '
                  'platforms.abbreviation, release_dates.region, release_dates.platform, '
                  'summary, alternative_names.name, alternative_names.comment')

# IGDB game types that are not a game of their own: DLC, expansion, bundle, mod,
# episode, season, fork, pack, update. IGDB lists them with the games it files
# under the same platform, and a hack can outrank the game it modifies.
_ADD_ON_GAME_TYPES = frozenset({1, 2, 3, 5, 6, 7, 12, 13, 14})


def _is_someone_elses_add_on(game, title):
    """True for an add-on the ROM is not named after. A ROM that is itself a hack
    or an expansion still finds its own record."""
    return (game.get('game_type') in _ADD_ON_GAME_TYPES
            and calculate_title_match_score(game.get('name', ''), title) < EXACT_TITLE_SCORE)


def search_games(title, system_name=None, limit=10):
    """Search games on IGDB using proper search endpoint"""
    try:
        token = igdb_auth()
        
        # Clean title for search - handle various special characters for IGDB API
        search_title = title
        
        # Remove/replace all apostrophe variants (ASCII and Unicode curly quotes)
        # IGDB search handles apostrophes poorly
        apostrophe_chars = ["'", "'", "'", "ʼ", "ʻ", "`", "´", "′"]
        for char in apostrophe_chars:
            search_title = search_title.replace(char, "")
        
        # Remove/replace all quote variants - quotes break the query
        quote_chars = ['"', '"', '"', '„', '«', '»']
        for char in quote_chars:
            search_title = search_title.replace(char, "")
        
        # Remove other special characters that might interfere with IGDB query syntax
        special_chars = ['&', '|', ';', '(', ')', '[', ']', '{', '}', '*', '\\', '/', '@', '#', '$', '%', '^', '!', ':']
        for char in special_chars:
            search_title = search_title.replace(char, " ")
        
        # Clean up multiple spaces
        import re
        search_title = re.sub(r'\s+', ' ', search_title).strip()
        
        # Get platform ID if available. A system IGDB does not list is not
        # searched: games from other platforms would match instead.
        platform_id = None
        if system_name:
            platform_id = get_platform_id(system_name)
            if not platform_id:
                logger.info(f"IGDB: no platform for '{system_name}' — not searched")
                return []
        # Every query below keeps the platform filter (user, 2026-10-27).
        platform_where = f' & platforms = ({platform_id})' if platform_id else ''

        # Use IGDB's dedicated search command (not name ~ regex)
        # The search command is designed to handle fuzzy matching better
        where_clause = 'version_parent = null' + platform_where

        # Build query using search command
        body = f"""
        search "{search_title}";
        fields {_SEARCH_FIELDS};
        where {where_clause};
        limit {limit};
        """

        logger.info(f"Searching IGDB for: '{title}' (cleaned: '{search_title}') on platform: {system_name} (id: {platform_id})")
        logger.debug(f"IGDB query: {body}")
        results = igdb_request("games", body, token)

        # Remaster/remake fallback: version_parent = null excludes remasters
        # on IGDB (they're marked as versions of the original).  If the best
        # title match so far is poor, retry WITHOUT the version_parent filter
        # so titles like "Alan Wake Remastered" can be found.
        if results:
            from scraper.base_scraper import normalize_roman_numerals
            _search_norm = normalize_roman_numerals(
                re.sub(r'\s+', ' ', re.sub(r'[:\-\u2013\u2014/]', ' ', search_title.lower())).strip()
            )
            best_title_score = 0
            for r in results:
                r_name = r.get('name', '')
                r_norm = normalize_roman_numerals(
                    re.sub(r'\s+', ' ', re.sub(r'[:\-\u2013\u2014/]', ' ', r_name.lower())).strip()
                )
                if r_norm == _search_norm:
                    best_title_score = 300
                    break
                r_words = set(r_norm.split())
                s_words = set(_search_norm.split())
                if s_words <= r_words or r_words == s_words:
                    best_title_score = max(best_title_score, 250)

            if best_title_score < 200:
                logger.info(f"IGDB: best title score {best_title_score} is low — retrying without version_parent filter (remaster fallback)")
                vp_where = ''
                if platform_id:
                    vp_where = f'platforms = ({platform_id})'
                vp_body = f"""
                search "{search_title}";
                fields {_SEARCH_FIELDS};
                {"where " + vp_where + ";" if vp_where else ""}
                limit {limit};
                """
                vp_results = igdb_request("games", vp_body, token)
                if vp_results:
                    # Merge: add any new games not already in results
                    existing_ids = {r.get('id') for r in results}
                    added = 0
                    for vr in vp_results:
                        if vr.get('id') not in existing_ids:
                            results.append(vr)
                            added += 1
                    if added:
                        logger.info(f"IGDB remaster fallback: added {added} additional result(s)")

        # If still no results, try alternative search strategies
        if not results:
            # Strategy 1: Try with name regex as fallback (some titles work better this way)
            logger.info(f"IGDB: Trying regex fallback for '{search_title}'")
            body = f"""
            fields {_SEARCH_FIELDS};
            where name ~ *"{search_title}"* & version_parent = null{platform_where};
            limit {limit};
            """
            results = igdb_request("games", body, token)
        
        if not results:
            # Strategy 2: Try with just the first two words (franchise name)
            words = search_title.split()
            if len(words) >= 2:
                short_title = ' '.join(words[:2])
                logger.info(f"IGDB: Trying short title search: '{short_title}'")
                body = f"""
                search "{short_title}";
                fields {_SEARCH_FIELDS};
                where version_parent = null{platform_where};
                limit {limit};
                """
                results = igdb_request("games", body, token)

        results = [g for g in results if not _is_someone_elses_add_on(g, title)]

        # IGDB region codes
        region_map = {
            1: 'Europe', 2: 'USA', 3: 'Australia', 4: 'New Zealand',
            5: 'Japan', 6: 'China', 7: 'Asia', 8: 'World'
        }
        
        # Format results
        formatted = []
        for game in results:
            # Try to get region from release dates
            region = None
            release_dates = game.get('release_dates', [])
            if release_dates:
                # Prefer USA or World region
                for rd in release_dates:
                    r = rd.get('region')
                    if r == 2:  # USA
                        region = 'USA'
                        break
                    elif r == 8:  # World
                        region = 'World'
                        break
                if not region and release_dates:
                    region = region_map.get(release_dates[0].get('region'))
            
            # Check if platform matches the searched platform
            platform_match = False
            matched_platform_name = None
            platforms_list = game.get('platforms', [])
            
            logger.info(f"IGDB platform check for '{game.get('name', '')}': platform_id={platform_id} (type={type(platform_id).__name__}), platforms_list={platforms_list}")
            
            if platform_id and platforms_list:
                # Convert platform_id to int for comparison
                search_platform_id = int(platform_id) if platform_id else None
                
                for plat in platforms_list:
                    plat_id = plat.get('id') if isinstance(plat, dict) else plat
                    # Convert to int for consistent comparison
                    try:
                        plat_id_int = int(plat_id) if plat_id is not None else None
                    except (ValueError, TypeError):
                        plat_id_int = None
                    
                    logger.info(f"  Checking: plat_id={plat_id_int}, search_platform_id={search_platform_id}")
                    
                    if plat_id_int is not None and plat_id_int == search_platform_id:
                        platform_match = True
                        matched_platform_name = plat.get('name', '') if isinstance(plat, dict) else None
                        logger.info(f"  MATCH FOUND! matched_platform={matched_platform_name}")
                        break
            
            if not platform_match:
                logger.info(f"  No platform match for '{game.get('name', '')}'")
            
            # Alternate names — {name, comment} pairs where comment is usually
            # a region hint like "Japanese title" or "JP". Surface for UI preview.
            alt_titles = []
            for alt in game.get('alternative_names') or []:
                alt_name = alt.get('name', '').strip() if isinstance(alt, dict) else ''
                if alt_name:
                    alt_titles.append({
                        'title': alt_name,
                        'region': (alt.get('comment') or '').strip() or None,
                    })

            formatted.append({
                'id': str(game.get('id')),
                'name': game.get('name', ''),
                'first_release_date': game.get('first_release_date'),
                'platforms': platforms_list,
                'summary': game.get('summary', ''),
                'region': region,
                'source': 'igdb',
                'platform_match': platform_match,
                'matched_platform': matched_platform_name,
                'alternate_titles': alt_titles,
            })
        
        logger.info(f"IGDB found {len(formatted)} results")
        return formatted
        
    except Exception as e:
        logger.error(f"IGDB search error: {e}")
        return []

# =============================================================================
# FETCH GAME DETAILS
# =============================================================================

def fetch_game_details(game_id):
    """Fetch detailed game information from IGDB"""
    try:
        token = igdb_auth()
        
        body = f"""
        fields name, first_release_date,
               release_dates.date, release_dates.y, release_dates.m, release_dates.date_format,
               release_dates.platform, release_dates.release_region,
               involved_companies.company.name, involved_companies.developer, involved_companies.publisher,
               genres.name, age_ratings.category, age_ratings.rating,
               age_ratings.organization.name, age_ratings.rating_category.rating,
               game_modes.name, player_perspectives.name,
               multiplayer_modes.platform, multiplayer_modes.offlinemax, multiplayer_modes.onlinemax,
               multiplayer_modes.campaigncoop, multiplayer_modes.splitscreen,
               multiplayer_modes.offlinecoop, multiplayer_modes.onlinecoop,
               summary, storyline, cover.url, screenshots.url, artworks.url, artworks.artwork_type,
               videos.video_id, alternative_names.name, alternative_names.comment,
               platforms.name, rating, rating_count, aggregated_rating, aggregated_rating_count;
        where id = {game_id};
        """
        
        results = igdb_request("games", body, token)
        
        if results:
            game = results[0]
            logger.info(f"IGDB details fetched for game ID: {game_id}")
            return game
        
        return None
        
    except Exception as e:
        logger.error(f"IGDB fetch details error: {e}")
        return None

