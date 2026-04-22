# =============================================================================
# RETRODB - Main Flask Application
# =============================================================================
# A retro gaming ROM library manager with web interface
# Features: ROM scanning, metadata scraping, beautiful cyberpunk UI
# =============================================================================

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, g
import sqlite3
import os
import sys
import logging
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, available_timezones

# Prevent decompression bomb attacks from scraped/uploaded images
from PIL import Image
Image.MAX_IMAGE_PIXELS = 25_000_000  # ~25MP, sufficient for boxart/screenshots

# ---------------------------------------------------------------------------
# ROCm GPU environment — MUST be set before any library loads ROCm/MIOpen.
# Overrides gfx1032 (RX 6600-series) to use gfx1030 pre-compiled kernels,
# forces MIOpen algorithm benchmarking, and cleans stale GPU cache.
# ---------------------------------------------------------------------------
if os.path.exists('/dev/kfd'):
    _miopen_cache = os.path.join(os.path.expanduser('~'), '.cache', 'realesrgan', 'miopen')
    os.makedirs(_miopen_cache, exist_ok=True)
    os.environ['HSA_OVERRIDE_GFX_VERSION'] = '10.3.0'
    os.environ['MIOPEN_FIND_MODE'] = '3'
    os.environ['MIOPEN_USER_DB_PATH'] = _miopen_cache
    os.environ['MIOPEN_CUSTOM_CACHE_DIR'] = _miopen_cache
    # Clean stale gfx1032 cache that conflicts with gfx1030 override
    import glob as _glob
    _stale = None
    for _stale in _glob.glob(os.path.join(_miopen_cache, 'gfx1032*')):
        try:
            os.remove(_stale)
        except OSError:
            pass
    del _miopen_cache, _glob, _stale

# Import configuration
import config

# Import settings manager for user-editable settings
import settings_manager

# Import log manager for file-based logging
import log_manager

# Import services layer
from services.database import query, execute
from services.auth import (
    hash_password, get_current_user, get_user_settings,
    has_permission, login_required, admin_required
)
from services.game_utils import (
    get_rating_image_map_js, get_rating_system_names_js,
    get_rating_crossmap_js, RATING_SYSTEM_KEYS,
    RATING_SYSTEMS, RATING_VALUES
)
from services.template_filters import register_filters as _register_template_filters
from services.database_init import init_database, ensure_user_tables
from services.assets import asset_url
from services.analytics import (
    build_analytics_context,
)

# Pre-compute static rating data (derived from constants, never changes)
_RATING_IMG_MAP_JS = get_rating_image_map_js()
_RATING_SYS_NAMES_JS = get_rating_system_names_js()
_RATING_TO_TIER_JS, _TIER_TO_RATING_JS = get_rating_crossmap_js()

# =============================================================================
# FLASK APP INITIALIZATION
# =============================================================================

app = Flask(__name__)
_register_template_filters(app)
# Register asset_url as a Jinja global so it is available in every template
# (including partials rendered without the context processor, e.g. bare
# `jinja_env.get_template(...).render(...)` in tests / tools).
app.jinja_env.globals['asset_url'] = asset_url


def _get_secret_key():
    """Get or generate a persistent secret key for Flask sessions.

    Priority: RETRODB_SECRET_KEY env var > data/.secret_key file > auto-generated.
    """
    # Check environment variable first (useful for Docker deployments)
    env_key = os.environ.get('RETRODB_SECRET_KEY')
    if env_key:
        return env_key

    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', '.secret_key')
    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    try:
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                key = f.read().strip()
                if key:
                    return key
    except OSError:
        pass
    # Generate new key
    key = secrets.token_hex(32)
    try:
        with open(key_path, 'w') as f:
            f.write(key)
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return key


app.secret_key = _get_secret_key()

# Session cookie hardening
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Operators fronting RetroDB with a TLS reverse proxy should set
# RETRODB_SECURE_COOKIES=true so the browser drops the session cookie on
# any plain-HTTP request. Default off: on a localhost HTTP deploy the flag
# would silently break login (browser refuses to send the cookie).
app.config['SESSION_COOKIE_SECURE'] = (
    os.environ.get('RETRODB_SECURE_COOKIES', '').lower() in ('true', '1', 'yes')
)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# =============================================================================
# RATE LIMITING
# =============================================================================

try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],  # No global default — only apply per-route
        storage_uri="memory://",
    )
except ImportError:
    limiter = None

# =============================================================================
# REGISTER BLUEPRINTS
# =============================================================================

# Original blueprints
from routes.auth import bp as auth_bp
from routes.trophies import bp as trophies_bp
from routes.achievements import bp as achievements_bp
from routes.tools import tools_bp
from routes.reports import reports_bp
from routes.scraper import scraper_bp

