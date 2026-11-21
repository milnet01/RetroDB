# =============================================================================
# MOBYGAMES SCRAPER (PASS-59-183)
# =============================================================================
# One endpoint, GET /v2/games. A game found costs two requests: a light title
# search, then the game's whole record by id. A search asking for whole records
# took 12 to 50 seconds; the light search took under a second and the record
# by id about one (measured 2026-11-21). A record is kept for ten minutes, so
# applying a search result picked moments ago asks nothing more. Spec:
# docs/specs/PASS-59-183-mobygames-source.md.
#
# MobyGames allows few requests and says how many in every reply, so the pace
# and the hour's stop come from the reply headers (read_limits).
# =============================================================================

import logging
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import service_limits
from scraper.base_scraper import http_get, safe_json
import config as _config

logger = logging.getLogger(__name__)

BASE_URL = 'https://api.mobygames.com/v2/games'
INCLUDE = ('game_id,title,moby_url,description,developers,publishers,genres,'
           'moby_score,official_url,platforms,release_date,covers,screenshots')
SEARCH_INCLUDE = 'game_id,title,moby_url,platforms,release_date'
_MAX_BYTES = getattr(_config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)

# A search the server has not seen lately took up to 50 seconds; a repeat
# took under one (2026-11-21). A record by id took about one.
_SEARCH_TIMEOUT = 60

# Waits used when a refusal does not say how long.
_KEY_REFUSED_SECONDS = 3600
_LIMIT_SECONDS = 3600
# A timeout or a server error pauses MobyGames, so a sick server does not
# make every later game wait out the timeout too.
_UNAVAILABLE_SECONDS = 600

# System folder -> MobyGames platform id, from its /v2/platforms list
# (fetched 2026-11-21). A folder missing here is not searched.
PLATFORM_MAP = {
    # Nintendo
    'nes': 22, 'famicom': 22, 'fds': 22, 'snes': 15, 'sfc': 15, 'satellaview': 15,
    'sufami': 15, 'n64': 9, 'n64dd': 9, 'gc': 14, 'wii': 82, 'wiiu': 132,
    'switch': 203, 'gb': 10, 'sgb': 10, 'gbc': 11, 'gba': 12, 'nds': 44,
    'n3ds': 101, 'virtualboy': 38, 'pokemini': 152,
    # Sony
    'psx': 6, 'ps2': 7, 'ps3': 81, 'ps4': 141, 'ps5': 288, 'psp': 46, 'psvita': 105,
    # Sega
    'genesis': 16, 'megadrive': 16, 'megadrivejp': 16, 'mastersystem': 26,
    'segacd': 20, 'sega32x': 21, 'sega32xjp': 21, 'sega32xna': 21,
    'saturn': 23, 'saturnjp': 23, 'dreamcast': 8, 'gamegear': 25,
    'sg-1000': 114, 'sc-3000': 114,
    # NEC
    'pcengine': 40, 'tg16': 40, 'pcenginecd': 45, 'tg-cd': 45, 'supergrafx': 127,
    'pcfx': 59, 'pc88': 94, 'pc98': 95,
    # SNK
    'neogeo': 36, 'neogeocd': 54, 'neogeocdjp': 54, 'ngp': 52, 'ngpc': 53,
    # Atari
    'atari2600': 28, 'atari5200': 33, 'atari7800': 34, 'atari800': 39, 'atarixe': 39,
    'atarilynx': 18, 'atarijaguar': 17, 'atarist': 24,
    # Commodore
    'c64': 27, 'vic20': 43, 'plus4': 115, 'amiga': 19, 'amigacd32': 56, 'cdtv': 83,
    # Other consoles and handhelds
    '3do': 35, 'cdimono1': 73, 'colecovision': 29, 'intellivision': 30,
    'vectrex': 37, 'odyssey2': 78, 'videopac': 78, 'channelf': 76,
    'wonderswan': 48, 'wonderswancolor': 49, 'supervision': 109, 'gamecom': 50,
    'ngage': 32, 'arduboy': 215, 'astrocade': 160, 'astrocde': 160, 'arcadia': 162,
    'scv': 138, 'supracan': 110, 'gp32': 108, 'tic80': 336, 'vsmile': 42,
    'crvision': 212,
    # Computers
    'apple2': 31, 'macintosh': 74, 'msx': 57, 'msx1': 57, 'msx2': 57, 'msxturbor': 57,
    'amstradcpc': 60, 'zxspectrum': 41, 'zx81': 119, 'bbcmicro': 92, 'electron': 93,
    'oric': 111, 'trs-80': 58, 'coco': 62, 'ti99': 47, 'x68000': 106, 'x1': 121,
    'fm7': 126, 'archimedes': 117, 'moto': 147, 'to8': 130, 'zxnext': 280, 'palm': 65,
    'dos': 2, 'pc': 3, 'windows': 3, 'windows9x': 3, 'windows3x': 5,
    # Microsoft
    'xbox': 13, 'xbox360': 69, 'xboxone': 142, 'xboxseriesx': 289,
    # Arcade
    'arcade': 143, 'mame': 143, 'fbneo': 143,
}

