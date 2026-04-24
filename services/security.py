# =============================================================================
# RETRODB - Security Utilities
# =============================================================================
# Shared security functions for path validation, filename sanitization,
# and login rate limiting. Used across all route blueprints.
# =============================================================================

import os
import time
import threading
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

# =============================================================================
# FILENAME & PATH VALIDATION
# =============================================================================

def safe_filename(filename):
    """
    Validate a filename to prevent path traversal.

    Rejects filenames containing '..', '/', '\\', or os.sep.
    Returns the sanitized filename or None if invalid.

    Args:
        filename: User-supplied filename string

    Returns:
        str or None: The filename if safe, None if rejected
    """
    if not filename or not isinstance(filename, str):
        return None
    if '..' in filename or '/' in filename or '\\' in filename:
        logger.warning(f"Rejected unsafe filename: {filename}")
        return None
    if os.sep != '/' and os.sep != '\\' and os.sep in filename:
        logger.warning(f"Rejected unsafe filename: {filename}")
        return None
    return filename


# Absolute paths that must never be accepted as a user-configurable root:
# assigning any of these to ROM_PATH or ES-DE roots would let media cleanup
# / rescan code traverse the whole system.
_FORBIDDEN_ROOTS = frozenset({
    '/', '/etc', '/boot', '/root', '/proc', '/sys', '/dev',
    '/bin', '/sbin', '/lib', '/lib64', '/usr',
})


def validate_settings_path(user_path, *, allow_empty=True):
    """Validate an admin-supplied absolute directory path destined for settings.

    Accepts empty strings when allow_empty is True (unset path). Otherwise
    rejects anything that is not (a) absolute, (b) an existing directory,
    (c) its own realpath (no symlink escape), (d) not a system root, and
    (e) not the current user's home directory itself.

    Returns (True, canonical_path) on success; (False, reason) on failure.
    """
    if user_path is None:
        user_path = ''
    if not isinstance(user_path, str):
        return False, 'must be a string'
    stripped = user_path.strip()
    if not stripped:
        if allow_empty:
            return True, ''
        return False, 'must not be empty'
    if not os.path.isabs(stripped):
        return False, 'must be an absolute path'
    if not os.path.isdir(stripped):
        return False, 'directory does not exist'
    try:
        canonical = os.path.realpath(stripped)
    except OSError as e:
        return False, f'could not resolve path: {e}'
    # Symlink-escape check: accept canonical (follow-through) but reject
    # the input itself being a distinct symlink target outside the tree.
    if os.path.normpath(stripped.rstrip('/')) != canonical.rstrip('/') and os.path.islink(stripped):
        return False, 'path is a symlink that resolves elsewhere'
    if canonical in _FORBIDDEN_ROOTS or canonical.rstrip('/') in _FORBIDDEN_ROOTS:
        return False, 'path is a protected system directory'
    try:
        home = os.path.realpath(os.path.expanduser('~'))
    except OSError:
        home = None
    if home and canonical == home:
        return False, 'path cannot be the home directory itself'
    return True, canonical


def safe_path(user_path, allowed_base):
    """
    Validate that a user-supplied path resolves within an allowed base directory.

    Resolves both paths with os.path.realpath() and verifies the user path
    starts with the allowed base. Prevents directory traversal attacks.

    Args:
        user_path: User-supplied path string
        allowed_base: The base directory the path must reside within

    Returns:
        str or None: The canonical path if safe, None if rejected
    """
    if not user_path or not isinstance(user_path, str):
        return None
    if not allowed_base or not isinstance(allowed_base, str):
        return None

    try:
        canonical = os.path.realpath(user_path)
        base = os.path.realpath(allowed_base)

        if not canonical.startswith(base + os.sep) and canonical != base:
            logger.warning(f"Rejected path traversal attempt: {user_path} (resolved to {canonical}, outside {base})")
            return None

        return canonical
    except Exception as e:
        logger.warning(f"Path validation error: {e}")
        return None


# =============================================================================
# LOGIN RATE LIMITING
# =============================================================================
# Pass 33.9 — replace the O(N) + O(N log N) sweep of a plain dict with an
# OrderedDict ordered by `first_attempt`. Eviction happens only when a new
# entry is inserted, and lazy per-key TTL check runs at read time. This
# removes the per-request full-scan and full-sort that made the previous
# implementation a soft-DoS amplifier under sustained load.

_login_attempts = OrderedDict()
_lock = threading.Lock()

# Configuration
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes
_MAX_ENTRIES = 10000


def _evict_if_over_cap():
    """If we're above the cap, evict the oldest entries until we're back
    under. OrderedDict insertion order === first_attempt order because we
    only insert with `move_to_end(..., last=True)` on create, and don't
    reorder existing entries.
    """
    while len(_login_attempts) > _MAX_ENTRIES:
        _login_attempts.popitem(last=False)


def _entry_is_expired(entry, now):
    return now - entry['first_attempt'] > WINDOW_SECONDS


def rate_limit_login(ip):
    """
    Check if a login attempt from this IP should be rate limited.

    Returns False (blocked) if there have been more than MAX_ATTEMPTS
    failed login attempts from this IP within WINDOW_SECONDS.

    Args:
        ip: The client IP address

    Returns:
        bool: True if the attempt is allowed, False if rate limited
    """
    with _lock:
        entry = _login_attempts.get(ip)
        if not entry:
            return True
        now = time.time()
        if _entry_is_expired(entry, now):
            # Lazy TTL expiry — the window has elapsed, drop the stale
            # record and allow this attempt.
            _login_attempts.pop(ip, None)
            return True
        if entry['failures'] >= MAX_ATTEMPTS:
            elapsed = now - entry['first_attempt']
            logger.warning(
                f"Login rate limited for IP: {ip} "
                f"({entry['failures']} failures in {elapsed:.0f}s)"
            )
            return False
        return True


def record_login_attempt(ip, success):
    """
    Record a login attempt result for rate limiting.

    On success, clears the failure counter for the IP.
    On failure, increments the counter or starts tracking.

    Args:
        ip: The client IP address
        success: True if login succeeded, False if failed
    """
    with _lock:
        if success:
            _login_attempts.pop(ip, None)
            return
        entry = _login_attempts.get(ip)
        now = time.time()
        if entry and not _entry_is_expired(entry, now):
            entry['failures'] += 1
            return
        # Either no entry, or an expired one — (re)seed.
        if entry:
            _login_attempts.pop(ip, None)
        _login_attempts[ip] = {'failures': 1, 'first_attempt': now}
        _evict_if_over_cap()
