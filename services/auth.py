# =============================================================================
# RETRODB - Authentication Service
# =============================================================================
# Provides user authentication, authorization, and session management.
# Includes decorators for protecting routes based on login status and roles.
# =============================================================================

import hashlib
import hmac
import secrets
from functools import wraps
from flask import g, session, redirect, url_for, flash, request

from services.database import query


# =============================================================================
# ROLE PERMISSIONS
# =============================================================================

ROLE_PERMISSIONS = {
    'admin': {
        'view', 'edit', 'delete_metadata', 'delete_rom', 'scrape',
        'manage_users', 'manage_settings', 'system_functions'
    },
    'editor': {
        'view', 'edit', 'delete_metadata', 'scrape'
    },
    'viewer': {
        'view'
    }
}


# =============================================================================
# PASSWORD HASHING
# =============================================================================

# OWASP 2026 Password Storage Cheat Sheet floor for PBKDF2-SHA256.
# Bumped from the pre-v2.84.0 value of 100,000 — still far below the Argon2id
# target but a no-dependency-change upgrade. Legacy 100k hashes are rehashed
# on next successful login (see needs_rehash() + api_login).
PBKDF2_ITERATIONS = 600_000


def hash_password(password, iterations=PBKDF2_ITERATIONS):
    """
    Hash a password with salt using PBKDF2-SHA256.

    Args:
        password: Plain text password
        iterations: PBKDF2 iteration count (defaults to current OWASP floor)

    Returns:
        str: Salted hash in format "pbkdf2:<iters>:<salt>:<hash>"
    """
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
    return f"pbkdf2:{iterations}:{salt}:{hash_obj.hex()}"


def verify_password(password, password_hash):
    """
    Verify a password against its stored hash.

    Accepts both the current format ("pbkdf2:<iters>:<salt>:<hash>") and the
    legacy pre-v2.84.0 format ("<salt>:<hash>", fixed at 100,000 iterations).
    Legacy hashes stay verifiable so existing users aren't locked out; they
    get upgraded to the current format the next time they log in (see
    needs_rehash() + the migrate-on-login branch in routes/auth.py::api_login).

    Args:
        password: Plain text password to verify
        password_hash: Stored hash string

    Returns:
        bool: True if password matches, False otherwise
    """
    try:
        parts = password_hash.split(':')
        if len(parts) == 4 and parts[0] == 'pbkdf2':
            iterations = int(parts[1])
            salt = parts[2]
            stored_hash = parts[3]
        elif len(parts) == 2:
            iterations = 100_000
            salt, stored_hash = parts
        else:
            return False
        hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), iterations)
        return hmac.compare_digest(hash_obj.hex(), stored_hash)
    except Exception:
        return False


def needs_rehash(password_hash):
    """
    Return True if the stored hash uses legacy parameters (pre-v2.84.0
    "<salt>:<hash>" format or a pbkdf2 iteration count below the current
    PBKDF2_ITERATIONS floor), or if the hash is malformed. Callers should
    re-hash on next successful login and UPDATE the stored value. Malformed
    hashes get flagged so callers migrate the credential rather than trust
    it forever.
    """
    try:
        parts = password_hash.split(':')
        if len(parts) != 4 or parts[0] != 'pbkdf2':
            return True
        return int(parts[1]) < PBKDF2_ITERATIONS
    except Exception:
        return True


# =============================================================================
# USER SESSION MANAGEMENT
# =============================================================================

def get_current_user():
    """
    Get the currently logged in user from session.
    
    Returns:
        dict: User record or None if not logged in
    """
    user_id = session.get('user_id')
    if user_id:
        return query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    return None


def get_user_settings(user_id):
    """
    Get settings for a specific user.

    Args:
        user_id: Database ID of the user

    Returns:
        dict: User settings record or None
    """
    return query("SELECT * FROM user_settings WHERE user_id = ?", (user_id,), one=True)


def get_user_ra_credentials():
    """Get RetroAchievements credentials for the current user.

    Prefers the logged-in user's per-account credentials from user_settings;
    falls back to the global config.py / settings.json credentials if the user
    hasn't configured their own.

    Returns:
        tuple: (username, api_key). Either may be empty if neither the user
               nor the global config has them set.
    """
    if g.user and g.user_settings:
        try:
            user_username = g.user_settings['ra_username'] or ''
            user_api_key = g.user_settings['ra_api_key'] or ''
            if user_username and user_api_key:
                return user_username, user_api_key
        except (KeyError, TypeError):
            pass

    from scraper.retroachievements import get_ra_credentials
    return get_ra_credentials()


def has_permission(permission):
    """
    Check if current user has a specific permission.
    
    Args:
        permission: Permission name to check (e.g., 'edit', 'delete_rom')
    
    Returns:
        bool: True if user has permission, False otherwise
    """
    if not g.user:
        return False
    role = g.user['role']
    return permission in ROLE_PERMISSIONS.get(role, set())


# =============================================================================
# ROUTE DECORATORS
# =============================================================================

def login_required(f):
    """
    Decorator to require login for a route.
    
    Public pages (dashboard, analytics, login, static) are exempt.
    Redirects to login page with 'next' parameter for return.
    
    Usage:
        @app.route('/protected')
        @login_required
        def protected_page():
            return render_template('protected.html')
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Public pages don't require login
        if request.endpoint in ['auth.login', 'auth.api_login', 'static', 'help_page', 'changelog']:
            return f(*args, **kwargs)
        if not g.user:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def permission_required(permission):
    """
    Decorator factory to require a specific permission.
    
    Args:
        permission: Permission name required (e.g., 'edit', 'manage_users')
    
    Usage:
        @app.route('/admin-only')
        @permission_required('manage_users')
        def admin_page():
            return render_template('admin.html')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.user:
                flash('Please log in to access this page', 'warning')
                return redirect(url_for('auth.login', next=request.url))
            if not has_permission(permission):
                flash('You do not have permission to access this feature', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_required(f):
    """
    Decorator to require admin role.
    
    Usage:
        @app.route('/admin')
        @admin_required
        def admin_page():
            return render_template('admin.html')
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        if g.user['role'] != 'admin':
            flash('This action requires administrator privileges', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def editor_required(f):
    """
    Decorator to require editor or admin role.
    
    Usage:
        @app.route('/edit-game')
        @editor_required
        def edit_game():
            return render_template('edit_game.html')
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.user:
            flash('Please log in to access this page', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        if g.user['role'] not in ['admin', 'editor']:
            flash('This action requires editor privileges', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function
