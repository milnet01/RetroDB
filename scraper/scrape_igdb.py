# =============================================================================
# IGDB SCRAPER
# =============================================================================
# Fallback scraper for game metadata when TheGamesDB fails
# =============================================================================

import os
import logging
import threading
from datetime import datetime
import sys

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import IMAGE_PATH, IGDB_PLATFORM_MAP
import config as _config

from scraper.base_scraper import http_post, download_image, get_scraper_conn

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

def get_platform_id(system_name):
    """Get IGDB platform ID from system name"""
    if not system_name:
        logger.info(f"IGDB get_platform_id: No system_name provided")
        return None
    
    system_key = system_name.lower().strip()
    logger.info(f"IGDB get_platform_id: Looking up '{system_name}' -> normalized: '{system_key}'")
    
    # Debug: Show available keys that contain 'playstation'
    ps_keys = [k for k in IGDB_PLATFORM_MAP.keys() if 'playstation' in k.lower()]
    logger.info(f"IGDB get_platform_id: Available PlayStation keys in map: {ps_keys}")
    
    # Direct lookup with spaces
    if system_key in IGDB_PLATFORM_MAP:
        platform_id = IGDB_PLATFORM_MAP[system_key]
        logger.info(f"IGDB get_platform_id: Direct match! '{system_key}' -> {platform_id}")
        return platform_id
    
    # Try without spaces
    system_key_nospace = system_key.replace(' ', '')
    logger.info(f"IGDB get_platform_id: No direct match, trying without spaces: '{system_key_nospace}'")
    for key, value in IGDB_PLATFORM_MAP.items():
        key_nospace = key.replace(' ', '')
        if key_nospace == system_key_nospace:
            logger.info(f"IGDB get_platform_id: Nospace match! '{key}' -> {value}")
            return value
    
    # Try partial match
    logger.info(f"IGDB get_platform_id: No nospace match, trying partial...")
    for key, value in IGDB_PLATFORM_MAP.items():
        key_nospace = key.replace(' ', '')
        if key_nospace in system_key_nospace or system_key_nospace in key_nospace:
            logger.info(f"IGDB get_platform_id: Partial match! '{key}' -> {value}")
            return value
    
    logger.info(f"IGDB get_platform_id: No match found for '{system_name}'")
    return None