app.register_blueprint(auth_bp)
app.register_blueprint(trophies_bp)
app.register_blueprint(achievements_bp)
app.register_blueprint(tools_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(scraper_bp)

# New extracted blueprints
from routes.clz_import import bp as clz_import_bp
from routes.controllers import bp as controllers_bp
from routes.bonus_discs import bp as bonus_discs_bp
from routes.settings import bp as settings_bp
from routes.systems import bp as systems_bp
from routes.games import bp as games_bp
from routes.games_hltb import bp as games_hltb_bp
from routes.games_ai import bp as games_ai_bp
from routes.games_search import bp as games_search_bp
from routes.games_media import bp as games_media_bp
from routes.maintenance import bp as maintenance_bp
from routes.bulk_scrape import bp as bulk_scrape_bp
from routes.ra_sync import bp as ra_sync_bp
from routes.scrape_logs import logs_bp
from routes.collections import bp as collections_bp
from routes.collector_trophies import bp as collector_trophies_bp
from routes.museum import bp as museum_bp
from routes.platform_import import bp as platform_import_bp
from routes.steam_achievements import bp as steam_achievements_bp
from routes.xbox_achievements import bp as xbox_achievements_bp
from routes.game_imports import bp as game_imports_bp

app.register_blueprint(clz_import_bp)
app.register_blueprint(controllers_bp)
app.register_blueprint(bonus_discs_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(systems_bp)
app.register_blueprint(games_bp)
app.register_blueprint(games_hltb_bp)
app.register_blueprint(games_ai_bp)
app.register_blueprint(games_search_bp)
app.register_blueprint(games_media_bp)
app.register_blueprint(maintenance_bp)
app.register_blueprint(bulk_scrape_bp)
app.register_blueprint(ra_sync_bp)
app.register_blueprint(logs_bp)
app.register_blueprint(collections_bp)
app.register_blueprint(collector_trophies_bp)
app.register_blueprint(museum_bp)
app.register_blueprint(platform_import_bp)
app.register_blueprint(steam_achievements_bp)
app.register_blueprint(xbox_achievements_bp)
app.register_blueprint(game_imports_bp)

# =============================================================================
# PER-ROUTE RATE LIMITS (applied after blueprint registration)
# =============================================================================

if limiter:
    # Expensive AI/scraping endpoints
    limiter.limit("10 per minute")(app.view_functions.get('games_ai.api_game_ai_fill', lambda: None))
    limiter.limit("5 per minute")(app.view_functions.get('bulk_scrape.api_bulk_scrape_job_start', lambda: None))
    # Login brute force protection (supplements existing IP-based rate limiting)
    limiter.limit("10 per minute")(app.view_functions.get('auth.api_login', lambda: None))
    # Heavy admin endpoints — on a localhost deploy the realistic risk is
    # the operator double-clicking, not a malicious DoS, but matching the
    # existing login/bulk-scrape pattern costs nothing.
    limiter.limit("2 per minute")(app.view_functions.get('maintenance.api_restart', lambda: None))
    limiter.limit("3 per minute")(app.view_functions.get('maintenance.api_scan', lambda: None))
    limiter.limit("3 per minute")(app.view_functions.get('maintenance.api_database_optimize', lambda: None))
    limiter.limit("3 per minute")(app.view_functions.get('maintenance.api_image_resize_start', lambda: None))
    limiter.limit("3 per minute")(app.view_functions.get('settings.api_backup', lambda: None))

# =============================================================================
# REQUEST-SCOPED DB CONNECTION CLEANUP
# =============================================================================

@app.teardown_appcontext
def close_request_db(exception):
    """Close the request-scoped database connection if one was opened."""
    db = g.pop('db', None)
    if db is not None:
        try:
            db.execute("PRAGMA optimize")
        except Exception:
            pass
        db.close()


# =============================================================================
# SECURITY HEADERS
# =============================================================================

@app.after_request
def set_security_headers(response):
    """Add security headers to every response"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


# =============================================================================
# GLOBAL ERROR HANDLERS
# =============================================================================

@app.errorhandler(404)
def handle_not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return render_template('base.html'), 404

@app.errorhandler(500)
def handle_internal_error(e):
    logger.error(f"Internal server error: {e}")
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
    return render_template('base.html'), 500


# =============================================================================
# USER SESSION SETUP
# =============================================================================

@app.before_request
def load_user():
    """Load current user before each request"""
    g.user = get_current_user()
    if g.user:
        g.user_settings = get_user_settings(g.user['id'])
    else:
        g.user_settings = None

    # Ensure a CSRF token exists in the session
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)


@app.before_request
def validate_csrf():
    """Validate CSRF token on state-changing requests.

    Checks the X-CSRF-Token header against the session token for POST/PUT/DELETE.
    Exempt: login, setup, static files, and GET/HEAD/OPTIONS requests.
    """
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    if not request.endpoint:
        return

    # Exempt endpoints that must work without a CSRF token
    csrf_exempt = {
        'static', 'auth.api_login', 'auth.login', 'setup_api',
        'setup_browse_folders',
    }
    if request.endpoint in csrf_exempt:
        return

    # Check X-CSRF-Token header or _csrf_token form field
    session_token = session.get('_csrf_token', '')
    if not session_token:
        return jsonify({'success': False, 'error': 'Invalid or missing CSRF token'}), 403
    token = request.headers.get('X-CSRF-Token', '') or request.form.get('_csrf_token', '')
    if not secrets.compare_digest(token, session_token):
        return jsonify({'success': False, 'error': 'Invalid or missing CSRF token'}), 403


@app.before_request
def check_first_time_setup():
    """Redirect to setup wizard on first launch"""
    # Skip for static files, the setup route itself, and API endpoints used by setup
    if not request.endpoint or request.endpoint in ('static', 'setup_page', 'setup_api',
                                                     'setup_browse_folders',
                                                     'auth.api_login', 'auth.login', 'auth.logout'):
        return
    # Check if setup has been completed
    user_settings = settings_manager.load_settings()
    has_rom_path = bool(user_settings.get('rom_path') or getattr(config, 'ROM_PATH', ''))
    setup_done = user_settings.get('setup_completed', False)
    if not setup_done and not has_rom_path:
        return redirect(url_for('setup_page'))


@app.before_request
def check_force_password_change():
    """Redirect admin users who must change their default password"""
    if not g.get('user'):
        return
    if not g.user.get('force_password_change'):
        return
    # Allow access to password change endpoint, logout, static, and setup
    allowed_endpoints = ('auth.api_change_password', 'auth.api_force_change_password',
                         'auth.logout', 'static', 'setup_page', 'setup_api')
    if request.endpoint in allowed_endpoints:
        return
    # Return the force change password page
    return render_template('force_change_password.html'), 200



# Get effective paths (settings.json overrides config.py if set)
def get_rom_path():
    return settings_manager.get_effective_path('rom_path', config.ROM_PATH)


def get_esde_gamelists_path():
    return settings_manager.get_effective_path('esde_gamelists_path', getattr(config, 'ESDE_GAMELISTS_PATH', ''))


def get_esde_media_path():
    return settings_manager.get_effective_path('esde_downloaded_media_path', getattr(config, 'ESDE_DOWNLOADED_MEDIA_PATH', ''))


def get_rpcs3_trophy_path():
    return settings_manager.get_effective_path('rpcs3_trophy_path', getattr(config, 'RPCS3_TROPHY_PATH', ''))


# Make config available to templates
app.config['APP_VERSION'] = config.APP_VERSION
app.config['APP_DESCRIPTION'] = config.APP_DESCRIPTION
app.config['ROM_PATH'] = get_rom_path()
app.config['DB_PATH'] = config.DB_PATH
app.config['RPCS3_TROPHY_PATH'] = get_rpcs3_trophy_path()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Install SecretRedactor on the root logger + its basicConfig StreamHandler
# before any module-level logger fires. CategoryFileHandler already attaches
# its own redactor; this adds the console-stream safety net that the
# CategoryFileHandler path cannot cover.
log_manager.install_global_redactor()
logger = logging.getLogger(__name__)

# Waitress logs a WARNING every time a request queues — with a 16-thread pool
# and 20+ parallel XHRs per page load, this fires dozens of times per
# navigation and drowns the actual log. Queueing at depth 1–2 is normal and
# not actionable. Bump the threshold so only sustained back-pressure (ERROR)
# surfaces. See waitress/task.py — "Task queue depth is N" is the message.
logging.getLogger('waitress.queue').setLevel(logging.ERROR)

# =============================================================================
# CATEGORY LOGGING
# =============================================================================

def log_to_category(category, level, message):
    """
    Write log message to category-specific log file.
    Categories: scraping, rom_tools, rom_reports, image_resize, system
    Levels: info, warning, error
    """
    try:
        settings = settings_manager.load_settings()
        log_settings = settings.get('logging', {}).get(category, {})

        # Check if this level is enabled for this category
        if not log_settings.get(level, level == 'error'):
            return

        # Ensure logs directory exists
        logs_dir = os.path.join(os.path.dirname(__file__), 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        # Create log filename with category and date
        today = datetime.now().strftime('%Y-%m-%d')
        log_file = os.path.join(logs_dir, f'{category}_{today}.log')

        # Format log message
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level.upper()}] {message}\n"

        # Append to log file
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)

        # Also log to standard logger for console output
        log_func = getattr(logger, level, logger.info)
        log_func(f"[{category}] {message}")

    except Exception as e:
        # Don't let logging errors break the app
        logger.error(f"Error writing to category log: {e}")


def system_log(level, message):
    """Convenience function for system category logging"""
    log_to_category('system', level, message)


# =============================================================================
# JINJA2 FILTERS — moved to services/template_filters.py
# Registered below after app creation.
# =============================================================================


def get_avatar_url(user, user_settings_row):
    """Get the avatar URL for a user, or None to fall back to role emoji"""
    if not user_settings_row:
        return None
    avatar = user_settings_row.get('avatar', '') if hasattr(user_settings_row, 'get') else (user_settings_row['avatar'] if 'avatar' in user_settings_row.keys() else '')
    if not avatar:
        return None
    if avatar.startswith('default_'):
        return f'/static/images/avatars/{avatar}.svg'
    return f'/static/images/avatars/{avatar}'


@app.context_processor
def inject_config():
    """Make config, user settings, and current user available to all templates"""
    user_settings = settings_manager.load_settings()

    # Get per-user timezone for JS and template use
    user_tz = 'UTC'
    user_settings_obj = g.get('user_settings')
    if user_settings_obj:
        if hasattr(user_settings_obj, 'get'):
            user_tz = user_settings_obj.get('timezone', 'UTC') or 'UTC'
        elif hasattr(user_settings_obj, 'keys') and 'timezone' in user_settings_obj.keys():
            user_tz = user_settings_obj['timezone'] or 'UTC'

    # Check if AI scraper is configured (for showing AI Fill button)
    ai_scraper_enabled = False
    try:
        from routes.scraper import SCRAPER_SETTINGS_FILE as _ssf
        if os.path.exists(_ssf):
            with open(_ssf, 'r') as _f:
                _ss = json.load(_f)
                _ak = _ss.get('api_keys', {})
                _prov = _ak.get('ai_provider', '')
                _key_map = {'gemini': 'ai_gemini_api_key', 'openai': 'ai_openai_api_key', 'claude': 'ai_claude_api_key'}
                ai_scraper_enabled = bool(_prov and _ak.get(_key_map.get(_prov, ''), '') and _ss.get('enabled', {}).get('ai', False))
    except Exception:
        pass  # non-fatal — missing/invalid scraper_settings.json just hides the AI Fill button in the UI

    return {
        'config': config,
        'user_settings': user_settings,
        'current_user': g.get('user'),
        'current_user_settings': g.get('user_settings'),
        'has_permission': has_permission,
        'get_avatar_url': get_avatar_url,
        'asset_url': asset_url,
        'user_timezone': user_tz,
        'csrf_token': session.get('_csrf_token', ''),
        'ai_scraper_enabled': ai_scraper_enabled,
        'rating_image_map_js': _RATING_IMG_MAP_JS,
        'rating_system_names_js': _RATING_SYS_NAMES_JS,
        'rating_system_keys': RATING_SYSTEM_KEYS,
        'rating_to_tier_js': _RATING_TO_TIER_JS,
        'tier_to_rating_js': _TIER_TO_RATING_JS,
        'collector_rank': _get_collector_rank_safe(),
    }


def _get_collector_rank_safe():
    """Return the current collector rank, or a zeroed placeholder if the
    trophies module / table isn't ready yet (e.g. first boot before the
    table has been populated). The sidebar badge reads this on every
    render, so it must never raise."""
    try:
        from routes.collector_trophies import get_current_rank
        return get_current_rank()
    except Exception:
        return None


# =============================================================================
# HELPER FUNCTIONS FOR MAIN PAGES
# =============================================================================

def get_stats():
    """Get library statistics - optimized single query"""
    try:
        stats = query("""
            SELECT
                (SELECT COUNT(*) FROM systems) as total_systems,
                (SELECT COUNT(*) FROM games) as total_games,
                (SELECT COUNT(*) FROM games WHERE scraped = 1) as scraped_games,
                (SELECT SUM(COALESCE(file_size, 0)) FROM games) as total_storage,
                (SELECT COUNT(*) FROM games WHERE completion_status IN ('completed', '100_percent')) as completed_games,
                (SELECT SUM(earned_achievements) FROM game_achievement_progress) as total_earned_achievements,
                (SELECT SUM(total_achievements) FROM game_achievement_progress) as total_available_achievements
        """, one=True)

        total_games = stats['total_games'] or 0
        completed = stats['completed_games'] or 0
        completion_rate = round((completed / total_games * 100) if total_games > 0 else 0, 1)

        # Parse HLTB playtime estimates to get total hours
        total_hltb_hours = 0
        try:
            hltb_rows = query("SELECT playtime_estimate FROM games WHERE playtime_estimate IS NOT NULL AND playtime_estimate != ''")
            for row in hltb_rows:
                est = row.get('playtime_estimate', '')
                if est:
                    # Parse "Main: 25h" or "Main Story: 25½ Hours" patterns
                    match = re.search(r'Main[^:]*:\s*([\d.½]+)', est)
                    if match:
                        val = match.group(1).replace('½', '.5')
                        try:
                            total_hltb_hours += float(val)
                        except ValueError:
                            pass
        except Exception:
            pass

        # Collection health score: weighted average of field completeness
        health_fields = query("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) as has_description,
                SUM(CASE WHEN boxart IS NOT NULL AND boxart != '' THEN 1 ELSE 0 END) as has_boxart,
                SUM(CASE WHEN genre IS NOT NULL AND genre != '' THEN 1 ELSE 0 END) as has_genre,
                SUM(CASE WHEN developer IS NOT NULL AND developer != '' THEN 1 ELSE 0 END) as has_developer,
                SUM(CASE WHEN publisher IS NOT NULL AND publisher != '' THEN 1 ELSE 0 END) as has_publisher,
                SUM(CASE WHEN release_date IS NOT NULL AND release_date != '' THEN 1 ELSE 0 END) as has_release_date,
                SUM(CASE WHEN screenshots IS NOT NULL AND screenshots != '' THEN 1 ELSE 0 END) as has_screenshots,
                SUM(CASE WHEN has_retroachievements = 1 THEN 1 ELSE 0 END) as has_ra
            FROM games
        """, one=True)

        health_score = 0
        if health_fields and health_fields['total'] > 0:
            t = health_fields['total']
            # Weighted: boxart & description more important
            health_score = round((
                (health_fields['has_boxart'] or 0) / t * 25 +
                (health_fields['has_description'] or 0) / t * 25 +
                (health_fields['has_genre'] or 0) / t * 15 +
                (health_fields['has_developer'] or 0) / t * 10 +
                (health_fields['has_publisher'] or 0) / t * 10 +
                (health_fields['has_release_date'] or 0) / t * 10 +
                (health_fields['has_screenshots'] or 0) / t * 5
            ), 1)

        # Per-field health percentages for mini rings
        health_boxart_pct = round((health_fields['has_boxart'] or 0) / t * 100, 1) if health_fields and health_fields['total'] > 0 else 0
        health_desc_pct = round((health_fields['has_description'] or 0) / t * 100, 1) if health_fields and health_fields['total'] > 0 else 0
        health_ra_pct = round((health_fields['has_ra'] or 0) / t * 100, 1) if health_fields and health_fields['total'] > 0 else 0

        return {
            'total_systems': stats['total_systems'],
            'total_games': total_games,
            'scraped_games': stats['scraped_games'],
            'missing_metadata': total_games - (stats['scraped_games'] or 0),
            'total_storage': stats['total_storage'] or 0,
            'completion_rate': completion_rate,
            'completed_games': completed,
            'total_earned_achievements': stats['total_earned_achievements'] or 0,
            'total_available_achievements': stats['total_available_achievements'] or 0,
            'total_hltb_hours': round(total_hltb_hours),
            'health_score': health_score,
            'health_boxart_pct': health_boxart_pct,
            'health_desc_pct': health_desc_pct,
            'health_ra_pct': health_ra_pct,
        }
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return {
            'total_systems': 0,
            'total_games': 0,
            'scraped_games': 0,
            'missing_metadata': 0,
            'total_storage': 0,
            'completion_rate': 0,
            'completed_games': 0,
            'total_earned_achievements': 0,
            'total_available_achievements': 0,
            'total_hltb_hours': 0,
            'health_score': 0,
            'health_boxart_pct': 0,
            'health_desc_pct': 0,
            'health_ra_pct': 0,
        }


