# =============================================================================
# RETRODB - Per-key validators for settings_manager.DEFAULT_SETTINGS
# =============================================================================
# Pass 32.2 — The previous /api/settings handler only checked that a key
# existed in DEFAULT_SETTINGS. The *value* was written verbatim, meaning an
# admin session could:
#   - persist rom_path bypassing 32.1's path check,
#   - set server_port='notaport',
#   - replace the nested `logging` dict with a primitive,
# breaking log_manager.setup_all_logging() on next start.
#
# This module provides a single `validate_settings_value(key, value)` entry
# point. Every persisted key has an explicit validator; unknown keys are
# rejected by the caller before reaching this module.
# =============================================================================

from services.security import validate_settings_path

import settings_manager

# Enum sets derived from existing UI / settings_manager defaults.
_ALLOWED_THEMES = {
    'cyberpunk', 'matrix', 'amber', 'ocean', 'christian', 'bladerunner', 'elite',
}
_ALLOWED_RATING_SYSTEMS = {
    'esrb', 'pegi', 'cero', 'usk', 'acb', 'fpb', 'grac', 'classind',
}
_ALLOWED_BOXART_MODES = {'2d', '3d'}
_ALLOWED_ARTICLE_PLACEMENTS = {'beginning', 'end'}
_ALLOWED_SORT_ORDERS = {'asc', 'desc'}
_ALLOWED_SCRAPERS = {'esde', 'tgdb', 'igdb', 'screenscraper', 'rawg'}
_ALLOWED_LOG_CATEGORIES = {'scraping', 'rom_tools', 'rom_reports', 'image_resize', 'system'}
_ALLOWED_LOG_LEVELS = {'info', 'warning', 'error'}
_ALLOWED_NAMING_SYSTEM_TYPES = {'console', 'handheld', 'computer'}
_ALLOWED_NAMING_TAGS = {
    'region', 'year', 'publisher', 'developer', 'genre', 'system_type', 'system_name',
}
_ALLOWED_NOTIFICATION_LEVELS = {'success', 'info', 'warning', 'error'}


def _path_validator(value):
    ok, result = validate_settings_path(value, allow_empty=True)
    if not ok:
        return False, result, None
    return True, None, result


def _bool_validator(value):
    if not isinstance(value, bool):
        return False, 'must be true or false', None
    return True, None, value


