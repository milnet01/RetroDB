# =============================================================================
# RETRODB - Xbox API Scraper
# =============================================================================
# Functions for fetching Xbox game libraries and achievement data.
# Uses Microsoft's Xbox Live API via OAuth2 authentication.
# =============================================================================

import logging
import json
import os
import requests
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Xbox Live API endpoints
XBOX_AUTH_URL = 'https://login.live.com/oauth20_authorize.srf'
XBOX_TOKEN_URL = 'https://login.live.com/oauth20_token.srf'  # noqa: S105 — URL constant, not a credential
XBL_AUTH_URL = 'https://user.auth.xboxlive.com/user/authenticate'
XSTS_AUTH_URL = 'https://xsts.auth.xboxlive.com/xsts/authorize'
XBOX_PROFILE_URL = 'https://profile.xboxlive.com'
XBOX_ACHIEVEMENTS_URL = 'https://achievements.xboxlive.com'
XBOX_TITLEHUB_URL = 'https://titlehub.xboxlive.com'

# Scopes for OAuth
SCOPES = 'XboxLive.signin XboxLive.offline_access'

# Platform mapping from Xbox API to RetroDB system folders
XBOX_PLATFORM_MAP = {
    'Xbox': 'xbox',
    'Xbox360': 'xbox360',
    'XboxOne': 'xboxone',
    'XboxSeries': 'xboxseriesx',
    'WindowsOneCore': 'windows',
    'Win32': 'windows',
    # Fallbacks
    'Mobile': None,
    'iOS': None,
    'Android': None,
}

# Token storage path
TOKENS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'xbox_tokens.json')


def get_auth_url(client_id, redirect_uri):
    """Generate the Microsoft OAuth authorization URL.

    Args:
        client_id: Azure AD application client ID
        redirect_uri: OAuth callback URL

    Returns:
        str: Authorization URL to redirect user to
    """
    params = {
        'client_id': client_id,
        'response_type': 'code',
        'redirect_uri': redirect_uri,
        'scope': SCOPES,
    }
    return f'{XBOX_AUTH_URL}?{urlencode(params)}'