def get_api_status():
    """
    Get API status based on configuration only (no network calls).
    Actual online checks are done asynchronously via /api/check-scraper/<scraper> endpoints.
    This makes Dashboard and Settings pages load instantly.
    """
    status = {
        'database': True,  # Always online since we got here
        'esde': True,  # Local filesystem - always available
        'rawg': False,
        'igdb': False,
        'retroachievements': False,
        'screenscraper': False,
        'tgdb': False,
    }

    # Load scraper settings for API keys
    scraper_settings = {}
    settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'scraper_settings.json')
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r') as f:
                scraper_settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    api_keys = scraper_settings.get('api_keys', {})
    enabled = scraper_settings.get('enabled', {})

    # Check if credentials are configured AND scraper is enabled
    # Disabled scrapers are excluded so they don't trigger offline warnings
    # This is instant - no network calls
    tgdb_key = api_keys.get('tgdb') or getattr(config, 'THEGAMESDB_API_KEY', '')
    tgdb_public = api_keys.get('tgdb_public') or getattr(config, 'THEGAMESDB_PUBLIC_API_KEY', '')
    status['tgdb'] = bool((tgdb_key or tgdb_public) and enabled.get('tgdb', True))

    igdb_client = api_keys.get('igdb_client_id') or getattr(config, 'IGDB_CLIENT_ID', '')
    igdb_secret = api_keys.get('igdb_client_secret') or getattr(config, 'IGDB_CLIENT_SECRET', '')
    status['igdb'] = bool(igdb_client and igdb_secret and enabled.get('igdb', True))

    ss_user = api_keys.get('screenscraper_username') or getattr(config, 'SCREENSCRAPER_USERNAME', '')
    ss_pass = api_keys.get('screenscraper_password') or getattr(config, 'SCREENSCRAPER_PASSWORD', '')
    status['screenscraper'] = bool(ss_user and ss_pass and enabled.get('screenscraper', True))

    rawg_key = api_keys.get('rawg') or api_keys.get('rawg_api_key') or getattr(config, 'RAWG_API_KEY', '')
    status['rawg'] = bool(rawg_key and enabled.get('rawg', True))

    ra_key = api_keys.get('ra_apikey') or getattr(config, 'RETROACHIEVEMENTS_API_KEY', '')
    ra_user = api_keys.get('ra_username') or getattr(config, 'RETROACHIEVEMENTS_USERNAME', '')
    status['retroachievements'] = bool(ra_key and ra_user)

    # Track which scrapers are disabled (have keys but user turned them off)
    status['_disabled'] = {
        'tgdb': bool((tgdb_key or tgdb_public) and not enabled.get('tgdb', True)),
        'igdb': bool((igdb_client and igdb_secret) and not enabled.get('igdb', True)),
        'screenscraper': bool((ss_user and ss_pass) and not enabled.get('screenscraper', True)),
        'rawg': bool(rawg_key and not enabled.get('rawg', True)),
    }

    return status


