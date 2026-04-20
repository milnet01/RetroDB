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

def hash_password(password):
    """
    Hash a password with salt using PBKDF2.
    
    Args:
        password: Plain text password
    
    Returns:
        str: Salted hash in format "salt:hash"
    """
    salt = secrets.token_hex(16)
    hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}:{hash_obj.hex()}"


def verify_password(password, password_hash):
    """
    Verify a password against its stored hash.
    
    Args:
        password: Plain text password to verify
        password_hash: Stored hash in format "salt:hash"
    
    Returns:
        bool: True if password matches, False otherwise
    """
    try:
        salt, stored_hash = password_hash.split(':')
        hash_obj = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return hmac.compare_digest(hash_obj.hex(), stored_hash)
    except Exception:
        return False


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
