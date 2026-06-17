# =============================================================================
# RETRODB - Auth Routes Blueprint
# =============================================================================
# Handles user authentication, login/logout, and user management.
# =============================================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from flask_babel import _
from datetime import datetime, timezone
from urllib.parse import urlparse
import os
import time

import config
from services.database import query, execute
from services.api_helpers import handle_api_errors, success, error
from services.i18n import available_locales
from services.auth import (
    hash_password, verify_password, needs_rehash, get_user_settings,
    admin_required, login_required, VALID_ROLES,
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
    """Process login — Pass 24.1: every role now requires a password. The
    prior passwordless branch for editor/viewer was a full authentication
    bypass (anyone hitting /api/login could assume any non-admin identity)."""
    data = request.get_json() or request.form
    user_id = data.get('user_id')
    password = data.get('password', '')

    # Rate limit login attempts
    client_ip = request.remote_addr or '127.0.0.1'
    if not rate_limit_login(client_ip):
        return error(_('Too many login attempts. Please try again later.'), 429)

    if not user_id:
        return error(_('No user selected'), code=200)

    user = query("SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,), one=True)

    if not user:
        record_login_attempt(client_ip, False)
        return error(_('User not found'), code=200)

    # Pass 24.1 — every role requires a password.
    if not user['password_hash']:
        # Legacy editor/viewer account created before Pass 24. Refuse the
        # login until an admin sets a password via User Management. We
        # deliberately do NOT silently authenticate — that's the bug we
        # came here to fix.
        record_login_attempt(client_ip, False)
        return error(
            _('This account has no password set. Ask an administrator to set one.'),
            code=200,
        )
    if not password:
        return error(_('Password required'), code=200, needs_password=True)
    if not verify_password(password, user['password_hash']):
        record_login_attempt(client_ip, False)
        return error(_('Invalid password'), code=200)

    # Migrate legacy (pre-v2.84.0) password hash to current OWASP floor.
    # We have the plaintext here, so this is the natural rehash point.
    if needs_rehash(user['password_hash']):
        execute("UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user['id']))

    # Login successful.
    record_login_attempt(client_ip, True)

    # Pass 24.2 — rotate the session on the auth boundary so any pre-login
    # session state (including an attacker-planted cookie) is discarded.
    # Flask doesn't expose a built-in regenerate(); clear-then-reset is the
    # idiomatic equivalent. The fresh cookie value is derived from the
    # server's secret_key on next response.
    session.clear()
    session['user_id'] = user['id']
    session.permanent = True

    # Update last login
    execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), user['id']))

    next_url = data.get('next', url_for('dashboard'))
    # Prevent open redirect: reject URLs with a netloc or backslashes (CVE-2023-49438)
    parsed = urlparse(next_url)
    if parsed.netloc or parsed.scheme or '\\' in next_url:
        next_url = url_for('dashboard')
    # Pass 24.3 is handled by the app.py::check_force_password_change
    # before_request hook — if force_password_change=1 the next request
    # under this session will be intercepted and rendered as the
    # force-change-password template regardless of next_url, so we don't
    # need a special branch here.
    # Pass 33.8: return the freshly-minted CSRF token so a client that
    # stashed a pre-login token (e.g. from the /login GET) can refresh it
    # without relying on a subsequent GET round-trip. The token is set by
    # app.py's @before_request ensure_csrf_token hook once session.clear()
    # has emptied the session.
    from flask import session as _flask_session
    _ensure_csrf = _flask_session.get('_csrf_token')
    if not _ensure_csrf:
        import secrets as _secrets
        _flask_session['_csrf_token'] = _secrets.token_hex(32)
        _ensure_csrf = _flask_session['_csrf_token']
    return success(redirect=next_url, csrf_token=_ensure_csrf)


