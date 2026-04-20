# =============================================================================
# RETRODB - Auth Routes Blueprint
# =============================================================================
# Handles user authentication, login/logout, and user management.
# =============================================================================

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, session, g
from datetime import datetime, timezone
from urllib.parse import urlparse
import os
import time

import config
from services.database import query, execute
from services.auth import (
    hash_password, verify_password, get_user_settings,
    admin_required, login_required
)
from services.security import rate_limit_login, record_login_attempt, safe_filename

bp = Blueprint('auth', __name__)


# =============================================================================
# LOGIN / LOGOUT ROUTES
# =============================================================================

@bp.route('/login')
def login():
    """Login page - shows list of users to select"""
    if g.user:
        return redirect(url_for('dashboard'))
    
    users = query("""
        SELECT u.id, u.username, u.display_name, u.role, us.avatar
        FROM users u LEFT JOIN user_settings us ON u.id = us.user_id
        WHERE u.is_active = 1 ORDER BY u.role, u.username
    """)
    next_url = request.args.get('next', url_for('dashboard'))
    return render_template('login.html', users=users, next_url=next_url)


@bp.route('/api/login', methods=['POST'])
def api_login():
    """Process login - admin requires password, others just click"""
    data = request.get_json() or request.form
    user_id = data.get('user_id')
    password = data.get('password', '')

    # Rate limit login attempts
    client_ip = request.remote_addr or '127.0.0.1'
    if not rate_limit_login(client_ip):
        return jsonify({'success': False, 'error': 'Too many login attempts. Please try again later.'}), 429

    if not user_id:
        return jsonify({'success': False, 'error': 'No user selected'})

    user = query("SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,), one=True)

    if not user:
        record_login_attempt(client_ip, False)
        return jsonify({'success': False, 'error': 'User not found'})

    # Admin requires password
    if user['role'] == 'admin':
        if not password:
            return jsonify({'success': False, 'error': 'Password required for admin', 'needs_password': True})
        if not verify_password(password, user['password_hash']):
            record_login_attempt(client_ip, False)
            return jsonify({'success': False, 'error': 'Invalid password'})

    # Login successful
    record_login_attempt(client_ip, True)
    session['user_id'] = user['id']
    session.permanent = True

    # Update last login
    execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), user['id']))

    next_url = data.get('next', url_for('dashboard'))
    # Prevent open redirect: reject URLs with a netloc or backslashes (CVE-2023-49438)
    parsed = urlparse(next_url)
    if parsed.netloc or parsed.scheme or '\\' in next_url:
        next_url = url_for('dashboard')
    return jsonify({'success': True, 'redirect': next_url})


@bp.route('/logout')
def logout():
    """Log out current user"""
    session.pop('user_id', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))


# =============================================================================
# USER MANAGEMENT API ROUTES (Admin only)
# =============================================================================

@bp.route('/api/users')
@admin_required
def api_list_users():
    """List all users (admin only)"""
    users = query("""
        SELECT u.id, u.username, u.display_name, u.role, u.created_at, u.last_login, u.is_active,
               us.rpcs3_trophy_path, us.ra_username
        FROM users u
        LEFT JOIN user_settings us ON u.id = us.user_id
        ORDER BY u.role, u.username
    """)
    return jsonify({'success': True, 'users': [dict(u) for u in users]})