# =============================================================================
# SEARCH GAMES
# =============================================================================

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
        
        # Get platform ID if available
        platform_id = None
        if system_name:
            platform_id = get_platform_id(system_name)
        
        # Use IGDB's dedicated search command (not name ~ regex)
        # The search command is designed to handle fuzzy matching better
        where_clause = 'version_parent = null'
        if platform_id:
            where_clause += f' & platforms = ({platform_id})'
        
        # Build query using search command
        body = f"""
        search "{search_title}";
        fields id, name, first_release_date, platforms.id, platforms.name, platforms.abbreviation,
               release_dates.region, release_dates.platform, summary,
               alternative_names.name, alternative_names.comment;
        where {where_clause};
        limit {limit};
        """
        
        logger.info(f"Searching IGDB for: '{title}' (cleaned: '{search_title}') on platform: {system_name} (id: {platform_id})")
        logger.debug(f"IGDB query: {body}")
        results = igdb_request("games", body, token)

        # If no results with platform filter, try without
        if not results and platform_id:
            logger.info(f"No IGDB results with platform filter, trying without...")
            body = f"""
            search "{search_title}";
            fields id, name, first_release_date, platforms.id, platforms.name, platforms.abbreviation,
                   release_dates.region, release_dates.platform, summary,
                   alternative_names.name, alternative_names.comment;
            where version_parent = null;
            limit {limit};
            """
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
                fields id, name, first_release_date, platforms.id, platforms.name, platforms.abbreviation,
                       release_dates.region, release_dates.platform, summary,
                       alternative_names.name, alternative_names.comment;
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
            fields id, name, first_release_date, platforms.id, platforms.name, platforms.abbreviation,
                   release_dates.region, release_dates.platform, summary,
                   alternative_names.name, alternative_names.comment;
            where name ~ *"{search_title}"* & version_parent = null;
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
                fields id, name, first_release_date, platforms.id, platforms.name, platforms.abbreviation,
                       release_dates.region, release_dates.platform, summary,
                       alternative_names.name, alternative_names.comment;
                where version_parent = null;
                limit {limit};
                """
                results = igdb_request("games", body, token)
        
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
               involved_companies.company.name, involved_companies.developer, involved_companies.publisher,
               genres.name, age_ratings.category, age_ratings.rating,
               game_modes.name, player_perspectives.name,
               multiplayer_modes.offlinemax, multiplayer_modes.onlinemax,
               multiplayer_modes.campaigncoop, multiplayer_modes.splitscreen,
               summary, storyline, cover.url, screenshots.url, artworks.url,
               videos.video_id, alternative_names.name,
               rating, rating_count, aggregated_rating, aggregated_rating_count;
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

# =============================================================================
# APPLY METADATA
# =============================================================================

def apply_metadata_to_game(db_game_id, igdb_data):
    """Apply IGDB metadata to database game"""
    conn = None
    
    try:
        conn = get_scraper_conn()
        c = conn.cursor()
        
        # Extract publisher and developer
        publisher = ''
        developer = ''
        
        involved_companies = igdb_data.get('involved_companies', [])
        for comp in involved_companies:
            if comp.get('publisher'):
                if publisher:
                    publisher += f", {comp['company']['name']}"
                else:
                    publisher = comp['company']['name']
            if comp.get('developer'):
                if developer:
                    developer += f", {comp['company']['name']}"
                else:
                    developer = comp['company']['name']
        
        # Release date
        release_date = igdb_data.get('first_release_date')
        if release_date:
            try:
                release_date = datetime.utcfromtimestamp(release_date).strftime('%Y-%m-%d')
            except Exception:
                release_date = ''
        else:
            release_date = ''
        
        # Genre
        genres = igdb_data.get('genres', [])
        genre = ', '.join(g['name'] for g in genres) if genres else ''
        
        # Age ratings - IGDB category: 1=ESRB, 2=PEGI
        # ESRB ratings: 6=RP, 7=EC, 8=E, 9=E10+, 10=T, 11=M, 12=AO
        # PEGI ratings: 1=3, 2=7, 3=12, 4=16, 5=18
        rating = ''
        esrb_rating = ''
        pegi_rating = ''
        
        age_ratings = igdb_data.get('age_ratings', [])
        for age_rating in age_ratings:
            category = age_rating.get('category')
            rating_value = age_rating.get('rating')
            
            if category == 1:  # ESRB
                esrb_map = {6: 'RP', 7: 'EC', 8: 'E', 9: 'E10+', 10: 'T', 11: 'M', 12: 'AO'}
                esrb_rating = esrb_map.get(rating_value, '')
                if esrb_rating:
                    logger.info(f"IGDB ESRB rating: {esrb_rating}")
            elif category == 2:  # PEGI
                pegi_map = {1: '3', 2: '7', 3: '12', 4: '16', 5: '18'}
                pegi_number = pegi_map.get(rating_value, '')
                if pegi_number:
                    pegi_rating = f"PEGI {pegi_number}"
                    logger.info(f"IGDB PEGI rating: {pegi_rating}")
        
        # Use ESRB or PEGI as main rating
        if esrb_rating:
            rating = esrb_rating
        elif pegi_rating:
            rating = pegi_rating
        
        # Game modes
        modes = ', '.join(g['name'] for g in igdb_data.get('game_modes', [])) or ''
        
        # Players — Pass 40.6: leave as None when IGDB has no value so
        # COALESCE(?, players) preserves the curated DB value.  The previous
        # default of 1 silently overwrote curated multi-player counts on
        # every re-scrape because COALESCE(1, players) is always 1.
        players = None
        multiplayer_modes = igdb_data.get('multiplayer_modes', [])
        if multiplayer_modes:
            max_players = max((m.get('offlinemax', 0) for m in multiplayer_modes), default=0)
            if max_players:
                players = max_players
        
        # Description
        description = igdb_data.get('storyline', igdb_data.get('summary', ''))
        
        # Download cover art
        boxart = None
        if 'cover' in igdb_data and 'url' in igdb_data['cover']:
            boxart_url = igdb_data['cover']['url'].replace('t_thumb', 't_cover_big')
            if not boxart_url.startswith('http'):
                boxart_url = f"https:{boxart_url}"
            
            from services.image_utils import preferred_image_extension
            boxart_filename = f"{db_game_id}_igdb{preferred_image_extension('boxart', '.jpg')}"
            local_dir = os.path.join(IMAGE_PATH, 'boxart')
            os.makedirs(local_dir, exist_ok=True)
            local_path = os.path.join(local_dir, boxart_filename)
            
            if download_image(boxart_url, local_path, timeout=10):
                boxart = boxart_filename
                logger.info(f"Downloaded IGDB cover for game {db_game_id}")
            else:
                logger.warning(f"Failed to download cover from {boxart_url}")
        
        # Download screenshots
        screenshots = []
        if 'screenshots' in igdb_data:
            screenshot_dir = os.path.join(IMAGE_PATH, 'screenshots')
            os.makedirs(screenshot_dir, exist_ok=True)
            
            for i, screenshot in enumerate(igdb_data['screenshots'][:3]):
                if 'url' in screenshot:
                    screenshot_url = screenshot['url'].replace('t_thumb', 't_screenshot_big')
                    if not screenshot_url.startswith('http'):
                        screenshot_url = f"https:{screenshot_url}"
                    
                    from services.image_utils import preferred_image_extension
                    screenshot_filename = f"{db_game_id}_ss{i+1}{preferred_image_extension('screenshots', '.jpg')}"
                    local_path = os.path.join(screenshot_dir, screenshot_filename)
                    
                    if download_image(screenshot_url, local_path, timeout=10):
                        screenshots.append(screenshot_filename)
                        logger.info(f"Downloaded screenshot {i+1} for game {db_game_id}")
                    else:
                        logger.warning(f"Failed to download screenshot from {screenshot_url}")
        
        # Download fanart/artwork (first one only)
        fanart = None
        if 'artworks' in igdb_data and igdb_data['artworks']:
            artwork = igdb_data['artworks'][0]
            if 'url' in artwork:
                artwork_url = artwork['url'].replace('t_thumb', 't_1080p')
                if not artwork_url.startswith('http'):
                    artwork_url = f"https:{artwork_url}"
                
                from services.image_utils import preferred_image_extension
                fanart_filename = f"{db_game_id}_igdb_fanart{preferred_image_extension('fanart', '.jpg')}"
                fanart_dir = os.path.join(IMAGE_PATH, 'fanart')
                os.makedirs(fanart_dir, exist_ok=True)
                local_path = os.path.join(fanart_dir, fanart_filename)
                
                if download_image(artwork_url, local_path, timeout=15):
                    fanart = fanart_filename
                    logger.info(f"Downloaded fanart for game {db_game_id}")
                else:
                    logger.warning(f"Failed to download fanart from {artwork_url}")
        
        # Extract critic/user scores
        critic_score = igdb_data.get('aggregated_rating')  # 0-100 scale
        critic_score_count = igdb_data.get('aggregated_rating_count')
        user_score = igdb_data.get('rating')  # 0-100 scale
        user_score_count = igdb_data.get('rating_count')
        
        if critic_score:
            logger.info(f"Critic score: {critic_score:.1f} ({critic_score_count} reviews)")
        if user_score:
            logger.info(f"User score: {user_score:.1f} ({user_score_count} ratings)")
        
        # Update game record (including title)
        scraped_title = igdb_data.get('name', '')
        screenshots_str = ','.join(screenshots) if screenshots else None
        
        # Fill-only writes: COALESCE preserves prior scraped/curated values when
        # the IGDB response is empty for a field. Matches scrape_esde's pattern.
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
                critic_score = COALESCE(?, critic_score),
                critic_score_count = COALESCE(?, critic_score_count),
                user_score = COALESCE(?, user_score),
                user_score_count = COALESCE(?, user_score_count),
                scraped = 1
            WHERE id = ?
        """, (
            scraped_title if scraped_title else None,
            publisher or None, developer or None, release_date or None, genre or None,
            rating or None, esrb_rating or None, pegi_rating or None,
            players if players else None, modes or None, description or None, boxart or None,
            screenshots_str, fanart,
            critic_score, critic_score_count,
            user_score, user_score_count,
            db_game_id
        ))
        
        conn.commit()
        logger.info(f"Applied IGDB metadata to game ID: {db_game_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error applying IGDB metadata: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()