def exchange_code_for_tokens(client_id, client_secret, code, redirect_uri):
    """Exchange an OAuth authorization code for access tokens.

    Args:
        client_id: Azure AD application client ID
        client_secret: Azure AD application client secret
        code: Authorization code from callback
        redirect_uri: OAuth callback URL (must match the one used in auth URL)

    Returns:
        dict: Token data including access_token, refresh_token, or None on error
    """
    try:
        resp = requests.post(XBOX_TOKEN_URL, data={
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Xbox token exchange error: {e}")
        return None


def refresh_access_token(client_id, client_secret, refresh_token):
    """Refresh an expired access token using a refresh token.

    Args:
        client_id: Azure AD application client ID
        client_secret: Azure AD application client secret
        refresh_token: OAuth refresh token

    Returns:
        dict: New token data, or None on error
    """
    try:
        resp = requests.post(XBOX_TOKEN_URL, data={
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
            'scope': SCOPES,
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Xbox token refresh error: {e}")
        return None


def authenticate_xbox_live(access_token):
    """Authenticate with Xbox Live using a Microsoft access token.

    Returns XBL token and user hash needed for XSTS authentication.

    Args:
        access_token: Microsoft OAuth access token

    Returns:
        tuple: (xbl_token, user_hash) or (None, None) on error
    """
    try:
        resp = requests.post(XBL_AUTH_URL, json={
            'Properties': {
                'AuthMethod': 'RPS',
                'SiteName': 'user.auth.xboxlive.com',
                'RpsTicket': f'd={access_token}',
            },
            'RelyingParty': 'http://auth.xboxlive.com',
            'TokenType': 'JWT',
        }, headers={'Content-Type': 'application/json'}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        xbl_token = data.get('Token')
        user_hash = data.get('DisplayClaims', {}).get('xui', [{}])[0].get('uhs')
        return xbl_token, user_hash
    except Exception as e:
        logger.error(f"Xbox Live auth error: {e}")
        return None, None


def get_xsts_token(xbl_token):
    """Get an XSTS token for Xbox API access.

    Args:
        xbl_token: XBL authentication token

    Returns:
        tuple: (xsts_token, xuid) or (None, None) on error
    """
    try:
        resp = requests.post(XSTS_AUTH_URL, json={
            'Properties': {
                'SandboxId': 'RETAIL',
                'UserTokens': [xbl_token],
            },
            'RelyingParty': 'http://xboxlive.com',
            'TokenType': 'JWT',
        }, headers={'Content-Type': 'application/json'}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        xsts_token = data.get('Token')
        xuid = data.get('DisplayClaims', {}).get('xui', [{}])[0].get('xid')
        return xsts_token, xuid
    except Exception as e:
        logger.error(f"XSTS auth error: {e}")
        return None, None


def _get_auth_header(user_hash, xsts_token):
    """Build the Xbox Live authorization header."""
    return f'XBL3.0 x={user_hash};{xsts_token}'


def save_tokens(tokens):
    """Save Xbox tokens to disk for persistence across restarts."""
    try:
        os.makedirs(os.path.dirname(TOKENS_FILE), exist_ok=True)
        with open(TOKENS_FILE, 'w') as f:
            json.dump(tokens, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save Xbox tokens: {e}")


def load_tokens():
    """Load saved Xbox tokens from disk.

    Returns:
        dict: Token data or None if not found
    """
    try:
        if os.path.exists(TOKENS_FILE):
            with open(TOKENS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load Xbox tokens: {e}")
    return None


def clear_tokens():
    """Remove saved Xbox tokens."""
    try:
        if os.path.exists(TOKENS_FILE):
            os.unlink(TOKENS_FILE)
    except Exception as e:
        logger.error(f"Failed to clear Xbox tokens: {e}")


def get_authenticated_session(client_id, client_secret):
    """Get an authenticated Xbox session, refreshing tokens if needed.

    Args:
        client_id: Azure AD app client ID
        client_secret: Azure AD app client secret

    Returns:
        dict: {auth_header, xuid, user_hash, xsts_token, gamertag} or None
    """
    tokens = load_tokens()
    if not tokens:
        return None

    # Try to use existing tokens; refresh if needed
    access_token = tokens.get('access_token')
    refresh_token_val = tokens.get('refresh_token')

    if not access_token and not refresh_token_val:
        return None

    # Try refresh if we have a refresh token
    if refresh_token_val:
        new_tokens = refresh_access_token(client_id, client_secret, refresh_token_val)
        if new_tokens:
            access_token = new_tokens.get('access_token')
            tokens.update(new_tokens)
            save_tokens(tokens)
        elif not access_token:
            return None

    # Authenticate with Xbox Live
    xbl_token, user_hash = authenticate_xbox_live(access_token)
    if not xbl_token:
        return None

    # Get XSTS token
    xsts_token, xuid = get_xsts_token(xbl_token)
    if not xsts_token:
        return None

    auth_header = _get_auth_header(user_hash, xsts_token)

    return {
        'auth_header': auth_header,
        'xuid': xuid,
        'user_hash': user_hash,
        'xsts_token': xsts_token,
    }


def get_title_history(auth_header, xuid, max_items=1000):
    """Get a user's Xbox game history (all played titles).

    Args:
        auth_header: Xbox Live authorization header
        xuid: Xbox user ID
        max_items: Maximum items to fetch

    Returns:
        list: Game title dicts with achievement summaries
    """
    all_titles = []
    continuation_token = None

    try:
        while len(all_titles) < max_items:
            url = f'{XBOX_TITLEHUB_URL}/users/xuid({xuid})/titles/titlehistory/decoration/achievement,image'

            params = {'maxItems': min(100, max_items - len(all_titles))}
            if continuation_token:
                params['continuationToken'] = continuation_token

            resp = requests.get(url, params=params, headers={
                'Authorization': auth_header,
                'x-xbl-contract-version': '2',
                'Accept-Language': 'en-US',
            }, timeout=30)

            if resp.status_code == 401:
                logger.error("Xbox API: Authentication expired")
                return all_titles

            resp.raise_for_status()
            data = resp.json()

            titles = data.get('titles', [])
            if not titles:
                break

            all_titles.extend(titles)
            continuation_token = data.get('pagingInfo', {}).get('continuationToken')
            if not continuation_token:
                break

        logger.info(f"Xbox: Fetched {len(all_titles)} title history entries for XUID {xuid}")
        return all_titles
    except Exception as e:
        logger.error(f"Xbox get_title_history error: {e}")
        return all_titles


def get_achievements(auth_header, xuid, title_id):
    """Get achievement details for a specific Xbox game.

    Args:
        auth_header: Xbox Live authorization header
        xuid: Xbox user ID
        title_id: Xbox title ID

    Returns:
        dict: {achievements: [...], earned: int, total: int} or None on error
    """
    try:
        url = f'{XBOX_ACHIEVEMENTS_URL}/users/xuid({xuid})/achievements'

        resp = requests.get(url, params={
            'titleId': title_id,
            'maxItems': 1000,
        }, headers={
            'Authorization': auth_header,
            'x-xbl-contract-version': '2',
            'Accept-Language': 'en-US',
        }, timeout=15)

        if resp.status_code in (401, 404):
            return None

        resp.raise_for_status()
        data = resp.json()

        achievements = data.get('achievements', [])
        earned = sum(1 for a in achievements
                     if a.get('progressState') == 'Achieved')

        return {
            'achievements': achievements,
            'earned': earned,
            'total': len(achievements),
        }
    except Exception as e:
        logger.error(f"Xbox get_achievements error (title {title_id}): {e}")
        return None


def parse_title_platform(title):
    """Determine the RetroDB system folder from an Xbox title's device list.

    Args:
        title: Xbox title dict from title history API

    Returns:
        str: RetroDB system folder (e.g. 'xbox360', 'xboxone'), or None
    """
    devices = title.get('devices', [])

    # Prefer console platforms over PC
    priority = ['XboxSeries', 'XboxOne', 'Xbox360', 'Xbox']
    for platform in priority:
        if platform in devices:
            return XBOX_PLATFORM_MAP.get(platform)

    # Fall back to first recognized device
    for device in devices:
        mapped = XBOX_PLATFORM_MAP.get(device)
        if mapped:
            return mapped

    # Default: if it's an Xbox title, assume Xbox One
    return 'xboxone'


def get_gamertag(auth_header, xuid):
    """Get the gamertag for an XUID.

    Args:
        auth_header: Xbox Live authorization header
        xuid: Xbox user ID

    Returns:
        str: Gamertag or None
    """
    try:
        url = f'{XBOX_PROFILE_URL}/users/xuid({xuid})/profile/settings'
        resp = requests.get(url, params={
            'settings': 'Gamertag',
        }, headers={
            'Authorization': auth_header,
            'x-xbl-contract-version': '2',
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        settings = data.get('profileUsers', [{}])[0].get('settings', [])
        for s in settings:
            if s.get('id') == 'Gamertag':
                return s.get('value')
        return None
    except Exception as e:
        logger.error(f"Xbox get_gamertag error: {e}")
        return None