@bp.route('/api/users/create', methods=['POST'])
@admin_required
def api_create_user():
    """Create a new user (admin only)"""
    data = request.get_json()
    username = data.get('username', '').strip()
    display_name = data.get('display_name', '').strip() or username
    role = data.get('role', 'viewer')
    
    if not username:
        return jsonify({'success': False, 'error': 'Username is required'})
    
    if role not in ['admin', 'editor', 'viewer']:
        return jsonify({'success': False, 'error': 'Invalid role'})
    
    # Check if username already exists
    existing = query("SELECT id FROM users WHERE username = ?", (username,), one=True)
    if existing:
        return jsonify({'success': False, 'error': 'Username already exists'})
    
    # Create user (no password for non-admin)
    password_hash = None
    if role == 'admin':
        # Admin users get a default password they should change
        password_hash = hash_password('changeme')
    
    try:
        user_id = execute("""
            INSERT INTO users (username, display_name, password_hash, role)
            VALUES (?, ?, ?, ?)
        """, (username, display_name, password_hash, role))
        
        # Create user settings record
        execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))
        
        return jsonify({'success': True, 'user_id': user_id, 'message': f'User "{username}" created successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/users/<int:user_id>/update', methods=['POST'])
@admin_required
def api_update_user(user_id):
    """Update a user (admin only)"""
    data = request.get_json()
    
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'})
    
    updates = []
    params = []
    
    if 'display_name' in data:
        updates.append('display_name = ?')
        params.append(data['display_name'])
    
    if 'role' in data and data['role'] in ['admin', 'editor', 'viewer']:
        updates.append('role = ?')
        params.append(data['role'])
    
    if 'is_active' in data:
        updates.append('is_active = ?')
        params.append(1 if data['is_active'] else 0)
    
    if 'new_password' in data and data['new_password']:
        updates.append('password_hash = ?')
        params.append(hash_password(data['new_password']))
    
    if updates:
        params.append(user_id)
        execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
    
    return jsonify({'success': True, 'message': 'User updated successfully'})


@bp.route('/api/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def api_delete_user(user_id):
    """Delete a user (admin only)"""
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'})
    
    # Can't delete yourself
    if g.user['id'] == user_id:
        return jsonify({'success': False, 'error': 'Cannot delete your own account'})
    
    # Can't delete the last admin
    admin_count = query("SELECT COUNT(*) as count FROM users WHERE role = 'admin' AND is_active = 1", one=True)
    if user['role'] == 'admin' and admin_count['count'] <= 1:
        return jsonify({'success': False, 'error': 'Cannot delete the last admin user'})
    
    try:
        # Delete custom avatar file if one exists
        user_settings = get_user_settings(user_id)
        if user_settings:
            avatar = dict(user_settings).get('avatar', '')
            if avatar and not avatar.startswith('default_'):
                clean_name = safe_filename(avatar)
                if clean_name:
                    avatar_path = os.path.join(config.IMAGE_PATH, 'avatars', clean_name)
                    if os.path.isfile(avatar_path):
                        os.remove(avatar_path)

        execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
        execute("DELETE FROM users WHERE id = ?", (user_id,))
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': 'An internal error occurred'})


@bp.route('/api/users/settings', methods=['GET', 'POST'])
def api_user_settings():
    """Get or update current user's settings"""
    if not g.user:
        return jsonify({'success': False, 'error': 'Not logged in'})
    
    if request.method == 'GET':
        settings = get_user_settings(g.user['id'])
        if settings:
            return jsonify({'success': True, 'settings': dict(settings)})
        return jsonify({'success': True, 'settings': {}})
    
    # POST - update settings
    data = request.get_json()
    
    updates = []
    params = []
    
    allowed_fields = ['rpcs3_trophy_path', 'ra_username', 'ra_api_key', 'theme_preference', 'items_per_page', 'psn_username', 'psn_npsso', 'avatar', 'timezone']
    
    for field in allowed_fields:
        if field in data:
            updates.append(f'{field} = ?')
            params.append(data[field])
    
    if updates:
        params.append(g.user['id'])
        execute(f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = ?", params)
        return jsonify({'success': True, 'message': 'Settings updated'})
    
    return jsonify({'success': True, 'message': 'No changes made'})


@bp.route('/api/profile/password', methods=['POST'])
def api_change_password():
    """Change current user's password (admin only)"""
    if not g.user:
        return jsonify({'success': False, 'error': 'Not logged in'})

    if g.user['role'] != 'admin':
        return jsonify({'success': False, 'error': 'Only admin accounts have passwords'})

    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not new_password:
        return jsonify({'success': False, 'error': 'New password is required'})

    if len(new_password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters'})

    # Verify current password
    user = query("SELECT password_hash FROM users WHERE id = ?", (g.user['id'],), one=True)
    if not user or not verify_password(current_password, user['password_hash']):
        return jsonify({'success': False, 'error': 'Current password is incorrect'})

    # Update password and clear force_password_change flag
    new_hash = hash_password(new_password)
    execute("UPDATE users SET password_hash = ?, force_password_change = 0 WHERE id = ?", (new_hash, g.user['id']))

    return jsonify({'success': True, 'message': 'Password changed successfully'})


@bp.route('/api/profile/force-change-password', methods=['POST'])
def api_force_change_password():
    """Change password when forced (first login with default password)"""
    if not g.user:
        return jsonify({'success': False, 'error': 'Not logged in'})

    if not g.user.get('force_password_change'):
        return jsonify({'success': False, 'error': 'Password change not required'})

    data = request.get_json()
    new_password = data.get('new_password', '')

    if not new_password:
        return jsonify({'success': False, 'error': 'New password is required'})

    if len(new_password) < 8:
        return jsonify({'success': False, 'error': 'Password must be at least 8 characters'})

    # Update password and clear force flag
    new_hash = hash_password(new_password)
    execute("UPDATE users SET password_hash = ?, force_password_change = 0 WHERE id = ?",
            (new_hash, g.user['id']))

    return jsonify({'success': True, 'message': 'Password changed successfully'})


# =============================================================================
# AVATAR ROUTES
# =============================================================================

ALLOWED_AVATAR_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB


def _delete_custom_avatar(user_id):
    """Delete any existing custom avatar file for a user"""
    avatars_dir = os.path.join(config.IMAGE_PATH, 'avatars')
    for ext in ALLOWED_AVATAR_EXTENSIONS:
        path = os.path.join(avatars_dir, f'user_{user_id}_avatar.{ext}')
        if os.path.isfile(path):
            os.remove(path)


@bp.route('/api/users/avatar', methods=['POST'])
@login_required
def api_upload_avatar():
    """Upload a custom avatar image"""
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'})

    file = request.files['avatar']
    if not file.filename:
        return jsonify({'success': False, 'error': 'No file selected'})

    # Validate extension
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return jsonify({'success': False, 'error': 'Invalid file type. Allowed: jpg, png, gif, webp'})

    # Read file data and check size
    file_data = file.read()
    if len(file_data) > MAX_AVATAR_SIZE:
        return jsonify({'success': False, 'error': 'File too large. Maximum size is 2MB'})

    # Delete any previous custom avatar
    _delete_custom_avatar(g.user['id'])

    filename = f"user_{g.user['id']}_avatar.{ext}"
    avatar_path = os.path.join(config.IMAGE_PATH, 'avatars', filename)

    # Try to resize with Pillow if available
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(file_data))
        img = img.convert('RGB') if ext in ('jpg', 'jpeg') else img.convert('RGBA')
        img.thumbnail((200, 200), Image.LANCZOS)
        img.save(avatar_path, quality=90)
    except ImportError:
        # Pillow not installed — save raw file
        with open(avatar_path, 'wb') as f:
            f.write(file_data)

    # Update user settings
    execute("UPDATE user_settings SET avatar = ? WHERE user_id = ?", (filename, g.user['id']))

    cache_bust = int(time.time())
    avatar_url = f'/static/images/avatars/{filename}?t={cache_bust}'
    return jsonify({'success': True, 'avatar_url': avatar_url})


@bp.route('/api/users/avatar/remove', methods=['POST'])
@login_required
def api_remove_avatar():
    """Remove current user's avatar (reset to role emoji)"""
    user_settings = get_user_settings(g.user['id'])
    if user_settings:
        avatar = dict(user_settings).get('avatar', '')
        if avatar and not avatar.startswith('default_'):
            _delete_custom_avatar(g.user['id'])

    execute("UPDATE user_settings SET avatar = '' WHERE user_id = ?", (g.user['id'],))
    return jsonify({'success': True})
