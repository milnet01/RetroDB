# =============================================================================
# SCRAPER MANAGER
# =============================================================================
# Coordinates multiple scraping sources:
# - TheGamesDB (platform-specific boxart)
# - IGDB (comprehensive metadata)
# - ES-DE (local gamelist.xml)
# - RAWG.io (detailed game info, ESRB ratings)
# - ScreenScraper (comprehensive retro gaming database)
# =============================================================================

import logging
import sys
import os
import json
import time
import threading
from datetime import datetime, timedelta

try:
    from circuitbreaker import circuit, CircuitBreakerError
    _CB_AVAILABLE = True
except ImportError:
    _CB_AVAILABLE = False
    # Define a dummy exception so except clauses don't fail at parse time
    class CircuitBreakerError(Exception):
        pass

# Add parent directory to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import config
except ImportError:
    config = None

# Settings file path
SCRAPER_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'scraper_settings.json')

# Minimum match score for bulk scrape auto-selection
# A score of 200 means roughly "close title match with platform confirmation" —
# anything below is likely the wrong game. Configurable via Settings page.
MIN_MATCH_SCORE = 200

# ScreenScraper search result cache (expires after 10 minutes, max 500 entries)
# Key: "gameid:systemid", Value: {"data": {...}, "timestamp": datetime}
_screenscraper_cache = {}
_screenscraper_cache_lock = threading.Lock()
_CACHE_EXPIRY_MINUTES = 10
_CACHE_MAX_SIZE = 500

def cache_screenscraper_result(game_id, system_id, data):
    """Cache a ScreenScraper search result (thread-safe)"""
    key = f"{game_id}:{system_id}"
    with _screenscraper_cache_lock:
        _screenscraper_cache[key] = {
            "data": data,
            "timestamp": datetime.now()
        }
        # Evict oldest entries if cache exceeds max size
        if len(_screenscraper_cache) > _CACHE_MAX_SIZE:
            cutoff = datetime.now() - timedelta(minutes=_CACHE_EXPIRY_MINUTES)
            expired = [k for k, v in _screenscraper_cache.items() if v["timestamp"] < cutoff]
            for k in expired:
                del _screenscraper_cache[k]
            # If still too large, remove oldest entries
            if len(_screenscraper_cache) > _CACHE_MAX_SIZE:
                sorted_keys = sorted(_screenscraper_cache, key=lambda k: _screenscraper_cache[k]["timestamp"])
                for k in sorted_keys[:len(_screenscraper_cache) - _CACHE_MAX_SIZE]:
                    del _screenscraper_cache[k]

def get_cached_screenscraper_result(game_id, system_id):
    """Get a cached ScreenScraper result if not expired (thread-safe)"""
    key = f"{game_id}:{system_id}"
    with _screenscraper_cache_lock:
        if key in _screenscraper_cache:
            entry = _screenscraper_cache[key]
            if datetime.now() - entry["timestamp"] < timedelta(minutes=_CACHE_EXPIRY_MINUTES):
                return entry["data"]
            else:
                # Expired, remove it
                del _screenscraper_cache[key]
    return None

_settings_cache = None
_settings_cache_time = 0
_SETTINGS_CACHE_TTL = 30  # seconds


