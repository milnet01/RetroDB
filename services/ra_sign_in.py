# =============================================================================
# RETRODB - RetroAchievements sign-in
# =============================================================================
# RetroArch cannot use the web API key in Settings > Account: it signs in with
# a token, and only a password earns one. The user types the password once; it
# goes to retroachievements.org and is dropped, and the token is kept per user.
# Each launch hands the launching user's token to RetroArch (launch_keys);
# services/ra_standalone.py hands it to DuckStation and PCSX2.
# =============================================================================

import logging

import requests
from flask_babel import gettext as _

import config
from services import platform_tokens

logger = logging.getLogger(__name__)

PLATFORM = 'retroachievements'
LOGIN_URL = 'https://retroachievements.org/dorequest.php'
_TIMEOUT = 20


class SignInError(Exception):
    """A sign-in that kept nothing, with the reason to show the user."""


def _record(user_id):
    """The user's sign-in, or None. A record with no token counts as none."""
    rec = platform_tokens.load_tokens(user_id, PLATFORM)
    return rec if rec and rec.get('username') and rec.get('token') else None


def status(user_id) -> dict:
    """What a page may show: never the token."""
    rec = _record(user_id) or {}
    return {'signed_in': bool(rec), 'username': rec.get('username', ''),
            'hardcore': bool(rec.get('hardcore'))}


def _ask_for_token(username, password):
    """(username as RetroAchievements spells it, token), or raises SignInError.
    The exception is not logged or shown: it could quote the request."""
    try:
        # No redirects: a redirected POST could carry the password elsewhere.
        reply = requests.post(LOGIN_URL,
                              data={'r': 'login2', 'u': username, 'p': password},
                              headers={'User-Agent': f'RetroDB/{config.APP_VERSION}'},
                              timeout=_TIMEOUT, allow_redirects=False)
    except requests.RequestException as e:
        logger.warning("RetroAchievements sign-in failed: %s", type(e).__name__)
        raise SignInError(_('Could not reach RetroAchievements. Try again later.')) from None
    try:
        body = reply.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    token = body.get('Token')
    if reply.status_code == 200 and body.get('Success') and token and isinstance(token, str):
        return str(body.get('User') or username), token
    reason = body.get('Error')
    if isinstance(reason, str) and reason:
        raise SignInError(reason)
    raise SignInError(_('RetroAchievements did not sign you in.'))


def sign_in(user_id, username, password) -> dict:
    """Swap the password for a token and keep it. Raises SignInError, and an
    earlier sign-in stays in place."""
    username = (username or '').strip()
    if not username or not password:
        raise SignInError(_('Enter your RetroAchievements username and password.'))
    name, token = _ask_for_token(username, password)
    platform_tokens.save_tokens(user_id, PLATFORM, {
        'username': name, 'token': token, 'hardcore': status(user_id)['hardcore']})
    return status(user_id)


def sign_out(user_id) -> dict:
    from services import ra_standalone
    rec = _record(user_id)
    platform_tokens.clear_tokens(user_id, PLATFORM)
    if rec:
        ra_standalone.sign_out(rec['username'])
    return status(user_id)


def set_hardcore(user_id, on) -> dict:
    rec = _record(user_id)
    if not rec:
        raise SignInError(_('Sign in to RetroAchievements first.'))
    platform_tokens.save_tokens(user_id, PLATFORM, dict(rec, hardcore=bool(on)))
    return status(user_id)


def launch_keys(user_id) -> dict:
    """The settings a launch by this user gives RetroArch; none if signed out."""
    rec = _record(user_id)
    if not rec:
        return {}
    return {
        'cheevos_enable': 'true',
        'cheevos_username': rec['username'],
        'cheevos_token': rec['token'],
        'cheevos_hardcore_mode_enable': 'true' if rec.get('hardcore') else 'false',
    }
