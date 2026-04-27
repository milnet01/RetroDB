# =============================================================================
# SCRAPER SETTINGS API BLUEPRINT
# =============================================================================
# Extracted from app.py - handles scraper configuration, API keys, and status checks
# 
# Routes:
#   GET  /api/scraper-settings         - Get scraper priority and settings
#   POST /api/scraper-settings         - Save scraper priority and settings
#   POST /api/scraper-api-keys         - Save API keys
#   GET  /api/check-scraper/<scraper>  - Check if scraper API is online
#   GET  /api/scraper-allowance/<scraper> - Check rate limits
# =============================================================================

import os
import json
import urllib.request
import urllib.error
import requests
import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify

import config
from services.api_helpers import handle_api_errors
from services.atomic_io import atomic_write_json
from services.auth import admin_required
from services.scraper_settings_validators import (
    validate_scraper_settings,
    validate_scraper_api_keys,
)

# Create blueprint
scraper_bp = Blueprint('scraper', __name__)

# Get logger
logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Path to scraper settings file - EXPORTED for use by app.py settings route
SCRAPER_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'scraper_settings.json')


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Pass 26.5 — API-key hygiene. Fields listed here are treated as secrets: on
# GET they're masked (`***<last4>`) before the response is serialized, and on
# PUT a value matching MASKED_SENTINEL (three-plus asterisks, optionally with
# last-4-visible tail) is interpreted as "don't change" and falls back to the
# stored value. Non-secret identifiers (client_id, usernames, model names,
# provider selector) are returned verbatim.
SECRET_API_KEY_FIELDS = frozenset({
    'tgdb',
    'tgdb_public',
    'igdb_client_secret',
    'rawg',
    'ra_apikey',
    'ai_gemini_api_key',
    'ai_openai_api_key',
    'ai_claude_api_key',
    'steam_api_key',
    'xbox_client_secret',
})

MASKED_SENTINEL_PREFIX = '***'


def mask_api_key(value):
    """Return a display-safe version of `value`: `***<last4>` or `***` if short.

    Empty/None → empty string. The output is intended purely for display — the
    real key stays in scraper_settings.json / config.py.
    """
    if not value:
        return ''
    value = str(value)
    if len(value) <= 4:
        return MASKED_SENTINEL_PREFIX
    return f"{MASKED_SENTINEL_PREFIX}{value[-4:]}"


def is_masked_sentinel(value):
    """True if `value` is a client echo of mask_api_key output (unchanged key)."""
    if not value or not isinstance(value, str):
        return False
    return value.startswith(MASKED_SENTINEL_PREFIX)


def mask_api_keys_for_response(api_keys):
    """Return a copy of `api_keys` with SECRET_API_KEY_FIELDS masked."""
    if not isinstance(api_keys, dict):
        return api_keys
    masked = {}
    for key, value in api_keys.items():
        if key in SECRET_API_KEY_FIELDS:
            masked[key] = mask_api_key(value)
        else:
            masked[key] = value
    return masked