def _port_validator(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return False, 'must be an integer port', None
    if not (1 <= value <= 65535):
        return False, 'must be between 1 and 65535', None
    return True, None, value


def _positive_int_validator(lo, hi):
    def _inner(value):
        if isinstance(value, bool) or not isinstance(value, int):
            return False, f'must be an integer between {lo} and {hi}', None
        if not (lo <= value <= hi):
            return False, f'must be between {lo} and {hi}', None
        return True, None, value
    return _inner


def _host_validator(value):
    if not isinstance(value, str):
        return False, 'must be a string', None
    stripped = value.strip()
    if not stripped:
        return False, 'must not be empty', None
    # Allow IPv4/IPv6/hostname forms; reject control characters and whitespace.
    if any(c.isspace() or ord(c) < 0x20 for c in stripped):
        return False, 'contains invalid characters', None
    if len(stripped) > 255:
        return False, 'host name too long', None
    return True, None, stripped


def _enum_validator(allowed, label):
    def _inner(value):
        if not isinstance(value, str) or value not in allowed:
            return False, f'must be one of {sorted(allowed)}', None
        return True, None, value
    return _inner


def _string_validator(max_len=255, allow_empty=False):
    def _inner(value):
        if not isinstance(value, str):
            return False, 'must be a string', None
        stripped = value.strip()
        if not allow_empty and not stripped:
            return False, 'must not be empty', None
        if len(stripped) > max_len:
            return False, f'must be at most {max_len} characters', None
        return True, None, stripped
    return _inner


def _region_options_validator(value):
    if not isinstance(value, list):
        return False, 'must be a list of region strings', None
    cleaned = []
    for item in value:
        if not isinstance(item, str):
            return False, 'every region must be a string', None
        stripped = item.strip()
        if not stripped or len(stripped) > 64:
            return False, 'region strings must be 1-64 characters', None
        cleaned.append(stripped)
    if not cleaned:
        return False, 'region_options must contain at least one value', None
    if len(cleaned) > 64:
        return False, 'region_options may contain at most 64 entries', None
    return True, None, cleaned


def _scraper_priority_validator(value):
    if not isinstance(value, list):
        return False, 'must be a list of scraper names', None
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in _ALLOWED_SCRAPERS:
            return False, f'every entry must be one of {sorted(_ALLOWED_SCRAPERS)}', None
        if item in seen:
            return False, f'duplicate scraper: {item}', None
        seen.add(item)
    return True, None, list(value)


def _scraper_enabled_validator(value):
    if not isinstance(value, dict):
        return False, 'must be an object of {scraper: bool}', None
    for key, enabled in value.items():
        if key not in _ALLOWED_SCRAPERS:
            return False, f'unknown scraper: {key}', None
        if not isinstance(enabled, bool):
            return False, f'{key} enablement must be a boolean', None
    return True, None, dict(value)


def _notification_timeouts_validator(value):
    if not isinstance(value, dict):
        return False, 'must be an object of {level: seconds}', None
    for key, seconds in value.items():
        if key not in _ALLOWED_NOTIFICATION_LEVELS:
            return False, f'unknown notification level: {key}', None
        if isinstance(seconds, bool) or not isinstance(seconds, int):
            return False, f'{key} timeout must be an integer', None
        if not (1 <= seconds <= 60):
            return False, f'{key} timeout must be between 1 and 60 seconds', None
    return True, None, dict(value)


def _naming_convention_validator(value):
    if not isinstance(value, dict):
        return False, 'must be an object of {system_type: [tags]}', None
    cleaned = {}
    for system_type, tags in value.items():
        if system_type not in _ALLOWED_NAMING_SYSTEM_TYPES:
            return False, f'unknown system type: {system_type}', None
        if not isinstance(tags, list):
            return False, f'{system_type} tags must be a list', None
        if len(tags) > 16:
            return False, f'{system_type}: too many tags', None
        tag_list = []
        for tag in tags:
            if not isinstance(tag, str) or tag not in _ALLOWED_NAMING_TAGS:
                return False, f'unknown tag in {system_type}: {tag}', None
            tag_list.append(tag)
        cleaned[system_type] = tag_list
    return True, None, cleaned


def _logging_validator(value):
    if not isinstance(value, dict):
        return False, 'must be an object of categories', None
    cleaned = {}
    for category, levels in value.items():
        if category not in _ALLOWED_LOG_CATEGORIES:
            return False, f'unknown log category: {category}', None
        if not isinstance(levels, dict):
            return False, f'{category} must be an object of {{level: bool}}', None
        level_map = {}
        for level, enabled in levels.items():
            if level not in _ALLOWED_LOG_LEVELS:
                return False, f'unknown log level in {category}: {level}', None
            if not isinstance(enabled, bool):
                return False, f'{category}.{level} must be boolean', None
            level_map[level] = enabled
        cleaned[category] = level_map
    return True, None, cleaned


# Mapping from settings-key → (key, value) -> (ok, reason, cleaned).
# Every persisted key must appear here; unknown keys are rejected by callers.
_VALIDATORS = {
    'setup_completed': _bool_validator,
    'rom_path': _path_validator,
    'esde_gamelists_path': _path_validator,
    'esde_downloaded_media_path': _path_validator,
    'rpcs3_trophy_path': _path_validator,
    'server_host': _host_validator,
    'server_port': _port_validator,
    'debug_mode': _bool_validator,
    'items_per_page': _positive_int_validator(1, 500),
    'default_sort': _string_validator(max_len=64),
    'default_sort_order': _enum_validator(_ALLOWED_SORT_ORDERS, 'default_sort_order'),
    'show_unscraped_first': _bool_validator,
    'preferred_boxart': _enum_validator(_ALLOWED_BOXART_MODES, 'preferred_boxart'),
    'preferred_rating_system': _enum_validator(_ALLOWED_RATING_SYSTEMS, 'preferred_rating_system'),
    'theme': _enum_validator(_ALLOWED_THEMES, 'theme'),
    'scraper_priority': _scraper_priority_validator,
    'scraper_enabled': _scraper_enabled_validator,
    'enable_animations': _bool_validator,
    'enable_mist_effect': _bool_validator,
    'enable_scanlines': _bool_validator,
    'notification_timeouts': _notification_timeouts_validator,
    'naming_convention': _naming_convention_validator,
    'region_options': _region_options_validator,
    'default_region': _string_validator(max_len=64),
    'article_placement': _enum_validator(_ALLOWED_ARTICLE_PLACEMENTS, 'article_placement'),
    'logging': _logging_validator,
}


def known_keys():
    """Return the set of valid settings keys."""
    # Cross-check at import time: every DEFAULT_SETTINGS key must have a
    # validator, so we don't silently persist a value that downstream code
    # depends on having a particular shape.
    return set(_VALIDATORS.keys())


def validate_settings_value(key, value):
    """Validate one (key, value) against the per-key validator table.

    Returns (ok, reason, cleaned):
        ok=True, reason=None, cleaned=<normalized value>   on success
        ok=False, reason=<string>, cleaned=None             on failure
    Unknown keys fail with ok=False, reason='unknown setting key'.
    """
    validator = _VALIDATORS.get(key)
    if validator is None:
        return False, 'unknown setting key', None
    return validator(value)


# Sanity check: every DEFAULT_SETTINGS key has a validator. If someone adds
# a new setting without wiring a validator, importing this module raises
# instead of silently passing bad values through.
_missing = set(settings_manager.DEFAULT_SETTINGS.keys()) - set(_VALIDATORS.keys())
if _missing:
    raise RuntimeError(
        f'settings_validators: DEFAULT_SETTINGS has keys with no validator: '
        f'{sorted(_missing)}'
    )
