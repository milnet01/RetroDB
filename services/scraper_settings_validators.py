# =============================================================================
# RETRODB - Per-key validators for scraper_settings.json
# =============================================================================
# Pass 45.11 — /api/scraper-settings POST and /api/scraper-api-keys POST were
# previously writing the request body verbatim via atomic_write_json. An admin
# session could persist:
#   - priority=['../../etc/passwd']  (bogus scraper name)
#   - enabled={'tgdb': 'yes'}        (string instead of bool)
#   - minimum_match_score='lots'     (string crashes scraper_manager)
#   - api_keys[ra_apikey]=42         (int crashes any URL formatter)
# breaking the next call to scraper_manager.scrape_game().
#
# This module mirrors services/settings_validators.py: every persisted key has
# an explicit per-shape validator; unknown keys are rejected by callers.
# =============================================================================

# Includes 'ai' alongside the metadata scrapers — scraper_settings.priority
# embeds the AI-fill provider as a pseudo-scraper.
_ALLOWED_SCRAPER_NAMES = {'esde', 'tgdb', 'igdb', 'screenscraper', 'rawg', 'ai'}

_ALLOWED_MATCH_MODES = {'score', 'criteria'}
_ALLOWED_TITLE_QUALITIES = {'exact', 'close', 'partial', 'any'}

# Allowlist for /api/scraper-api-keys POST. Every key must appear here; unknown
# fields are rejected. Values are validated as either string secrets or short
# identifier strings. The masked-sentinel pass-through happens upstream of this
# validator (routes/scraper.py:_apply_masked_sentinels).
_ALLOWED_API_KEY_FIELDS = {
    'tgdb', 'tgdb_public',
    'igdb_client_id', 'igdb_client_secret',
    'rawg',
    'screenscraper_username', 'screenscraper_password',
    'screenscraper_devid', 'screenscraper_devpassword',
    'ra_username', 'ra_apikey',
    'steam_api_key', 'steam_id',
    'xbox_client_id', 'xbox_client_secret',
    'ai_provider',
    'ai_gemini_api_key', 'ai_gemini_model', 'ai_gemini_project_id',
    'ai_openai_api_key', 'ai_openai_model',
    'ai_claude_api_key', 'ai_claude_model',
}

# Provider selector is enum, not freeform.
_ALLOWED_AI_PROVIDERS = {'', 'gemini', 'openai', 'claude'}

# Cap api-key strings — generous but prevents unbounded JSON blob writes.
_MAX_API_KEY_LEN = 4096


def _bool(value):
    if not isinstance(value, bool):
        return False, 'must be true or false', None
    return True, None, value


def _priority_validator(value):
    if not isinstance(value, list):
        return False, 'priority must be a list of scraper names', None
    seen = set()
    cleaned = []
    for item in value:
        if not isinstance(item, str) or item not in _ALLOWED_SCRAPER_NAMES:
            return False, f'every priority entry must be one of {sorted(_ALLOWED_SCRAPER_NAMES)}', None
        if item in seen:
            return False, f'duplicate scraper in priority: {item}', None
        seen.add(item)
        cleaned.append(item)
    return True, None, cleaned


def _enabled_validator(value):
    if not isinstance(value, dict):
        return False, 'enabled must be an object of {scraper: bool}', None
    cleaned = {}
    for key, enabled in value.items():
        if key not in _ALLOWED_SCRAPER_NAMES:
            return False, f'unknown scraper in enabled: {key}', None
        if not isinstance(enabled, bool):
            return False, f'enabled.{key} must be true or false', None
        cleaned[key] = enabled
    return True, None, cleaned