@bp.route('/logout')
def logout():
    """Log out current user.

    Pass 33.6: clear the whole session on logout. The old `session.pop` of
    just `user_id` (and later `oauth_state_xbox` per 31.9) left the CSRF
    token, `permanent` flag, and any other ambient state in the cookie,
    which survived into the next login. `session.clear()` wipes everything
    atomically; the next request cycles a fresh CSRF token via
    app.py's ensure_csrf_token hook.
    """
    session.clear()
    flash(_('You have been logged out'), 'info')
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
    return success(users=[dict(u) for u in users])


@bp.route('/api/users/create', methods=['POST'])
@admin_required
@handle_api_errors
def api_create_user():
    """Create a new user (admin only)"""
    data = request.get_json()
    username = data.get('username', '').strip()
    display_name = data.get('display_name', '').strip() or username
    role = data.get('role', 'viewer')

    if not username:
        return error(_('Username is required'), code=200)

    if role not in VALID_ROLES:
        return error(_('Invalid role'), code=200)

    # Check if username already exists
    existing = query("SELECT id FROM users WHERE username = ?", (username,), one=True)
    if existing:
        return error(_('Username already exists'), code=200)

    # Pass 24.1 — every role now requires a password, so every new account
    # seeds the same `changeme` + force_password_change=1 onboarding flow
    # that admin accounts already used. The new user's first login lands
    # on the force-change-password page via the app.py before_request hook.
    # An admin can override this during creation by passing `password`.
    raw_password = data.get('password', '').strip()
    if raw_password:
        if len(raw_password) < 12:
            return error(_('Password must be at least 12 characters'), code=200)
        password_hash = hash_password(raw_password)
        must_change = 0
    else:
        password_hash = hash_password('changeme')
        must_change = 1

    user_id = execute("""
        INSERT INTO users (username, display_name, password_hash, role, force_password_change)
        VALUES (?, ?, ?, ?, ?)
    """, (username, display_name, password_hash, role, must_change))

    # Create user settings record
    execute("INSERT INTO user_settings (user_id) VALUES (?)", (user_id,))

    return success(user_id=user_id, message=f'User "{username}" created successfully')


@bp.route('/api/users/<int:user_id>/update', methods=['POST'])
@admin_required
def api_update_user(user_id):
    """Update a user (admin only)"""
    data = request.get_json()
    
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        return error(_('User not found'), code=200)

    updates = []
    params = []
    
    if 'display_name' in data:
        updates.append('display_name = ?')
        params.append(data['display_name'])
    
    if 'role' in data and data['role'] in VALID_ROLES:
        updates.append('role = ?')
        params.append(data['role'])
    
    if 'is_active' in data:
        updates.append('is_active = ?')
        params.append(1 if data['is_active'] else 0)
    
    if 'new_password' in data and data['new_password']:
        # Pass 33.3: enforce the same 12-char floor that api_create_user
        # applies. Admin was previously able to silently set a 3-char
        # password via this endpoint, violating the Pass 24.4 contract.
        raw_password = data['new_password']
        if len(raw_password) < 12:
            return error(_('Password must be at least 12 characters'), code=200)
        updates.append('password_hash = ?')
        params.append(hash_password(raw_password))
        # Pass 33.4: admin-reset passwords must trigger a force-change on
        # the next login (OWASP ASVS). Admin can opt out of the forced
        # change by passing `skip_force_change: true` (e.g. re-issuing
        # one's own password during troubleshooting).
        if not data.get('skip_force_change'):
            updates.append('force_password_change = ?')
            params.append(1)

    if updates:
        params.append(user_id)
        execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)

    return success(message='User updated successfully')


@bp.route('/api/users/<int:user_id>/delete', methods=['POST'])
@admin_required
@handle_api_errors
def api_delete_user(user_id):
    """Delete a user (admin only)"""
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        return error(_('User not found'), code=200)

    # Can't delete yourself
    if g.user['id'] == user_id:
        return error(_('Cannot delete your own account'), code=200)

    # Can't delete the last admin
    admin_count = query("SELECT COUNT(*) as count FROM users WHERE role = 'admin' AND is_active = 1", one=True)
    if user['role'] == 'admin' and admin_count['count'] <= 1:
        return error(_('Cannot delete the last admin user'), code=200)

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
    return success(message='User deleted successfully')


