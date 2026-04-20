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

# Pre-compute static rating data (derived from constants, never changes)
_RATING_IMG_MAP_JS = get_rating_image_map_js()
_RATING_SYS_NAMES_JS = get_rating_system_names_js()
_RATING_TO_TIER_JS, _TIER_TO_RATING_JS = get_rating_crossmap_js()

# =============================================================================
# FLASK APP INITIALIZATION
# =============================================================================

app = Flask(__name__)


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
    limiter.limit("10 per minute")(app.view_functions.get('games.api_game_ai_fill', lambda: None))
    limiter.limit("5 per minute")(app.view_functions.get('bulk_scrape.api_bulk_scrape_start', lambda: None))
    # Login brute force protection (supplements existing IP-based rate limiting)
    limiter.limit("10 per minute")(app.view_functions.get('auth.api_login', lambda: None))

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


def ensure_user_tables():
    """Ensure user-related tables exist"""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT,
            is_active BOOLEAN DEFAULT 1,
            force_password_change BOOLEAN DEFAULT 0
        )
    """)

    # Add force_password_change column if it doesn't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN force_password_change BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Create user_settings table for per-user configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            rpcs3_trophy_path TEXT DEFAULT '',
            ra_username TEXT DEFAULT '',
            ra_api_key TEXT DEFAULT '',
            theme_preference TEXT DEFAULT 'default',
            items_per_page INTEGER DEFAULT 50,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Add avatar column to user_settings if it doesn't exist
    try:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN avatar TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Add timezone column to user_settings if it doesn't exist
    try:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN timezone TEXT DEFAULT 'UTC'")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Check if admin user exists, create if not
    cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    admin_exists = cursor.fetchone()

    if not admin_exists:
        # Create default admin user
        # Default password is 'admin' - must be changed on first login!
        default_password_hash = hash_password('admin')
        cursor.execute("""
            INSERT INTO users (username, display_name, password_hash, role, force_password_change)
            VALUES (?, ?, ?, ?, ?)
        """, ('admin', 'Administrator', default_password_hash, 'admin', 1))
        admin_id = cursor.lastrowid

        # Create settings record for admin
        cursor.execute("""
            INSERT INTO user_settings (user_id)
            VALUES (?)
        """, (admin_id,))

        logger.info("Created default admin user (username: admin, password: admin)")

    conn.commit()
    conn.close()


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
logger = logging.getLogger(__name__)

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
# JINJA2 FILTERS
# =============================================================================

@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    """Convert Unix timestamp to date string"""
    if timestamp:
        try:
            dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            return dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError, OSError):
            return str(timestamp)
    return ""


@app.template_filter('trophy_type_name')
def trophy_type_name_filter(trophy_type):
    """Convert trophy type letter to full name for image filename"""
    return {'P': 'platinum', 'G': 'gold', 'S': 'silver', 'B': 'bronze'}.get(trophy_type, 'bronze')


@app.template_filter('format_number')
def format_number_filter(num):
    """Format number with space as thousand separator (e.g., 12573 → 12 573)"""
    if num is None:
        return '0'
    try:
        n = int(num)
        return '{:,}'.format(n).replace(',', ' ')
    except (ValueError, TypeError):
        return str(num)


@app.template_filter('format_size')
def format_size_filter(bytes_size):
    """Format bytes to human readable size (also available as Jinja filter)"""
    return format_size(bytes_size)


@app.template_filter('format_ratio')
def format_ratio_filter(numerator, denominator):
    """Format a ratio as 'X / Y' with proper number formatting"""
    num = format_number_filter(numerator)
    den = format_number_filter(denominator)
    return f"{num} / {den}"


@app.template_filter('tz')
def tz_filter(value, fmt='datetime'):
    """Convert a UTC datetime string to the current user's timezone.

    fmt: 'datetime' → 'YYYY-MM-DD HH:MM:SS'
         'date'     → 'YYYY-MM-DD'
         'short'    → 'YYYY-MM-DD HH:MM'
    """
    if not value:
        return value

    try:
        # Get user timezone from request context
        user_tz_name = 'UTC'
        user_settings_obj = g.get('user_settings')
        if user_settings_obj:
            if hasattr(user_settings_obj, 'get'):
                user_tz_name = user_settings_obj.get('timezone', 'UTC') or 'UTC'
            elif hasattr(user_settings_obj, 'keys') and 'timezone' in user_settings_obj.keys():
                user_tz_name = user_settings_obj['timezone'] or 'UTC'

        user_tz = ZoneInfo(user_tz_name)

        # Parse the value into a datetime object
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            clean = value.strip()
            # Handle 'Z' suffix (Python < 3.11 fromisoformat doesn't support it)
            if clean.endswith('Z'):
                clean = clean[:-1] + '+00:00'
            # Try fromisoformat first (handles timezone offsets like +00:00)
            dt = None
            try:
                dt = datetime.fromisoformat(clean)
            except (ValueError, TypeError):
                pass
            # Fallback: manual patterns for non-standard formats
            if dt is None:
                clean2 = clean.replace('T', ' ')
                for pattern in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f',
                                '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                    try:
                        dt = datetime.strptime(clean2[:len('2000-01-01 00:00:00.000000')], pattern)
                        break
                    except ValueError:
                        continue
            if dt is None:
                return value  # Could not parse
        else:
            return value

        # Treat naive datetimes as UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # Convert to user timezone
        local_dt = dt.astimezone(user_tz)

        # Format output
        if fmt == 'date':
            return local_dt.strftime('%Y-%m-%d')
        elif fmt == 'short':
            return local_dt.strftime('%Y-%m-%d %H:%M')
        else:
            return local_dt.strftime('%Y-%m-%d %H:%M:%S')

    except (ValueError, TypeError, KeyError, AttributeError):
        return value


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
        pass

    return {
        'config': config,
        'user_settings': user_settings,
        'current_user': g.get('user'),
        'current_user_settings': g.get('user_settings'),
        'has_permission': has_permission,
        'get_avatar_url': get_avatar_url,
        'user_timezone': user_tz,
        'csrf_token': session.get('_csrf_token', ''),
        'ai_scraper_enabled': ai_scraper_enabled,
        'rating_image_map_js': _RATING_IMG_MAP_JS,
        'rating_system_names_js': _RATING_SYS_NAMES_JS,
        'rating_system_keys': RATING_SYSTEM_KEYS,
        'rating_to_tier_js': _RATING_TO_TIER_JS,
        'tier_to_rating_js': _TIER_TO_RATING_JS,
    }


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


# Manufacturer mapping for analytics
MANUFACTURER_MAP = {
    'nes': 'Nintendo', 'snes': 'Nintendo', 'n64': 'Nintendo', 'gc': 'Nintendo',
    'gamecube': 'Nintendo', 'wii': 'Nintendo', 'wiiu': 'Nintendo', 'switch': 'Nintendo',
    'gb': 'Nintendo', 'gbc': 'Nintendo', 'gba': 'Nintendo', 'nds': 'Nintendo',
    'n3ds': 'Nintendo', '3ds': 'Nintendo', 'virtualboy': 'Nintendo', 'fds': 'Nintendo',
    'famicom': 'Nintendo', 'superfamicom': 'Nintendo', 'pokemini': 'Nintendo',
    'psx': 'Sony', 'ps2': 'Sony', 'ps3': 'Sony', 'ps4': 'Sony', 'ps5': 'Sony',
    'psp': 'Sony', 'psvita': 'Sony', 'vita': 'Sony',
    'genesis': 'Sega', 'megadrive': 'Sega', 'mastersystem': 'Sega', 'sms': 'Sega',
    'segacd': 'Sega', 'sega32x': 'Sega', '32x': 'Sega', 'saturn': 'Sega',
    'dreamcast': 'Sega', 'gamegear': 'Sega', 'gg': 'Sega', 'sg1000': 'Sega',
    'xbox': 'Microsoft', 'xbox360': 'Microsoft', 'xboxone': 'Microsoft',
    'atari2600': 'Atari', 'atari5200': 'Atari', 'atari7800': 'Atari',
    'atarist': 'Atari', 'atari800': 'Atari', 'lynx': 'Atari', 'jaguar': 'Atari',
    'tg16': 'NEC', 'pcengine': 'NEC', 'pcenginecd': 'NEC', 'supergrafx': 'NEC',
    'neogeo': 'SNK', 'neogeocd': 'SNK', 'ngp': 'SNK', 'ngpc': 'SNK',
    'colecovision': 'Coleco', 'coleco': 'Coleco', 'intellivision': 'Mattel',
    '3do': 'Panasonic', 'channelf': 'Fairchild', 'odyssey2': 'Magnavox',
    'vectrex': 'GCE', 'wonderswan': 'Bandai', 'wonderswancolor': 'Bandai',
}


def get_manufacturer(folder):
    """Get manufacturer for a system folder"""
    folder_lower = folder.lower()
    return MANUFACTURER_MAP.get(folder_lower, 'Other')


def format_size(bytes_size):
    """Format bytes to human readable size"""
    if bytes_size is None:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} PB"


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


def _get_analytics_stats():
    """Get basic analytics counts, storage, and completion rate"""
    total_games = query("SELECT COUNT(*) as count FROM games", one=True)['count']
    total_systems = query("SELECT COUNT(*) as count FROM systems", one=True)['count']

    # Total storage from file_size column
    storage_row = query("SELECT SUM(COALESCE(file_size, 0)) as total FROM games", one=True)
    total_bytes = storage_row['total'] or 0

    # Completion stats
    completion_counts = query("""
        SELECT completion_status, COUNT(*) as count
        FROM games
        GROUP BY completion_status
    """)
    completion_map = {row['completion_status'] or 'not_started': row['count'] for row in completion_counts}
    completed = completion_map.get('completed', 0) + completion_map.get('100_percent', 0)
    completion_rate = round((completed / total_games * 100) if total_games > 0 else 0, 1)

    stats = {
        'total_games': total_games,
        'total_systems': total_systems,
        'total_storage': format_size(total_bytes),
        'completion_rate': completion_rate
    }

    completion_data = [
        completion_map.get('not_started', 0) + completion_map.get(None, 0),
        completion_map.get('in_progress', 0),
        completion_map.get('played', 0),
        completion_map.get('completed', 0),
        completion_map.get('100_percent', 0)
    ]

    return total_games, stats, completion_data


def _get_manufacturer_data():
    """Get games by manufacturer using a single JOIN query"""
    rows = query("""
        SELECT s.folder, COUNT(g.id) as game_count
        FROM systems s
        JOIN games g ON s.id = g.system_id
        GROUP BY s.id
    """)
    manufacturer_counts = {}
    for row in rows:
        mfr = get_manufacturer(row['folder'])
        manufacturer_counts[mfr] = manufacturer_counts.get(mfr, 0) + row['game_count']

    sorted_mfrs = sorted(manufacturer_counts.items(), key=lambda x: x[1], reverse=True)
    return [m[0] for m in sorted_mfrs[:10]], [m[1] for m in sorted_mfrs[:10]]


def _get_decade_data():
    """Get games grouped by release decade using SQL aggregation"""
    rows = query("""
        SELECT (CAST(SUBSTR(release_date, 1, 4) AS INTEGER) / 10 * 10) || 's' AS decade,
               COUNT(*) AS cnt
        FROM games
        WHERE release_date IS NOT NULL
          AND LENGTH(release_date) >= 4
          AND SUBSTR(release_date, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
        GROUP BY decade
        ORDER BY decade
    """)
    return [r['decade'] for r in rows], [r['cnt'] for r in rows]


def _get_genre_data():
    """Get top 10 genres by game count"""
    genre_counts = {}
    games_with_genre = query("SELECT genre FROM games WHERE genre IS NOT NULL AND genre != ''")
    for game in games_with_genre:
        for genre in game['genre'].split(','):
            genre = genre.strip()
            if genre:
                genre_counts[genre] = genre_counts.get(genre, 0) + 1

    sorted_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return [g[0] for g in sorted_genres], [g[1] for g in sorted_genres]


def _get_storage_by_system():
    """Get storage by system using a single GROUP BY query"""
    rows = query("""
        SELECT s.name, SUM(COALESCE(g.file_size, 0)) as total_size
        FROM systems s
        JOIN games g ON s.id = g.system_id
        WHERE g.file_size IS NOT NULL AND g.file_size > 0
        GROUP BY s.id
        HAVING total_size > 0
        ORDER BY total_size DESC
        LIMIT 15
    """)
    storage_labels = [r['name'] for r in rows]
    storage_data = [round(r['total_size'] / (1024**3), 2) for r in rows]
    return storage_labels, storage_data


def _get_top_systems():
    """Get top 15 systems with game count, storage, and manufacturer in a single query"""
    rows = query("""
        SELECT s.id, s.name, s.folder,
               COUNT(g.id) as game_count,
               SUM(COALESCE(g.file_size, 0)) as total_size
        FROM systems s
        LEFT JOIN games g ON s.id = g.system_id
        GROUP BY s.id
        HAVING game_count > 0
        ORDER BY game_count DESC
        LIMIT 15
    """)

    top_systems_list = []
    for row in rows:
        sys_dict = dict(row)
        sys_dict['manufacturer'] = get_manufacturer(row['folder'])
        total_size = row['total_size'] or 0
        sys_dict['storage_formatted'] = format_size(total_size)
        sys_dict['avg_size_formatted'] = format_size(total_size // row['game_count']) if row['game_count'] > 0 else "N/A"
        top_systems_list.append(sys_dict)

    return top_systems_list


def _get_largest_games():
    """Get the 20 largest games by file size"""
    largest_games = query("""
        SELECT g.id, g.title, g.rom_path, g.file_size, s.name as system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.file_size IS NOT NULL AND g.file_size > 0
        ORDER BY g.file_size DESC
        LIMIT 20
    """)

    largest_list = []
    for game in largest_games:
        g = dict(game)
        g['size_formatted'] = format_size(game['file_size'])
        largest_list.append(g)

    return largest_list


def _get_ra_statistics(total_games):
    """Get RetroAchievements stats and per-system coverage"""
    ra_total = query("SELECT COUNT(*) as count FROM games WHERE has_retroachievements = 1", one=True)['count']
    ra_percentage = round((ra_total / total_games * 100) if total_games > 0 else 0, 1)

    ra_by_system = query("""
        SELECT s.name, s.folder,
               COUNT(g.id) as total_games,
               SUM(CASE WHEN g.has_retroachievements = 1 THEN 1 ELSE 0 END) as ra_games
        FROM systems s
        JOIN games g ON s.id = g.system_id
        GROUP BY s.id
        HAVING ra_games > 0
        ORDER BY ra_games DESC
        LIMIT 12
    """)

    ra_system_labels = [s['name'] for s in ra_by_system]
    ra_system_data = [s['ra_games'] for s in ra_by_system]
    ra_system_totals = [s['total_games'] for s in ra_by_system]

    ra_coverage = []
    for s in ra_by_system:
        coverage = round((s['ra_games'] / s['total_games'] * 100) if s['total_games'] > 0 else 0, 1)
        ra_coverage.append({
            'name': s['name'],
            'ra_games': s['ra_games'],
            'total_games': s['total_games'],
            'coverage': coverage
        })

    return ra_total, ra_percentage, ra_system_labels, ra_system_data, ra_system_totals, ra_coverage


def _get_score_statistics():
    """Get review score stats, distribution, and per-system averages"""
    score_stats_query = query("""
        SELECT
            COUNT(CASE WHEN critic_score IS NOT NULL AND critic_score > 0 THEN 1 END) as games_with_critic,
            COUNT(CASE WHEN user_score IS NOT NULL AND user_score > 0 THEN 1 END) as games_with_user,
            AVG(CASE WHEN critic_score IS NOT NULL AND critic_score > 0 THEN critic_score END) as avg_critic,
            AVG(CASE WHEN user_score IS NOT NULL AND user_score > 0 THEN user_score END) as avg_user
        FROM games
    """, one=True)

    score_stats = {
        'games_with_critic': score_stats_query['games_with_critic'] or 0,
        'games_with_user': score_stats_query['games_with_user'] or 0,
        'avg_critic': round(score_stats_query['avg_critic'], 1) if score_stats_query['avg_critic'] else None,
        'avg_user': round(score_stats_query['avg_user'], 1) if score_stats_query['avg_user'] else None
    }

    # Score distribution using single CASE query instead of 10 separate queries
    score_dist_labels = ['0-10', '11-20', '21-30', '31-40', '41-50', '51-60', '61-70', '71-80', '81-90', '91-100']
    dist_row = query("""
        SELECT
            COUNT(CASE WHEN critic_score >= 0 AND critic_score <= 10 THEN 1 END) as bin0,
            COUNT(CASE WHEN critic_score > 10 AND critic_score <= 20 THEN 1 END) as bin1,
            COUNT(CASE WHEN critic_score > 20 AND critic_score <= 30 THEN 1 END) as bin2,
            COUNT(CASE WHEN critic_score > 30 AND critic_score <= 40 THEN 1 END) as bin3,
            COUNT(CASE WHEN critic_score > 40 AND critic_score <= 50 THEN 1 END) as bin4,
            COUNT(CASE WHEN critic_score > 50 AND critic_score <= 60 THEN 1 END) as bin5,
            COUNT(CASE WHEN critic_score > 60 AND critic_score <= 70 THEN 1 END) as bin6,
            COUNT(CASE WHEN critic_score > 70 AND critic_score <= 80 THEN 1 END) as bin7,
            COUNT(CASE WHEN critic_score > 80 AND critic_score <= 90 THEN 1 END) as bin8,
            COUNT(CASE WHEN critic_score > 90 AND critic_score <= 100 THEN 1 END) as bin9
        FROM games
    """, one=True)
    score_dist_data = [dist_row[f'bin{i}'] for i in range(10)]

    # Average scores by system
    score_by_system = query("""
        SELECT s.name,
               AVG(g.critic_score) as avg_critic,
               AVG(g.user_score) as avg_user,
               COUNT(CASE WHEN g.critic_score IS NOT NULL AND g.critic_score > 0 THEN 1 END) as count
        FROM systems s
        JOIN games g ON s.id = g.system_id
        WHERE g.critic_score IS NOT NULL AND g.critic_score > 0
        GROUP BY s.id
        HAVING count >= 5
        ORDER BY avg_critic DESC
        LIMIT 10
    """)

    score_system_labels = [s['name'] for s in score_by_system]
    score_system_critic = [round(s['avg_critic'], 1) if s['avg_critic'] else 0 for s in score_by_system]
    score_system_user = [round(s['avg_user'], 1) if s['avg_user'] else 0 for s in score_by_system]

    # Top and lowest rated games
    top_rated_games = query("""
        SELECT g.id, g.title, g.critic_score, g.user_score, s.name as system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.critic_score IS NOT NULL AND g.critic_score > 0
        ORDER BY g.critic_score DESC
        LIMIT 10
    """)

    lowest_rated_games = query("""
        SELECT g.id, g.title, g.critic_score, g.user_score, s.name as system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.critic_score IS NOT NULL AND g.critic_score > 0
        ORDER BY g.critic_score ASC
        LIMIT 10
    """)

    return (score_stats, score_dist_labels, score_dist_data,
            score_system_labels, score_system_critic, score_system_user,
            top_rated_games, lowest_rated_games)


def _get_rating_data():
    """Get rating distribution for the user's preferred system and per-system maturity breakdown"""
    settings = settings_manager.load_settings()
    pref_key = settings.get('preferred_rating_system', 'esrb')
    if pref_key not in RATING_SYSTEMS:
        pref_key = 'esrb'
    sys_info = RATING_SYSTEMS[pref_key]
    db_col = sys_info['db_column']
    sys_name = sys_info['name']
    ordered_values = RATING_VALUES.get(pref_key, [])

    # Distribution for preferred rating system
    rating_counts = query(f"""
        SELECT {db_col} as rating, COUNT(*) as count
        FROM games
        WHERE {db_col} IS NOT NULL AND {db_col} != ''
        GROUP BY {db_col}
        ORDER BY count DESC
    """)
    rating_labels = [r['rating'] for r in rating_counts]
    rating_data = [r['count'] for r in rating_counts]
    rating_total = sum(rating_data)
    top_rating = rating_labels[0] if rating_labels else 'N/A'

    no_rating_count = query("""
        SELECT COUNT(*) as count FROM games
        WHERE (esrb_rating IS NULL OR esrb_rating = '')
        AND (pegi_rating IS NULL OR pegi_rating = '')
        AND (cero_rating IS NULL OR cero_rating = '')
        AND (usk_rating IS NULL OR usk_rating = '')
        AND (acb_rating IS NULL OR acb_rating = '')
        AND (fpb_rating IS NULL OR fpb_rating = '')
        AND (grac_rating IS NULL OR grac_rating = '')
        AND (classind_rating IS NULL OR classind_rating = '')
    """, one=True)['count']

    # Maturity breakdown uses all rating systems mapped to tiers
    rating_by_system = query("""
        SELECT s.name,
               SUM(CASE WHEN g.esrb_rating IN ('E', 'EC') OR g.pegi_rating IN ('PEGI 3', 'PEGI 7')
                   OR g.cero_rating = 'A' OR g.usk_rating IN ('0', '6')
                   OR g.acb_rating IN ('G', 'PG') OR g.grac_rating = 'ALL'
                   OR g.classind_rating IN ('L', '10')
                   THEN 1 ELSE 0 END) as family,
               SUM(CASE WHEN g.esrb_rating IN ('E10+', 'T') OR g.pegi_rating IN ('PEGI 12', 'PEGI 16')
                   OR g.cero_rating IN ('B', 'C') OR g.usk_rating IN ('12', '16')
                   OR g.acb_rating IN ('M', 'MA15+') OR g.grac_rating IN ('12', '15')
                   OR g.classind_rating IN ('12', '14', '16')
                   THEN 1 ELSE 0 END) as teen,
               SUM(CASE WHEN g.esrb_rating IN ('M', 'AO') OR g.pegi_rating = 'PEGI 18'
                   OR g.cero_rating IN ('D', 'Z') OR g.usk_rating = '18'
                   OR g.acb_rating = 'R18+' OR g.grac_rating = '18'
                   OR g.classind_rating = '18'
                   THEN 1 ELSE 0 END) as mature
        FROM systems s
        JOIN games g ON s.id = g.system_id
        WHERE (g.esrb_rating IS NOT NULL AND g.esrb_rating != '')
           OR (g.pegi_rating IS NOT NULL AND g.pegi_rating != '')
           OR (g.cero_rating IS NOT NULL AND g.cero_rating != '')
           OR (g.usk_rating IS NOT NULL AND g.usk_rating != '')
           OR (g.acb_rating IS NOT NULL AND g.acb_rating != '')
           OR (g.fpb_rating IS NOT NULL AND g.fpb_rating != '')
           OR (g.grac_rating IS NOT NULL AND g.grac_rating != '')
           OR (g.classind_rating IS NOT NULL AND g.classind_rating != '')
        GROUP BY s.id
        HAVING (family + teen + mature) >= 5
        ORDER BY (family + teen + mature) DESC
        LIMIT 12
    """)

    rating_system_labels = [r['name'] for r in rating_by_system]
    rating_system_family = [r['family'] for r in rating_by_system]
    rating_system_teen = [r['teen'] for r in rating_by_system]
    rating_system_mature = [r['mature'] for r in rating_by_system]

    return (pref_key, sys_name, rating_labels, rating_data, rating_total,
            top_rating, ordered_values, no_rating_count,
            rating_system_labels, rating_system_family, rating_system_teen, rating_system_mature)


def _get_developer_publisher_data():
    """Get top developers and publishers by game count"""
    # Developers (comma-separated field)
    dev_rows = query("SELECT developer FROM games WHERE developer IS NOT NULL AND developer != ''")
    dev_counts = {}
    for row in dev_rows:
        for dev in row['developer'].split(','):
            dev = dev.strip()
            if dev:
                dev_counts[dev] = dev_counts.get(dev, 0) + 1
    sorted_devs = sorted(dev_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    dev_labels = [d[0] for d in sorted_devs]
    dev_data = [d[1] for d in sorted_devs]

    # Publishers (comma-separated field)
    pub_rows = query("SELECT publisher FROM games WHERE publisher IS NOT NULL AND publisher != ''")
    pub_counts = {}
    for row in pub_rows:
        for pub in row['publisher'].split(','):
            pub = pub.strip()
            if pub:
                pub_counts[pub] = pub_counts.get(pub, 0) + 1
    sorted_pubs = sorted(pub_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    pub_labels = [p[0] for p in sorted_pubs]
    pub_data = [p[1] for p in sorted_pubs]

    return dev_labels, dev_data, pub_labels, pub_data


def _get_franchise_data():
    """Get top franchises by game count"""
    rows = query("SELECT franchise FROM games WHERE franchise IS NOT NULL AND franchise != ''")
    counts = {}
    for row in rows:
        for f in row['franchise'].split(','):
            f = f.strip()
            if f:
                counts[f] = counts.get(f, 0) + 1
    sorted_f = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:15]
    return [f[0] for f in sorted_f], [f[1] for f in sorted_f]


def _get_gameplay_data():
    """Get perspective, dimension, modes, and player count distributions"""
    # Perspective
    persp_rows = query("SELECT perspective FROM games WHERE perspective IS NOT NULL AND perspective != ''")
    persp_counts = {}
    for row in persp_rows:
        for p in row['perspective'].split(','):
            p = p.strip()
            if p:
                persp_counts[p] = persp_counts.get(p, 0) + 1
    sorted_persp = sorted(persp_counts.items(), key=lambda x: x[1], reverse=True)
    persp_labels = [p[0] for p in sorted_persp]
    persp_data = [p[1] for p in sorted_persp]

    # Dimension
    dim_rows = query("SELECT dimension FROM games WHERE dimension IS NOT NULL AND dimension != ''")
    dim_counts = {}
    for row in dim_rows:
        for d in row['dimension'].split(','):
            d = d.strip()
            if d:
                dim_counts[d] = dim_counts.get(d, 0) + 1
    sorted_dim = sorted(dim_counts.items(), key=lambda x: x[1], reverse=True)
    dim_labels = [d[0] for d in sorted_dim]
    dim_data = [d[1] for d in sorted_dim]

    # Modes
    mode_rows = query("SELECT modes FROM games WHERE modes IS NOT NULL AND modes != ''")
    mode_counts = {}
    for row in mode_rows:
        for m in row['modes'].split(','):
            m = m.strip()
            if m:
                mode_counts[m] = mode_counts.get(m, 0) + 1
    sorted_modes = sorted(mode_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    mode_labels = [m[0] for m in sorted_modes]
    mode_data = [m[1] for m in sorted_modes]

    # Player count distribution
    player_rows = query("""
        SELECT
            CASE
                WHEN players = 1 THEN '1 Player'
                WHEN players = 2 THEN '2 Players'
                WHEN players BETWEEN 3 AND 4 THEN '3-4 Players'
                WHEN players >= 5 THEN '5+ Players'
            END as player_group,
            COUNT(*) as count
        FROM games
        WHERE players IS NOT NULL AND players > 0
        GROUP BY player_group
        ORDER BY MIN(players)
    """)
    player_labels = [r['player_group'] for r in player_rows]
    player_data = [r['count'] for r in player_rows]

    return (persp_labels, persp_data, dim_labels, dim_data,
            mode_labels, mode_data, player_labels, player_data)


def _get_playtime_data():
    """Get HLTB playtime statistics"""
    rows = query("SELECT title, playtime_estimate, system_id FROM games WHERE playtime_estimate IS NOT NULL AND playtime_estimate != ''")

    main_hours = []
    for row in rows:
        est = row.get('playtime_estimate', '')
        match = re.search(r'Main[^:]*:\s*([\d.½]+)', est)
        if match:
            val = match.group(1).replace('½', '.5')
            try:
                main_hours.append(float(val))
            except ValueError:
                pass

    # Length distribution buckets
    buckets = {'< 5h': 0, '5-10h': 0, '10-20h': 0, '20-40h': 0, '40-60h': 0, '60-100h': 0, '100h+': 0}
    for h in main_hours:
        if h < 5:
            buckets['< 5h'] += 1
        elif h < 10:
            buckets['5-10h'] += 1
        elif h < 20:
            buckets['10-20h'] += 1
        elif h < 40:
            buckets['20-40h'] += 1
        elif h < 60:
            buckets['40-60h'] += 1
        elif h < 100:
            buckets['60-100h'] += 1
        else:
            buckets['100h+'] += 1

    length_labels = list(buckets.keys())
    length_data = list(buckets.values())

    # Stats
    avg_length = round(sum(main_hours) / len(main_hours), 1) if main_hours else 0
    games_with_hltb = len(main_hours)

    return length_labels, length_data, avg_length, games_with_hltb


def _get_metadata_quality():
    """Get metadata completeness for radar chart and progress bars"""
    fields = query("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) as description,
            SUM(CASE WHEN boxart IS NOT NULL AND boxart != '' THEN 1 ELSE 0 END) as boxart,
            SUM(CASE WHEN genre IS NOT NULL AND genre != '' THEN 1 ELSE 0 END) as genre,
            SUM(CASE WHEN developer IS NOT NULL AND developer != '' THEN 1 ELSE 0 END) as developer,
            SUM(CASE WHEN publisher IS NOT NULL AND publisher != '' THEN 1 ELSE 0 END) as publisher,
            SUM(CASE WHEN release_date IS NOT NULL AND release_date != '' THEN 1 ELSE 0 END) as release_date,
            SUM(CASE WHEN screenshots IS NOT NULL AND screenshots != '' THEN 1 ELSE 0 END) as screenshots,
            SUM(CASE WHEN fanart IS NOT NULL AND fanart != '' THEN 1 ELSE 0 END) as fanart,
            SUM(CASE WHEN video IS NOT NULL AND video != '' THEN 1 ELSE 0 END) as video,
            SUM(CASE WHEN manual IS NOT NULL AND manual != '' THEN 1 ELSE 0 END) as manual,
            SUM(CASE WHEN playtime_estimate IS NOT NULL AND playtime_estimate != '' THEN 1 ELSE 0 END) as hltb,
            SUM(CASE WHEN (critic_score IS NOT NULL AND critic_score > 0) THEN 1 ELSE 0 END) as ratings,
            SUM(CASE WHEN modes IS NOT NULL AND modes != '' THEN 1 ELSE 0 END) as modes,
            SUM(CASE WHEN region IS NOT NULL AND region != '' THEN 1 ELSE 0 END) as region
        FROM games
    """, one=True)

    total = fields['total'] or 1  # Avoid division by zero
    quality = {}
    for field_name in ['description', 'boxart', 'genre', 'developer', 'publisher',
                        'release_date', 'screenshots', 'fanart', 'video', 'manual',
                        'hltb', 'ratings', 'modes', 'region']:
        quality[field_name] = round((fields[field_name] or 0) / total * 100, 1)

    return quality


def _get_year_data():
    """Get game counts per release year (not decade)"""
    rows = query("""
        SELECT SUBSTR(release_date, 1, 4) as year, COUNT(*) as count
        FROM games
        WHERE release_date IS NOT NULL AND LENGTH(release_date) >= 4
        AND CAST(SUBSTR(release_date, 1, 4) AS INTEGER) BETWEEN 1970 AND 2030
        GROUP BY year
        ORDER BY year
    """)
    return [r['year'] for r in rows], [r['count'] for r in rows]


def _get_region_data():
    """Get region distribution"""
    rows = query("SELECT region FROM games WHERE region IS NOT NULL AND region != ''")
    counts = {}
    for row in rows:
        for r in row['region'].split(','):
            r = r.strip()
            if r:
                counts[r] = counts.get(r, 0) + 1
    sorted_r = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
    return [r[0] for r in sorted_r], [r[1] for r in sorted_r]


def _get_collection_growth():
    """Get collection growth over time using created_at or ID as fallback"""
    # Try created_at first
    rows = query("""
        SELECT SUBSTR(created_at, 1, 7) as month, COUNT(*) as count
        FROM games
        WHERE created_at IS NOT NULL AND created_at != ''
        GROUP BY month
        ORDER BY month
    """)
    if rows:
        # Cumulative sum
        labels = [r['month'] for r in rows]
        cumulative = []
        total = 0
        for r in rows:
            total += r['count']
            cumulative.append(total)
        return labels, cumulative

    # Fallback: use ID order, group by batches of ~50
    total_count = query("SELECT COUNT(*) as c FROM games", one=True)['c']
    if total_count == 0:
        return [], []
    batch_size = max(total_count // 20, 1)
    labels = []
    cumulative = []
    for i in range(0, total_count, batch_size):
        labels.append(f"Batch {len(labels) + 1}")
        cumulative.append(min(i + batch_size, total_count))
    return labels, cumulative


def _get_score_scatter():
    """Get critic vs user score data for scatter plot"""
    rows = query("""
        SELECT title, critic_score, user_score
        FROM games
        WHERE critic_score IS NOT NULL AND critic_score > 0
        AND user_score IS NOT NULL AND user_score > 0
        LIMIT 200
    """)
    scatter_data = []
    for r in rows:
        # Normalize user_score to 0-100 if it's on 0-10 scale
        user = r['user_score']
        if user <= 10:
            user = user * 10
        scatter_data.append({
            'x': round(r['critic_score'], 1),
            'y': round(user, 1),
            'title': r['title'][:30]
        })
    return scatter_data


def _get_minor_analytics():
    """Get save type, media completeness, bonus discs, editions data"""
    # Save type distribution
    save_rows = query("SELECT save_type FROM games WHERE save_type IS NOT NULL AND save_type != ''")
    save_counts = {}
    for row in save_rows:
        for s in row['save_type'].split(','):
            s = s.strip()
            if s:
                save_counts[s] = save_counts.get(s, 0) + 1
    sorted_saves = sorted(save_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    save_labels = [s[0] for s in sorted_saves]
    save_data = [s[1] for s in sorted_saves]

    # Bonus disc count
    bonus_count = query("SELECT COUNT(*) as c FROM games WHERE is_bonus_disc = 1", one=True)['c']

    # Edition breakdown
    edition_rows = query("SELECT edition FROM games WHERE edition IS NOT NULL AND edition != ''")
    edition_count = len(edition_rows)

    return save_labels, save_data, bonus_count, edition_count


@app.route('/analytics')
@login_required
def analytics():
    """Collection analytics page with charts"""
    try:
        total_games, stats, completion_data = _get_analytics_stats()
        manufacturer_labels, manufacturer_data = _get_manufacturer_data()
        decade_labels, decade_data = _get_decade_data()
        genre_labels, genre_data = _get_genre_data()
        storage_labels, storage_data = _get_storage_by_system()
        top_systems_list = _get_top_systems()
        largest_list = _get_largest_games()
        ra_total, ra_percentage, ra_system_labels, ra_system_data, ra_system_totals, ra_coverage = _get_ra_statistics(total_games)
        (score_stats, score_dist_labels, score_dist_data,
         score_system_labels, score_system_critic, score_system_user,
         top_rated_games, lowest_rated_games) = _get_score_statistics()
        (pref_rating_key, pref_rating_name, rating_labels, rating_data, rating_total,
         top_rating, ordered_rating_values, no_rating_count,
         rating_system_labels, rating_system_family, rating_system_teen, rating_system_mature) = _get_rating_data()

        # New analytics data
        dev_labels, dev_data, pub_labels, pub_data = _get_developer_publisher_data()
        franchise_labels, franchise_data = _get_franchise_data()
        (persp_labels, persp_data, dim_labels, dim_data,
         mode_labels, mode_data, player_labels, player_data) = _get_gameplay_data()
        length_labels, length_data, avg_length, games_with_hltb = _get_playtime_data()
        metadata_quality = _get_metadata_quality()
        year_labels, year_data = _get_year_data()
        region_labels, region_data = _get_region_data()
        growth_labels, growth_data = _get_collection_growth()
        score_scatter = _get_score_scatter()
        save_labels, save_data, bonus_count, edition_count = _get_minor_analytics()

        return render_template('analytics.html',
            stats=stats,
            manufacturer_labels=manufacturer_labels,
            manufacturer_data=manufacturer_data,
            decade_labels=decade_labels,
            decade_data=decade_data,
            genre_labels=genre_labels,
            genre_data=genre_data,
            completion_data=completion_data,
            storage_labels=storage_labels,
            storage_data=storage_data,
            top_systems=top_systems_list,
            largest_games=largest_list,
            ra_total=ra_total,
            ra_percentage=ra_percentage,
            ra_system_labels=ra_system_labels,
            ra_system_data=ra_system_data,
            ra_system_totals=ra_system_totals,
            ra_coverage=ra_coverage,
            score_stats=score_stats,
            score_dist_labels=score_dist_labels,
            score_dist_data=score_dist_data,
            score_system_labels=score_system_labels,
            score_system_critic=score_system_critic,
            score_system_user=score_system_user,
            top_rated_games=top_rated_games,
            lowest_rated_games=lowest_rated_games,
            pref_rating_key=pref_rating_key,
            pref_rating_name=pref_rating_name,
            rating_labels=rating_labels,
            rating_data=rating_data,
            rating_total=rating_total,
            top_rating=top_rating,
            ordered_rating_values=ordered_rating_values,
            no_rating_count=no_rating_count,
            rating_system_labels=rating_system_labels,
            rating_system_family=rating_system_family,
            rating_system_teen=rating_system_teen,
            rating_system_mature=rating_system_mature,
            # New analytics
            dev_labels=dev_labels,
            dev_data=dev_data,
            pub_labels=pub_labels,
            pub_data=pub_data,
            franchise_labels=franchise_labels,
            franchise_data=franchise_data,
            persp_labels=persp_labels,
            persp_data=persp_data,
            dim_labels=dim_labels,
            dim_data=dim_data,
            mode_labels=mode_labels,
            mode_data=mode_data,
            player_labels=player_labels,
            player_data=player_data,
            length_labels=length_labels,
            length_data=length_data,
            avg_length=avg_length,
            games_with_hltb=games_with_hltb,
            metadata_quality=metadata_quality,
            year_labels=year_labels,
            year_data=year_data,
            region_labels=region_labels,
            region_data=region_data,
            growth_labels=growth_labels,
            growth_data=growth_data,
            score_scatter=score_scatter,
            save_labels=save_labels,
            save_data=save_data,
            bonus_count=bonus_count,
            edition_count=edition_count,
        )
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

def init_database():
    """Initialize database if it doesn't exist"""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    # Create systems table
    c.execute("""
        CREATE TABLE IF NOT EXISTS systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            folder TEXT NOT NULL UNIQUE,
            logo TEXT
        )
    """)

    # Create games table
    c.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            publisher TEXT,
            developer TEXT,
            release_date TEXT,
            genre TEXT,
            rating TEXT,
            esrb_rating TEXT,
            pegi_rating TEXT,
            players INTEGER,
            modes TEXT,
            description TEXT,
            boxart TEXT,
            boxart_3d TEXT,
            screenshots TEXT,
            fanart TEXT,
            video TEXT,
            manual TEXT,
            region TEXT,
            franchise TEXT,
            similar_games TEXT,
            playtime_estimate TEXT,
            controller_support TEXT,
            save_type TEXT,
            sort_title TEXT,
            rom_path TEXT NOT NULL UNIQUE,
            scraped BOOLEAN DEFAULT 0,
            is_bonus_disc BOOLEAN DEFAULT 0,
            parent_game_id INTEGER,
            FOREIGN KEY(system_id) REFERENCES systems(id),
            FOREIGN KEY(parent_game_id) REFERENCES games(id)
        )
    """)

    # Create publishers lookup table
    c.execute("""
        CREATE TABLE IF NOT EXISTS publishers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenscraper_id TEXT UNIQUE,
            name TEXT NOT NULL
        )
    """)

    # Create developers lookup table
    c.execute("""
        CREATE TABLE IF NOT EXISTS developers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenscraper_id TEXT UNIQUE,
            name TEXT NOT NULL
        )
    """)

    # Add new columns if they don't exist (for existing databases)
    new_columns = [
        ('fanart', 'TEXT'),
        ('video', 'TEXT'),
        ('manual', 'TEXT'),
        ('region', 'TEXT'),
        ('franchise', 'TEXT'),
        ('similar_games', 'TEXT'),
        ('playtime_estimate', 'TEXT'),
        ('controller_support', 'TEXT'),
        ('save_type', 'TEXT'),
        ('scrape_history', 'TEXT'),  # JSON storing scrape history
        ('completion_status', 'TEXT DEFAULT "not_started"'),  # Completion tracking
        ('file_size', 'INTEGER'),  # File size in bytes
        ('last_viewed', 'TEXT'),  # Last viewed timestamp
        ('sort_title', 'TEXT'),  # Sortable title (Roman numerals converted)
        ('hltb_match_name', 'TEXT'),  # HLTB matched game name
        ('hltb_match_platform', 'TEXT'),  # HLTB matched platform
        ('hltb_match_confidence', 'REAL'),  # HLTB match confidence (0-1)
        ('boxart_3d', 'TEXT'),  # 3D boxart image
        ('clz_title', 'TEXT'),  # Original title from CLZ Games import
        ('perspective', 'TEXT'),  # Game perspective (First-Person, Third-Person, etc.)
        ('dimension', 'TEXT'),  # Game dimension (2D, 2.5D, 3D, VR, etc.)
        ('created_at', 'TEXT'),  # Timestamp when game was added to library
        ('last_bulk_scraped', 'TEXT'),  # Timestamp of last bulk scrape processing
        ('steam_app_id', 'TEXT'),  # Steam app ID for imported Steam games
        ('xbox_title_id', 'TEXT'),  # Xbox title ID for imported Xbox games
        ('psn_npwr_id', 'TEXT'),  # PSN NPWR ID for imported PSN games
        ('cero_rating', 'TEXT'),  # CERO age rating (Japan)
        ('usk_rating', 'TEXT'),  # USK age rating (Germany)
        ('acb_rating', 'TEXT'),  # ACB age rating (Australia)
        ('fpb_rating', 'TEXT'),  # FPB age rating (South Africa)
        ('grac_rating', 'TEXT'),  # GRAC age rating (South Korea)
        ('classind_rating', 'TEXT'),  # CLASS_IND age rating (Brazil)
    ]
    for col_name, col_type in new_columns:
        try:
            c.execute(f"ALTER TABLE games ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added new column: {col_name}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Backfill clz_title for existing CLZ imports (extract original title from rom_path)
    # rom_path format: clz_import/{system_folder}/{title}
    try:
        c.execute("""
            UPDATE games
            SET clz_title = SUBSTR(rom_path,
                LENGTH('clz_import/') + INSTR(SUBSTR(rom_path, LENGTH('clz_import/') + 1), '/') + 1)
            WHERE rom_path LIKE 'clz_import/%/%'
              AND (clz_title IS NULL OR clz_title = '')
        """)
        if c.rowcount > 0:
            logger.info(f"Backfilled clz_title for {c.rowcount} existing CLZ imports")
    except Exception as e:
        logger.warning(f"Could not backfill clz_title: {e}")

    # Create game_achievement_progress table for storing RetroAchievements progress locally
    c.execute("""
        CREATE TABLE IF NOT EXISTS game_achievement_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL UNIQUE,
            ra_game_id INTEGER,
            earned_achievements INTEGER DEFAULT 0,
            total_achievements INTEGER DEFAULT 0,
            earned_points INTEGER DEFAULT 0,
            total_points INTEGER DEFAULT 0,
            completion_percentage REAL DEFAULT 0,
            last_synced TEXT,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    # Add source column to game_achievement_progress for multi-platform achievement tracking
    for col_name, col_type in [
        ('steam_app_id', 'TEXT'),
        ('xbox_title_id', 'TEXT'),
        ('source', "TEXT DEFAULT 'ra'"),
    ]:
        try:
            c.execute(f"ALTER TABLE game_achievement_progress ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added {col_name} column to game_achievement_progress")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Create normalization_rules table for custom genre/modes normalization
    c.execute("""
        CREATE TABLE IF NOT EXISTS normalization_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            from_value TEXT NOT NULL,
            to_value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, from_value)
        )
    """)

    # Create dropdown_options table (for editable dropdowns)
    c.execute("""
        CREATE TABLE IF NOT EXISTS dropdown_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            value TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            UNIQUE(category, value)
        )
    """)

    # Seed perspective options
    perspective_defaults = [
        ('perspective', 'First-Person', 1),
        ('perspective', 'Isometric', 2),
        ('perspective', 'Side-Scroller', 3),
        ('perspective', 'Third-Person', 4),
        ('perspective', 'Top-Down', 5),
    ]
    for cat, val, order in perspective_defaults:
        try:
            c.execute("INSERT OR IGNORE INTO dropdown_options (category, value, sort_order) VALUES (?, ?, ?)",
                      (cat, val, order))
        except sqlite3.OperationalError:
            pass  # Table may not exist yet

    # Seed dimension options
    dimension_defaults = [
        ('dimension', '2D', 1),
        ('dimension', '2.5D', 2),
        ('dimension', '3D', 3),
        ('dimension', 'AR', 4),
        ('dimension', 'FMV', 5),
        ('dimension', 'Pseudo-3D', 6),
        ('dimension', 'VR', 7),
    ]
    for cat, val, order in dimension_defaults:
        try:
            c.execute("INSERT OR IGNORE INTO dropdown_options (category, value, sort_order) VALUES (?, ?, ?)",
                      (cat, val, order))
        except sqlite3.OperationalError:
            pass  # Table may not exist yet

    # Create indexes for faster lookups
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_achievement_progress_game ON game_achievement_progress(game_id)")
    except sqlite3.OperationalError:
        pass

    # Add indexes for games table to improve Library page performance
    game_indexes = [
        ("idx_games_system_id", "system_id"),
        ("idx_games_is_bonus_disc", "is_bonus_disc"),
        ("idx_games_sort_title", "sort_title"),
        ("idx_games_parent_game_id", "parent_game_id"),
        ("idx_games_scraped", "scraped"),
        ("idx_games_title", "title"),
        ("idx_games_completion_status", "completion_status"),
        ("idx_games_has_retroachievements", "has_retroachievements"),
        ("idx_games_genre", "genre"),
        ("idx_games_developer", "developer"),
        ("idx_games_publisher", "publisher"),
        ("idx_games_franchise", "franchise"),
        ("idx_games_release_date", "release_date"),
        ("idx_games_critic_score", "critic_score"),
        ("idx_games_created_at", "created_at"),
        ("idx_games_steam_app_id", "steam_app_id"),
        ("idx_games_xbox_title_id", "xbox_title_id"),
        ("idx_games_psn_npwr_id", "psn_npwr_id"),
        ("idx_games_rom_path", "rom_path"),
    ]
    for idx_name, idx_col in game_indexes:
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON games({idx_col})")
        except sqlite3.OperationalError:
            pass

    # Composite indexes for common multi-column queries
    composite_indexes = [
        ("idx_games_system_scraped", "system_id, scraped"),
        ("idx_games_system_bonus", "system_id, is_bonus_disc"),
        ("idx_games_system_bonus_scraped", "system_id, is_bonus_disc, scraped"),
    ]
    for idx_name, idx_cols in composite_indexes:
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON games({idx_cols})")
        except sqlite3.OperationalError:
            pass

    # Add trophies_synced column to psn_games if it exists (for tracking bulk refresh status)
    try:
        c.execute("ALTER TABLE psn_games ADD COLUMN trophies_synced INTEGER DEFAULT 0")
        logger.info("Added trophies_synced column to psn_games")
    except sqlite3.OperationalError:
        pass  # Column already exists or table doesn't exist

    # Add trophy_level and avatar_url columns to psn_sync_status
    for col_name, col_type in [("trophy_level", "INTEGER DEFAULT 0"), ("avatar_url", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE psn_sync_status ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added {col_name} column to psn_sync_status")
        except sqlite3.OperationalError:
            pass  # Column already exists or table doesn't exist

    # Add HLTB columns to psn_games for storing How Long to Beat data
    hltb_columns = [
        ("hltb_id", "INTEGER"),
        ("hltb_title", "TEXT"),
        ("hltb_main", "TEXT"),
        ("hltb_extra", "TEXT"),
        ("hltb_complete", "TEXT")
    ]
    for col_name, col_type in hltb_columns:
        try:
            c.execute(f"ALTER TABLE psn_games ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added {col_name} column to psn_games")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Create job_queue table for background job persistence and crash recovery
    c.execute("""
        CREATE TABLE IF NOT EXISTS job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT DEFAULT 'running',
            progress TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT,
            params TEXT
        )
    """)

    # Add index for quickly finding running/incomplete jobs on startup
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue(status)")
    except sqlite3.OperationalError:
        pass

    # ==========================================================================
    # Tags & Lists system
    # ==========================================================================
    c.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            color TEXT DEFAULT '#4cc9f0',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS game_tags (
            game_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (game_id, tag_id),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            icon TEXT DEFAULT '📋',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS list_games (
            list_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0,
            added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (list_id, game_id),
            FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    # ==========================================================================
    # Wishlist system
    # ==========================================================================
    c.execute("""
        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            system_name TEXT,
            notes TEXT,
            priority INTEGER DEFAULT 2,
            added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            game_id INTEGER,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE SET NULL
        )
    """)

    # ==========================================================================
    # Collector Trophies system
    # ==========================================================================
    c.execute("""
        CREATE TABLE IF NOT EXISTS collector_trophies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            icon TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'bronze',
            category TEXT NOT NULL DEFAULT 'general',
            threshold INTEGER DEFAULT 0,
            earned_at TEXT,
            progress INTEGER DEFAULT 0
        )
    """)

    # ==========================================================================
    # System Museum (encyclopedia)
    # ==========================================================================
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_museum (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL UNIQUE,
            history TEXT,
            summary TEXT,
            top_games TEXT,
            generated_at TEXT,
            generated_by TEXT,
            FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
        )
    """)

    # ==========================================================================
    # Steam individual achievements
    # ==========================================================================
    c.execute("""
        CREATE TABLE IF NOT EXISTS steam_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            apiname TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            icon_url TEXT,
            icon_locked_url TEXT,
            achieved INTEGER DEFAULT 0,
            unlock_time INTEGER DEFAULT 0,
            UNIQUE(game_id, apiname),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    # ==========================================================================
    # Xbox individual achievements
    # ==========================================================================
    c.execute("""
        CREATE TABLE IF NOT EXISTS xbox_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            icon_url TEXT,
            icon_locked_url TEXT,
            gamerscore INTEGER DEFAULT 0,
            achieved INTEGER DEFAULT 0,
            unlock_time TEXT,
            UNIQUE(game_id, achievement_id),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    # Indexes for new tables
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_game ON game_tags(game_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_tag ON game_tags(tag_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_list_games_list ON list_games(list_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_list_games_game ON list_games(game_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wishlist_priority ON wishlist(priority)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_collector_trophies_tier ON collector_trophies(tier)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_system_museum_system ON system_museum(system_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_steam_ach_game ON steam_achievements(game_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_xbox_ach_game ON xbox_achievements(game_id)")
    except sqlite3.OperationalError:
        pass

    # Migrate genre values to canonical schema forms (idempotent)
    _migrate_genre_canonical(c)

    # Migrate bare PEGI numbers to "PEGI X" format (idempotent)
    _migrate_pegi_format(c)

    # Run PRAGMA optimize to update query planner statistics where needed
    c.execute("PRAGMA optimize")

    conn.commit()
    conn.close()
    logger.info("Database initialized")


def _migrate_genre_canonical(cursor):
    """Migrate existing genre values to canonical schema forms.

    Uses REPLACE() on the genre column. Safe to re-run — REPLACE is idempotent
    when old value is no longer present.
    """
    migrations = [
        # FPS → First-Person-Shooter
        ('FPS', 'First-Person-Shooter'),
        # Shoot 'em Up variations → Shoot-em-up
        ("Shoot 'em Up", 'Shoot-em-up'),
        ("Shoot'em Up", 'Shoot-em-up'),
        # Beat 'em Up variations → Beat-em-up
        ("Beat 'em Up", 'Beat-em-up'),
        ("Beat'em Up", 'Beat-em-up'),
        # Hack and Slash → Hack-n-Slash
        ('Hack and Slash', 'Hack-n-Slash'),
        # Third-Person Shooter → Shooter
        ('Third-Person Shooter', 'Shooter'),
        # Light Gun → Light-Gun
        ('Light Gun', 'Light-Gun'),
        # Tower Defense → Tower-Defence
        ('Tower Defense', 'Tower-Defence'),
        # Battle Royale → Battle-Royale
        ('Battle Royale', 'Battle-Royale'),
        # Board Game / Card Game → Board-Card
        ('Board Game', 'Board-Card'),
        ('Card Game', 'Board-Card'),
        # Visual Novel → Visual-Novel
        ('Visual Novel', 'Visual-Novel'),
        # Life Simulation → Life-Simulation
        ('Life Simulation', 'Life-Simulation'),
        # City Builder → City-Builder
        ('City Builder', 'City-Builder'),
        # Survival Horror → Survival-Horror
        ('Survival Horror', 'Survival-Horror'),
        # Psychological Horror → Psychological-Horror
        ('Psychological Horror', 'Psychological-Horror'),
        # Flight Simulator → Flight
        ('Flight Simulator', 'Flight'),
        # Kart Racing → Racing
        ('Kart Racing', 'Racing'),
        # Tactical RPG → Strategy
        ('Tactical RPG', 'Strategy'),
    ]
    try:
        for old_val, new_val in migrations:
            cursor.execute(
                "UPDATE games SET genre = REPLACE(genre, ?, ?) WHERE genre LIKE ?",
                (old_val, new_val, f'%{old_val}%')
            )
        logger.info("Genre canonical migration completed")
    except Exception as e:
        logger.warning(f"Genre canonical migration skipped: {e}")


def _migrate_pegi_format(cursor):
    """Migrate bare PEGI numbers (e.g. '12') to 'PEGI 12' format.

    Safe to re-run — only updates values that are bare numbers.
    """
    try:
        for num in ['3', '7', '12', '16', '18']:
            cursor.execute(
                "UPDATE games SET pegi_rating = ? WHERE pegi_rating = ?",
                (f'PEGI {num}', num)
            )
        logger.info("PEGI format migration completed")
    except Exception as e:
        logger.warning(f"PEGI format migration skipped: {e}")


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

        serve(app, host=host, port=port, threads=4)