def _minimum_match_score_validator(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return False, 'minimum_match_score must be an integer', None
    if not (0 <= value <= 1000):
        return False, 'minimum_match_score must be between 0 and 1000', None
    return True, None, value


def _match_mode_validator(value):
    if not isinstance(value, str) or value not in _ALLOWED_MATCH_MODES:
        return False, f'match_mode must be one of {sorted(_ALLOWED_MATCH_MODES)}', None
    return True, None, value


def _match_criteria_validator(value):
    if not isinstance(value, dict):
        return False, 'match_criteria must be an object', None
    cleaned = {}
    if 'platform_required' in value:
        if not isinstance(value['platform_required'], bool):
            return False, 'match_criteria.platform_required must be true or false', None
        cleaned['platform_required'] = value['platform_required']
    if 'title_quality' in value:
        tq = value['title_quality']
        if not isinstance(tq, str) or tq not in _ALLOWED_TITLE_QUALITIES:
            return False, f'match_criteria.title_quality must be one of {sorted(_ALLOWED_TITLE_QUALITIES)}', None
        cleaned['title_quality'] = tq
    extra = set(value.keys()) - {'platform_required', 'title_quality'}
    if extra:
        return False, f'match_criteria has unknown keys: {sorted(extra)}', None
    return True, None, cleaned


# Top-level keys for /api/scraper-settings POST. `api_keys` is preserved
# upstream from existing storage (POST body never carries it through this path)
# but if present we validate it as a dict and let the api-keys endpoint own
# field-level validation.
_SETTINGS_VALIDATORS = {
    'priority': _priority_validator,
    'enabled': _enabled_validator,
    'minimum_match_score': _minimum_match_score_validator,
    'match_mode': _match_mode_validator,
    'match_criteria': _match_criteria_validator,
}


def validate_scraper_settings(data):
    """Validate the body for /api/scraper-settings POST.

    Returns (ok, reason, cleaned). `api_keys` is intentionally NOT validated
    here — the route preserves the existing api_keys block from disk.
    Top-level unknown keys are rejected.
    """
    if not isinstance(data, dict):
        return False, 'request body must be a JSON object', None
    cleaned = {}
    for key, value in data.items():
        if key == 'api_keys':
            # Preserved by the route; passthrough untouched.
            if not isinstance(value, dict):
                return False, 'api_keys must be an object', None
            cleaned['api_keys'] = value
            continue
        validator = _SETTINGS_VALIDATORS.get(key)
        if validator is None:
            return False, f'unknown scraper-settings key: {key}', None
        ok, reason, value_clean = validator(value)
        if not ok:
            return False, reason, None
        cleaned[key] = value_clean
    return True, None, cleaned


def _ai_provider_validator(value):
    if not isinstance(value, str) or value not in _ALLOWED_AI_PROVIDERS:
        return False, f'ai_provider must be one of {sorted(_ALLOWED_AI_PROVIDERS)}', None
    return True, None, value


def _api_key_string_validator(value, *, field):
    if not isinstance(value, str):
        return False, f'{field} must be a string', None
    if len(value) > _MAX_API_KEY_LEN:
        return False, f'{field} exceeds {_MAX_API_KEY_LEN}-char limit', None
    # Reject control characters (covers NUL, CR/LF that would smuggle into
    # logs or query strings). Tab and printable ASCII OK.
    if any(ord(c) < 0x20 and c != '\t' for c in value):
        return False, f'{field} contains control characters', None
    return True, None, value


def validate_scraper_api_keys(data):
    """Validate the body for /api/scraper-api-keys POST.

    Returns (ok, reason, cleaned). Unknown fields are rejected. Each field is
    a string capped at _MAX_API_KEY_LEN; ai_provider is enum.
    """
    if not isinstance(data, dict):
        return False, 'request body must be a JSON object', None
    cleaned = {}
    for key, value in data.items():
        if key not in _ALLOWED_API_KEY_FIELDS:
            return False, f'unknown api-key field: {key}', None
        if key == 'ai_provider':
            ok, reason, clean = _ai_provider_validator(value)
        else:
            ok, reason, clean = _api_key_string_validator(value, field=key)
        if not ok:
            return False, reason, None
        cleaned[key] = clean
    return True, None, cleaned