# Manufacturer mapping and size formatting moved to services.formatters
# (see import near top of file)


# =============================================================================
# MAIN PAGE ROUTES
# =============================================================================

@app.route('/')
def index():
    """Redirect to dashboard (or login if not authenticated)"""
    if not g.user:
        return redirect(url_for('auth.login'))
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard page"""
    try:
        stats = get_stats()
        api_status = get_api_status()

        # Get systems with ROM counts, scraped counts, and system_type (limit to 8 for dashboard)
        systems = query("""
            SELECT s.*, COUNT(g.id) AS rom_count,
                   SUM(CASE WHEN g.scraped = 1 THEN 1 ELSE 0 END) AS scraped_count
            FROM systems s
            LEFT JOIN games g ON s.id = g.system_id
            GROUP BY s.id
            HAVING rom_count > 0
            ORDER BY rom_count DESC
            LIMIT 8
        """)

        # Get recent games (recently added) with genre and release date
        recent_games = query("""
            SELECT g.id, g.title, g.boxart, g.boxart_3d, g.scraped,
                   g.genre, g.release_date, g.system_id, s.name AS system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            ORDER BY g.id DESC
            LIMIT 5
        """)

        # Get recently viewed games
        recently_viewed = query("""
            SELECT g.id, g.title, g.boxart, g.boxart_3d, g.system_id,
                   g.completion_status, s.name AS system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.last_viewed IS NOT NULL
            ORDER BY g.last_viewed DESC
            LIMIT 5
        """)

        # Get continue playing games (in-progress)
        continue_playing = query("""
            SELECT g.id, g.title, g.boxart, g.boxart_3d, g.system_id,
                   g.completion_status, g.playtime_estimate,
                   s.name AS system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.completion_status = 'in_progress'
            ORDER BY g.last_viewed DESC
            LIMIT 5
        """)

        # Get recently scraped games (from scrape_history JSON)
        recently_scraped = query("""
            SELECT g.id, g.title, g.boxart, g.boxart_3d, g.scraped,
                   g.scrape_history, g.system_id, s.name AS system_name
            FROM games g
            JOIN systems s ON g.system_id = s.id
            WHERE g.scrape_history IS NOT NULL AND g.scrape_history != '' AND g.scrape_history != '[]'
            ORDER BY g.id DESC
            LIMIT 20
        """)
        # Sort by most recent scrape timestamp from history JSON
        scraped_with_dates = []
        for game in recently_scraped:
            try:
                history = json.loads(game.get('scrape_history', '[]'))
                if history:
                    last_entry = history[-1] if isinstance(history, list) else history
                    ts = last_entry.get('timestamp', last_entry.get('date', ''))
                    scraped_with_dates.append((ts, game))
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
        scraped_with_dates.sort(key=lambda x: x[0], reverse=True)
        recently_scraped = [g for _, g in scraped_with_dates[:5]]

        # Check for offline configured APIs (for warning banner)
        api_warning = False
        for key in ['rawg', 'igdb', 'screenscraper', 'tgdb']:
            if api_status.get(key):
                api_warning = True  # At least one configured; JS will check online status
                break

        # Check for recoverable (interrupted/queued) jobs
        from services.jobs.base import get_recoverable_jobs
        raw_recoverable = get_recoverable_jobs()
        recoverable_jobs = []
        for rj in raw_recoverable:
            params = rj.get('params', {})
            progress = rj.get('progress', {})
            jtype = rj['job_type']
            status = rj['status']

            # Determine if this job had real progress (interrupted mid-run)
            # vs was just queued (no work done yet)
            has_progress = progress.get('current', 0) > 0

            # Build human-readable description
            if jtype == 'bulk_scrape':
                sys_name = params.get('system_name', 'Unknown')
                if has_progress:
                    current = progress.get('current', 0)
                    total = progress.get('total', params.get('game_count', 0))
                    desc = f"{sys_name} bulk scrape was interrupted ({current}/{total} completed)"
                else:
                    count = params.get('game_count', len(params.get('game_ids', [])))
                    desc = f"{sys_name} bulk scrape was queued ({count} games)"
            elif jtype == 'ra_refresh':
                desc = "RetroAchievements refresh was interrupted" if has_progress else "RetroAchievements refresh was queued"
            elif jtype == 'ra_sync':
                desc = "RetroAchievements sync was interrupted" if has_progress else "RetroAchievements sync was queued"
            elif jtype == 'psn_refresh':
                desc = "PSN trophy refresh was interrupted" if has_progress else "PSN trophy refresh was queued"
            elif jtype == 'steam_sync':
                desc = "Steam achievement sync was interrupted" if has_progress else "Steam achievement sync was queued"
            elif jtype == 'xbox_sync':
                desc = "Xbox achievement sync was interrupted" if has_progress else "Xbox achievement sync was queued"
            else:
                desc = f"{jtype} job was {status}"

            recoverable_jobs.append({
                'id': rj['id'],
                'job_type': jtype,
                'status': status,
                'description': desc,
                'action_label': 'Resume' if has_progress else 'Start'
            })

        return render_template('dashboard.html',
                             stats=stats,
                             api_status=api_status,
                             systems=systems,
                             recent_games=recent_games,
                             recently_viewed=recently_viewed,
                             continue_playing=continue_playing,
                             recently_scraped=recently_scraped,
                             api_warning=api_warning,
                             recoverable_jobs=recoverable_jobs)
    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        return "An error occurred loading the dashboard. Check logs for details.", 500


@app.route('/api/jobs/resume/<int:job_id>', methods=['POST'])
@login_required
def resume_job(job_id):
    """Resume an interrupted or queued job from the dashboard recovery banner."""
    from services.jobs.base import get_recoverable_jobs, persist_job_complete
    from services.jobs import bulk_scrape_job, ra_sync_job, ra_refresh_job, psn_refresh_job
    from services.jobs.platform_sync import SteamSyncJob, XboxSyncJob
    from services.jobs import steam_sync_job, xbox_sync_job

    try:
        # Find the job
        recoverable = get_recoverable_jobs()
        job = None
        for rj in recoverable:
            if rj['id'] == job_id:
                job = rj
                break

        if not job:
            return jsonify({'success': False, 'error': 'Job not found or already handled'}), 404

        handler_map = {
            'bulk_scrape': bulk_scrape_job,
            'ra_refresh': ra_refresh_job,
            'ra_sync': ra_sync_job,
            'psn_refresh': psn_refresh_job,
            'steam_sync': steam_sync_job,
            'xbox_sync': xbox_sync_job,
        }
        handler = handler_map.get(job['job_type'])
        if not handler or not hasattr(handler, 'resume_from_params'):
            return jsonify({'success': False, 'error': f"No handler for job type '{job['job_type']}'"}), 400

        success = handler.resume_from_params(job['params'], progress=job.get('progress'))
        if success:
            # Mark the old interrupted/queued row as completed so it doesn't reappear
            persist_job_complete(job_id, status='completed')
            logger.info(f"Resumed {job['job_type']} job (DB id={job_id}) from dashboard")
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Could not resume job — handler returned false'}), 500

    except Exception as e:
        logger.error(f"Error resuming job {job_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/jobs/dismiss/<int:job_id>', methods=['POST'])
@login_required
def dismiss_job_route(job_id):
    """Dismiss a recoverable job so it no longer appears on the dashboard."""
    from services.jobs.base import dismiss_job
    try:
        dismiss_job(job_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error dismissing job {job_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/random-game')
@login_required
def random_game():
    """Get a random game from the library"""
    try:
        game = query("SELECT id FROM games ORDER BY RANDOM() LIMIT 1", one=True)
        if game:
            return jsonify({'success': True, 'game_id': game['id']})
        return jsonify({'success': False, 'message': 'No games in library'}), 404
    except Exception as e:
        logger.error(f"Random game error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500



@app.route('/analytics')
@login_required
def analytics():
    """Collection analytics page with charts"""
    try:
        ctx = build_analytics_context()
        return render_template('analytics.html', **ctx)
    except Exception as e:
        logger.error(f"Analytics error: {e}", exc_info=True)
        return "An error occurred loading analytics. Check logs for details.", 500


@app.route('/changelog')
def changelog():
    """Changelog page showing version history"""
    import yaml
    yaml_path = os.path.join(os.path.dirname(__file__), 'data', 'changelog.yaml')
    with open(yaml_path, 'r') as f:
        entries = yaml.safe_load(f)
    return render_template('changelog.html', changelog=entries)


@app.route('/help')
def help_page():
    """Help and documentation page"""
    return render_template('help.html')


@app.route('/setup')
def setup_page():
    """First-time setup wizard"""
    from platform_utils import PLATFORM_NAME
    # Redirect away if setup is already complete
    user_settings = settings_manager.load_settings()
    has_rom_path = bool(user_settings.get('rom_path') or getattr(config, 'ROM_PATH', ''))
    setup_done = user_settings.get('setup_completed', False)
    if setup_done or has_rom_path:
        return redirect(url_for('dashboard'))
    return render_template('setup.html', setup_mode=True, platform_name=PLATFORM_NAME)


@app.route('/api/setup/browse-folders', methods=['POST'])
def setup_browse_folders():
    """Browse filesystem folders during setup (no auth required, only works before setup is complete)"""
    # Only accessible when setup is NOT completed
    user_settings_check = settings_manager.load_settings()
    has_rom_path = bool(user_settings_check.get('rom_path') or getattr(config, 'ROM_PATH', ''))
    setup_done = user_settings_check.get('setup_completed', False)
    if setup_done or has_rom_path:
        return jsonify({'success': False, 'error': 'Setup has already been completed'}), 403

    try:
        data = request.get_json() or {}
        requested_path = data.get('path', '')

        # Default to user's home directory
        home_dir = os.path.expanduser('~')
        current_path = requested_path if requested_path else home_dir

        # Resolve and validate
        try:
            current_path = os.path.realpath(current_path)
        except (OSError, ValueError):
            current_path = home_dir

        if not os.path.exists(current_path) or not os.path.isdir(current_path):
            current_path = home_dir

        # Parent path (allow navigating up to filesystem root)
        parent_path = None
        parent = os.path.dirname(current_path)
        if parent != current_path:  # Not at filesystem root
            parent_path = parent

        folders = []
        try:
            for item in sorted(os.listdir(current_path)):
                if item.startswith('.'):
                    continue
                item_path = os.path.join(current_path, item)
                if not os.path.isdir(item_path):
                    continue
                try:
                    contents = os.listdir(item_path)
                    file_count = sum(1 for f in contents if os.path.isfile(os.path.join(item_path, f)))
                    subfolder_count = sum(1 for f in contents if os.path.isdir(os.path.join(item_path, f)))
                except PermissionError:
                    file_count = 0
                    subfolder_count = 0
                folders.append({
                    'name': item,
                    'path': item_path,
                    'file_count': file_count,
                    'subfolder_count': subfolder_count
                })
        except PermissionError:
            return jsonify({'success': False, 'error': 'Permission denied'}), 403

        return jsonify({
            'success': True,
            'base_path': home_dir,
            'current_path': current_path,
            'parent_path': parent_path,
            'folders': folders,
            'is_root': parent == current_path
        })
    except Exception:
        return jsonify({'success': False, 'error': 'An internal error occurred'}), 500


@app.route('/api/setup', methods=['POST'])
def setup_api():
    """Process setup wizard form submission"""
    # Prevent re-running setup after it's already complete
    user_settings_check = settings_manager.load_settings()
    has_rom_path = bool(user_settings_check.get('rom_path') or getattr(config, 'ROM_PATH', ''))
    setup_done = user_settings_check.get('setup_completed', False)
    if setup_done or has_rom_path:
        return jsonify({'success': False, 'error': 'Setup has already been completed'})

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'})

    # Require license acceptance
    if not data.get('license_accepted'):
        return jsonify({'success': False, 'error': 'You must accept the license and terms before completing setup'})

    # 1. Create admin account if username/password provided
    admin_username = data.get('admin_username', '').strip()
    admin_password = data.get('admin_password', '').strip()
    if admin_username and admin_password:
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        # Update existing admin or create new one
        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        admin = cursor.fetchone()
        new_hash = hash_password(admin_password)
        if admin:
            cursor.execute("""
                UPDATE users SET username = ?, password_hash = ?, force_password_change = 0
                WHERE id = ?
            """, (admin_username, new_hash, admin[0]))
        else:
            cursor.execute("""
                INSERT INTO users (username, display_name, password_hash, role, force_password_change)
                VALUES (?, ?, ?, 'admin', 0)
            """, (admin_username, admin_username, new_hash))
            admin_id = cursor.lastrowid
            cursor.execute("INSERT INTO user_settings (user_id) VALUES (?)", (admin_id,))
        conn.commit()
        conn.close()

    # 2. Save paths to settings
    user_settings = settings_manager.load_settings()
    if data.get('rom_path'):
        user_settings['rom_path'] = data['rom_path']
    if data.get('esde_gamelists_path'):
        user_settings['esde_gamelists_path'] = data['esde_gamelists_path']
    if data.get('esde_media_path'):
        user_settings['esde_downloaded_media_path'] = data['esde_media_path']

    # 3. Save API keys to scraper_settings.json
    scraper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'scraper_settings.json')
    scraper_settings = {}
    if os.path.exists(scraper_path):
        try:
            with open(scraper_path, 'r') as f:
                scraper_settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    api_keys = scraper_settings.get('api_keys', {})
    key_mapping = {
        'tgdb_key': 'tgdb',
        'tgdb_public_key': 'tgdb_public',
        'igdb_client_id': 'igdb_client_id',
        'igdb_client_secret': 'igdb_client_secret',
        'rawg_key': 'rawg',
        'ss_username': 'screenscraper_username',
        'ss_password': 'screenscraper_password',
        'ss_devid': 'screenscraper_devid',
        'ss_devpassword': 'screenscraper_devpassword',
        'ra_username': 'ra_username',
        'ra_apikey': 'ra_apikey',
    }
    for form_key, settings_key in key_mapping.items():
        val = data.get(form_key, '').strip()
        if val:
            api_keys[settings_key] = val

    scraper_settings['api_keys'] = api_keys
    if 'priority' not in scraper_settings:
        scraper_settings['priority'] = ['esde', 'screenscraper', 'rawg', 'tgdb', 'igdb']
    if 'enabled' not in scraper_settings:
        scraper_settings['enabled'] = {'esde': True, 'tgdb': True, 'igdb': True, 'rawg': True, 'screenscraper': True}

    try:
        with open(scraper_path, 'w') as f:
            json.dump(scraper_settings, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving scraper settings during setup: {e}")

    # 4. Save timezone to admin's user_settings if provided
    if data.get('timezone'):
        import sqlite3 as _sqlite3_tz
        tz_conn = _sqlite3_tz.connect(config.DB_PATH)
        tz_cursor = tz_conn.cursor()
        tz_cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        tz_admin = tz_cursor.fetchone()
        if tz_admin:
            tz_cursor.execute("UPDATE user_settings SET timezone = ? WHERE user_id = ?",
                              (data['timezone'], tz_admin[0]))
        tz_conn.commit()
        tz_conn.close()

    # 5. Mark setup as completed
    user_settings['setup_completed'] = True
    settings_manager.save_settings(user_settings)

    # Update runtime config paths
    app.config['ROM_PATH'] = get_rom_path()

    return jsonify({'success': True, 'message': 'Setup complete!'})


@app.route('/api/timezones')
def api_timezones():
    """Return all IANA timezones grouped by region for timezone picker"""
    grouped = {}
    for tz_name in sorted(available_timezones()):
        # Skip non-region timezones (e.g., 'EST', 'UTC') except UTC itself
        if '/' not in tz_name:
            if tz_name == 'UTC':
                grouped.setdefault('UTC', []).append(tz_name)
            continue
        region = tz_name.split('/')[0]
        grouped.setdefault(region, []).append(tz_name)

    # Sort each group
    for region in grouped:
        grouped[region].sort()

    return jsonify({'timezones': grouped})


# =============================================================================
# DATABASE INITIALIZATION
# =============================================================================


# =============================================================================
# ENSURE DATABASE IS INITIALIZED (runs on import)
# =============================================================================
# This ensures database migrations run even when Flask auto-reloads
init_database()
ensure_user_tables()

# Mark interrupted jobs for dashboard recovery (no silent auto-resume)
# In debug mode, Flask's reloader spawns a child process (worker) that handles
# HTTP requests. Module-level code runs in BOTH processes. We must only mark
# jobs in the worker process so the dashboard reads correct state.
_is_worker = os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not config.DEBUG_MODE
if _is_worker:
    try:
        from services.jobs.base import mark_jobs_interrupted
        _interrupted = mark_jobs_interrupted()
        if _interrupted:
            logger.info(f"Marked {len(_interrupted)} interrupted job(s) for dashboard recovery")
    except Exception as _e:
        logger.warning(f"Could not mark interrupted jobs: {_e}")

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == '__main__':
    from platform_utils import get_local_ip

    # Flask debug mode runs a reloader that spawns a subprocess
    # Only log startup info in the main process (when WERKZEUG_RUN_MAIN is set)
    # or when not in debug mode at all
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'

    if is_reloader_process or not config.DEBUG_MODE:
        logger.info("=" * 60)
        logger.info(f"Starting {config.APP_NAME} v{config.APP_VERSION}")
        logger.info("=" * 60)

    # Create required directories (always, in both processes is fine)
    for subdir in ['boxart', 'boxart_3d', 'screenshots', 'systems', 'ratings', 'fanart', 'videos', 'manuals', 'avatars', 'controllers']:
        os.makedirs(os.path.join(config.IMAGE_PATH, subdir), exist_ok=True)

    # Create data directory for settings
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'), exist_ok=True)

    # Create logs directory
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs'), exist_ok=True)

    # Initialize file-based logging (only once)
    if is_reloader_process or not config.DEBUG_MODE:
        log_manager.setup_all_logging()
        logger.info("File-based logging initialized")

    # Eager GPU warm-up on main thread — MIOpen handles are NOT thread-safe,
    # so the find/benchmark phase must complete here before Flask worker
    # threads try to run inference.  Only in the reloader child process
    # (the one that actually serves requests).
    if is_reloader_process or not config.DEBUG_MODE:
        try:
            from services.image_utils import _get_upscaler
            _get_upscaler()  # triggers init + warm-up on main thread
        except Exception:
            pass  # non-fatal; logged inside _init_upscaler

    host = config.SERVER_HOST
    port = config.SERVER_PORT
    local_ip = get_local_ip()

    if config.DEBUG_MODE:
        # Development: use Flask dev server with auto-reload
        print(f"\n  * Running in DEBUG mode (Flask dev server)")
        print(f"  * Local:   http://localhost:{port}")
        print(f"  * Network: http://{local_ip}:{port}\n")
        app.run(debug=True, host=host, port=port)
    else:
        # Production: use Waitress WSGI server
        try:
            from waitress import serve
        except ImportError:
            print("ERROR: Waitress is not installed. Install with: pip install waitress")
            print("       Or set DEBUG_MODE = True in config.py to use the Flask dev server.")
            sys.exit(1)

        print()
        print("=" * 58)
        print(f"  {config.APP_NAME} v{config.APP_VERSION}")
        print("=" * 58)
        print(f"  Server:  Waitress (production)")
        print(f"  Local:   http://localhost:{port}")
        print(f"  Network: http://{local_ip}:{port}")
        print("=" * 58)
        print(f"  Press Ctrl+C to stop the server")
        print()

        # A single /games or /dashboard load fires 20+ parallel XHRs (card
        # data, fanart, per-row API lookups). 4 threads meant most of those
        # queued behind each other and every page load flooded the log with
        # "Task queue depth" warnings. 16 gives comfortable headroom for a
        # local single-user / small-household workload without being wasteful.
        serve(app, host=host, port=port, threads=16)
