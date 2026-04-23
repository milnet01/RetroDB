# settings_manager.py - Manages user-editable settings
# ================================================================================
# This module handles all user-configurable settings via the web interface.
# Settings are stored in data/settings.json (paths, preferences, server config).
# API keys are stored separately in data/scraper_settings.json.
# ================================================================================

import os
import json
import logging
import threading

from services.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# Default settings file location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE_DIR, 'data', 'settings.json')

# In-memory cache for settings
_settings_cache = None
_settings_cache_mtime = None
_settings_cache_lock = threading.Lock()

# Default values for user-editable settings
DEFAULT_SETTINGS = {
    # Setup wizard completion flag
    'setup_completed': False,

    # Paths - configured via Settings page or setup wizard
    'rom_path': '',
    'esde_gamelists_path': '',
    'esde_downloaded_media_path': '',
    'rpcs3_trophy_path': '',
    
    # Server settings
    'server_host': '0.0.0.0',
    'server_port': 5000,
    'debug_mode': True,
    
    # UI Preferences
    'items_per_page': 50,
    'default_sort': 'title',
    'default_sort_order': 'asc',
    'show_unscraped_first': False,
    'preferred_boxart': '2d',  # '2d' or '3d' - if 3d, falls back to 2d when unavailable
    'preferred_rating_system': 'esrb',  # esrb, pegi, cero, usk, acb, fpb, grac, classind
    'theme': 'cyberpunk',  # 'cyberpunk', 'matrix', 'amber', 'ocean'
    
    # Scraper settings
    'scraper_priority': ['esde', 'screenscraper', 'tgdb', 'igdb', 'rawg'],
    'scraper_enabled': {
        'esde': True,
        'tgdb': True,
        'igdb': True,
        'screenscraper': True,
        'rawg': True
    },
    
    # Feature toggles
    'enable_animations': True,
    'enable_mist_effect': True,
    'enable_scanlines': True,

    # Notification timeout settings (in seconds)
    'notification_timeouts': {
        'success': 3,
        'info': 3,
        'warning': 5,
        'error': 8
    },
    
    # ROM naming convention per system type
    # Each value is a list of tag keys in order. Title is always first (implicit).
    # Available tags: region, year, publisher, developer, genre, system_type, system_name
    'naming_convention': {
        'console':  ['region'],
        'handheld': ['region'],
        'computer': ['year', 'publisher'],
    },

    # Region options and default
    'region_options': ['USA', 'Europe', 'Japan', 'World'],
    'default_region': 'USA',

    # Article placement in game titles and ROM filenames
    # 'beginning' = natural: "The Legend of Zelda", "A Bug's Life"
    # 'end' = sort-friendly: "Legend of Zelda, The", "Bug's Life, A"
    'article_placement': 'beginning',

    # Logging settings
    'logging': {
        'scraping': {
            'info': True,
            'warning': True,
            'error': True
        },
        'rom_tools': {
            'info': False,
            'warning': True,
            'error': True
        },
        'rom_reports': {
            'info': False,
            'warning': True,
            'error': True
        },
        'image_resize': {
            'info': True,
            'warning': True,
            'error': True
        },
        'system': {
            'info': False,
            'warning': True,
            'error': True
        }
    }
}


def ensure_settings_dir():
    """Ensure the data directory exists"""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)


def _invalidate_cache():
    """Invalidate the settings cache (called after saving)"""
    global _settings_cache, _settings_cache_mtime
    with _settings_cache_lock:
        _settings_cache = None
        _settings_cache_mtime = None


def _deep_merge(base, override):
    """Deep merge two dictionaries, with override values taking precedence"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings():
    """Load settings from JSON file, merging with defaults. Uses in-memory caching."""
    global _settings_cache, _settings_cache_mtime
    
    ensure_settings_dir()
    
    # Check if we can use cached settings
    with _settings_cache_lock:
        if _settings_cache is not None:
            # Check if file has been modified externally
            try:
                current_mtime = os.path.getmtime(SETTINGS_FILE) if os.path.exists(SETTINGS_FILE) else None
                if current_mtime == _settings_cache_mtime:
                    # Cache is still valid
                    return _settings_cache.copy()
            except OSError:
                pass
        
        # Need to load from disk - start with deep copy of defaults
        import copy
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    # Deep merge saved settings with defaults (saved takes precedence)
                    settings = _deep_merge(settings, saved)
                    logger.debug("Loaded user settings from settings.json")
                
                # Update cache
                _settings_cache = copy.deepcopy(settings)
                _settings_cache_mtime = os.path.getmtime(SETTINGS_FILE)
            except Exception as e:
                logger.warning(f"Could not load settings.json: {e}")
                _settings_cache = copy.deepcopy(settings)
                _settings_cache_mtime = None
        else:
            # No file exists, cache the defaults
            import copy
            _settings_cache = copy.deepcopy(settings)
            _settings_cache_mtime = None
        
        return settings


def save_settings(settings):
    """Save settings to JSON file"""
    ensure_settings_dir()
    
    try:
        atomic_write_json(SETTINGS_FILE, settings)
        logger.info("Saved user settings to settings.json")
        
        # Invalidate cache so next load picks up new values
        _invalidate_cache()
        
        return True
    except Exception as e:
        logger.error(f"Could not save settings: {e}")
        return False


def get_setting(key, default=None):
    """Get a single setting value"""
    settings = load_settings()
    return settings.get(key, default)


def set_setting(key, value):
    """Set a single setting value"""
    settings = load_settings()
    settings[key] = value
    return save_settings(settings)


def get_effective_path(setting_key, config_fallback=''):
    """
    Get the effective path from settings.json.
    The config_fallback parameter exists for backwards compatibility but
    is always empty in normal operation — all paths are set via the web UI.
    """
    settings = load_settings()
    user_value = settings.get(setting_key, '')
    
    if user_value and user_value.strip():
        return user_value.strip()
    return config_fallback


def reset_to_defaults():
    """Reset all settings to defaults"""
    return save_settings(DEFAULT_SETTINGS.copy())


# =============================================================================
# SETTINGS THAT REQUIRE RESTART
# =============================================================================

RESTART_REQUIRED_SETTINGS = [
    'rom_path',
    'server_host', 
    'server_port',
    'debug_mode'
]

def requires_restart(changed_keys):
    """Check if any of the changed settings require a restart"""
    return any(key in RESTART_REQUIRED_SETTINGS for key in changed_keys)