# Records a search returned, by game id: {game_id: (time, record)}.
_RECORD_SECONDS = 600
_RECORD_LIMIT = 200
_records = {}
_records_lock = threading.Lock()


def _get_api_key():
    from scraper.scraper_manager import get_api_key
    return get_api_key('mobygames_apikey')


def platform_id(system_folder):
    """MobyGames platform for this system folder, or None."""
    return PLATFORM_MAP.get(system_folder.lower()) if system_folder else None


def _seconds(value, default):
    try:
        return max(int(float(value)), 1)
    except (TypeError, ValueError):
        return default


def read_limits(response):
    """Set MobyGames' pace and stop from one reply (spec §4.2)."""
    headers = {k.lower(): v for k, v in (response.headers or {}).items()}
    status = response.status_code
    if status in (401, 403):
        service_limits.stop(service_limits.MOBYGAMES, _KEY_REFUSED_SECONDS,
                            service_limits.KEY_REJECTED)
        return
    if status == 429:
        service_limits.stop(service_limits.MOBYGAMES,
                            _seconds(headers.get('retry-after'), _LIMIT_SECONDS))
        return
    # "0.2;w=1, 720;w=3600": the first entry is the rate per second.
    match = re.match(r'\s*([\d.]+)\s*;\s*w=1\b', headers.get('ratelimit-policy', ''))
    if match and float(match.group(1)) > 0:
        service_limits.set_pace(service_limits.MOBYGAMES, 1 / float(match.group(1)))
    if headers.get('ratelimit-remaining', '').strip() == '0':
        service_limits.stop(service_limits.MOBYGAMES,
                            _seconds(headers.get('ratelimit-reset'), _LIMIT_SECONDS))


def _request(params, include=INCLUDE, timeout=60):
    """One API request; the reply's JSON, or None. The key travels in params, so
    no logged address carries it."""
    key = _get_api_key()
    if not key:
        logger.info('MobyGames: no API key saved')
        return None
    if not service_limits.wait_for_turn(service_limits.MOBYGAMES):
        return None
    # No retries: a 429 retry would wait up to a minute, where read_limits
    # already says how long to wait.
    response = http_get(BASE_URL, params={**params, 'include': include, 'api_key': key},
                        timeout=timeout, retries=0, max_bytes=_MAX_BYTES)
    if response is None or response.status_code >= 500:
        service_limits.stop(service_limits.MOBYGAMES, _UNAVAILABLE_SECONDS,
                            service_limits.UNAVAILABLE)
        return None
    read_limits(response)
    if response.status_code != 200:
        logger.warning(f'MobyGames request failed: {response.status_code}')
        return None
    return safe_json(response)


def _keep(record):
    with _records_lock:
        if len(_records) >= _RECORD_LIMIT:
            oldest = min(_records, key=lambda k: _records[k][0])
            del _records[oldest]
        _records[record['game_id']] = (time.time(), record)


def _kept(game_id):
    with _records_lock:
        entry = _records.get(int(game_id))
        if entry and time.time() - entry[0] < _RECORD_SECONDS:
            return entry[1]
        return None


def _platform_entry(record, moby_platform):
    for entry in record.get('platforms') or []:
        if entry.get('platform_id') == moby_platform:
            return entry
    return None


def search_games(title, system_folder=None, limit=10):
    """Games titled like `title` on this system's platform, best first as listed."""
    moby_platform = platform_id(system_folder)
    if not moby_platform:
        logger.info(f"MobyGames: no platform for system folder '{system_folder}', not searched")
        return []
    data = _request({'title': title, 'platform': moby_platform, 'limit': limit},
                    include=SEARCH_INCLUDE, timeout=_SEARCH_TIMEOUT)
    results = []
    for record in (data or {}).get('games') or []:
        if not record.get('game_id'):
            continue
        entry = _platform_entry(record, moby_platform)
        results.append({
            'id': record['game_id'],
            'name': record.get('title') or '',
            'source': 'mobygames',
            'scraper': 'mobygames',
            'release_date': (entry or {}).get('release_date') or record.get('release_date') or '',
            'platform_match': entry is not None,
            'matched_platform': (entry or {}).get('name'),
            'platforms': [{'id': p.get('platform_id'), 'name': p.get('name')}
                          for p in record.get('platforms') or []],
            'url': record.get('moby_url'),
        })
    return results


def fetch_game_details(game_id, system_folder=None):
    """The game's whole record: one kept from the last ten minutes, else one
    request by id."""
    record = _kept(game_id)
    if record:
        return record
    params = {'id': game_id}
    moby_platform = platform_id(system_folder)
    if moby_platform:
        params['platform'] = moby_platform
    games = (_request(params) or {}).get('games') or []
    if not games:
        return None
    _keep(games[0])
    return games[0]
