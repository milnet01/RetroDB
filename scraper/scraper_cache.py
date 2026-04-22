# =============================================================================
# RETRODB - Scraper Result Cache
# =============================================================================
# Thread-safe TTL-backed cache for ScreenScraper search results so we don't
# have to re-fetch the full record when the user picks a result out of the
# search list. Extracted from scraper/scraper_manager.py.
# =============================================================================

import threading
from datetime import datetime, timedelta


_CACHE_EXPIRY_MINUTES = 10
_CACHE_MAX_SIZE = 500

_cache = {}
_cache_lock = threading.Lock()


def cache_screenscraper_result(game_id, system_id, data):
    """Cache a ScreenScraper search result (thread-safe)."""
    key = f"{game_id}:{system_id}"
    with _cache_lock:
        _cache[key] = {"data": data, "timestamp": datetime.now()}
        if len(_cache) > _CACHE_MAX_SIZE:
            # First: drop expired entries.
            cutoff = datetime.now() - timedelta(minutes=_CACHE_EXPIRY_MINUTES)
            expired = [k for k, v in _cache.items() if v["timestamp"] < cutoff]
            for k in expired:
                del _cache[k]
            # Still full: drop oldest until we're back under the cap.
            if len(_cache) > _CACHE_MAX_SIZE:
                sorted_keys = sorted(_cache, key=lambda k: _cache[k]["timestamp"])
                for k in sorted_keys[:len(_cache) - _CACHE_MAX_SIZE]:
                    del _cache[k]


def get_cached_screenscraper_result(game_id, system_id):
    """Return a cached ScreenScraper result if not expired, else None."""
    key = f"{game_id}:{system_id}"
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if datetime.now() - entry["timestamp"] < timedelta(minutes=_CACHE_EXPIRY_MINUTES):
            return entry["data"]
        del _cache[key]
    return None
