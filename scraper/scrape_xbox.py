# =============================================================================
# RETRODB - Xbox API Scraper (OpenXBL, PASS-59-261)
# =============================================================================
# Fetches a user's Xbox title history and achievements through OpenXBL
# (https://xbl.io). Each RetroDB user pastes their own free OpenXBL key; there
# is no Microsoft app registration and no OAuth sign-in. OpenXBL passes
# Microsoft's own replies through, so the shapes read here are Xbox Live's
# TitleHub and achievements shapes.
#
# The free key allows 150 calls an hour, and every call counts, a refused one
# included. So a call is never retried on 429, and a 429 stops calls on that
# key for the hour (service_limits); the sender then returns its usual nothing.
# =============================================================================

import hashlib
import logging
import time

import config
from scraper import service_limits
# scrapers.md §10: base_scraper is the only sanctioned HTTP layer.
from scraper.base_scraper import http_get
from services.platform_tokens import (
    load_tokens as _platform_load_tokens,
    save_tokens as _platform_save_tokens,
    clear_tokens as _platform_clear_tokens,
)

logger = logging.getLogger(__name__)

OPENXBL_URL = 'https://api.xbl.io/v2'

# OpenXBL resets its count each hour and documents no Retry-After.
LIMIT_STOP_SECONDS = 3600

# get_account's answer when OpenXBL turns the key down (401/403).
KEY_REFUSED = object()

# Device names in a title's `devices` list, to RetroDB system folders.
# Phone-only titles map to nothing and are left out of the import list.
XBOX_PLATFORM_MAP = {
    'Xbox': 'xbox',
    'Xbox360': 'xbox360',
    'XboxOne': 'xboxone',
    'XboxSeries': 'xboxseriesx',
    'PC': 'windows',
    'WindowsOneCore': 'windows',
    'Win32': 'windows',
}

# Consoles before PC, newest console first.
_PLATFORM_PRIORITY = ('XboxSeries', 'XboxOne', 'Xbox360', 'Xbox')


def _limit_source(api_key):
    """The service_limits name for one key: OpenXBL counts calls per key."""
    return 'openxbl:' + hashlib.sha256(api_key.encode()).hexdigest()[:12]