def load_scraper_settings():
    """Load all scraper settings from file, with config.py as fallback"""
    global _settings_cache, _settings_cache_time
    now = time.time()
    if _settings_cache is not None and (now - _settings_cache_time) < _SETTINGS_CACHE_TTL:
        return _settings_cache

    # Defaults - ScreenScraper first as preferred by user
    defaults = {
        'priority': ['screenscraper', 'esde', 'tgdb', 'igdb', 'rawg'],
        'enabled': {
            'esde': getattr(config, 'SCRAPER_ESDE_ENABLED', True) if config else True,
            'tgdb': getattr(config, 'SCRAPER_TGDB_ENABLED', True) if config else True,
            'igdb': getattr(config, 'SCRAPER_IGDB_ENABLED', True) if config else True,
            'rawg': getattr(config, 'SCRAPER_RAWG_ENABLED', True) if config else True,
            'screenscraper': getattr(config, 'SCRAPER_SCREENSCRAPER_ENABLED', True) if config else True
        },
        'api_keys': {}
    }
    
    try:
        if os.path.exists(SCRAPER_SETTINGS_FILE):
            with open(SCRAPER_SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
                # Merge saved settings with defaults
                if 'priority' in saved:
                    defaults['priority'] = saved['priority']
                if 'enabled' in saved:
                    defaults['enabled'].update(saved['enabled'])
                if 'api_keys' in saved:
                    defaults['api_keys'] = saved['api_keys']
                # Pass through match filtering settings
                for key in ('minimum_match_score', 'match_mode', 'match_criteria'):
                    if key in saved:
                        defaults[key] = saved[key]
                _settings_cache = defaults
                _settings_cache_time = now
                return defaults
    except Exception as e:
        logging.warning(f"Could not load scraper settings: {e}")

    _settings_cache = defaults
    _settings_cache_time = now
    return defaults

def load_scraper_priority():
    """Load scraper priority from settings file"""
    return load_scraper_settings()['priority']

def load_scraper_enabled():
    """Load scraper enabled status from settings file"""
    return load_scraper_settings()['enabled']

def get_match_settings():
    """Load bulk scrape match filtering settings from scraper_settings.json.

    Returns a dict with:
        mode: 'score' or 'criteria'
        min_score: int threshold for score mode
        title_quality: 'exact'|'close'|'partial'|'any' for criteria mode
        platform_required: bool for criteria mode
    """
    settings = load_scraper_settings()
    mode = settings.get('match_mode', 'score')
    min_score = settings.get('minimum_match_score', MIN_MATCH_SCORE)
    criteria = settings.get('match_criteria', {})
    return {
        'mode': mode if mode in ('score', 'criteria') else 'score',
        'min_score': int(min_score) if min_score else MIN_MATCH_SCORE,
        'title_quality': criteria.get('title_quality', 'close'),
        'platform_required': criteria.get('platform_required', True),
    }


# Title quality thresholds for criteria mode filtering
_TITLE_QUALITY_THRESHOLDS = {
    'exact': 280,
    'close': 150,
    'partial': 50,
    'any': 0,
}


def passes_match_filter(result, match_settings):
    """Check whether a search result passes the active match filter.

    Args:
        result: Search result dict (must have 'score'; may have 'title_score', 'platform_match')
        match_settings: Dict from get_match_settings()

    Returns:
        True if the result passes the filter.
    """
    if match_settings['mode'] == 'criteria':
        threshold = _TITLE_QUALITY_THRESHOLDS.get(match_settings['title_quality'], 150)
        title_score = result.get('title_score', result.get('score', 0))
        if title_score < threshold:
            return False
        if match_settings['platform_required'] and not result.get('platform_match'):
            return False
        return True
    else:
        # Score mode (default)
        return result.get('score', 0) >= match_settings['min_score']


def get_api_key(service, key_name=None):
    """Get an API key from scraper_settings.json, falling back to config.py.

    Centralized credential access for all scrapers. Avoids each scraper
    implementing its own settings file loading logic.

    Args:
        service: Service name matching scraper_settings.json keys
                 (e.g., 'tgdb_apikey', 'igdb_client_id', 'ra_apikey')
        key_name: Optional config.py attribute name to fall back to.
                  If not provided, returns empty string on miss.

    Returns:
        The API key string, or empty string if not found.
    """
    settings = load_scraper_settings()
    api_keys = settings.get('api_keys', {})
    value = api_keys.get(service, '')
    if value:
        return value
    # Fallback to config.py
    if key_name and config:
        return getattr(config, key_name, '')
    return ''

from .scrape_metadata_thegamesdb import (
    search_games as search_tgdb,
    fetch_game_details as fetch_tgdb,
    apply_metadata_to_game as apply_tgdb
)
from .scrape_metadata_igdb import (
    search_games as search_igdb,
    fetch_game_details as fetch_igdb,
    apply_metadata_to_game as apply_igdb
)

logger = logging.getLogger(__name__)

# Try to import ES-DE scraper (always try, check enabled status dynamically)
ESDE_AVAILABLE = False
try:
    from .scrape_esde import (
        search_esde_games as search_esde,
        fetch_esde_game_details as fetch_esde,
        apply_esde_metadata as apply_esde,
        normalize_external_platform_name
    )
    ESDE_AVAILABLE = True
except ImportError:
    logger.warning("ES-DE scraper module not available")

# Try to import RAWG.io scraper
RAWG_AVAILABLE = False
try:
    from .scrape_rawg import (
        search_games as search_rawg,
        get_game_details as fetch_rawg,
        check_api_status as check_rawg_status
    )
    RAWG_AVAILABLE = True
    logger.info("RAWG.io scraper module loaded successfully")
except ImportError:
    logger.warning("RAWG.io scraper module not available")

# Try to import ScreenScraper scraper
SCREENSCRAPER_AVAILABLE = False
try:
    from .scrape_screenscraper import (
        search_game as search_screenscraper,
        get_game_info as fetch_screenscraper,
        check_credentials as check_screenscraper_status
    )
    SCREENSCRAPER_AVAILABLE = True
    logger.info("ScreenScraper scraper module loaded successfully")
except ImportError as e:
    logger.warning(f"ScreenScraper scraper module not available: {e}")

# Try to import AI metadata scraper
AI_AVAILABLE = False
try:
    from .scrape_ai import (
        get_game_details as fetch_ai,
        check_api_status as check_ai_status
    )
    AI_AVAILABLE = True
    logger.info("AI metadata scraper module loaded successfully")
except ImportError as e:
    logger.debug(f"AI metadata scraper module not available: {e}")


# =============================================================================
# CIRCUIT BREAKERS — skip dead API sources after consecutive failures
# =============================================================================
# After 5 consecutive failures, the circuit opens and the source is skipped
# for 2 minutes before allowing a test request through.

if _CB_AVAILABLE:
    _tgdb_breaker = circuit(failure_threshold=5, recovery_timeout=120, expected_exception=Exception)
    _igdb_breaker = circuit(failure_threshold=5, recovery_timeout=120, expected_exception=Exception)
    _rawg_breaker = circuit(failure_threshold=5, recovery_timeout=120, expected_exception=Exception)
    _screenscraper_breaker = circuit(failure_threshold=5, recovery_timeout=120, expected_exception=Exception)
    _ai_breaker = circuit(failure_threshold=5, recovery_timeout=120, expected_exception=Exception)
else:
    # Fallback: no-op decorator when circuitbreaker not installed
    def _noop_breaker(func):
        return func
    _tgdb_breaker = _noop_breaker
    _igdb_breaker = _noop_breaker
    _rawg_breaker = _noop_breaker
    _screenscraper_breaker = _noop_breaker
    _ai_breaker = _noop_breaker


class ScraperManager:
    """Manages multiple scraping sources"""
    
    def __init__(self):
        # Sources are determined dynamically now
        pass
    
    def get_enabled_scrapers(self):
        """Get list of currently enabled scrapers"""
        enabled = load_scraper_enabled()
        sources = []
        if enabled.get('tgdb', True):
            sources.append('thegamesdb')
        if enabled.get('igdb', True):
            sources.append('igdb')
        if ESDE_AVAILABLE and enabled.get('esde', True):
            sources.append('esde')
        if RAWG_AVAILABLE and enabled.get('rawg', True):
            sources.append('rawg')
        if SCREENSCRAPER_AVAILABLE and enabled.get('screenscraper', False):
            sources.append('screenscraper')
        if AI_AVAILABLE and enabled.get('ai', False):
            sources.append('ai')
        return sources
    
    def search_games(self, title, system_name=None, system_folder=None, limit=10):
        """
        Search games using ALL available sources simultaneously
        Shows results from TheGamesDB, IGDB, ES-DE, RAWG, and ScreenScraper so user can choose
        """
        all_results = []
        
        # Load enabled status dynamically
        enabled = load_scraper_enabled()
        
        logger.info(f"Searching for: '{title}' on system: {system_name} (folder: {system_folder})")
        logger.info(f"Enabled scrapers: {enabled}")
        
        # Search ES-DE first (local, fastest)
        if ESDE_AVAILABLE and enabled.get('esde', True) and system_folder:
            try:
                esde_results = search_esde(title, system_folder, limit)
                if esde_results:
                    logger.info(f"ES-DE found {len(esde_results)} results")
                    # ES-DE results already have score calculated; store as title_score
                    # for criteria-mode filtering (before priority boost is added)
                    for r in esde_results:
                        r['title_score'] = r.get('score', 0)
                    all_results.extend(esde_results)
            except Exception as e:
                logger.error(f"ES-DE search failed: {e}")
        
        # Search TheGamesDB
        if enabled.get('tgdb', True):
            try:
                tgdb_results = _tgdb_breaker(search_tgdb)(title, system_name, limit)
                if tgdb_results:
                    logger.info(f"TheGamesDB found {len(tgdb_results)} results")
                    for result in tgdb_results:
                        result['source'] = 'thegamesdb'
                        result['scraper'] = 'thegamesdb'
                        result['score'] = self._calculate_tgdb_score(result, title, system_name)
                    all_results.extend(tgdb_results)
            except CircuitBreakerError:
                logger.info("TheGamesDB circuit breaker open — skipping (recent failures)")
            except Exception as e:
                logger.error(f"TheGamesDB search failed: {e}")

        # Search IGDB
        if enabled.get('igdb', True):
            try:
                igdb_results = _igdb_breaker(search_igdb)(title, system_name, limit)
                if igdb_results:
                    logger.info(f"IGDB found {len(igdb_results)} results")
                    for result in igdb_results:
                        result['source'] = 'igdb'
                        result['scraper'] = 'igdb'
                        result['score'] = self._calculate_igdb_score(result, title, system_name)
                    all_results.extend(igdb_results)
            except CircuitBreakerError:
                logger.info("IGDB circuit breaker open — skipping (recent failures)")
            except Exception as e:
                logger.error(f"IGDB search failed: {e}")

        # Search RAWG.io
        if RAWG_AVAILABLE and enabled.get('rawg', True):
            try:
                rawg_results = _rawg_breaker(search_rawg)(title, system_folder, limit)
                if rawg_results:
                    logger.info(f"RAWG found {len(rawg_results)} results")
                    for result in rawg_results:
                        result['source'] = 'rawg'
                        result['scraper'] = 'rawg'
                        result['score'] = self._calculate_rawg_score(result, title, system_name)
                    all_results.extend(rawg_results)
            except CircuitBreakerError:
                logger.info("RAWG circuit breaker open — skipping (recent failures)")
            except Exception as e:
                logger.error(f"RAWG search failed: {e}")
        
        # Search ScreenScraper
        logger.info(f"ScreenScraper check: available={SCREENSCRAPER_AVAILABLE}, enabled={enabled.get('screenscraper', False)}, folder={system_folder}")
        if SCREENSCRAPER_AVAILABLE and enabled.get('screenscraper', False) and system_folder:
            try:
                settings = load_scraper_settings()
                api_keys = settings.get('api_keys', {})
                ss_username = api_keys.get('screenscraper_username', '')
                ss_password = api_keys.get('screenscraper_password', '')
                ss_devid = api_keys.get('screenscraper_devid', '')
                ss_devpassword = api_keys.get('screenscraper_devpassword', '')
                
                logger.info(f"ScreenScraper credentials: username={ss_username}, has_password={bool(ss_password)}, devid={ss_devid}")
                
                if ss_username and ss_password:
                    logger.info(f"ScreenScraper searching for: '{title}' on system: {system_folder}")
                    ss_results = _screenscraper_breaker(search_screenscraper)(
                        title, system_folder,
                        ss_username, ss_password,
                        ss_devid, ss_devpassword
                    )
                    if ss_results:
                        logger.info(f"ScreenScraper found {len(ss_results)} results")
                        for result in ss_results:
                            # Get system ID and name from result
                            system_info = result.get('systeme', {})
                            ss_system_id = system_info.get('id', '')
                            ss_system_name = system_info.get('text', '')
                            
                            # Get region from dates - ONLY use English-preferred regions
                            dates = result.get('dates', [])
                            region = None
                            region_text = None
                            # English-preferred regions only
                            region_priority = ['us', 'wor', 'eu', 'uk', 'au', 'en']
                            
                            # First pass: look for preferred regions
                            for pref_region in region_priority:
                                for d in dates:
                                    r = d.get('region', '').lower()
                                    if r == pref_region:
                                        region = r.upper()
                                        region_text = d.get('text', '')
                                        break
                                if region:
                                    break
                            
                            # Only show region if it's an English-preferred one
                            # Don't fallback to FR, DE, ES, IT etc.
                            if not region and dates:
                                first_region = dates[0].get('region', '').lower()
                                # Only use fallback if it's still English-acceptable
                                if first_region in ['us', 'usa', 'wor', 'world', 'eu', 'eur', 'uk', 'au', 'en']:
                                    region = first_region.upper()
                                    region_text = dates[0].get('text', '')
                            
                            # Check if the system matches the searched system
                            platform_match = False
                            if system_folder:
                                searched_system_id = SCREENSCRAPER_AVAILABLE and hasattr(search_screenscraper, '__self__')
                                # Just check if result system matches what we searched for
                                from scraper.scrape_screenscraper import get_system_id
                                searched_ss_id = get_system_id(system_folder)
                                if searched_ss_id and str(searched_ss_id) == str(ss_system_id):
                                    platform_match = True
                            
                            # Parse ScreenScraper result format
                            # ID format: gameid:systemid for later fetching
                            game_id = result.get('id')
                            
                            # Cache the full result for later use when applying
                            cache_screenscraper_result(game_id, ss_system_id, result)
                            
                            # Get name - prefer English/US region
                            name = self._get_ss_localized_text(result.get('noms', []), 'text')

                            # Alternate names — ScreenScraper's `noms` is a list
                            # of {region, langue, text} for every regional release.
                            # Surface them all (minus the one used as primary name).
                            alt_titles = []
                            _primary_lower = (name or '').strip().lower()
                            for nom in result.get('noms') or []:
                                if not isinstance(nom, dict):
                                    continue
                                alt_name = (nom.get('text') or '').strip()
                                if not alt_name or alt_name.lower() == _primary_lower:
                                    continue
                                alt_titles.append({
                                    'title': alt_name,
                                    'region': (nom.get('region') or nom.get('langue') or '').strip() or None,
                                })

                            parsed = {
                                'id': f"{game_id}:{ss_system_id}",
                                'name': name,
                                'source': 'screenscraper',
                                'scraper': 'screenscraper',
                                'release_date': region_text if region_text else self._get_ss_localized_text(result.get('dates', []), 'text'),
                                'platform': ss_system_name,
                                'platforms': [{'name': ss_system_name}] if ss_system_name else [],
                                'region': region,
                                'platform_match': platform_match,
                                'matched_platform': ss_system_name if platform_match else None,
                                'alternate_titles': alt_titles,
                            }
                            parsed['score'] = self._calculate_ss_score(parsed, title, system_name)
                            all_results.append(parsed)
                    else:
                        logger.info("ScreenScraper returned no results")
                else:
                    logger.warning("ScreenScraper: No credentials configured")
            except CircuitBreakerError:
                logger.info("ScreenScraper circuit breaker open — skipping (recent failures)")
            except Exception as e:
                logger.error(f"ScreenScraper search failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Load priority settings and apply priority boost
        priority = load_scraper_priority()
        source_map = {
            'esde': 'esde',
            'tgdb': 'thegamesdb',
            'igdb': 'igdb',
            'rawg': 'rawg',
            'screenscraper': 'screenscraper',
            'ai': 'ai'
        }
        
        # Apply priority boost (higher priority = higher boost)
        # Each priority position adds 10 points (max 50 for first position)
        # With sort-by-score-only in bulk scrape, this is the sole mechanism for
        # scraper preference — meaningful enough to break ties, not override better matches
        for result in all_results:
            result_source = result.get('source', '')
            for idx, prio_key in enumerate(priority):
                if source_map.get(prio_key) == result_source:
                    priority_boost = (len(priority) - idx) * 10  # First = 50, second = 40, etc.
                    result['score'] = result.get('score', 0) + priority_boost
                    break
        
        # Sort by score (keeps best matches at top, with priority boost applied)
        all_results.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        # Return top results (will include mix of all sources)
        final_results = all_results[:limit * 2]  # Return more results for 4-column display

        # Normalize platform names across all scrapers for consistency
        if ESDE_AVAILABLE:
            for result in final_results:
                if result.get('platform'):
                    result['platform'] = normalize_external_platform_name(result['platform'])
                if result.get('matched_platform'):
                    result['matched_platform'] = normalize_external_platform_name(result['matched_platform'])
                if result.get('platforms'):
                    for p in result['platforms']:
                        if isinstance(p, dict) and p.get('name'):
                            p['name'] = normalize_external_platform_name(p['name'])

        # Log summary
        esde_count = sum(1 for r in final_results if r.get('source') == 'esde')
        tgdb_count = sum(1 for r in final_results if r.get('source') == 'thegamesdb')
        igdb_count = sum(1 for r in final_results if r.get('source') == 'igdb')
        rawg_count = sum(1 for r in final_results if r.get('source') == 'rawg')
        ss_count = sum(1 for r in final_results if r.get('source') == 'screenscraper')
        logger.info(f"Returning {len(final_results)} results (ES-DE: {esde_count}, TGDB: {tgdb_count}, IGDB: {igdb_count}, RAWG: {rawg_count}, SS: {ss_count})")
        logger.info(f"Using scraper priority: {priority}")
        
        return final_results
    
    def _get_ss_localized_text(self, items, text_key='text'):
        """Get localized text from ScreenScraper result, preferring English"""
        if not items:
            return ''
        
        # Priority: en/us, then wor (world), then first available
        for region in ['us', 'eu', 'wor', 'ss']:
            for item in items:
                if isinstance(item, dict) and item.get('region', '').lower() == region:
                    result = item.get(text_key, '')
                    if result:
                        return result
        
        # Fallback to first item
        if items and isinstance(items[0], dict):
            return items[0].get(text_key, '')
        
        return ''
    
    def _strip_title_noise(self, title):
        """
        Strip common noise from titles that tanks match scores.
        Removes region tags, disc indicators, version/revision, edition tags,
        and bracketed content like [NTSC], [USA], etc.
        """
        import re
        if not title:
            return title

        # Remove bracketed content: [NTSC], [USA], [PAL], etc.
        title = re.sub(r'\s*\[[^\]]*\]', '', title)

        # Remove parenthesized noise patterns (order matters — specific before general)
        # Region tags: (USA), (Europe), (Japan), (World), (En,Fr,De), (U), (E), (J), etc.
        title = re.sub(r'\s*\((?:USA|Europe|Japan|World|Asia|Australia|Brazil|Canada|China|France|Germany|Italy|Korea|Netherlands|Russia|Spain|Sweden|Taiwan|UK|En|Fr|De|Es|It|Ja|Ko|Nl|Pt|Ru|Sv|Zh|Da|Fi|No|Pl|Tr|Cs|Hu|Ro|El|Ar|He|Th|Vi|U|E|J|W)(?:\s*,\s*(?:USA|Europe|Japan|World|Asia|Australia|Brazil|Canada|China|France|Germany|Italy|Korea|Netherlands|Russia|Spain|Sweden|Taiwan|UK|En|Fr|De|Es|It|Ja|Ko|Nl|Pt|Ru|Sv|Zh|Da|Fi|No|Pl|Tr|Cs|Hu|Ro|El|Ar|He|Th|Vi|U|E|J|W))*\)', '', title, flags=re.IGNORECASE)

        # Disc indicators: (Disc 1), (Disc 1 of 3), (Disk 2), (CD1)
        title = re.sub(r'\s*\((?:Disc|Disk|CD)\s*\d+(?:\s*of\s*\d+)?\)', '', title, flags=re.IGNORECASE)

        # Version/revision: (Rev 1), (Rev A), (v1.0), (v1.1), (Beta), (Proto), (Sample), (Demo)
        title = re.sub(r'\s*\((?:Rev\s*[A-Za-z0-9.]+|v\d+[.\d]*|Beta|Proto(?:type)?|Sample|Demo|Promo|Preview|Unl)\)', '', title, flags=re.IGNORECASE)

        # Edition tags: (Greatest Hits), (GOTY), (Remastered), (Collector's Edition), etc.
        title = re.sub(r"\s*\((?:Greatest\s+Hits|Platinum|Player'?s?\s+Choice|Nintendo\s+Selects|Classics|Budget|GOTY|Game\s+of\s+the\s+Year|Remaster(?:ed)?|Collector'?s?\s+Edition|Special\s+Edition|Limited\s+Edition|Definitive\s+Edition|Complete\s+Edition|Gold\s+Edition|Premium\s+Edition|Deluxe\s+Edition|Ultimate\s+Edition|Standard\s+Edition|Digital\s+Edition|Anniversary\s+Edition|Enhanced\s+Edition|Director'?s?\s+Cut|Black\s+Label|Not\s+for\s+Resale|NFR|Rental)\)", '', title, flags=re.IGNORECASE)

        # Clean up extra whitespace
        title = re.sub(r'\s+', ' ', title).strip()

        return title

    def _word_order_bonus(self, result_words_list, search_words_list):
        """
        Calculate a bonus for words appearing in correct sequential order.
        Uses longest common subsequence (LCS) on word lists.
        Returns 0-40 bonus points.
        """
        if not result_words_list or not search_words_list:
            return 0

        # LCS on word lists
        m, n = len(result_words_list), len(search_words_list)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if result_words_list[i - 1] == search_words_list[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        lcs_len = dp[m][n]
        max_len = max(m, n)
        if max_len == 0:
            return 0

        ratio = lcs_len / max_len
        bonus = int(ratio * 40)
        return bonus

    def _calculate_title_match_score(self, result_title, search_title):
        """
        Calculate a match score between result title and search title.
        Improved algorithm that:
        1. Heavily rewards exact matches
        2. Penalizes short partial matches
        3. Uses word overlap similarity
        4. Prioritizes complete matches over partial matches
        5. Strips noise (region tags, edition tags) before comparison
        6. Adds word-order bonus via LCS
        """
        if not result_title or not search_title:
            return 0

        # Check for raw exact match BEFORE noise stripping — a title that
        # already matches without needing to strip brackets/editions is a
        # stronger signal than one that only matches after stripping.
        raw_exact = result_title.strip().lower() == search_title.strip().lower()

        # Strip noise before any comparison
        result_title = self._strip_title_noise(result_title)
        search_title = self._strip_title_noise(search_title)

        result_lower = result_title.lower()
        search_lower = search_title.lower()
        
        # Normalize - replace punctuation with spaces for comparison
        # Remove ALL apostrophe-like characters using explicit Unicode code points
        import re
        
        # Comprehensive pattern for ALL apostrophe variants (using Unicode escapes for safety)
        # U+0027 = ' (ASCII apostrophe)
        # U+2019 = ' (right single quote - curly)
        # U+2018 = ' (left single quote - curly)
        # U+02BC = ʼ (modifier letter apostrophe)
        # U+02BB = ʻ (modifier letter turned comma)
        # U+0060 = ` (grave accent)
        # U+00B4 = ´ (acute accent)
        # U+2032 = ′ (prime)
        # U+02B9 = ʹ (modifier letter prime)
        apostrophe_chars = "'\u2019\u2018\u02BC\u02BB`\u00B4\u2032\u02B9"
        
        # First remove possessive 's (with any apostrophe variant)
        possessive_pattern = f"[{apostrophe_chars}]s\\b"
        result_normalized = re.sub(possessive_pattern, '', result_lower)
        search_normalized = re.sub(possessive_pattern, '', search_lower)
        
        # Then remove any remaining apostrophes
        apostrophe_pattern = f"[{apostrophe_chars}]"
        result_normalized = re.sub(apostrophe_pattern, '', result_normalized)
        search_normalized = re.sub(apostrophe_pattern, '', search_normalized)
        
        # Replace other punctuation with spaces
        result_normalized = re.sub(r'[:\-–—/]', ' ', result_normalized)
        result_normalized = re.sub(r'\s+', ' ', result_normalized).strip()

        search_normalized = re.sub(r'[:\-–—/]', ' ', search_normalized)
        search_normalized = re.sub(r'\s+', ' ', search_normalized).strip()

        # Normalize Roman numerals to Arabic (e.g., "II" -> "2", "VII" -> "7")
        # so "Rick Dangerous II" matches "Rick Dangerous 2"
        from scraper.base_scraper import normalize_roman_numerals
        result_normalized = normalize_roman_numerals(result_normalized)
        search_normalized = normalize_roman_numerals(search_normalized)

        # Create word lists (for order bonus) and sets (for overlap)
        result_words_list = result_normalized.split()
        search_words_list = search_normalized.split()
        result_words = set(result_words_list)
        search_words = set(search_words_list)

        logger.info(f"Title match: result='{result_normalized}' search='{search_normalized}' | result_words={result_words} search_words={search_words}")

        # Debug: Check if strings look equal but aren't
        if result_words == search_words and result_normalized != search_normalized:
            logger.info(f"  WARN: Words match but strings differ! result_repr={repr(result_normalized)} search_repr={repr(search_normalized)}")

        score = 0

        # Exact match (highest priority) - very high score
        # Exact matches already have perfect word order, no bonus needed
        if result_normalized == search_normalized:
            # Bonus if the raw title matched without noise stripping needed
            # e.g. "Halo 2" > "Halo 2 [Platinum Collection]" when both
            # normalize to the same string after stripping brackets
            bonus = 50 if raw_exact else 0
            logger.info(f"  -> EXACT MATCH: {300 + bonus} (raw_exact={raw_exact})")
            return 300 + bonus

        # Check if all search words are in result words (search is subset of result)
        # This handles cases like searching "Rogue" finding "Assassin's Creed Rogue"
        if search_words <= result_words:
            # All search words present - very good match
            # But penalize results with extra words (like "Remastered", "HD", etc.)
            extra_words = len(result_words) - len(search_words)
            if extra_words == 0:
                # Exact word match (just different punctuation/case)
                score = 280
                logger.info(f"  -> EXACT WORDS: {score}")
            elif extra_words <= 2:
                # Few extra words (like "Collector's Edition")
                completeness = len(search_words) / len(result_words) if result_words else 0
                score = int(200 * completeness)
                logger.info(f"  -> search subset of result ({extra_words} extra): {score}")
            else:
                # Many extra words - less relevant
                completeness = len(search_words) / len(result_words) if result_words else 0
                score = int(150 * completeness)
                logger.info(f"  -> search subset of result ({extra_words} extra, many): {score}")
        # Check if all result words are in search words (result is subset of search)
        # This handles cases like searching "Assassin's Creed Rogue" finding "Assassin's Creed"
        elif result_words <= search_words:
            # Result is missing some words from search - penalize significantly!
            # "Assassin's Creed" should NOT beat "Assassin's Creed Rogue" when searching for latter
            missing_words = len(search_words) - len(result_words)
            completeness = len(result_words) / len(search_words) if search_words else 0
            if missing_words == 1:
                # Just 1 word missing - moderate penalty
                score = int(100 * completeness)
                logger.info(f"  -> result subset of search ({missing_words} missing): {score}")
            elif missing_words == 2:
                # 2 words missing - significant penalty
                score = int(60 * completeness)
                logger.info(f"  -> result subset of search ({missing_words} missing): {score}")
            else:
                # Many words missing - low score
                score = int(30 * completeness)
                logger.info(f"  -> result subset of search ({missing_words} missing, many): {score}")
        else:
            # Partial overlap - use Jaccard for general similarity
            if result_words and search_words:
                common_words = result_words & search_words
                union_words = result_words | search_words
                jaccard = len(common_words) / len(union_words) if union_words else 0

                # Calculate how many of the search words are present
                search_coverage = len(common_words) / len(search_words) if search_words else 0

                if search_coverage >= 0.8:
                    # Most search words found - good match
                    score += int(120 * jaccard)
                elif search_coverage >= 0.6:
                    score += int(80 * jaccard)
                elif search_coverage >= 0.4:
                    score += int(50 * jaccard)
                else:
                    score += int(20 * jaccard)

        # Word-order bonus (0-40 points) — rewards correct sequential ordering
        # "Final Fantasy VII" vs "VII Fantasy Final" will now score differently
        order_bonus = self._word_order_bonus(result_words_list, search_words_list)
        if order_bonus > 0:
            score += order_bonus
            logger.info(f"  -> Word order bonus: +{order_bonus}")

        return score
    
    def _calculate_ss_score(self, result, search_title, system_name):
        """Calculate relevance score for ScreenScraper results"""
        score = self._calculate_title_match_score(result.get('name', ''), search_title)
        result['title_score'] = score

        # Release date bonus
        if result.get('release_date'):
            score += 10
        
        # Platform match bonus - MAJOR boost to ensure correct platform shows first
        if result.get('platform_match'):
            score += 150
        
        # Region bonus - prefer US/World (handle None explicitly)
        region = (result.get('region') or '').upper()
        if region in ['US', 'USA', 'WOR']:
            score += 20
        elif region in ['EU', 'UK']:
            score += 10
        
        return score
    
    def _calculate_tgdb_score(self, result, search_title, system_name):
        """Calculate relevance score for TheGamesDB results"""
        score = self._calculate_title_match_score(result.get('name', ''), search_title)
        result['title_score'] = score

        # Release date bonus
        if result.get('release_date'):
            score += 10
        
        # Platform match bonus - MAJOR boost to ensure correct platform shows first
        if result.get('platform_match'):
            score += 150
        
        # Region bonus - prefer US/World
        region = result.get('region', '').upper() if result.get('region') else ''
        if region in ['USA', 'WORLD']:
            score += 20
        elif region in ['EUROPE', 'EU', 'UK']:
            score += 10
        
        return score
    
    def _calculate_igdb_score(self, result, search_title, system_name):
        """Calculate relevance score for IGDB results"""
        score = self._calculate_title_match_score(result.get('name', ''), search_title)
        result['title_score'] = score

        # Popularity/date bonus
        if result.get('first_release_date'):
            score += 20
        
        # Platform match bonus - MAJOR boost to ensure correct platform shows first
        if result.get('platform_match'):
            score += 150
        
        return score
    
    def _calculate_rawg_score(self, result, search_title, system_name):
        """Calculate relevance score for RAWG results"""
        title_score = self._calculate_title_match_score(result.get('name', ''), search_title)
        result['title_score'] = title_score

        score = title_score
        
        # Has release date bonus
        if result.get('release_date'):
            score += 20
        
        # Has image bonus
        if result.get('image'):
            score += 10
        
        # Platform match bonus - MAJOR boost to ensure correct platform shows first
        if result.get('platform_match'):
            score += 150  # High enough to always put platform matches at top
        
        # Has Metacritic score bonus
        if result.get('metacritic'):
            score += 15
        
        logger.info(f"RAWG Score for '{result.get('name', '')}': title={title_score}, platform_match={result.get('platform_match')}, total={score}")
        
        return score
    
    def fetch_game_details(self, game_id, source, system_folder=None):
        """Fetch game details from specified source"""
        logger.info(f"Fetching details from {source} for ID: {game_id}")
        
        try:
            if source == 'thegamesdb':
                return fetch_tgdb(game_id)
            elif source == 'igdb':
                return fetch_igdb(game_id)
            elif source == 'esde' and ESDE_AVAILABLE:
                return fetch_esde(game_id, system_folder)
            elif source == 'rawg' and RAWG_AVAILABLE:
                return fetch_rawg(game_id)
            else:
                logger.error(f"Unknown source: {source}")
                return None
        except Exception as e:
            logger.error(f"Error fetching details from {source}: {e}")
            return None
    
    def apply_metadata(self, db_game_id, game_data, source, system_folder=None):
        """Apply metadata from specified source to database game"""
        logger.info(f"Applying metadata from {source} to game {db_game_id}")
        
        try:
            if source == 'thegamesdb':
                return apply_tgdb(db_game_id, game_data)
            elif source == 'igdb':
                return apply_igdb(db_game_id, game_data)
            elif source == 'esde' and ESDE_AVAILABLE:
                return apply_esde(db_game_id, game_data, system_folder)
            elif source in ('rawg', 'screenscraper'):
                # RAWG and ScreenScraper don't have standalone apply functions;
                # route through hybrid scraper which handles all sources
                logger.info(f"{source} apply routed through hybrid scraper")
                return False  # Caller should use apply_hybrid_metadata instead
            else:
                logger.error(f"Unknown source: {source}")
                return False
        except Exception as e:
            logger.error(f"Error applying metadata from {source}: {e}")
            return False
    
    def apply_hybrid_metadata(self, db_game_id, primary_source, primary_id,
                              system_folder, all_results=None, explicit_secondary=None):
        """
        Apply metadata from primary source, then fill gaps from other scrapers.

        Args:
            db_game_id: Database game ID
            primary_source: 'esde', 'thegamesdb', or 'igdb'
            primary_id: ID for the primary source
            system_folder: System folder name
            all_results: List of all search results to find secondary sources
            explicit_secondary: User-selected secondary sources from UI checkboxes.
                When provided (non-empty list), these override auto-picked secondaries.
                Each entry: {'source': str, 'id': str, 'name': str}
        """
        try:
            from scraper.hybrid_scraper import apply_hybrid_metadata as hybrid_apply

            # Map source names
            source_map = {'thegamesdb': 'tgdb', 'igdb': 'igdb', 'esde': 'esde', 'rawg': 'rawg', 'screenscraper': 'screenscraper'}
            primary = source_map.get(primary_source, primary_source)

            # Find the selected result from all_results to pass its data directly
            # This fixes the bug where ES-DE would re-fetch using the path and get wrong data
            primary_data = None
            if all_results:
                for r in all_results:
                    if r.get('id') == primary_id and source_map.get(r.get('source'), r.get('source')) == primary:
                        primary_data = r
                        logger.info(f"Found selected result data for {primary}: {r.get('name', 'Unknown')}")
                        break

            # Use explicit user selections if provided, otherwise auto-build from all_results
            if explicit_secondary:
                secondary_sources = []
                for sel in explicit_secondary:
                    src = source_map.get(sel.get('source'), sel.get('source'))
                    if src != primary:
                        secondary_sources.append({
                            'source': src,
                            'id': sel.get('id'),
                            'name': sel.get('name', '')
                        })
                logger.info(f"Using {len(secondary_sources)} explicit secondary selection(s): "
                           f"{[s['source'] + ':' + s.get('name', '') for s in secondary_sources]}")
            else:
                secondary_sources = []
                if all_results:
                    for r in all_results:
                        src = source_map.get(r.get('source'), r.get('source'))
                        if src != primary:
                            secondary_sources.append({
                                'source': src,
                                'id': r.get('id'),
                                'name': r.get('name', '')
                            })

            result = hybrid_apply(
                db_game_id=db_game_id,
                primary_source=primary,
                primary_id=primary_id,
                system_folder=system_folder,
                secondary_sources=secondary_sources,
                fill_gaps=True,
                primary_data=primary_data,
                restrict_to_selected=bool(explicit_secondary)
            )

            return result
            
        except Exception as e:
            logger.error(f"Error in hybrid metadata: {e}")
            # Fall back to regular apply
            game_data = self.fetch_game_details(primary_id, primary_source, system_folder)
            if game_data:
                return {'success': self.apply_metadata(db_game_id, game_data, primary_source, system_folder)}
            return {'success': False}


# Create global instance
scraper_manager = ScraperManager()