@bp.route('/api/users/settings', methods=['GET', 'POST'])
def api_user_settings():
    """Get or update current user's settings"""
    if not g.user:
        return error(_('Not logged in'), code=200)

    if request.method == 'GET':
        settings = get_user_settings(g.user['id'])
        if settings:
            return success(settings=dict(settings))
        return success(settings={})
    
    # POST - update settings. silent=True + `or {}` so a non-JSON body yields an
    # empty dict (→ "No changes made") rather than faulting the membership tests
    # below with a TypeError on None — matches the house idiom across routes.
    data = request.get_json(silent=True) or {}

    updates = []
    params = []

    # Pass 33.2: `avatar` is deliberately omitted from this allowlist. The
    # avatar field is owned by the dedicated upload flow
    # (api_upload_avatar / api_remove_avatar), which writes a sanitized
    # filename via safe_filename(). Accepting a free-form `avatar` value
    # here would let any authenticated user POST
    # `{"avatar": "../../.secret_key"}` and have the resulting DB value
    # reconstructed verbatim into `os.path.join(IMAGE_PATH, 'avatars',
    # clean_name)` — anyone downstream that re-derives a path from that
    # stored string inherits the traversal.
    allowed_fields = [
        'rpcs3_trophy_path', 'ra_username', 'ra_api_key', 'theme_preference',
        'items_per_page', 'psn_username', 'psn_npsso', 'timezone',
        'locale_preference',
    ]

    # Pass 43.1 — validate the locale at request time (not against a frozen
    # snapshot) so a catalog added after process start is accepted and a
    # removed one cannot be persisted.
    if 'locale_preference' in data and data['locale_preference'] not in available_locales():
        # code=200 (success:false envelope) to match every other validation
        # error in this route — API.post throws on non-2xx, so a 400 would
        # surface as a generic "Network error" toast instead of this message.
        return error(_('Invalid locale'), code=200)

    for field in allowed_fields:
        if field in data:
            updates.append(f'{field} = ?')
            params.append(data[field])

    if updates:
        params.append(g.user['id'])
        execute(f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = ?", params)
        return success(message='Settings updated')

    return success(message='No changes made')


@bp.route('/api/profile/password', methods=['POST'])
def api_change_password():
    """Change current user's password (any authenticated role — Pass 24.1)."""
    if not g.user:
        return error(_('Not logged in'), code=200)

    # Pass 41.1.B — bucket on (ip, user_id), not bare IP.  The legacy
    # IP-only bucket was shared with /api/login, so 5 failed
    # change-password attempts from user A on a shared LAN locked out
    # /api/login for every other user on that LAN.  Per-(ip, user)
    # buckets isolate the change-password counter from /api/login AND
    # from other users.  Same MAX_ATTEMPTS budget as Pass 24.4.
    client_ip = request.remote_addr or '127.0.0.1'
    user_id = g.user['id']
    rl_bucket = f"{client_ip}:cpw:{user_id}"
    if not rate_limit_login(rl_bucket):
        return error(_('Too many attempts. Please try again later.'), 429)

    data = request.get_json()
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not new_password:
        return error(_('New password is required'), code=200)

    # Pass 24.4 — 8 → 12 char floor. OWASP 2026 Password Storage Cheat
    # Sheet minimum for accounts without MFA; 8 chars let `password` pass.
    if len(new_password) < 12:
        return error(_('Password must be at least 12 characters'), code=200)

    # Verify current password
    user = query("SELECT password_hash FROM users WHERE id = ?", (user_id,), one=True)
    if not user or not verify_password(current_password, user['password_hash']):
        record_login_attempt(rl_bucket, False)
        return error(_('Current password is incorrect'), code=200)

    # Update password and clear force_password_change flag
    new_hash = hash_password(new_password)
    execute("UPDATE users SET password_hash = ?, force_password_change = 0 WHERE id = ?", (new_hash, user_id))

    record_login_attempt(rl_bucket, True)

    # Pass 33.5 — OWASP ASVS V3.7. A credentials-change is a
    # session-rotation boundary: a hijacked cookie that reaches this path
    # must not keep its authenticated state, and concurrent sessions of
    # the same account must be invalidated. Clear + re-set mirrors
    # api_login's regenerate flow. We also mint a fresh CSRF token so the
    # client can keep POSTing without a GET round-trip.
    session.clear()
    session['user_id'] = user_id
    session.permanent = True
    import secrets as _secrets
    session['_csrf_token'] = _secrets.token_hex(32)
    return success(message='Password changed successfully', csrf_token=session['_csrf_token'])


@bp.route('/api/profile/force-change-password', methods=['POST'])
def api_force_change_password():
    """Change password when forced (first login with default password)"""
    if not g.user:
        return error(_('Not logged in'), code=200)

    if not g.user.get('force_password_change'):
        return error(_('Password change not required'), code=200)

    data = request.get_json()
    new_password = data.get('new_password', '')

    if not new_password:
        return error(_('New password is required'), code=200)

    # Pass 24.4 — 8 → 12 char floor, matching api_change_password.
    if len(new_password) < 12:
        return error(_('Password must be at least 12 characters'), code=200)

    # Update password and clear force flag
    new_hash = hash_password(new_password)
    user_id = g.user['id']
    execute("UPDATE users SET password_hash = ?, force_password_change = 0 WHERE id = ?",
            (new_hash, user_id))

    # Pass 33.5 — same session-rotation contract as api_change_password.
    # force-change-password is the first place a user touches after a
    # `changeme` or admin-reset login; rotating here means the original
    # bootstrap cookie cannot be replayed after the password is set.
    session.clear()
    session['user_id'] = user_id
    session.permanent = True
    import secrets as _secrets
    session['_csrf_token'] = _secrets.token_hex(32)
    return success(message='Password changed successfully', csrf_token=session['_csrf_token'])


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
        return error(_('No file provided'), code=200)

    file = request.files['avatar']
    if not file.filename:
        return error(_('No file selected'), code=200)

    # Validate extension
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return error(_('Invalid file type. Allowed: jpg, png, gif, webp'), code=200)

    # Read file data and check size
    file_data = file.read()
    if len(file_data) > MAX_AVATAR_SIZE:
        return error(_('File too large. Maximum size is 2MB'), code=200)

    # Delete any previous custom avatar
    _delete_custom_avatar(g.user['id'])

    filename = f"user_{g.user['id']}_avatar.{ext}"
    avatar_path = os.path.join(config.IMAGE_PATH, 'avatars', filename)

    # Pass 33.7 — Pillow is a hard dependency for avatar uploads. Without
    # it we have only extension validation, and a `.png`-renamed PHP / JSP
    # / ASP payload would persist verbatim on a proxied deploy that hands
    # `static/images/avatars/` to an interpreter. Pillow is pinned in
    # requirements.txt / requirements.lock, so ImportError is now a fatal
    # 500 rather than a quiet fallback.
    try:
        from PIL import Image
    except ImportError:
        return error(
            _('Avatar uploads require Pillow; please ask the operator to '
              'install the project requirements.'),
            code=500,
        )
    import io
    try:
        # verify() consumes the stream, so open a fresh BytesIO for the
        # actual processing step afterwards.
        with Image.open(io.BytesIO(file_data)) as _probe:
            _probe.verify()
        img = Image.open(io.BytesIO(file_data))
        img = img.convert('RGB') if ext in ('jpg', 'jpeg') else img.convert('RGBA')
        img.thumbnail((200, 200), Image.LANCZOS)
        img.save(avatar_path, quality=90)
    except Exception:
        # PIL.verify() failed or decode error — treat as invalid upload.
        return error(_('Invalid image file'), code=200)

    # Update user settings
    execute("UPDATE user_settings SET avatar = ? WHERE user_id = ?", (filename, g.user['id']))

    cache_bust = int(time.time())
    avatar_url = f'/static/images/avatars/{filename}?t={cache_bust}'
    return success(avatar_url=avatar_url)


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
    return success()