def minutes_until_allowed(api_key):
    """Minutes until a key over its hourly count may call again, else 0."""
    stop = service_limits.stopped(_limit_source(api_key)) if api_key else None
    return max(1, int((stop['until'] - time.time()) // 60) + 1) if stop else 0


def _get(api_key, path):
    """GET one OpenXBL path: the response, or None when no call was made
    (no key, or the key is over its count) or no answer came back."""
    if not api_key:
        return None
    source = _limit_source(api_key)
    if not service_limits.wait_for_turn(source):
        return None
    resp = http_get(f'{OPENXBL_URL}{path}', headers={
        'X-Authorization': api_key,
        'Accept': 'application/json',
        'Accept-Language': 'en-US',
    }, timeout=30, retries=0,
        max_bytes=getattr(config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024))
    if resp is not None and resp.status_code == 429:
        service_limits.stop(source, LIMIT_STOP_SECONDS)
        return None
    return resp


def _json(resp):
    if resp is None or resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        logger.error("OpenXBL: the reply was not JSON")
        return None


# -----------------------------------------------------------------------------
# The key: per user, in user_platform_tokens under 'xbox', as
# {'api_key', 'xuid', 'gamertag', 'connected_at'}
# -----------------------------------------------------------------------------

def save_tokens(tokens, user_id):
    if not user_id:
        logger.warning("Xbox key save skipped: no user_id supplied")
        return
    _platform_save_tokens(user_id, 'xbox', tokens)


def load_tokens(user_id):
    """This user's stored Xbox record, or None. A record left by the retired
    Microsoft sign-in has no api_key and counts as none."""
    if not user_id:
        return None
    try:
        tokens = _platform_load_tokens(user_id, 'xbox')
    except Exception as e:
        logger.error(f"Failed to load Xbox key (user={user_id}): {e}")
        return None
    if not tokens or not tokens.get('api_key') or not tokens.get('xuid'):
        return None
    return tokens


def clear_tokens(user_id):
    if not user_id:
        return
    try:
        _platform_clear_tokens(user_id, 'xbox')
    except Exception as e:
        logger.error(f"Failed to clear Xbox key (user={user_id}): {e}")


def get_account(api_key):
    """The key owner's (xuid, gamertag); KEY_REFUSED when OpenXBL turns the
    key down; None when there was no usable answer."""
    resp = _get(api_key, '/account')
    if resp is not None and resp.status_code in (401, 403):
        return KEY_REFUSED
    data = _json(resp)
    users = data.get('profileUsers') if isinstance(data, dict) else None
    if not users or not isinstance(users[0], dict):
        return None
    xuid = str(users[0].get('id') or '')
    if not xuid:
        return None
    gamertag = next((s.get('value') or '' for s in users[0].get('settings') or []
                     if s.get('id') == 'Gamertag'), '')
    return xuid, gamertag


# -----------------------------------------------------------------------------
# Library and achievements
# -----------------------------------------------------------------------------

def get_title_history(api_key):
    """Every title the key owner has played, or None on no usable answer.

    One call: OpenXBL's title history takes no page token and returns the
    whole list (PASS-59-162 X1)."""
    data = _json(_get(api_key, '/player/titleHistory'))
    titles = data.get('titles') if isinstance(data, dict) else None
    if not isinstance(titles, list):
        return None
    if (data.get('pagingInfo') or {}).get('continuationToken'):
        logger.warning("Xbox title history says it has more; only what came was read")
    return titles


def is_game(title):
    """Apps (Netflix, the Store) share the list with games (X4). A title
    with no type is kept."""
    kind = title.get('type')
    return not kind or kind == 'Game'


def parse_title_platform(title):
    """The RetroDB system folder for a title's devices, or None when none of
    them is a console or a PC (phone-only titles; X3)."""
    devices = title.get('devices') or []
    for platform in _PLATFORM_PRIORITY:
        if platform in devices:
            return XBOX_PLATFORM_MAP[platform]
    for device in devices:
        if XBOX_PLATFORM_MAP.get(device):
            return XBOX_PLATFORM_MAP[device]
    return None


def _from_x360(ach):
    """An Xbox 360 achievement (Microsoft's contract 1) in the contract-2
    shape the rest of RetroDB reads (X2)."""
    unlocked = bool(ach.get('unlocked') or ach.get('unlockedOnline'))
    description = ach.get('description', '')
    if not unlocked and ach.get('lockedDescription'):
        description = ach['lockedDescription']
    return {
        'id': ach.get('id'),
        'name': ach.get('name', ''),
        'description': description,
        'progressState': 'Achieved' if unlocked else 'NotStarted',
        'progression': {'timeUnlocked': ach.get('timeUnlocked', '') if unlocked else ''},
        'rewards': [{'type': 'Gamerscore', 'value': ach.get('gamerscore', 0)}],
        'mediaAssets': [],
    }


def get_achievements(api_key, xuid, title_id, xbox360=False):
    """One title's achievements as {achievements, earned, total}, or None.

    Xbox 360 titles have their own OpenXBL path, whose reply is in Microsoft's
    contract-1 shape; it is converted to contract 2 (X2)."""
    kind = 'x360' if xbox360 else 'player'
    data = _json(_get(api_key, f'/achievements/{kind}/{xuid}/title/{title_id}'))
    achievements = data.get('achievements') if isinstance(data, dict) else None
    if not isinstance(achievements, list):
        return None
    if achievements and 'progressState' not in achievements[0]:
        achievements = [_from_x360(a) for a in achievements]
    earned = sum(1 for a in achievements if a.get('progressState') == 'Achieved')
    return {'achievements': achievements, 'earned': earned, 'total': len(achievements)}


def unlock_time(ach):
    """When an achievement was earned, or '' for a locked one: Microsoft
    sends 0001-01-01 for those (X6)."""
    when = (ach.get('progression') or {}).get('timeUnlocked') or ''
    if not isinstance(when, str) or when.startswith('0001-'):
        return ''
    return when