def get_saved_api_keys():
    """Get API keys from saved settings, falling back to config.py"""
    keys = {
        'tgdb': getattr(config, 'THEGAMESDB_API_KEY', ''),
        'tgdb_public': getattr(config, 'THEGAMESDB_PUBLIC_API_KEY', ''),
        'igdb_client_id': getattr(config, 'IGDB_CLIENT_ID', ''),
        'igdb_client_secret': getattr(config, 'IGDB_CLIENT_SECRET', ''),
        'rawg': getattr(config, 'RAWG_API_KEY', ''),
        'ra_username': getattr(config, 'RETROACHIEVEMENTS_USERNAME', ''),
        'ra_apikey': getattr(config, 'RETROACHIEVEMENTS_API_KEY', ''),
        'ai_provider': getattr(config, 'AI_METADATA_PROVIDER', ''),
        'ai_gemini_api_key': getattr(config, 'AI_GEMINI_API_KEY', ''),
        'ai_gemini_model': '',
        'ai_gemini_project_id': '',
        'ai_openai_api_key': getattr(config, 'AI_OPENAI_API_KEY', ''),
        'ai_openai_model': '',
        'ai_claude_api_key': getattr(config, 'AI_CLAUDE_API_KEY', ''),
        'ai_claude_model': '',
        'steam_api_key': '',
        'steam_id': '',
        'xbox_client_id': '',
        'xbox_client_secret': '',
    }
    
    try:
        if os.path.exists(SCRAPER_SETTINGS_FILE):
            with open(SCRAPER_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                if 'api_keys' in settings:
                    # Override with saved keys (only if not empty)
                    for key, value in settings['api_keys'].items():
                        if value:  # Only override if value is not empty
                            keys[key] = value
    except Exception as e:
        logger.warning(f"Could not load saved API keys: {e}")
    
    return keys


# =============================================================================
# ROUTES
# =============================================================================

@scraper_bp.route('/api/scraper-settings', methods=['GET'])
@admin_required
def api_get_scraper_settings():
    """Get scraper priority and settings"""
    try:
        if os.path.exists(SCRAPER_SETTINGS_FILE):
            with open(SCRAPER_SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                
                # Ensure all scrapers are in the settings (for backwards compatibility)
                # Add screenscraper if missing
                if 'screenscraper' not in settings.get('enabled', {}):
                    settings.setdefault('enabled', {})['screenscraper'] = False
                if 'screenscraper' not in settings.get('priority', []):
                    settings.setdefault('priority', []).append('screenscraper')
                
                # Add RAWG if missing (for older settings files)
                if 'rawg' not in settings.get('enabled', {}):
                    settings.setdefault('enabled', {})['rawg'] = config.SCRAPER_RAWG_ENABLED
                if 'rawg' not in settings.get('priority', []):
                    # Insert RAWG before screenscraper if possible
                    priority = settings.get('priority', [])
                    if 'screenscraper' in priority:
                        idx = priority.index('screenscraper')
                        priority.insert(idx, 'rawg')
                    else:
                        priority.append('rawg')
                    settings['priority'] = priority

                # Add AI if missing (for older settings files)
                if 'ai' not in settings.get('enabled', {}):
                    settings.setdefault('enabled', {})['ai'] = False
                if 'ai' not in settings.get('priority', []):
                    settings.get('priority', []).append('ai')

                # Pass 26.5 — mask secret API keys before returning.
                if isinstance(settings.get('api_keys'), dict):
                    settings['api_keys'] = mask_api_keys_for_response(settings['api_keys'])

                return jsonify(settings)
        else:
            # Return defaults
            return jsonify({
                'priority': ['esde', 'tgdb', 'igdb', 'rawg', 'screenscraper'],
                'enabled': {
                    'esde': config.SCRAPER_ESDE_ENABLED,
                    'tgdb': config.SCRAPER_TGDB_ENABLED,
                    'igdb': config.SCRAPER_IGDB_ENABLED,
                    'rawg': config.SCRAPER_RAWG_ENABLED,
                    'screenscraper': getattr(config, 'SCRAPER_SCREENSCRAPER_ENABLED', False)
                }
            })
    except Exception as e:
        logger.error(f"Error loading scraper settings: {e}")
        return jsonify({'error': 'An internal error occurred'}), 500


@scraper_bp.route('/api/scraper-settings', methods=['POST'])
@admin_required
@handle_api_errors
def api_save_scraper_settings():
    """Save scraper priority and settings"""
    data = request.get_json()

    # Pass 45.11 — every persisted key validated against an allowlist; rejects
    # malformed shapes (string instead of bool, bogus scraper names, etc.) that
    # would otherwise crash scraper_manager on next call.
    ok, reason, data = validate_scraper_settings(data)
    if not ok:
        return jsonify({'success': False, 'error': f'invalid scraper settings: {reason}'}), 400

    # Ensure data directory exists
    os.makedirs(os.path.dirname(SCRAPER_SETTINGS_FILE), exist_ok=True)

    # Load existing settings to preserve API keys
    existing = {}
    if os.path.exists(SCRAPER_SETTINGS_FILE):
        with open(SCRAPER_SETTINGS_FILE, 'r') as f:
            existing = json.load(f)

    # Merge new settings with existing (preserve api_keys if not in new data)
    if 'api_keys' in existing and 'api_keys' not in data:
        data['api_keys'] = existing['api_keys']

    # Preserve match filtering settings if not in new data
    for key in ('minimum_match_score', 'match_mode', 'match_criteria'):
        if key in existing and key not in data:
            data[key] = existing[key]

    # Save to file
    atomic_write_json(SCRAPER_SETTINGS_FILE, data)

    logger.info(f"Saved scraper settings: priority={data.get('priority')}, enabled={data.get('enabled')}")

    return jsonify({'success': True, 'message': 'Settings saved'})


@scraper_bp.route('/api/scraper-api-keys', methods=['POST'])
@admin_required
@handle_api_errors
def api_save_api_keys():
    """Save scraper API keys"""
    data = request.get_json()

    # Ensure data directory exists
    os.makedirs(os.path.dirname(SCRAPER_SETTINGS_FILE), exist_ok=True)

    # Load existing settings
    existing = {}
    if os.path.exists(SCRAPER_SETTINGS_FILE):
        with open(SCRAPER_SETTINGS_FILE, 'r') as f:
            existing = json.load(f)

    # Pass 26.5 — for every secret field, treat `***<anything>` as "unchanged"
    # and keep the stored value. The frontend sends the masked display value
    # back on save when the user didn't retype the key.
    prior_keys = existing.get('api_keys', {}) if isinstance(existing.get('api_keys'), dict) else {}
    if isinstance(data, dict):
        for field in SECRET_API_KEY_FIELDS:
            if field in data and is_masked_sentinel(data[field]):
                data[field] = prior_keys.get(field, '')

    # Pass 45.11 — every field allowlisted; values type-checked. Runs AFTER
    # masked-sentinel substitution so the cleaned data round-trips even if the
    # frontend echoes the *** display value.
    ok, reason, data = validate_scraper_api_keys(data)
    if not ok:
        return jsonify({'success': False, 'error': f'invalid api keys: {reason}'}), 400

    # Update API keys
    existing['api_keys'] = data

    # Save to file
    atomic_write_json(SCRAPER_SETTINGS_FILE, existing)

    logger.info(f"Saved API keys for scrapers")

    return jsonify({'success': True, 'message': 'API keys saved'})


@scraper_bp.route('/api/check-scraper/<scraper>')
@admin_required
def api_check_scraper(scraper):
    """Check if a scraper API is online"""
    # Get API keys from saved settings
    api_keys = get_saved_api_keys()
    
    try:
        timeout = 5
        
        if scraper == 'tgdb':
            # Check TheGamesDB — try public key first (per-IP), fall back to private (monthly pool)
            tgdb_public = api_keys.get('tgdb_public', '') or getattr(config, 'THEGAMESDB_PUBLIC_API_KEY', '')
            tgdb_private = api_keys.get('tgdb') or getattr(config, 'THEGAMESDB_API_KEY', '')

            keys_to_try = []
            if tgdb_public:
                keys_to_try.append(('public', tgdb_public))
            if tgdb_private:
                keys_to_try.append(('private', tgdb_private))

            if not keys_to_try:
                return jsonify({'online': False, 'scraper': scraper, 'reason': 'No API key'})

            last_error = 'Connection error'
            for key_type, key in keys_to_try:
                try:
                    url = f'https://api.thegamesdb.net/v1/Platforms?apikey={key}'
                    req = urllib.request.Request(url, headers={'User-Agent': 'RetroDB/1.0'})
                    response = urllib.request.urlopen(req, timeout=timeout)
                    result = {'online': True, 'scraper': scraper}
                    if key_type == 'private' and tgdb_public:
                        result['note'] = 'Public key failed, using private key'
                    return jsonify(result)
                except urllib.error.HTTPError as e:
                    if e.code in (403, 429):
                        logger.warning(f"TGDB {key_type} key returned {e.code}, trying next...")
                        last_error = f'{key_type.title()} key: monthly limit reached or invalid'
                        continue
                    # Non-403/429 error — read the response body for details
                    error_reason = f'HTTP {e.code}'
                    try:
                        error_body = e.read().decode('utf-8')
                        error_data = json.loads(error_body)
                        if 'message' in error_data:
                            error_reason = error_data['message']
                        elif 'error' in error_data:
                            error_reason = error_data['error']
                        elif 'status' in error_data:
                            error_reason = error_data['status']
                    except (ValueError, KeyError, OSError):
                        if e.code == 401:
                            error_reason = 'Invalid API key'
                    last_error = error_reason
                except Exception as e:
                    logger.error(f"TGDB check error ({key_type}): {e}")
                    last_error = 'Connection error'

            return jsonify({'online': False, 'scraper': scraper, 'reason': last_error})
                
        elif scraper == 'igdb':
            # Check IGDB (need to check if we have credentials)
            client_id = api_keys.get('igdb_client_id', '')
            client_secret = api_keys.get('igdb_client_secret', '')
            
            if client_id and client_secret:
                # Try to get a token
                try:
                    url = f'https://id.twitch.tv/oauth2/token?client_id={client_id}&client_secret={client_secret}&grant_type=client_credentials'
                    req = urllib.request.Request(url, method='POST', headers={'User-Agent': 'RetroDB/1.0'})
                    response = urllib.request.urlopen(req, timeout=timeout)
                    return jsonify({'online': True, 'scraper': scraper})
                except urllib.error.HTTPError as e:
                    # Try to read the actual error message from response body
                    error_reason = f'HTTP {e.code}'
                    try:
                        error_body = e.read().decode('utf-8')
                        error_data = json.loads(error_body)
                        if 'message' in error_data:
                            error_reason = error_data['message']
                        elif 'error' in error_data:
                            error_reason = error_data['error']
                    except (ValueError, KeyError, OSError):
                        if e.code == 401:
                            error_reason = 'Invalid client ID or secret'
                        elif e.code == 403:
                            error_reason = 'Access forbidden'
                    return jsonify({'online': False, 'scraper': scraper, 'reason': error_reason})
                except Exception as e:
                    logger.error(f"IGDB check error: {e}")
                    return jsonify({'online': False, 'scraper': scraper, 'reason': 'Connection error'})
            else:
                return jsonify({'online': False, 'scraper': scraper, 'reason': 'No credentials'})
                
        elif scraper == 'rawg':
            # Check RAWG.io
            rawg_key = api_keys.get('rawg', '') or api_keys.get('rawg_api_key', '')
            if rawg_key:
                try:
                    url = f'https://api.rawg.io/api/games?key={rawg_key}&page_size=1'
                    req = urllib.request.Request(url, headers={'User-Agent': 'RetroDB/1.0'})
                    response = urllib.request.urlopen(req, timeout=timeout)
                    data = response.read().decode('utf-8')
                    # Check if we got a valid response (should have "results" array)
                    if '"results"' in data:
                        return jsonify({'online': True, 'scraper': scraper})
                    else:
                        # Check if response contains an error message
                        try:
                            json_data = json.loads(data)
                            if 'error' in json_data:
                                return jsonify({'online': False, 'scraper': scraper, 'reason': json_data['error']})
                            elif 'detail' in json_data:
                                return jsonify({'online': False, 'scraper': scraper, 'reason': json_data['detail']})
                        except (ValueError, KeyError):
                            pass
                        return jsonify({'online': False, 'scraper': scraper, 'reason': 'Invalid response'})
                except urllib.error.HTTPError as e:
                    # Try to read the actual error message from response body
                    error_reason = f'HTTP {e.code}'
                    try:
                        error_body = e.read().decode('utf-8')
                        error_data = json.loads(error_body)
                        # RAWG returns error messages in 'error' or 'detail' field
                        if 'error' in error_data:
                            error_reason = error_data['error']
                        elif 'detail' in error_data:
                            error_reason = error_data['detail']
                    except (ValueError, KeyError, OSError):
                        # Fallback to generic messages based on status code
                        if e.code == 401:
                            error_reason = 'Invalid API key'
                        elif e.code == 403:
                            error_reason = 'Access forbidden'
                        elif e.code == 429:
                            error_reason = 'Rate limit exceeded'
                    return jsonify({'online': False, 'scraper': scraper, 'reason': error_reason})
                except Exception as e:
                    logger.error(f"RAWG check error: {e}")
                    return jsonify({'online': False, 'scraper': scraper, 'reason': 'Connection error'})
            else:
                return jsonify({'online': False, 'scraper': scraper, 'reason': 'No API key'})
        
        elif scraper == 'screenscraper':
            # Check ScreenScraper - needs longer timeout as their API can be slow
            ss_username = api_keys.get('screenscraper_username', '')
            ss_password = api_keys.get('screenscraper_password', '')
            ss_devid = api_keys.get('screenscraper_devid', '')
            ss_devpassword = api_keys.get('screenscraper_devpassword', '')
            
            # Pass 33.11: downgrade username/devid to DEBUG; INFO only sees
            # booleans so routine check output never holds the raw credentials.
            logger.debug(
                f"ScreenScraper check - username: {ss_username}, "
                f"has_password: {bool(ss_password)}, devid: {ss_devid}, "
                f"has_devpass: {bool(ss_devpassword)}"
            )
            logger.info(
                "ScreenScraper check configured: "
                f"has_username={bool(ss_username)}, has_password={bool(ss_password)}, "
                f"has_devid={bool(ss_devid)}, has_devpass={bool(ss_devpassword)}"
            )
            
            if ss_username and ss_password:
                try:
                    # Build params with correct order - devid/devpassword BEFORE ssid/sspassword
                    params = []
                    if ss_devid and ss_devpassword:
                        params.append(('devid', ss_devid))
                        params.append(('devpassword', ss_devpassword))
                    params.extend([
                        ('softname', 'RetroDB'),
                        ('output', 'json'),
                        ('ssid', ss_username),
                        ('sspassword', ss_password)
                    ])
                    
                    url = 'https://api.screenscraper.fr/api2/ssuserInfos.php'
                    # Pass 33.11: raw devid is credential material.
                    logger.debug(f"ScreenScraper checking with devid={ss_devid}")

                    # Use requests library with 30 second timeout
                    response = requests.get(url, params=params, timeout=30, headers={'User-Agent': 'RetroDB/1.0'})
                    data = response.text

                    # Pass 33.11: the check endpoint's upstream response body can
                    # contain the logged-in user's ssid / session envelope. Log
                    # only the status code at INFO; body preview stays at DEBUG.
                    logger.info(f"ScreenScraper response status: {response.status_code}")
                    logger.debug(f"ScreenScraper response (first 300 chars): {data[:300]}")
                    
                    if response.status_code == 200:
                        if '"ssuser"' in data or '"success": "true"' in data or '"success":"true"' in data:
                            return jsonify({'online': True, 'scraper': scraper})
                        elif 'Erreur de login' in data or 'login' in data.lower():
                            return jsonify({'online': False, 'scraper': scraper, 'reason': 'Invalid credentials'})
                        else:
                            return jsonify({'online': False, 'scraper': scraper, 'reason': 'Unknown response'})
                    elif response.status_code == 403:
                        return jsonify({'online': False, 'scraper': scraper, 'reason': 'Access denied - check dev credentials'})
                    else:
                        return jsonify({'online': False, 'scraper': scraper, 'reason': f'HTTP {response.status_code}'})
                        
                except requests.exceptions.Timeout:
                    logger.error("ScreenScraper timeout after 30 seconds")
                    return jsonify({'online': False, 'scraper': scraper, 'reason': 'Timeout - API may be slow'})
                except requests.exceptions.ConnectionError as e:
                    logger.error(f"ScreenScraper connection error: {e}")
                    return jsonify({'online': False, 'scraper': scraper, 'reason': 'Connection failed'})
                except Exception as e:
                    logger.error(f"ScreenScraper check error: {type(e).__name__}: {e}")
                    return jsonify({'online': False, 'scraper': scraper, 'reason': f'Error: {type(e).__name__}'})
            else:
                return jsonify({'online': False, 'scraper': scraper, 'reason': 'No credentials'})
        
        elif scraper == 'ai':
            # Check AI metadata provider
            try:
                from scraper.scrape_ai import check_api_status as check_ai_status
                result = check_ai_status()
                return jsonify({
                    'online': result.get('online', False),
                    'scraper': scraper,
                    'reason': result.get('reason', ''),
                    'provider': result.get('provider', ''),
                    'model': result.get('model', '')
                })
            except ImportError:
                return jsonify({'online': False, 'scraper': scraper, 'reason': 'AI module not available'})
            except Exception as e:
                logger.error(f"AI check error: {e}")
                return jsonify({'online': False, 'scraper': scraper, 'reason': 'Connection error'})

        else:
            return jsonify({'online': False, 'scraper': scraper, 'reason': 'Unknown scraper'})

    except Exception as e:
        logger.error(f"Error checking scraper {scraper}: {e}")
        return jsonify({'online': False, 'scraper': scraper, 'error': 'An internal error occurred'})


@scraper_bp.route('/api/scraper-allowance/<scraper>')
@admin_required
def api_scraper_allowance(scraper):
    """
    Check rate limit allowance for scrapers that support it.
    
    TGDB returns: remaining_monthly_allowance, extra_allowance, allowance_refresh_timer
    ScreenScraper returns: maxrequestsperday, requeststoday, maxrequestspermin, etc.
    """
    api_keys = get_saved_api_keys()
    
    try:
        if scraper == 'tgdb':
            tgdb_private = api_keys.get('tgdb') or getattr(config, 'THEGAMESDB_API_KEY', '')
            tgdb_public = api_keys.get('tgdb_public', '') or getattr(config, 'THEGAMESDB_PUBLIC_API_KEY', '')

            if not tgdb_private and not tgdb_public:
                return jsonify({'success': False, 'error': 'No TGDB API key configured'})

            result = {
                'success': True,
                'scraper': 'tgdb',
                'public_key_configured': bool(tgdb_public),
                'private_key_configured': bool(tgdb_private),
            }

            # Check private key allowance (only private key has a trackable monthly pool)
            # TGDB appends allowance data to every API response, even on 403/429
            if tgdb_private:
                try:
                    url = f'https://api.thegamesdb.net/v1/Platforms?apikey={tgdb_private}'
                    r = requests.get(url, timeout=10)

                    # Try to parse allowance data from response body regardless of status code
                    data = None
                    try:
                        data = r.json()
                    except (ValueError, json.JSONDecodeError):
                        pass

                    if data and data.get('remaining_monthly_allowance') is not None:
                        refresh_timer = data.get('allowance_refresh_timer')

                        reset_date = None
                        if refresh_timer is not None:
                            try:
                                secs = int(refresh_timer)
                                if secs > 0:
                                    reset_dt = datetime.now(timezone.utc) + timedelta(seconds=secs)
                                    reset_date = reset_dt.strftime('%Y-%m-%d %H:%M UTC')
                            except (ValueError, TypeError):
                                pass

                        if not reset_date:
                            now = datetime.now(timezone.utc)
                            if now.month == 12:
                                reset_dt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                            else:
                                reset_dt = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
                            reset_date = reset_dt.strftime('%Y-%m-%d %H:%M UTC')

                        result['remaining_monthly'] = data.get('remaining_monthly_allowance', 'Unknown')
                        result['extra_allowance'] = data.get('extra_allowance', 0)
                        result['refresh_timer'] = refresh_timer if refresh_timer else 'Unknown'
                        result['reset_date'] = reset_date
                        result['raw'] = {
                            'remaining_monthly_allowance': data.get('remaining_monthly_allowance'),
                            'extra_allowance': data.get('extra_allowance'),
                            'allowance_refresh_timer': data.get('allowance_refresh_timer')
                        }
                    elif r.status_code in (403, 429):
                        result['remaining_monthly'] = 0
                        result['private_key_error'] = 'Monthly allowance exceeded'
                    elif r.status_code != 200:
                        result['private_key_error'] = f'HTTP {r.status_code}'
                except Exception as e:
                    logger.error(f"TGDB private key allowance check error: {e}")
                    result['private_key_error'] = 'Connection error'

            # Check public key allowance (TGDB appends allowance data to every response)
            if tgdb_public:
                try:
                    url = f'https://api.thegamesdb.net/v1/Platforms?apikey={tgdb_public}'
                    r = requests.get(url, timeout=10)

                    # Try to parse allowance data from response body regardless of status code
                    pub_data = None
                    try:
                        pub_data = r.json()
                    except (ValueError, json.JSONDecodeError):
                        pass

                    if pub_data and pub_data.get('remaining_monthly_allowance') is not None:
                        result['public_key_status'] = 'active'
                        result['public_remaining_monthly'] = pub_data.get('remaining_monthly_allowance')
                        result['public_extra_allowance'] = pub_data.get('extra_allowance', 0)
                        pub_refresh = pub_data.get('allowance_refresh_timer')
                        if pub_refresh is not None:
                            try:
                                secs = int(pub_refresh)
                                if secs > 0:
                                    reset_dt = datetime.now(timezone.utc) + timedelta(seconds=secs)
                                    result['public_reset_date'] = reset_dt.strftime('%Y-%m-%d %H:%M UTC')
                            except (ValueError, TypeError):
                                pass
                    elif r.status_code in (403, 429):
                        result['public_key_status'] = 'exhausted'
                        result['public_remaining_monthly'] = 0
                    elif r.status_code == 200:
                        result['public_key_status'] = 'active'
                    else:
                        result['public_key_status'] = f'HTTP {r.status_code}'
                except (requests.RequestException, OSError):
                    result['public_key_status'] = 'error'

            return jsonify(result)
        
        elif scraper == 'screenscraper':
            ss_username = api_keys.get('screenscraper_username', '')
            ss_password = api_keys.get('screenscraper_password', '')
            ss_devid = api_keys.get('screenscraper_devid', '')
            ss_devpassword = api_keys.get('screenscraper_devpassword', '')
            
            if not ss_username or not ss_password:
                return jsonify({'success': False, 'error': 'No ScreenScraper credentials configured'})
            
            # ScreenScraper ssuserInfos.php endpoint returns quota info
            params = []
            if ss_devid and ss_devpassword:
                params.append(('devid', ss_devid))
                params.append(('devpassword', ss_devpassword))
            params.extend([
                ('softname', 'RetroDB'),
                ('output', 'json'),
                ('ssid', ss_username),
                ('sspassword', ss_password)
            ])
            
            url = 'https://api.screenscraper.fr/api2/ssuserInfos.php'
            r = requests.get(url, params=params, timeout=30)  # Increased timeout - SS can be slow
            
            if r.status_code == 200:
                try:
                    data = r.json()
                    user_data = data.get('response', {}).get('ssuser', {})
                    if not user_data:
                        # Try alternate response format
                        user_data = data.get('ssuser', {})
                    return jsonify({
                        'success': True,
                        'scraper': 'screenscraper',
                        'max_requests_per_day': user_data.get('maxrequestsperday', 'Unknown'),
                        'requests_today': user_data.get('requeststoday', 0),
                        'max_requests_per_min': user_data.get('maxrequestspermin', 'Unknown'),
                        'max_download_speed': user_data.get('maxdownloadspeed', 'Unknown'),
                        'max_threads': user_data.get('maxthreads', 'Unknown'),
                        'user_level': user_data.get('niveau', 'Unknown'),
                        'contribution': user_data.get('contribution', 'Unknown'),
                        'raw': user_data
                    })
                except json.JSONDecodeError:
                    return jsonify({'success': False, 'error': 'Invalid JSON response from ScreenScraper'})
                except Exception as e:
                    logger.error(f"Error parsing ScreenScraper response: {e}")
                    return jsonify({'success': False, 'error': 'Error parsing API response'})
            else:
                return jsonify({'success': False, 'error': f'HTTP {r.status_code}'})
        
        elif scraper == 'igdb':
            # IGDB doesn't have a public rate limit endpoint
            # But we can report that it uses OAuth tokens which have their own limits
            return jsonify({
                'success': True,
                'scraper': 'igdb',
                'note': 'IGDB uses Twitch OAuth tokens. Rate limits are typically 4 requests/second.',
                'limit_type': 'requests_per_second',
                'limit': 4
            })

        elif scraper == 'rawg':
            rawg_key = api_keys.get('rawg', '') or api_keys.get('rawg_api_key', '') or getattr(config, 'RAWG_API_KEY', '')
            if not rawg_key:
                return jsonify({'success': False, 'error': 'No RAWG API key configured'})

            # Make a lightweight API call to check for rate limit headers
            try:
                r = requests.get(f'https://api.rawg.io/api/games?key={rawg_key}&page_size=1', timeout=10)
                headers = r.headers

                # Monthly reset: 1st of next month
                now = datetime.now(timezone.utc)
                if now.month == 12:
                    reset_dt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    reset_dt = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
                reset_date = reset_dt.strftime('%Y-%m-%d %H:%M UTC')

                result = {
                    'success': True,
                    'scraper': 'rawg',
                    'limit_type': 'requests_per_month',
                    'limit': 20000,
                    'reset_date': reset_date,
                }

                # Check for standard rate limit headers
                remaining = headers.get('X-RateLimit-Remaining') or headers.get('x-ratelimit-remaining')
                limit = headers.get('X-RateLimit-Limit') or headers.get('x-ratelimit-limit')
                if remaining is not None:
                    result['remaining'] = int(remaining)
                if limit is not None:
                    result['limit'] = int(limit)

                return jsonify(result)
            except (requests.RequestException, OSError, ValueError):
                # Fallback to static info if API call fails
                now = datetime.now(timezone.utc)
                if now.month == 12:
                    reset_dt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
                else:
                    reset_dt = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
                return jsonify({
                    'success': True,
                    'scraper': 'rawg',
                    'limit_type': 'requests_per_month',
                    'limit': 20000,
                    'reset_date': reset_dt.strftime('%Y-%m-%d %H:%M UTC'),
                })

        elif scraper == 'retroachievements':
            return jsonify({
                'success': True,
                'scraper': 'retroachievements',
                'note': 'RetroAchievements does not publish rate limits.',
                'limit_type': 'unknown'
            })

        elif scraper == 'ai':
            # Check AI provider rate limits by making a minimal API call
            # and reading rate limit headers from the response
            from scraper.scrape_ai import _get_active_provider, PROVIDERS
            provider_config = _get_active_provider()
            if not provider_config:
                return jsonify({'success': False, 'error': 'No AI provider configured'})

            provider = provider_config['provider']
            api_key = provider_config['api_key']
            model = provider_config['model']
            provider_name = PROVIDERS.get(provider, {}).get('name', provider)
            test_prompt = 'Return this exact JSON: {"status": "ok"}'

            try:
                response = None
                if provider == 'gemini':
                    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
                    payload = {
                        'contents': [{'parts': [{'text': test_prompt}]}],
                        'generationConfig': {'maxOutputTokens': 20}
                    }
                    gemini_headers = {'Content-Type': 'application/json'}
                    project_id = provider_config.get('project_id', '')
                    if project_id:
                        gemini_headers['x-goog-user-project'] = project_id
                    response = requests.post(url, json=payload,
                                             headers=gemini_headers, timeout=15)
                elif provider == 'openai':
                    url = 'https://api.openai.com/v1/chat/completions'
                    payload = {
                        'model': model,
                        'messages': [{'role': 'user', 'content': test_prompt}],
                        'max_tokens': 20,
                    }
                    response = requests.post(url, json=payload, headers={
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {api_key}',
                    }, timeout=15)
                elif provider == 'claude':
                    url = 'https://api.anthropic.com/v1/messages'
                    payload = {
                        'model': model,
                        'max_tokens': 20,
                        'messages': [{'role': 'user', 'content': test_prompt}],
                    }
                    response = requests.post(url, json=payload, headers={
                        'Content-Type': 'application/json',
                        'x-api-key': api_key,
                        'anthropic-version': '2023-06-01',
                    }, timeout=15)
                else:
                    return jsonify({'success': False, 'error': f'Unknown AI provider: {provider}'})

                if response is None:
                    return jsonify({'success': False, 'error': 'No response from AI provider'})

                h = response.headers
                result = {
                    'success': True,
                    'scraper': 'ai',
                    'provider': provider_name,
                    'model': model,
                }

                # Extract rate limit headers (provider-specific)
                if provider == 'claude':
                    # Anthropic headers: anthropic-ratelimit-requests-limit, -remaining, -reset
                    #                    anthropic-ratelimit-tokens-limit, -remaining, -reset
                    #                    anthropic-ratelimit-input-tokens-limit, -remaining, -reset
                    req_limit = h.get('anthropic-ratelimit-requests-limit')
                    req_remaining = h.get('anthropic-ratelimit-requests-remaining')
                    req_reset = h.get('anthropic-ratelimit-requests-reset')
                    tok_limit = h.get('anthropic-ratelimit-tokens-limit')
                    tok_remaining = h.get('anthropic-ratelimit-tokens-remaining')
                    tok_reset = h.get('anthropic-ratelimit-tokens-reset')
                    input_tok_limit = h.get('anthropic-ratelimit-input-tokens-limit')
                    input_tok_remaining = h.get('anthropic-ratelimit-input-tokens-remaining')

                    if req_limit is not None:
                        result['requests_limit'] = int(req_limit)
                    if req_remaining is not None:
                        result['requests_remaining'] = int(req_remaining)
                    if req_reset:
                        result['requests_reset'] = req_reset
                    if tok_limit is not None:
                        result['tokens_limit'] = int(tok_limit)
                    if tok_remaining is not None:
                        result['tokens_remaining'] = int(tok_remaining)
                    if tok_reset:
                        result['tokens_reset'] = tok_reset
                    if input_tok_limit is not None:
                        result['input_tokens_limit'] = int(input_tok_limit)
                    if input_tok_remaining is not None:
                        result['input_tokens_remaining'] = int(input_tok_remaining)

                elif provider == 'openai':
                    # OpenAI headers: x-ratelimit-limit-requests, x-ratelimit-remaining-requests
                    #                 x-ratelimit-limit-tokens, x-ratelimit-remaining-tokens
                    #                 x-ratelimit-reset-requests, x-ratelimit-reset-tokens
                    req_limit = h.get('x-ratelimit-limit-requests')
                    req_remaining = h.get('x-ratelimit-remaining-requests')
                    req_reset = h.get('x-ratelimit-reset-requests')
                    tok_limit = h.get('x-ratelimit-limit-tokens')
                    tok_remaining = h.get('x-ratelimit-remaining-tokens')
                    tok_reset = h.get('x-ratelimit-reset-tokens')

                    if req_limit is not None:
                        result['requests_limit'] = int(req_limit)
                    if req_remaining is not None:
                        result['requests_remaining'] = int(req_remaining)
                    if req_reset:
                        result['requests_reset'] = req_reset
                    if tok_limit is not None:
                        result['tokens_limit'] = int(tok_limit)
                    if tok_remaining is not None:
                        result['tokens_remaining'] = int(tok_remaining)
                    if tok_reset:
                        result['tokens_reset'] = tok_reset

                elif provider == 'gemini':
                    # Gemini uses standard headers when available
                    req_limit = h.get('x-ratelimit-limit')
                    req_remaining = h.get('x-ratelimit-remaining')
                    req_reset = h.get('x-ratelimit-reset')

                    if req_limit is not None:
                        result['requests_limit'] = int(req_limit)
                    if req_remaining is not None:
                        result['requests_remaining'] = int(req_remaining)
                    if req_reset:
                        result['requests_reset'] = req_reset

                    # Gemini free tier: 15 RPM / 1500 RPD for Flash, 2 RPM / 50 RPD for Pro
                    if not result.get('requests_limit'):
                        if 'flash' in model.lower():
                            result['static_rpm'] = 15
                            result['static_rpd'] = 1500
                        elif 'pro' in model.lower():
                            result['static_rpm'] = 2
                            result['static_rpd'] = 50

                return jsonify(result)

            except (requests.RequestException, OSError, ValueError) as e:
                logger.error(f"AI rate limit check error: {e}")
                return jsonify({'success': False, 'error': f'Connection error: {type(e).__name__}'})

        else:
            return jsonify({'success': False, 'error': f'Allowance check not supported for {scraper}'})
    
    except Exception as e:
        logger.error(f"Error checking allowance for {scraper}: {e}")
        return jsonify({'success': False, 'error': 'An internal error occurred'})
