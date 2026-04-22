# =============================================================================
# SCRAPER MANAGER
# =============================================================================
# Coordinates multiple scraping sources:
# - TheGamesDB (platform-specific boxart)
# - IGDB (comprehensive metadata)
# - ES-DE (local gamelist.xml)
# - RAWG.io (detailed game info, ESRB ratings)
# - ScreenScraper (comprehensive retro gaming database)
#
# Scoring / noise-stripping live in scraper.match_scorer + scraper.title_normalizer.
# ScreenScraper result cache lives in scraper.scraper_cache.
# =============================================================================

import logging
import sys
import os
import json
import time

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

# Cache helpers — re-exported for hybrid_scraper and any legacy importer.
from scraper.scraper_cache import (
    cache_screenscraper_result,
    get_cached_screenscraper_result,
)
from scraper.match_scorer import (
    calculate_ss_score,
    calculate_tgdb_score,
    calculate_igdb_score,
    calculate_rawg_score,
)

# Settings file path
SCRAPER_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'scraper_settings.json')

# Minimum match score for bulk scrape auto-selection
# A score of 200 means roughly "close title match with platform confirmation" —
# anything below is likely the wrong game. Configurable via Settings page.
MIN_MATCH_SCORE = 200

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
                        result['score'] = calculate_tgdb_score(result, title)
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
                        result['score'] = calculate_igdb_score(result, title)
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
                        result['score'] = calculate_rawg_score(result, title)
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
                            parsed = self._parse_ss_result(result, system_folder)
                            parsed['score'] = calculate_ss_score(parsed, title)
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

    def _parse_ss_result(self, result, system_folder):
        """Convert a raw ScreenScraper API result into our common result shape.

        Also caches the full raw record under `gameid:systemid` so the hybrid
        scraper can pull it back without re-fetching when the user picks it.
        """
        # System identity
        system_info = result.get('systeme', {})
        ss_system_id = system_info.get('id', '')
        ss_system_name = system_info.get('text', '')

        # Region (English-preferred only — don't fall back to FR/DE/ES/IT).
        region, region_text = self._pick_ss_region(result.get('dates', []))

        # Platform match: did ScreenScraper return a result whose system ID
        # matches the folder we searched under?
        platform_match = False
        if system_folder:
            from scraper.scrape_screenscraper import get_system_id
            searched_ss_id = get_system_id(system_folder)
            if searched_ss_id and str(searched_ss_id) == str(ss_system_id):
                platform_match = True

        game_id = result.get('id')
        cache_screenscraper_result(game_id, ss_system_id, result)

        # Primary name — prefer English / US region.
        name = self._get_ss_localized_text(result.get('noms', []), 'text')

        # Alternate names — every regional release except the one used as primary.
        alt_titles = []
        primary_lower = (name or '').strip().lower()
        for nom in result.get('noms') or []:
            if not isinstance(nom, dict):
                continue
            alt_name = (nom.get('text') or '').strip()
            if not alt_name or alt_name.lower() == primary_lower:
                continue
            alt_titles.append({
                'title': alt_name,
                'region': (nom.get('region') or nom.get('langue') or '').strip() or None,
            })

        return {
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

    @staticmethod
    def _pick_ss_region(dates):
        """Pick the best English-preferred region/date pair from a SS `dates` list."""
        region_priority = ['us', 'wor', 'eu', 'uk', 'au', 'en']
        for pref_region in region_priority:
            for d in dates:
                if d.get('region', '').lower() == pref_region:
                    return pref_region.upper(), d.get('text', '')
        if dates:
            first_region = dates[0].get('region', '').lower()
            if first_region in ('us', 'usa', 'wor', 'world', 'eu', 'eur', 'uk', 'au', 'en'):
                return first_region.upper(), dates[0].get('text', '')
        return None, None

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
